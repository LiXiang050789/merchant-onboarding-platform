from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class RealtimeEvent:
    seq: int
    tenant_id: str
    type: str
    payload: dict[str, Any]
    sent_at: str


_events: deque[RealtimeEvent] = deque(maxlen=1000)
_subscribers: dict[str, set[asyncio.Queue[RealtimeEvent]]] = {}
_seq = 0


def event_to_dict(event: RealtimeEvent) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "type": event.type,
        "payload": event.payload,
        "sent_at": event.sent_at,
    }


async def publish_event(tenant_id: str, event_type: str, payload: dict[str, Any]) -> RealtimeEvent:
    global _seq
    _seq += 1
    event = RealtimeEvent(
        seq=_seq,
        tenant_id=tenant_id,
        type=event_type,
        payload=payload,
        sent_at=datetime.now(UTC).isoformat(),
    )
    _events.append(event)
    for queue in list(_subscribers.get(tenant_id, set())):
        await queue.put(event)
    return event


def events_since(tenant_id: str, seq: int) -> list[dict[str, Any]]:
    return [event_to_dict(event) for event in _events if event.tenant_id == tenant_id and event.seq > seq]


async def subscribe(tenant_id: str) -> asyncio.Queue[RealtimeEvent]:
    queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=100)
    _subscribers.setdefault(tenant_id, set()).add(queue)
    return queue


def unsubscribe(tenant_id: str, queue: asyncio.Queue[RealtimeEvent]) -> None:
    subscribers = _subscribers.get(tenant_id)
    if subscribers is None:
        return
    subscribers.discard(queue)
    if not subscribers:
        _subscribers.pop(tenant_id, None)
