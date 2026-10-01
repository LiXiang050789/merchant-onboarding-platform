from __future__ import annotations

import asyncio

import pytest

from backend.app.realtime import GLOBAL_TOPIC, _events, _subscribers, publish_event, subscribe, unsubscribe
from backend.tests.conftest import login

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def clear_realtime_state():
    _events.clear()
    _subscribers.clear()
    yield
    _events.clear()
    _subscribers.clear()


async def test_global_subscriber_receives_all_tenants_but_tenant_scope_stays_isolated():
    global_queue = await subscribe(GLOBAL_TOPIC)
    tenant_b_queue = await subscribe("tenant_b")
    tenant_a_queue = await subscribe("tenant_a")
    try:
        event = await publish_event("tenant_b", "batch.progress", {"batch_id": "batch_scope", "processed": 1, "total": 1})

        assert await asyncio.wait_for(global_queue.get(), timeout=0.2) == event
        assert await asyncio.wait_for(tenant_b_queue.get(), timeout=0.2) == event
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(tenant_a_queue.get(), timeout=0.05)
    finally:
        unsubscribe(GLOBAL_TOPIC, global_queue)
        unsubscribe("tenant_b", tenant_b_queue)
        unsubscribe("tenant_a", tenant_a_queue)


async def test_admin_poll_events_can_see_other_tenant_events(client):
    await publish_event("tenant_b", "batch.status_changed", {"batch_id": "batch_other", "status": "completed"})
    token = await login(client, "admin@example.com", "pass-admin")

    response = await client.get("/api/v1/events?since=0", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    events = response.json()["events"]
    assert any(item["payload"].get("batch_id") == "batch_other" for item in events)


async def test_tenant_poll_events_cannot_see_other_tenant_events(client):
    await publish_event("tenant_b", "batch.status_changed", {"batch_id": "batch_hidden", "status": "completed"})
    await publish_event("tenant_a", "batch.status_changed", {"batch_id": "batch_visible", "status": "completed"})
    token = await login(client, "a@example.com", "pass-a")

    response = await client.get("/api/v1/events?since=0", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    batch_ids = {item["payload"].get("batch_id") for item in response.json()["events"]}
    assert "batch_visible" in batch_ids
    assert "batch_hidden" not in batch_ids
