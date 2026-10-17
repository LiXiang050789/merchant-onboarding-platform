from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .batch_pipeline import ensure_business_event, payload_is_valid, should_fail, upsert_checkpoint
from .db import SessionLocal
from .models import Batch, BatchItem, BatchStatus, DLQItem, DLQState, Form, FormStatus
from .realtime import publish_event

logger = logging.getLogger(__name__)


async def converge_batch(session: AsyncSession, item: DLQItem, now: datetime) -> list[tuple[str, str, dict]]:
    batches = list((await session.scalars(
        select(Batch).join(BatchItem, BatchItem.batch_id == Batch.id)
        .where(BatchItem.form_id == item.form_id, Batch.tenant_id == item.tenant_id)
        .with_for_update()
    )).all())
    events = []
    for batch in batches:
        forms = list((await session.scalars(
            select(Form).join(BatchItem, BatchItem.form_id == Form.id).where(BatchItem.batch_id == batch.id)
        )).all())
        if not forms or not all(
            form.status in {FormStatus.published, FormStatus.withdrawn}
            or (form.status == FormStatus.failed and form.retry_count >= 3)
            for form in forms
        ):
            continue
        target = BatchStatus.failed if any(form.status == FormStatus.failed for form in forms) else BatchStatus.completed
        if batch.status != target:
            batch.status = target
            batch.updated_at = now
            events.append((batch.tenant_id, "batch.status_changed", {"batch_id": batch.id, "status": target.value}))
    return events


async def process_dlq_once(session: AsyncSession, now: datetime | None = None) -> int:
    now = datetime.now(UTC).replace(tzinfo=None) if now is None else now
    if now.tzinfo is not None:
        now = now.astimezone(UTC).replace(tzinfo=None)
    eligible = (
        DLQItem.state == DLQState.pending,
        DLQItem.next_retry_at <= now,
        DLQItem.retry_count < 3,
    )
    ids = list((await session.scalars(
        select(DLQItem.id).where(*eligible).order_by(DLQItem.next_retry_at, DLQItem.id).limit(20)
    )).all())
    await session.commit()
    processed = 0
    for item_id in ids:
        try:
            item = await session.scalar(
                select(DLQItem).where(DLQItem.id == item_id, *eligible).with_for_update()
                .execution_options(populate_existing=True)
            )
            if item is None:
                await session.rollback()
                continue
            form = await session.scalar(
                select(Form).where(Form.id == item.form_id, Form.tenant_id == item.tenant_id)
                .with_for_update().execution_options(populate_existing=True)
            )
            events = []
            if form is None or form.status in {FormStatus.withdrawn, FormStatus.published}:
                item.state = DLQState.resolved
            elif form.retry_count >= 3:
                # A manual run or an older DLQ row may have used the retry budget.
                item.retry_count = form.retry_count
                item.state = DLQState.exhausted
            else:
                form.status = FormStatus.processing
                valid = payload_is_valid(form)
                if valid and not should_fail(form, item.stage):
                    form.status = FormStatus.published
                    await ensure_business_event(session, form)
                    if form.batch_id:
                        await upsert_checkpoint(session, form.batch_id, item.stage, form.id)
                    item.state = DLQState.resolved
                else:
                    form.status = FormStatus.failed
                    form.retry_count = max(form.retry_count, item.retry_count) + 1
                    item.retry_count = form.retry_count
                    item.error_code = "pipeline_failed" if valid else "validation_failed"
                    item.error_message = "forced pipeline failure" if valid else "required payload fields missing"
                    item.state = DLQState.exhausted if item.retry_count >= 3 else DLQState.pending
                    if item.state == DLQState.pending:
                        item.next_retry_at = now + timedelta(minutes=2 ** item.retry_count)
                form.updated_at = now
                events.append((form.tenant_id, "form.status_changed", {"form_id": form.id, "status": form.status.value}))
            await session.flush()
            events.extend(await converge_batch(session, item, now))
            state, retry_count = item.state.value, item.retry_count
            await session.commit()
            processed += 1
            logger.info("dlq_item_processed id=%s state=%s retry_count=%s", item_id, state, retry_count)
            for tenant_id, kind, payload in events:
                await publish_event(tenant_id, kind, payload)
        except Exception:
            # Roll back only this item; committed predecessors remain durable.
            await session.rollback()
            logger.exception("dlq_item_failed id=%s", item_id)
    return processed


async def dlq_worker_loop(interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with SessionLocal() as session:
                await process_dlq_once(session)
        except Exception:
            # A failed scan must not stop the API or subsequent retry ticks.
            logger.exception("dlq_worker_failed")


def start_dlq_worker(interval_seconds: int) -> asyncio.Task:
    return asyncio.create_task(dlq_worker_loop(interval_seconds))


async def stop_dlq_worker(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
