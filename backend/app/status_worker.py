from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .db import SessionLocal
from .models import Form, FormAuditEvent, FormStatus
from .realtime import publish_event
from .schemas import REQUIRED_BY_TYPE

SYSTEM_ACTOR_ID = "system_worker"


def payload_is_complete(form: Form) -> bool:
    return not (REQUIRED_BY_TYPE[form.form_type] - form.payload.keys()) and 73 <= form.lng <= 135 and 18 <= form.lat <= 54


async def audit_status(session: AsyncSession, form: Form, previous: FormStatus, target: FormStatus) -> None:
    session.add(
        FormAuditEvent(
            tenant_id=form.tenant_id,
            form_id=form.id,
            actor_id=SYSTEM_ACTOR_ID,
            event_type="status_auto_changed",
            from_status=previous.value,
            to_status=target.value,
            payload_hash="system_worker",
        )
    )


async def transition_form(session: AsyncSession, form: Form, expected: FormStatus, target: FormStatus) -> bool:
    now = datetime.now(UTC).replace(tzinfo=None)
    result = await session.execute(
        update(Form)
        .where(Form.id == form.id, Form.status == expected)
        .values(status=target, updated_at=now)
    )
    if result.rowcount != 1:
        return False
    form.status = target
    form.updated_at = now
    await audit_status(session, form, expected, target)
    return True


async def process_status_once(session: AsyncSession, *, limit: int = 50) -> int:
    result = await session.execute(
        select(Form)
        .where(Form.status.in_([FormStatus.submitted, FormStatus.validating]))
        .order_by(Form.created_at.asc(), Form.id.asc())
        .limit(limit)
    )
    forms = list(result.scalars())
    changed = 0
    events: list[tuple[str, str, str]] = []
    for form in forms:
        if form.status == FormStatus.submitted:
            if await transition_form(session, form, FormStatus.submitted, FormStatus.validating):
                changed += 1
                events.append((form.tenant_id, form.id, FormStatus.validating.value))
        if form.status == FormStatus.validating:
            target = FormStatus.validated if payload_is_complete(form) else FormStatus.rejected
            if await transition_form(session, form, FormStatus.validating, target):
                changed += 1
                events.append((form.tenant_id, form.id, target.value))
    await session.commit()
    for tenant_id, form_id, status in events:
        await publish_event(tenant_id, "form.status_changed", {"form_id": form_id, "status": status})
    return changed


async def status_worker_loop(interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with SessionLocal() as session:
                await process_status_once(session)
        except Exception:
            # Worker failure must not affect the API process; next tick retries.
            pass


def start_status_worker(interval_seconds: int) -> asyncio.Task:
    return asyncio.create_task(status_worker_loop(interval_seconds))


async def stop_status_worker(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
