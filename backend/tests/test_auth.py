from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_login_issues_access_and_refresh_tokens(client):
    response = await client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "pass-a"})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] == 1800


async def test_login_rejects_wrong_password(client):
    response = await client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
