from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from backend.app.models import (
    Batch,
    BatchCheckpoint,
    BatchItem,
    BatchStatus,
    DLQItem,
    Form,
    FormStatus,
    FormType,
    SubmissionEvent,
    SubmissionEventType,
)
from backend.tests.conftest import login

pytestmark = pytest.mark.asyncio


REQUIRED_PAYLOAD = {
    FormType.merchant_info: {"merchant_name": "青石小馆", "license_no": "LIC-001"},
    FormType.property: {"property_name": "静安小铺", "address": "南京西路 1 号"},
    FormType.product: {"product_name": "咖啡豆", "sku": "SKU-001"},
    FormType.report: {"report_name": "日报", "period": "2026-09"},
}


def make_form(idx: int, form_type: FormType, city: str = "shanghai", payload_extra: dict | None = None) -> Form:
    lng_lat = {
        "shanghai": (121.4737 + idx * 0.0001, 31.2304 + idx * 0.0001),
        "beijing": (116.4074 + idx * 0.0001, 39.9042 + idx * 0.0001),
    }[city]
    payload = dict(REQUIRED_PAYLOAD[form_type])
    if payload_extra:
        payload.update(payload_extra)
    now = datetime(2026, 9, 19, 8, idx, 0)
    return Form(
        id=f"form_batch_{idx:03d}",
        tenant_id="tenant_a",
        form_type=form_type,
        status=FormStatus.validated,
        idempotency_key=f"batch_idem_{idx:03d}",
        city_code=city,
        district_code="core",
        industry="restaurant",
        lng=lng_lat[0],
        lat=lng_lat[1],
        payload=payload,
        created_by="user_a",
        created_at=now,
        updated_at=now,
    )


async def admin_headers(client):
    token = await login(client, "admin@example.com", "pass-admin")
    return {"Authorization": f"Bearer {token}"}


async def test_build_batches_groups_by_city_and_marks_forms_batched(client, session):
    session.add_all(
        [
            make_form(1, FormType.merchant_info, "shanghai"),
            make_form(2, FormType.property, "shanghai"),
            make_form(3, FormType.product, "beijing"),
        ]
    )
    await session.commit()

    response = await client.post(
        "/api/v1/batches/build",
        json={"capacity": 50, "radius_m": 3000},
        headers=await admin_headers(client),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_forms"] == 3
    assert {item["city_code"] for item in body["batches"]} == {"shanghai", "beijing"}

    batch_items = (await session.execute(select(BatchItem))).scalars().all()
    assert len(batch_items) == 3
    forms = (await session.execute(select(Form))).scalars().all()
    assert {item.status for item in forms} == {FormStatus.batched}


async def test_run_batch_publishes_four_type_pipeline_and_is_idempotent(client, session):
    session.add_all(
        [
            make_form(10, FormType.merchant_info),
            make_form(11, FormType.property),
            make_form(12, FormType.product),
            make_form(13, FormType.report),
        ]
    )
    await session.commit()
    headers = await admin_headers(client)
    build = await client.post("/api/v1/batches/build", json={"city": "shanghai", "capacity": 50, "radius_m": 3000}, headers=headers)
    batch_id = build.json()["batches"][0]["id"]

    first = await client.post(f"/api/v1/batches/{batch_id}/run", headers=headers)
    second = await client.post(f"/api/v1/batches/{batch_id}/run", headers=headers)

    assert first.status_code == 200, first.text
    assert first.json()["status"] == BatchStatus.completed.value
    assert first.json()["published"] == 4
    assert set(first.json()["checkpoint_stages"]) == {
        "merchant_info_pipeline",
        "property_pipeline",
        "product_pipeline",
        "report_pipeline",
    }
    assert second.status_code == 200
    assert second.json()["status"] == BatchStatus.completed.value
    assert second.json()["processed"] == 0

    business_events = (
        await session.execute(select(SubmissionEvent).where(SubmissionEvent.event_type == SubmissionEventType.business_published))
    ).scalars().all()
    assert len(business_events) == 4


async def test_run_batch_writes_dlq_and_retry_can_resume(client, session):
    good = make_form(20, FormType.merchant_info)
    bad = make_form(21, FormType.product, payload_extra={"force_dlq_stage": "product_pipeline"})
    session.add_all([good, bad])
    await session.commit()
    headers = await admin_headers(client)
    build = await client.post("/api/v1/batches/build", json={"city": "shanghai", "capacity": 50, "radius_m": 3000}, headers=headers)
    batch_id = build.json()["batches"][0]["id"]

    failed = await client.post(f"/api/v1/batches/{batch_id}/run", headers=headers)
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == BatchStatus.failed.value
    assert failed.json()["failed"] == 1

    dlq = await session.scalar(select(DLQItem).where(DLQItem.form_id == bad.id))
    assert dlq is not None
    assert dlq.stage == "product_pipeline"
    checkpoint = await session.scalar(select(BatchCheckpoint).where(BatchCheckpoint.batch_id == batch_id))
    assert checkpoint is not None

    bad.payload = dict(REQUIRED_PAYLOAD[FormType.product])
    batch = await session.get(Batch, batch_id)
    assert batch is not None
    batch.status = BatchStatus.created
    await session.commit()

    resumed = await client.post(f"/api/v1/batches/{batch_id}/run", headers=headers)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == BatchStatus.completed.value

    refreshed_bad = await session.get(Form, bad.id)
    assert refreshed_bad is not None
    await session.refresh(refreshed_bad)
    assert refreshed_bad.status == FormStatus.published
    assert refreshed_bad.retry_count == 1
