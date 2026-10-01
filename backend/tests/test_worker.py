from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from backend.app.models import Form, FormAuditEvent, FormStatus, FormType
from backend.app.realtime import events_since
from backend.app.status_worker import process_status_once

pytestmark = pytest.mark.asyncio


def make_submitted(form_id: str, payload: dict, *, lat: float = 31.2304, lng: float = 121.4737) -> Form:
    now = datetime(2026, 9, 20, 9, 0, 0)
    return Form(
        id=form_id,
        tenant_id="tenant_a",
        form_type=FormType.merchant_info,
        status=FormStatus.submitted,
        idempotency_key=f"idem_{form_id}",
        city_code="shanghai",
        district_code="core",
        industry="restaurant",
        lng=lng,
        lat=lat,
        payload=payload,
        created_by="user_a",
        created_at=now,
        updated_at=now,
    )


async def test_process_status_once_validates_complete_submitted_form(session):
    form = make_submitted("worker_ok", {"merchant_name": "青石小馆", "license_no": "LIC-001"})
    session.add(form)
    await session.commit()

    changed = await process_status_once(session)

    assert changed == 2
    refreshed = await session.get(Form, form.id)
    assert refreshed is not None
    assert refreshed.status == FormStatus.validated
    audits = (await session.execute(select(FormAuditEvent).where(FormAuditEvent.form_id == form.id).order_by(FormAuditEvent.id))).scalars().all()
    assert [(item.from_status, item.to_status) for item in audits] == [("submitted", "validating"), ("validating", "validated")]
    assert all(item.actor_id == "system_worker" for item in audits)
    events = [item for item in events_since("tenant_a", 0) if item["payload"].get("form_id") == form.id]
    assert [item["payload"]["status"] for item in events[-2:]] == ["validating", "validated"]


async def test_process_status_once_rejects_incomplete_payload(session):
    form = make_submitted("worker_bad", {"merchant_name": "青石小馆"})
    session.add(form)
    await session.commit()

    changed = await process_status_once(session)

    assert changed == 2
    refreshed = await session.get(Form, form.id)
    assert refreshed is not None
    assert refreshed.status == FormStatus.rejected


async def test_process_status_once_is_idempotent_after_terminal_status(session):
    form = make_submitted("worker_once", {"merchant_name": "青石小馆", "license_no": "LIC-001"})
    session.add(form)
    await session.commit()

    assert await process_status_once(session) == 2
    assert await process_status_once(session) == 0
