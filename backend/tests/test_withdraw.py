from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from backend.app.batch_pipeline import run_batch
from backend.app.models import (
    Batch,
    BatchItem,
    BatchStatus,
    Form,
    FormAuditEvent,
    FormStatus,
    FormType,
    SubmissionEvent,
    SubmissionEventType,
)
from backend.app.stats import compute_success_rate
from backend.tests.conftest import login

pytestmark = pytest.mark.asyncio

BASE = datetime(2026, 9, 19, 10, 0, 0)

REQUIRED_PAYLOAD = {
    FormType.merchant_info: {"merchant_name": "青石小馆", "license_no": "LIC-001"},
    FormType.property: {"property_name": "静安门店", "address": "南京西路"},
    FormType.product: {"product_name": "咖啡豆", "sku": "SKU-001"},
    FormType.report: {"report_name": "日报", "period": "2026-09"},
}


def make_form(
    idx: int,
    *,
    status: FormStatus = FormStatus.submitted,
    tenant_id: str = "tenant_a",
    created_by: str = "user_a",
    form_type: FormType = FormType.merchant_info,
    batch_id: str | None = None,
) -> Form:
    return Form(
        id=f"form_withdraw_{idx:02d}",
        tenant_id=tenant_id,
        form_type=form_type,
        status=status,
        idempotency_key=f"withdraw_key_{idx:02d}",
        city_code="shanghai",
        district_code="core",
        industry="restaurant",
        lng=121.4737 + idx * 0.001,
        lat=31.2304 + idx * 0.001,
        payload=dict(REQUIRED_PAYLOAD[form_type]),
        batch_id=batch_id,
        retry_count=0,
        created_by=created_by,
        created_at=BASE,
        updated_at=BASE,
    )


def batch(batch_id: str, item_count: int, status: BatchStatus = BatchStatus.created) -> Batch:
    return Batch(
        id=batch_id,
        tenant_id="tenant_a",
        city_code="shanghai",
        status=status,
        center_lng=121.47,
        center_lat=31.23,
        capacity=50,
        item_count=item_count,
        created_at=BASE,
        updated_at=BASE,
    )


async def auth(client, email: str = "a@example.com", password: str = "pass-a") -> dict[str, str]:
    token = await login(client, email, password)
    return {"Authorization": f"Bearer {token}"}


async def test_creator_can_withdraw_submitted_form_and_writes_audit_event(client, session):
    form = make_form(1)
    session.add(form)
    await session.commit()

    response = await client.post(
        f"/api/v1/forms/{form.id}/withdraw",
        json={"reason": "资料填错"},
        headers=await auth(client),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "withdrawn"
    assert body["withdraw_reason"] == "资料填错"
    assert body["withdrawn_at"] is not None

    refreshed = await session.get(Form, form.id)
    assert refreshed is not None
    await session.refresh(refreshed)
    assert refreshed.status == FormStatus.withdrawn
    assert refreshed.batch_id is None

    audit = await session.scalar(select(FormAuditEvent).where(FormAuditEvent.form_id == form.id, FormAuditEvent.event_type == "form_withdrawn"))
    assert audit is not None
    assert audit.from_status == FormStatus.submitted.value
    assert audit.to_status == FormStatus.withdrawn.value

    event = await session.scalar(select(SubmissionEvent).where(SubmissionEvent.form_id == form.id, SubmissionEvent.event_type == SubmissionEventType.form_withdrawn))
    assert event is not None
    assert event.idempotency_key == form.idempotency_key


async def test_withdraw_respects_owner_and_tenant_boundaries(client, session):
    mine = make_form(2)
    other_tenant = make_form(3, tenant_id="tenant_b", created_by="user_b")
    session.add_all([mine, other_tenant])
    await session.commit()

    operator_response = await client.post(f"/api/v1/forms/{mine.id}/withdraw", json={}, headers=await auth(client, "op@example.com", "pass-op"))
    cross_tenant_response = await client.post(f"/api/v1/forms/{other_tenant.id}/withdraw", json={}, headers=await auth(client))

    assert operator_response.status_code == 403
    assert operator_response.json()["code"] == "forbidden"
    assert cross_tenant_response.status_code == 404
    assert cross_tenant_response.json()["code"] == "not_found"


async def test_withdraw_rejects_terminal_and_duplicate_withdraw(client, session):
    published = make_form(4, status=FormStatus.published)
    submitted = make_form(5)
    session.add_all([published, submitted])
    await session.commit()
    headers = await auth(client)

    rejected = await client.post(f"/api/v1/forms/{published.id}/withdraw", json={}, headers=headers)
    first = await client.post(f"/api/v1/forms/{submitted.id}/withdraw", json={}, headers=headers)
    duplicate = await client.post(f"/api/v1/forms/{submitted.id}/withdraw", json={}, headers=headers)

    assert rejected.status_code == 409
    assert rejected.json()["code"] == "not_withdrawable"
    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "not_withdrawable"


async def test_withdraw_batched_form_removes_item_and_cancels_empty_batch(client, session):
    batch_id = "batch_withdraw_empty"
    form = make_form(6, status=FormStatus.batched, batch_id=batch_id)
    session.add_all([batch(batch_id, 1), form, BatchItem(batch_id=batch_id, form_id=form.id, distance_m=12)])
    await session.commit()

    response = await client.post(f"/api/v1/forms/{form.id}/withdraw", json={"reason": "不再入驻"}, headers=await auth(client))

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "withdrawn"
    assert await session.get(BatchItem, {"batch_id": batch_id, "form_id": form.id}) is None
    refreshed_batch = await session.get(Batch, batch_id)
    assert refreshed_batch is not None
    await session.refresh(refreshed_batch)
    assert refreshed_batch.item_count == 0
    assert refreshed_batch.status == BatchStatus.canceled


async def test_withdraw_batched_form_keeps_non_empty_batch_created(client, session):
    batch_id = "batch_withdraw_keep"
    target = make_form(7, status=FormStatus.batched, batch_id=batch_id)
    remaining = make_form(8, status=FormStatus.batched, batch_id=batch_id)
    session.add_all(
        [
            batch(batch_id, 2),
            target,
            remaining,
            BatchItem(batch_id=batch_id, form_id=target.id, distance_m=12),
            BatchItem(batch_id=batch_id, form_id=remaining.id, distance_m=18),
        ]
    )
    await session.commit()

    response = await client.post(f"/api/v1/forms/{target.id}/withdraw", json={}, headers=await auth(client))

    assert response.status_code == 200, response.text
    refreshed_batch = await session.get(Batch, batch_id)
    assert refreshed_batch is not None
    await session.refresh(refreshed_batch)
    assert refreshed_batch.item_count == 1
    assert refreshed_batch.status == BatchStatus.created
    assert await session.get(BatchItem, {"batch_id": batch_id, "form_id": remaining.id}) is not None


async def test_withdraw_locks_batched_form_once_batch_started(client, session):
    batch_id = "batch_withdraw_locked"
    form = make_form(9, status=FormStatus.batched, batch_id=batch_id)
    session.add_all([batch(batch_id, 1, BatchStatus.processing), form, BatchItem(batch_id=batch_id, form_id=form.id, distance_m=12)])
    await session.commit()

    response = await client.post(f"/api/v1/forms/{form.id}/withdraw", json={}, headers=await auth(client))

    assert response.status_code == 409
    assert response.json()["code"] == "batch_locked"


async def test_batch_pipeline_skips_withdrawn_items(session):
    batch_id = "batch_skip_withdrawn"
    withdrawn = make_form(10, status=FormStatus.withdrawn, form_type=FormType.merchant_info, batch_id=batch_id)
    active = make_form(11, status=FormStatus.batched, form_type=FormType.product, batch_id=batch_id)
    session.add_all(
        [
            batch(batch_id, 2),
            withdrawn,
            active,
            BatchItem(batch_id=batch_id, form_id=withdrawn.id, distance_m=10),
            BatchItem(batch_id=batch_id, form_id=active.id, distance_m=15),
        ]
    )
    await session.commit()

    summary = await run_batch(session, await session.get(Batch, batch_id))
    await session.commit()

    assert summary.status == BatchStatus.completed
    assert summary.processed == 1
    await session.refresh(withdrawn)
    await session.refresh(active)
    assert withdrawn.status == FormStatus.withdrawn
    assert active.status == FormStatus.published


async def test_withdrawal_rate_and_end_to_end_denominator_exclude_withdrawn(session):
    session.add_all([make_form(12), make_form(13), make_form(14)])
    session.add_all(
        [
            SubmissionEvent(tenant_id="tenant_a", form_id="form_withdraw_12", idempotency_key="k_ok", event_type=SubmissionEventType.submit_attempt, client_trace_id="trace_ok", occurred_at=BASE, received_at=BASE, meta={}),
            SubmissionEvent(tenant_id="tenant_a", form_id="form_withdraw_12", idempotency_key="k_ok", event_type=SubmissionEventType.business_published, client_trace_id="trace_ok2", occurred_at=BASE + timedelta(minutes=1), received_at=BASE + timedelta(minutes=1), meta={}),
            SubmissionEvent(tenant_id="tenant_a", form_id="form_withdraw_13", idempotency_key="k_withdraw", event_type=SubmissionEventType.submit_attempt, client_trace_id="trace_w", occurred_at=BASE, received_at=BASE, meta={}),
            SubmissionEvent(tenant_id="tenant_a", form_id="form_withdraw_13", idempotency_key="k_withdraw", event_type=SubmissionEventType.form_withdrawn, client_trace_id="trace_w2", occurred_at=BASE + timedelta(minutes=2), received_at=BASE + timedelta(minutes=2), meta={}),
            SubmissionEvent(tenant_id="tenant_a", form_id="form_withdraw_14", idempotency_key="k_fail", event_type=SubmissionEventType.submit_attempt, client_trace_id="trace_f", occurred_at=BASE, received_at=BASE, meta={}),
        ]
    )
    await session.commit()

    result = await compute_success_rate(session, "tenant_a", start=BASE - timedelta(minutes=1), end=BASE + timedelta(minutes=10), use_cache=False)

    assert result["deduped_attempts"] == 3
    assert result["withdrawal_rate"] == {"numerator": 1, "denominator": 3, "rate": 0.333333}
    assert result["end_to_end_success_rate"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
