from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from backend.app import dlq_worker
from backend.app.batch_pipeline import run_batch
from backend.app.models import (
    Batch, BatchCheckpoint, BatchItem, BatchStatus, DLQItem, DLQState,
    Form, FormStatus, FormType, SubmissionEvent, SubmissionEventType,
)
from backend.app.realtime import subscribe, unsubscribe
from backend.tests.test_batch_pipeline import make_form
from scripts.load_seed import ensure_v6_schema

pytestmark = pytest.mark.asyncio
ROOT = Path(__file__).resolve().parents[2]


async def failed_batch(session, idx: int):
    form = make_form(idx, FormType.product, payload_extra={"force_dlq_stage": "product_pipeline"})
    batch = Batch(
        id=f"dlq_batch_{idx}", tenant_id=form.tenant_id, city_code=form.city_code,
        status=BatchStatus.created, center_lng=form.lng, center_lat=form.lat, capacity=50, item_count=1,
    )
    form.status = FormStatus.batched
    form.batch_id = batch.id
    session.add_all([batch, form, BatchItem(batch_id=batch.id, form_id=form.id, distance_m=0)])
    await session.commit()
    result = await run_batch(session, batch)
    await session.commit()
    assert result.status == BatchStatus.failed
    item = await session.scalar(select(DLQItem).where(DLQItem.form_id == form.id))
    assert item is not None
    assert item.state == DLQState.pending
    assert item.retry_count == form.retry_count == 1
    return batch, form, item


async def event_count(session):
    return await session.scalar(select(func.count()).select_from(SubmissionEvent))


async def snapshot(session, batch, form, item, now=None):
    for obj in (batch, form, item):
        await session.refresh(obj)
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "injected_now": now.isoformat() if now else None,
        "form_status": form.status.value, "form_retry_count": form.retry_count,
        "retry_count": item.retry_count, "next_retry_at": item.next_retry_at.isoformat(),
        "state": item.state.value, "batch_status": batch.status.value,
        "business_events": await session.scalar(select(func.count()).select_from(SubmissionEvent).where(
            SubmissionEvent.form_id == form.id, SubmissionEvent.event_type == SubmissionEventType.business_published,
        )),
    }


async def test_real_retry_success_and_exhaustion_timeline(seeded_session):
    session = seeded_session
    batch, form, item = await failed_batch(session, 1)
    success = [await snapshot(session, batch, form, item)]
    form.payload = {key: value for key, value in form.payload.items() if key != "force_dlq_stage"}
    await session.commit()
    now = item.next_retry_at
    queue = await subscribe(form.tenant_id)
    try:
        assert await dlq_worker.process_dlq_once(session, now=now) == 1
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert [(event.type, event.payload["status"]) for event in events] == [
            ("form.status_changed", "published"), ("batch.status_changed", "completed"),
        ]
    finally:
        unsubscribe(form.tenant_id, queue)
    success.append(await snapshot(session, batch, form, item, now))
    assert form.status == FormStatus.published
    assert batch.status == BatchStatus.completed
    assert item.state == DLQState.resolved
    checkpoint = await session.get(BatchCheckpoint, {"batch_id": batch.id, "stage": item.stage})
    assert checkpoint is not None and checkpoint.last_form_id == form.id
    assert success[-1]["business_events"] == 1
    assert await dlq_worker.process_dlq_once(session, now=now + timedelta(days=1)) == 0
    assert await event_count(session) == 1

    batch, form, item = await failed_batch(session, 2)
    failure = [await snapshot(session, batch, form, item)]
    for count in (2, 3):
        now = item.next_retry_at
        assert await dlq_worker.process_dlq_once(session, now=now) == 1
        failure.append(await snapshot(session, batch, form, item, now))
        assert item.retry_count == form.retry_count == count
        assert item.state == (DLQState.pending if count < 3 else DLQState.exhausted)
        assert form.status == FormStatus.failed and batch.status == BatchStatus.failed
        if count < 3:
            assert item.next_retry_at == now + timedelta(minutes=2 ** count)
        assert failure[-1]["business_events"] == 0
    assert await dlq_worker.process_dlq_once(session, now=now + timedelta(days=1)) == 0
    assert await session.get(BatchCheckpoint, {"batch_id": batch.id, "stage": item.stage}) is None
    evidence = {"database": await session.scalar(text("SELECT DATABASE()")), "success": success, "exhaustion": failure}
    assert evidence["database"] == "merchant_test"
    destination = ROOT / "artifacts/data/p15_dlq.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("status", [FormStatus.published, FormStatus.withdrawn, None])
async def test_terminal_or_missing_form_is_resolved_without_new_events(seeded_session, status):
    session = seeded_session
    batch, form, item = await failed_batch(session, 3)
    if status is None:
        await session.delete(form)
    else:
        form.status = status
    await session.commit()
    before = await event_count(session)
    assert await dlq_worker.process_dlq_once(session, now=item.next_retry_at) == 1
    await session.refresh(item)
    assert item.state == DLQState.resolved and item.retry_count == 1
    assert await event_count(session) == before
    assert await dlq_worker.process_dlq_once(session, now=item.next_retry_at + timedelta(days=1)) == 0


@pytest.mark.parametrize("state,offset", [
    (DLQState.pending, -1), (DLQState.resolved, 1), (DLQState.exhausted, 1),
])
async def test_scan_filters_due_time_and_state(seeded_session, state, offset):
    session = seeded_session
    batch, form, item = await failed_batch(session, 4)
    item.state = state
    await session.commit()
    due = item.next_retry_at
    assert await dlq_worker.process_dlq_once(session, now=due + timedelta(seconds=offset)) == 0
    await session.refresh(item)
    assert item.state == state and item.retry_count == 1 and item.next_retry_at == due
    assert form.status == FormStatus.failed and batch.status == BatchStatus.failed
    assert await event_count(session) == 0


async def test_required_payload_failure_retries_and_exhausts(seeded_session):
    session = seeded_session
    batch, form, item = await failed_batch(session, 5)
    form.payload = {}
    await session.commit()
    for count in (2, 3):
        assert await dlq_worker.process_dlq_once(session, now=item.next_retry_at) == 1
        await session.refresh(item)
        assert item.retry_count == count and item.error_code == "validation_failed"
    assert item.state == DLQState.exhausted
    assert form.status == FormStatus.failed and batch.status == BatchStatus.failed
    assert await event_count(session) == 0


async def test_fail_fast_unprocessed_members_do_not_auto_complete_batch(seeded_session):
    session = seeded_session
    batch, form, item = await failed_batch(session, 6)
    other = make_form(7, FormType.report)
    other.status, other.batch_id = FormStatus.batched, batch.id
    batch.item_count = 2
    form.payload = {"product_name": "retry", "sku": "retry"}
    session.add_all([other, BatchItem(batch_id=batch.id, form_id=other.id, distance_m=0)])
    await session.commit()
    assert await dlq_worker.process_dlq_once(session, now=item.next_retry_at) == 1
    await session.refresh(batch)
    assert batch.status == BatchStatus.failed
    assert form.status == FormStatus.published and other.status == FormStatus.batched
    await run_batch(session, batch)
    await session.commit()
    assert batch.status == BatchStatus.completed and other.status == FormStatus.published
    assert await event_count(session) == 2


async def test_one_exception_rolls_back_only_that_item_and_continues(seeded_session, monkeypatch, caplog):
    session = seeded_session
    entries = [await failed_batch(session, idx) for idx in (8, 9, 10)]
    now = max(item.next_retry_at for _, _, item in entries)
    for _, form, _ in entries:
        form.payload = {"product_name": "retry", "sku": "retry"}
    await session.commit()
    broken_id = entries[1][1].id
    original = dlq_worker.payload_is_valid

    def injected_failure(form):
        if form.id == broken_id:
            raise RuntimeError("test_item_failure")
        return original(form)

    monkeypatch.setattr(dlq_worker, "payload_is_valid", injected_failure)
    assert await dlq_worker.process_dlq_once(session, now=now) == 2
    for index, (batch, form, item) in enumerate(entries):
        for obj in (batch, form, item):
            await session.refresh(obj)
        assert item.state == (DLQState.pending if index == 1 else DLQState.resolved)
        assert form.status == (FormStatus.failed if index == 1 else FormStatus.published)
        assert batch.status == (BatchStatus.failed if index == 1 else BatchStatus.completed)
    assert "dlq_item_failed" in caplog.text
    assert await event_count(session) == 2


async def test_scan_order_and_twenty_item_limit(seeded_session):
    session = seeded_session
    entries = [await failed_batch(session, idx) for idx in range(11, 32)]
    now = max(item.next_retry_at for _, _, item in entries) + timedelta(minutes=1)
    for offset, (_, _, item) in enumerate(reversed(entries)):
        item.next_retry_at = now - timedelta(seconds=30 - offset)
    await session.commit()
    assert await dlq_worker.process_dlq_once(session, now=now) == 20
    for _, _, item in entries:
        await session.refresh(item)
    assert entries[0][2].retry_count == 1
    assert all(item.retry_count == 2 for _, _, item in entries[1:])
    assert await event_count(session) == 0


async def test_manual_exhaustion_cannot_be_retried_via_an_old_dlq_row(seeded_session):
    session = seeded_session
    batch, form, item = await failed_batch(session, 32)
    form.retry_count = 3
    await session.commit()
    assert await dlq_worker.process_dlq_once(session, now=item.next_retry_at) == 1
    await session.refresh(item)
    assert item.retry_count == 3 and item.state == DLQState.exhausted
    assert form.status == FormStatus.failed and batch.status == BatchStatus.failed
    assert await event_count(session) == 0


async def test_v6_upgrade_preserves_rows_and_is_idempotent(seeded_session):
    session = seeded_session
    batch, form, item = await failed_batch(session, 33)
    item_id = item.id
    item.retry_count = 3
    await session.commit()
    await session.execute(text("ALTER TABLE dlq_items DROP INDEX ix_dlq_items_state"))
    await session.execute(text("ALTER TABLE dlq_items DROP COLUMN state"))
    await session.commit()
    connection = await session.connection()
    await ensure_v6_schema(connection)
    await ensure_v6_schema(connection)
    await session.commit()
    await session.refresh(item)
    assert item.id == item_id and item.retry_count == 3 and item.state == DLQState.exhausted
    assert await session.scalar(text("SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='dlq_items' AND COLUMN_NAME='state'")) == 1
    assert form.status == FormStatus.failed and batch.status == BatchStatus.failed
