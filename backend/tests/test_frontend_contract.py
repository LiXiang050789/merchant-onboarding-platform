from __future__ import annotations

from datetime import datetime

import pytest

from backend.app.models import Form, FormStatus, FormType
from backend.tests.conftest import login

pytestmark = pytest.mark.asyncio


def map_form(idx: int) -> Form:
    now = datetime(2026, 9, 19, 9, idx, 0)
    return Form(
        id=f"form_map_{idx:03d}",
        tenant_id="tenant_a",
        form_type=FormType.merchant_info,
        status=FormStatus.published,
        idempotency_key=f"map_idem_{idx:03d}",
        city_code="shanghai",
        district_code="core",
        industry="restaurant",
        lng=121.47 + idx * 0.001,
        lat=31.23 + idx * 0.001,
        payload={"merchant_name": "青石小馆", "license_no": "LIC-001"},
        created_by="user_a",
        created_at=now,
        updated_at=now,
    )


async def test_clusters_support_etag_and_304(client, session):
    session.add_all([map_form(1), map_form(2)])
    await session.commit()
    token = await login(client, "a@example.com", "pass-a")
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.get(
        "/api/v1/clusters?bbox=121.30,31.05,121.70,31.35&zoom=11&status=published&city=shanghai",
        headers=headers,
    )
    etag = first.headers.get("etag")
    second = await client.get(
        "/api/v1/clusters?bbox=121.30,31.05,121.70,31.35&zoom=11&status=published&city=shanghai",
        headers={**headers, "If-None-Match": etag or ""},
    )

    assert first.status_code == 200
    assert first.json()["type"] == "FeatureCollection"
    assert first.json()["features"]
    assert etag
    assert second.status_code == 304


async def test_polling_events_receive_form_changes(client):
    token = await login(client, "a@example.com", "pass-a")
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "poll-event-001"}
    created = await client.post(
        "/api/v1/forms",
        headers=headers,
        json={
            "form_type": "merchant_info",
            "city_code": "shanghai",
            "district_code": "core",
            "industry": "restaurant",
            "lng": 121.4737,
            "lat": 31.2304,
            "payload": {"merchant_name": "青石小馆", "license_no": "LIC-001"},
        },
    )
    events = await client.get("/api/v1/events?since=0", headers={"Authorization": f"Bearer {token}"})

    assert created.status_code == 200
    assert events.status_code == 200
    assert any(item["type"] == "form.status_changed" for item in events.json()["events"])
