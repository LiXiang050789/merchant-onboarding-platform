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


async def test_refresh_accepts_only_refresh_token(client):
    login_response = await client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "pass-a"})
    refresh_token = login_response.json()["refresh_token"]
    access_token = login_response.json()["access_token"]

    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    rejected = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})

    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]
    assert rejected.status_code == 401
    assert rejected.json()["code"] == "unauthorized"
