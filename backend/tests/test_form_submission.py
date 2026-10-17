from __future__ import annotations

import pytest
from sqlalchemy import select

import backend.app.main as main
from backend.app.models import File, Shop
from backend.tests.test_forms import auth_headers, valid_form

pytestmark = pytest.mark.asyncio


@pytest.fixture
def upload_root(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "UPLOAD_ROOT", tmp_path)
    return tmp_path


async def test_upload_download_and_tenant_isolation(client, session, upload_root):
    headers = await auth_headers(client)
    response = await client.post("/api/v1/files", headers=headers,
                                 files={"file": ("../../执照.PNG", b"image-bytes", "text/html")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"file_id", "filename", "mime_type", "size_bytes"}
    assert body["filename"] == "执照.PNG"
    assert body["mime_type"] == "image/png"
    assert body["size_bytes"] == 11
    record = await session.get(File, body["file_id"])
    assert record.tenant_id == "tenant_a" and record.uploader_id == "user_a"
    assert record.storage_path == f"tenant_a/{body['file_id']}.png"
    assert (upload_root / record.storage_path).read_bytes() == b"image-bytes"
    result = await client.get(f"/api/v1/files/{body['file_id']}", headers=headers)
    assert result.status_code == 200 and result.content == b"image-bytes"
    assert result.headers["x-content-type-options"] == "nosniff"
    assert result.headers["cache-control"] == "private, no-store"
    other = await auth_headers(client, "b@example.com", "pass-b")
    assert (await client.get(f"/api/v1/files/{body['file_id']}", headers=other)).status_code == 404
    assert (await client.get("/api/v1/files/f_missing", headers=headers)).status_code == 404
    assert (await client.get(f"/api/v1/files/{body['file_id']}")).status_code == 401


@pytest.mark.parametrize("extension", ["png", "jpg", "jpeg", "webp", "gif", "pdf", "doc", "docx", "xls", "xlsx", "txt", "md"])
async def test_upload_whitelisted_extensions(client, upload_root, extension):
    response = await client.post("/api/v1/files", headers=await auth_headers(client),
                                 files={"file": (f"sample.{extension}", b"sample")})
    assert response.status_code == 200, response.text


async def test_upload_rejects_unsafe_types_and_large_files(client, session, upload_root):
    headers = await auth_headers(client)
    for filename in ["bad.html", "bad.svg", "bad.exe", "bad.png.exe", "no-extension"]:
        response = await client.post("/api/v1/files", headers=headers, files={"file": (filename, b"x")})
        assert response.status_code == 422
    assert (await client.post("/api/v1/files", files={"file": ("x.png", b"x")})).status_code == 401
    accepted = await client.post("/api/v1/files", headers=headers, files={"file": ("limit.pdf", b"x" * main.MAX_FILE_BYTES)})
    assert accepted.status_code == 200 and accepted.json()["size_bytes"] == main.MAX_FILE_BYTES
    rejected = await client.post("/api/v1/files", headers=headers, files={"file": ("large.pdf", b"x" * (main.MAX_FILE_BYTES + 1))})
    assert rejected.status_code == 413
    assert len(list((upload_root / "tenant_a").iterdir())) == 1
    assert len((await session.scalars(select(File))).all()) == 1


async def test_shop_detail_filter_and_scope(client, seeded_session):
    for shop_id, tenant, city in [("a_sh", "tenant_a", "shanghai"), ("a_bj", "tenant_a", "beijing"), ("b_sh", "tenant_b", "shanghai")]:
        seeded_session.add(Shop(id=shop_id, tenant_id=tenant, name=shop_id, city_code=city,
                                district_code="core", address="road", lng=121.4, lat=31.2))
    await seeded_session.commit()
    headers = await auth_headers(client)
    created = await client.post("/api/v1/forms", headers=headers, json=valid_form(shop_id="a_sh"))
    assert created.status_code == 200, created.text
    form_id = created.json()["id"]
    duplicate = await client.post("/api/v1/forms", headers=headers, json=valid_form(shop_id="a_bj"))
    assert duplicate.json()["id"] == form_id and duplicate.json()["shop_id"] == "a_sh"
    detail = (await client.get(f"/api/v1/forms/{form_id}", headers=headers)).json()
    assert detail["shop_id"] == "a_sh" and detail["shop_name"] == "a_sh" and detail["batch_id"] is None
    assert detail["payload"]["merchant_name"] == "青石小馆"
    listing = (await client.get("/api/v1/forms?shop_id=a_sh", headers=headers)).json()
    assert listing["total"] == 1 and listing["items"][0]["shop_name"] == "a_sh"
    assert (await client.get("/api/v1/forms?shop_id=a_bj", headers=headers)).json()["total"] == 0
    other = await auth_headers(client, "b@example.com", "pass-b")
    assert (await client.get(f"/api/v1/forms/{form_id}", headers=other)).status_code == 404
    assert (await client.get(f"/api/v1/forms/{form_id}")).status_code == 401
    admin = await auth_headers(client, "admin@example.com", "pass-admin")
    assert len((await client.get("/api/v1/shops?own_tenant=true", headers=admin)).json()) == 2
    for shop_id in ["b_sh", "missing"]:
        invalid = await client.post("/api/v1/forms", headers=headers, json=valid_form(shop_id=shop_id))
        assert invalid.status_code == 422
    beijing = await client.post("/api/v1/forms", headers={**headers, "Idempotency-Key": "beijing"}, json=valid_form(city_code="beijing", shop_id="a_bj"))
    operator = await auth_headers(client, "op@example.com", "pass-op")
    assert (await client.get(f"/api/v1/forms/{beijing.json()['id']}", headers=operator)).status_code == 404
    assert (await client.get("/api/v1/forms?shop_id=a_bj", headers=operator)).json()["total"] == 0


@pytest.mark.parametrize("field,value", [
    ("merchant_name", ""), ("merchant_name", "x" * 129), ("license_no", 123),
    ("intro", "x" * 5001), ("contact_phone", "x" * 65), ("reg_capital", -1),
    ("price", True), ("revenue", "100"), ("area_sqm", 1e16), ("order_count", 1.5),
    ("photos", "f_wrong"), ("license_photo", []), ("attachments", ["f_x"] * 21),
])
async def test_known_payload_fields_rejected(client, field, value):
    body = valid_form()
    body["payload"][field] = value
    result = await client.post("/api/v1/forms", headers=await auth_headers(client), json=body)
    assert result.status_code == 422, result.text


async def test_payload_file_references_and_compatible_optional_fields(client, upload_root):
    headers = await auth_headers(client)
    upload = await client.post("/api/v1/files", headers=headers, files={"file": ("note.md", b"note")})
    file_id = upload.json()["file_id"]
    body = valid_form()
    body["payload"].update({"license_photo": file_id, "attachments": [file_id], "intro": "x" * 5000,
                            "reg_capital": 0, "order_count": 2, "custom_unknown": {"anything": True}})
    accepted = await client.post("/api/v1/forms", headers=headers, json=body)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["shop_id"] is None
    assert accepted.json()["payload"]["custom_unknown"] == {"anything": True}
    for refs in [{"license_photo": "f_missing"}, {"photos": ["f_missing"]}]:
        rejected = await client.post("/api/v1/forms", headers=headers, json=valid_form(payload={"merchant_name": "X", "license_no": "Y", **refs}))
        assert rejected.status_code == 422
    other = await auth_headers(client, "b@example.com", "pass-b")
    foreign = await client.post("/api/v1/forms", headers=other, json=body)
    assert foreign.status_code == 422


@pytest.mark.parametrize("form_type,payload", [
    ("property", {"property_name": "门店", "address": "路 1 号", "area_sqm": 50}),
    ("product", {"product_name": "咖啡", "sku": "SKU1", "price": 10}),
    ("report", {"report_name": "月报", "period": "2026-09", "customer_count": 20}),
])
async def test_other_form_types_remain_compatible(client, form_type, payload):
    response = await client.post("/api/v1/forms", headers=await auth_headers(client), json=valid_form(form_type=form_type, payload=payload))
    assert response.status_code == 200, response.text
