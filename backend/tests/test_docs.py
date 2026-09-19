from __future__ import annotations

import pytest
from pymongo import MongoClient

from backend.app.docs_store import DocsRepository, get_docs_repo
from backend.app.main import app
from backend.tests.conftest import login


TEST_MONGO_URL = "mongodb://127.0.0.1:27017"
TEST_DOCS_DB = "merchant_docs_test"


@pytest.fixture
def docs_repo():
    client = MongoClient(TEST_MONGO_URL, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    client.drop_database(TEST_DOCS_DB)
    repo = DocsRepository(client[TEST_DOCS_DB])
    app.dependency_overrides[get_docs_repo] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_docs_repo, None)
    client.drop_database(TEST_DOCS_DB)
    client.close()


async def auth_headers(client, email: str = "a@example.com", password: str = "pass-a") -> dict[str, str]:
    token = await login(client, email, password)
    return {"Authorization": f"Bearer {token}"}


async def create_doc(client, headers: dict[str, str], title: str = "入驻审核规则", content: str = "消防通道必须保持畅通。"):
    response = await client.post("/api/v1/docs", json={"title": title, "content": content}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_docs_crud_search_and_tenant_scope(client, docs_repo):
    headers_a = await auth_headers(client)
    doc = await create_doc(client, headers_a)

    get_response = await client.get(f"/api/v1/docs/{doc['id']}", headers=headers_a)
    assert get_response.status_code == 200
    assert get_response.json()["current_version"] == 1
    assert "消防通道" in get_response.json()["content"]

    search_response = await client.get("/api/v1/docs", params={"q": "消防通道"}, headers=headers_a)
    assert search_response.status_code == 200
    assert search_response.json()["total"] == 1
    assert search_response.json()["items"][0]["id"] == doc["id"]

    headers_b = await auth_headers(client, "b@example.com", "pass-b")
    hidden_response = await client.get(f"/api/v1/docs/{doc['id']}", headers=headers_b)
    assert hidden_response.status_code == 404
    list_b = await client.get("/api/v1/docs", headers=headers_b)
    assert list_b.json()["total"] == 0


async def test_doc_update_requires_current_if_match(client, docs_repo):
    headers = await auth_headers(client)
    doc = await create_doc(client, headers)

    updated = await client.patch(
        f"/api/v1/docs/{doc['id']}",
        json={"title": "入驻审核规则 v2", "content": "许可证必须在有效期内。"},
        headers={**headers, "If-Match": "1"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["current_version"] == 2

    stale = await client.patch(
        f"/api/v1/docs/{doc['id']}",
        json={"title": "旧版本误写", "content": "不应覆盖。"},
        headers={**headers, "If-Match": "1"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"


async def test_doc_soft_delete_is_invisible(client, docs_repo):
    headers = await auth_headers(client)
    doc = await create_doc(client, headers)

    deleted = await client.delete(f"/api/v1/docs/{doc['id']}", headers=headers)
    assert deleted.status_code == 204

    get_response = await client.get(f"/api/v1/docs/{doc['id']}", headers=headers)
    assert get_response.status_code == 404
    list_response = await client.get("/api/v1/docs", headers=headers)
    assert list_response.json()["total"] == 0
    stored = docs_repo.docs.find_one({"_id": doc["id"]})
    assert stored["status"] == "deleted"
    assert stored["deleted_at"] is not None


async def test_doc_rollback_creates_new_version_from_history(client, docs_repo):
    headers = await auth_headers(client)
    doc = await create_doc(client, headers, content="旧版：只检查营业执照。")
    updated = await client.patch(
        f"/api/v1/docs/{doc['id']}",
        json={"title": "入驻审核规则 v2", "content": "新版：新增房源材料检查。"},
        headers={**headers, "If-Match": "1"},
    )
    assert updated.status_code == 200

    rolled_back = await client.post(f"/api/v1/docs/{doc['id']}/rollback", json={"version_no": 1}, headers=headers)
    assert rolled_back.status_code == 200, rolled_back.text
    body = rolled_back.json()
    assert body["current_version"] == 3
    assert body["content"] == "旧版：只检查营业执照。"

    versions = list(docs_repo.versions.find({"doc_id": doc["id"]}).sort("version_no", 1))
    assert [item["version_no"] for item in versions] == [1, 2, 3]
    assert versions[2]["rollback_from_version"] == 1
