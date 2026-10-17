from __future__ import annotations

import math
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from backend.app.aggregation import grid_size_for_zoom
from backend.app.models import Form, FormStatus, FormType, Shop
from backend.tests.conftest import login
from backend.tests.test_frontend_contract import map_form

pytestmark = pytest.mark.asyncio
CLUSTER = "z11:2430:625"


async def headers(client, email="a@example.com", password="pass-a"):
    return {"Authorization": f"Bearer {await login(client, email, password)}"}


def member(idx, **changes):
    form = map_form(idx)
    form.lng, form.lat = 121.525, 31.275
    for key, value in changes.items():
        setattr(form, key, value)
    return form


@pytest.mark.parametrize("zoom", [1, 9, 11, 13, 20])
async def test_members_match_aggregation_on_cell_edges(client, session, zoom):
    industry = f"p14-{uuid4().hex}"
    points = [(121.5, 31.25), (121.525, 31.275), (121.55, 31.275),
              (121.525, 31.3), (121.499, 31.275), (121.525, 31.249), (121.56, 31.28)]
    session.add_all([member(idx, lng=lng, lat=lat, industry=industry) for idx, (lng, lat) in enumerate(points, 1)])
    await session.commit()
    session.expire_all()
    stored = list((await session.scalars(select(Form))).all())
    expected = {}
    size = grid_size_for_zoom(zoom)
    for form in stored:
        key = f"z{zoom}:{math.floor(form.lng / size)}:{math.floor(form.lat / size)}"
        expected.setdefault(key, set()).add(form.id)
    auth = await headers(client)
    aggregate = await client.get("/api/v1/clusters", headers=auth, params={
        "bbox": "121.4,31.15,121.65,31.4", "zoom": zoom, "industry": industry,
    })
    assert aggregate.status_code == 200
    actual_counts = {feature["properties"]["cluster_id"]: feature["properties"]["count"] for feature in aggregate.json()["features"]}
    assert actual_counts == {key: len(ids) for key, ids in expected.items()}
    for key, ids in expected.items():
        response = await client.get("/api/v1/clusters/members", headers=auth, params={"cluster_id": key, "industry": industry})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == len(ids), (key, body, ids)
        assert {item["id"] for item in body["members"]} == ids


async def test_members_respect_admin_tenant_and_operator_scope(client, session):
    session.add_all([member(1), member(2), member(3, city_code="beijing"),
                     member(4, tenant_id="tenant_b", created_by="user_b")])
    await session.commit()
    for email, password, ids in [
        ("admin@example.com", "pass-admin", {1, 2, 3, 4}),
        ("a@example.com", "pass-a", {1, 2, 3}),
        ("op@example.com", "pass-op", {1, 2}),
        ("b@example.com", "pass-b", {4}),
    ]:
        response = await client.get("/api/v1/clusters/members", headers=await headers(client, email, password), params={"cluster_id": CLUSTER})
        assert response.status_code == 200
        assert response.json()["total"] == len(ids)
        assert {item["id"] for item in response.json()["members"]} == {f"form_map_{idx:03d}" for idx in ids}
    operator = await client.get("/api/v1/clusters/members", headers=await headers(client, "op@example.com", "pass-op"), params={"cluster_id": CLUSTER, "city": "beijing"})
    assert operator.json()["total"] == 0 and operator.json()["members"] == []
    assert (await client.get("/api/v1/clusters/members", params={"cluster_id": CLUSTER})).status_code == 401


async def test_members_compose_all_filters(client, session):
    session.add_all([member(1), member(2, industry="retail"), member(3, status=FormStatus.validated),
                     member(4, form_type=FormType.product), member(5, city_code="beijing")])
    await session.commit()
    auth = await headers(client)
    filters = {"cluster_id": CLUSTER, "city": "shanghai", "status": "published", "form_type": "merchant_info", "industry": "restaurant"}
    response = await client.get("/api/v1/clusters/members", headers=auth, params=filters)
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["members"][0]["id"] == "form_map_001"
    for changed in [{"city": "chengdu"}, {"status": "failed"}, {"form_type": "report"}, {"industry": "missing"}]:
        body = (await client.get("/api/v1/clusters/members", headers=auth, params={**filters, **changed})).json()
        assert body["total"] == 0 and body["members"] == []


async def test_member_names_and_batched_shop_lookup(client, session, engine):
    session.add(Shop(id="p14_shop", tenant_id="tenant_a", name="测试店铺", city_code="shanghai", district_code="core", address="路1号", lng=121.525, lat=31.275))
    for idx, (kind, key) in enumerate([(FormType.merchant_info, "merchant_name"), (FormType.property, "property_name"), (FormType.product, "product_name"), (FormType.report, "report_name")], 1):
        session.add(member(idx, form_type=kind, payload={key: f"名称{idx}"}, shop_id="p14_shop"))
    session.add(member(5, payload={}))
    await session.commit()
    queries = []
    def record(conn, cursor, statement, parameters, context, executemany):
        if "FROM shops" in statement:
            queries.append(statement)
    auth = await headers(client)
    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        response = await client.get("/api/v1/clusters/members", headers=auth, params={"cluster_id": CLUSTER})
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    body = response.json()
    assert body["total"] == 5 and len(queries) == 1
    by_id = {item["id"]: item for item in body["members"]}
    for idx in range(1, 5):
        item = by_id[f"form_map_{idx:03d}"]
        assert item["display_name"] == f"名称{idx}" and item["shop_name"] == "测试店铺"
        assert set(item) == {"id", "form_type", "status", "city_code", "industry", "display_name", "shop_name", "created_at"}
    assert by_id["form_map_005"]["display_name"] == "form_map_005"
    assert by_id["form_map_005"]["shop_name"] is None


async def test_members_limit_and_empty_cluster(client, session):
    session.add_all([member(idx) for idx in range(1, 26)])
    await session.commit()
    auth = await headers(client)
    body = (await client.get("/api/v1/clusters/members", headers=auth, params={"cluster_id": CLUSTER})).json()
    assert body["cluster_id"] == CLUSTER and body["total"] == 25 and len(body["members"]) == 20
    assert [item["id"] for item in body["members"]] == [f"form_map_{idx:03d}" for idx in range(25, 5, -1)]
    empty = (await client.get("/api/v1/clusters/members", headers=auth, params={"cluster_id": "z11:-1:-1"})).json()
    assert empty == {"cluster_id": "z11:-1:-1", "total": 0, "members": []}


@pytest.mark.parametrize("cluster_id", ["z0:1:1", "z21:1:1", "abc", "z11:1", "z11:1.5:2", "z11:a:2", "z1.5:1:2", "z11:1:2:3", "z11:1:2x"])
async def test_invalid_cluster_ids_return_422(client, cluster_id):
    response = await client.get("/api/v1/clusters/members", headers=await headers(client), params={"cluster_id": cluster_id})
    assert response.status_code == 422 and response.json()["code"] == "invalid_cluster"
