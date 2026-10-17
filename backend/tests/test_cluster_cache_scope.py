from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.cluster_service import cache_key, etag_for
from backend.app.models import User, UserRole
from backend.app.security import hash_password
from backend.tests.conftest import login
from backend.tests.test_frontend_contract import map_form


def test_cache_keys_and_etags_separate_role_and_region_scopes():
    bbox = (121.30, 31.05, 121.70, 31.35)
    filters = {"city": None, "status": None, "form_type": None, "industry": None}
    scopes = ("admin", "operator:shanghai", "operator:beijing")
    keys = [cache_key("tenant_a", bbox, 11, {**filters, "scope": scope}) for scope in scopes]
    etags = [etag_for({**filters, "bbox": bbox, "zoom": 11, "scope": scope}, 2, "same-update") for scope in scopes]
    assert len(set(keys)) == 3
    assert len(set(etags)) == 3


@pytest.mark.asyncio
async def test_cluster_cache_isolates_admin_tenant_and_operator_regions(client, session):
    for idx in range(1, 5):
        form = map_form(idx)
        if idx > 2:
            form.tenant_id = "tenant_b"
            form.created_by = "user_b"
        session.add(form)
    beijing = map_form(5)
    beijing.city_code = "beijing"
    beijing.lng, beijing.lat = 116.4074, 39.9042
    session.add(beijing)
    session.add(User(
        id="operator_beijing", tenant_id="tenant_a", email="op-beijing@example.com",
        password_hash=hash_password("pass-op-beijing", salt="salt-op-beijing"),
        role=UserRole.operator, region_code="beijing",
    ))
    await session.commit()
    headers = {}
    for role, email, password in (
        ("admin", "admin@example.com", "pass-admin"),
        ("shanghai", "op@example.com", "pass-op"),
        ("beijing", "op-beijing@example.com", "pass-op-beijing"),
    ):
        headers[role] = {"Authorization": f"Bearer {await login(client, email, password)}"}

    offset = (uuid4().int % 100000) / 1000000
    shanghai_params = {"bbox": f"{121.20 + offset:.6f},31.05,121.70,31.35", "zoom": 11}
    beijing_params = {"bbox": f"{116.20 + offset:.6f},39.70,116.70,40.10", "zoom": 11}

    async def query(role, params):
        response = await client.get("/api/v1/clusters", params=params, headers=headers[role])
        assert response.status_code == 200, response.text
        return response

    def count(response):
        return sum(feature["properties"]["count"] for feature in response.json()["features"])

    admin = await query("admin", shanghai_params)
    assert count(admin) == 4
    admin_cached = await query("admin", shanghai_params)
    assert admin_cached.headers["X-Cache"] == "HIT"
    operator = await query("shanghai", shanghai_params)
    assert count(operator) == 2
    assert operator.json() != admin.json()
    assert operator.headers["ETag"] != admin.headers["ETag"]
    operator_cached = await query("shanghai", shanghai_params)
    assert operator_cached.headers["X-Cache"] == "HIT"
    assert count(await query("admin", shanghai_params)) == 4
    cross_etag = await client.get(
        "/api/v1/clusters", params=shanghai_params,
        headers={**headers["shanghai"], "If-None-Match": admin.headers["ETag"]},
    )
    assert cross_etag.status_code == 200
    assert count(cross_etag) == 2

    assert count(await query("beijing", beijing_params)) == 1
    assert count(await query("shanghai", beijing_params)) == 0
    assert count(await query("beijing", beijing_params)) == 1
