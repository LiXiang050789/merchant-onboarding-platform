from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.app.models import FormAuditEvent
from backend.tests.conftest import login

pytestmark = pytest.mark.asyncio


def valid_form(**overrides):
    payload = {
        "form_type": "merchant_info",
        "city_code": "shanghai",
        "district_code": "core",
        "industry": "restaurant",
        "lng": 121.4737,
        "lat": 31.2304,
        "payload": {"merchant_name": "青石小馆", "license_no": "LIC-001"},
    }
    payload.update(overrides)
    return payload


async def auth_headers(client, email="a@example.com", password="pass-a", idem="idem-001"):
    token = await login(client, email, password)
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": idem}


async def create_form(client, **overrides):
    headers = await auth_headers(client, idem=overrides.pop("idem", "idem-001"))
    return await client.post("/api/v1/forms", json=valid_form(**overrides), headers=headers)


async def test_create_form_writes_audit_event_and_returns_submitted(client, session):
    response = await create_form(client)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_a"
    assert body["status"] == "submitted"
    assert body["created_by"] == "user_a"

    event = await session.scalar(select(FormAuditEvent).where(FormAuditEvent.form_id == body["id"]))
    assert event is not None
    assert event.event_type == "form_created"
    assert event.to_status == "submitted"


async def test_idempotency_key_returns_existing_form(client):
    first = await create_form(client)
    second = await create_form(client, city_code="beijing")

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["city_code"] == "shanghai"


async def test_tenant_scope_hides_other_tenant_form(client):
    created = await create_form(client)
    token_b = await login(client, "b@example.com", "pass-b")

    response = await client.get(
        f"/api/v1/forms/{created.json()['id']}",
        headers={"Authorization": f"Bearer {token_b}"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_rejects_invalid_coordinates(client):
    headers = await auth_headers(client, idem="idem-invalid-coord")
    response = await client.post("/api/v1/forms", json=valid_form(lng=999, lat=31.2), headers=headers)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_rejects_missing_type_specific_payload(client):
    headers = await auth_headers(client, idem="idem-missing-payload")
    response = await client.post(
        "/api/v1/forms",
        json=valid_form(form_type="product", payload={"product_name": "咖啡豆"}),
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_merchant_cannot_drive_illegal_state_transition(client):
    created = await create_form(client)
    headers = await auth_headers(client, idem="unused")

    response = await client.patch(
        f"/api/v1/forms/{created.json()['id']}/status",
        json={"target_status": "published"},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_allows_legal_state_transition(client):
    created = await create_form(client)
    token = await login(client, "admin@example.com", "pass-admin")

    response = await client.patch(
        f"/api/v1/forms/{created.json()['id']}/status",
        json={"target_status": "validating"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "validating"


async def test_merchant_cannot_drive_legal_state_transition(client):
    created = await create_form(client)
    headers = await auth_headers(client, idem="unused")

    response = await client.patch(
        f"/api/v1/forms/{created.json()['id']}/status",
        json={"target_status": "validating"},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_operator_region_scope_lists_only_own_city(client):
    await create_form(client, idem="idem-sh", city_code="shanghai", industry="restaurant")
    await create_form(client, idem="idem-bj", city_code="beijing", industry="retail")
    token = await login(client, "op@example.com", "pass-op")

    response = await client.get("/api/v1/forms", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["city_code"] == "shanghai"


async def test_filter_combination_respects_tenant_scope(client):
    await create_form(client, idem="idem-sh", city_code="shanghai", industry="restaurant")
    await create_form(client, idem="idem-bj", city_code="beijing", industry="retail")
    token = await login(client, "a@example.com", "pass-a")

    response = await client.get(
        "/api/v1/forms?city=shanghai&status=submitted&form_type=merchant_info&industry=restaurant",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["city_code"] == "shanghai"
