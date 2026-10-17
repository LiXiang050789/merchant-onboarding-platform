from __future__ import annotations

import pytest

from backend.app.models import Shop
from backend.tests.conftest import login


@pytest.fixture
async def shops(seeded_session):
    for shop_id, tenant, city, name in (
        ("shop_a_sh_2", "tenant_a", "shanghai", "C shop"),
        ("shop_b_sh", "tenant_b", "shanghai", "A shop"),
        ("shop_a_bj", "tenant_a", "beijing", "D shop"),
        ("shop_a_sh_1", "tenant_a", "shanghai", "B shop"),
    ):
        seeded_session.add(Shop(
            id=shop_id, tenant_id=tenant, name=name, city_code=city,
            district_code="core", address="Test address", lng=121.47, lat=31.23,
        ))
    await seeded_session.commit()


async def query_shops(client, email, password, params=None):
    token = await login(client, email, password)
    response = await client.get("/api/v1/shops", headers={"Authorization": f"Bearer {token}"}, params=params)
    assert response.status_code == 200, response.text
    data = response.json()
    assert [item["name"] for item in data] == sorted(item["name"] for item in data)
    assert all(set(item) == {"id", "name", "city_code", "district_code", "address", "lng", "lat"} for item in data)
    return data


@pytest.mark.asyncio
async def test_merchant_only_sees_own_tenant_shops(client, shops):
    data = await query_shops(client, "a@example.com", "pass-a")
    assert {item["id"] for item in data} == {"shop_a_sh_1", "shop_a_sh_2", "shop_a_bj"}


@pytest.mark.asyncio
async def test_admin_sees_all_tenants_shops(client, shops):
    data = await query_shops(client, "admin@example.com", "pass-admin")
    assert len(data) == 4
    assert {item["id"] for item in data} == {"shop_a_sh_1", "shop_a_sh_2", "shop_a_bj", "shop_b_sh"}


@pytest.mark.asyncio
async def test_operator_only_sees_own_tenant_region_shops(client, shops):
    data = await query_shops(client, "op@example.com", "pass-op")
    assert {item["id"] for item in data} == {"shop_a_sh_1", "shop_a_sh_2"}
    assert {item["city_code"] for item in data} == {"shanghai"}
    assert await query_shops(client, "op@example.com", "pass-op", {"city": "beijing"}) == []


@pytest.mark.asyncio
async def test_city_filter_preserves_role_scope(client, shops):
    merchant = await query_shops(client, "a@example.com", "pass-a", {"city": "shanghai"})
    assert {item["id"] for item in merchant} == {"shop_a_sh_1", "shop_a_sh_2"}
    admin = await query_shops(client, "admin@example.com", "pass-admin", {"city": "shanghai"})
    assert {item["id"] for item in admin} == {"shop_a_sh_1", "shop_a_sh_2", "shop_b_sh"}


@pytest.mark.asyncio
async def test_shops_require_authentication(client, shops):
    response = await client.get("/api/v1/shops")
    assert response.status_code == 401
