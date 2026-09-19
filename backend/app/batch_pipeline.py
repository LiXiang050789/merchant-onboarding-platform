from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .aggregation import PointSet, greedy_batches_grid, haversine_meters
from .models import (
    Batch,
    BatchCheckpoint,
    BatchItem,
    BatchStatus,
    DLQItem,
    Form,
    FormStatus,
    FormType,
    SubmissionEvent,
    SubmissionEventType,
    User,
    UserRole,
)
from .schemas import REQUIRED_BY_TYPE


PIPELINE_STAGE = {
    FormType.merchant_info: "merchant_info_pipeline",
    FormType.property: "property_pipeline",
    FormType.product: "product_pipeline",
    FormType.report: "report_pipeline",
}


@dataclass(frozen=True)
class RunSummary:
    batch_id: str
    status: BatchStatus
    processed: int
    published: int
    failed: int
    checkpoint_stages: list[str]


def scoped_batches(stmt: Select[tuple[Batch]], actor: User) -> Select[tuple[Batch]]:
    if actor.role == UserRole.admin:
        return stmt
    stmt = stmt.where(Batch.tenant_id == actor.tenant_id)
    if actor.role == UserRole.operator and actor.region_code:
        stmt = stmt.where(Batch.city_code == actor.region_code)
    return stmt


def forms_to_points(forms: list[Form]) -> PointSet:
    return PointSet(
        ids=np.array([item.id for item in forms], dtype=object),
        tenant_ids=np.array([item.tenant_id for item in forms], dtype=object),
        form_types=np.array([item.form_type.value for item in forms], dtype=object),
        statuses=np.array([item.status.value for item in forms], dtype=object),
        city_codes=np.array([item.city_code for item in forms], dtype=object),
        industries=np.array([item.industry for item in forms], dtype=object),
        lng=np.array([item.lng for item in forms], dtype=np.float64),
        lat=np.array([item.lat for item in forms], dtype=np.float64),
    )


async def build_batches(
    session: AsyncSession,
    actor: User,
    *,
    city: str | None,
    form_type: FormType | None,
    capacity: int,
    radius_m: int,
) -> tuple[list[Batch], int]:
    stmt = select(Form).where(Form.status == FormStatus.validated)
    if actor.role != UserRole.admin:
        stmt = stmt.where(Form.tenant_id == actor.tenant_id)
    if actor.role == UserRole.operator and actor.region_code:
        stmt = stmt.where(Form.city_code == actor.region_code)
    if city:
        stmt = stmt.where(Form.city_code == city)
    if form_type:
        stmt = stmt.where(Form.form_type == form_type)
    result = await session.execute(stmt.order_by(Form.city_code, Form.id))
    forms = list(result.scalars())
    by_city: dict[str, list[Form]] = {}
    for form in forms:
        by_city.setdefault(form.city_code, []).append(form)

    created: list[Batch] = []
    now = datetime.now(UTC).replace(tzinfo=None)
    for city_code, city_forms in by_city.items():
        points = forms_to_points(city_forms)
        batches = greedy_batches_grid(points, capacity=capacity, radius_m=radius_m)
        for members in batches:
            seed = members[0]
            member_array = np.array(members, dtype=np.int64)
            distances = haversine_meters(points.lng[seed], points.lat[seed], points.lng[member_array], points.lat[member_array])
            batch = Batch(
                id=f"batch_{uuid4().hex[:19]}",
                tenant_id=city_forms[0].tenant_id,
                city_code=city_code,
                status=BatchStatus.created,
                center_lng=float(np.mean(points.lng[member_array])),
                center_lat=float(np.mean(points.lat[member_array])),
                capacity=capacity,
                item_count=len(members),
                created_at=now,
                updated_at=now,
            )
            session.add(batch)
            created.append(batch)
            for member, distance in zip(members, distances):
                form = city_forms[member]
                form.status = FormStatus.batched
                form.batch_id = batch.id
                form.updated_at = now
                session.add(BatchItem(batch_id=batch.id, form_id=form.id, distance_m=int(round(float(distance)))))
    await session.flush()
    return created, len(forms)


async def get_batch_for_actor(session: AsyncSession, actor: User, batch_id: str) -> Batch | None:
    result = await session.execute(scoped_batches(select(Batch).where(Batch.id == batch_id), actor))
    return result.scalar_one_or_none()


async def list_batches(session: AsyncSession, actor: User, *, page: int, size: int) -> tuple[list[Batch], int]:
    stmt = scoped_batches(select(Batch), actor)
    total = int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    result = await session.execute(stmt.order_by(Batch.created_at.desc(), Batch.id.desc()).offset((page - 1) * size).limit(size))
    return list(result.scalars()), total


def payload_is_valid(form: Form) -> bool:
    return not (REQUIRED_BY_TYPE[form.form_type] - form.payload.keys())


def should_fail(form: Form, stage: str) -> bool:
    forced = form.payload.get("force_dlq_stage")
    return forced in {True, stage}


async def upsert_checkpoint(session: AsyncSession, batch_id: str, stage: str, form_id: str) -> None:
    checkpoint = await session.get(BatchCheckpoint, {"batch_id": batch_id, "stage": stage})
    now = datetime.now(UTC).replace(tzinfo=None)
    if checkpoint is None:
        session.add(BatchCheckpoint(batch_id=batch_id, stage=stage, last_form_id=form_id, updated_at=now))
    else:
        checkpoint.last_form_id = form_id
        checkpoint.updated_at = now


async def ensure_business_event(session: AsyncSession, form: Form) -> None:
    existing = await session.scalar(
        select(SubmissionEvent.id).where(
            SubmissionEvent.tenant_id == form.tenant_id,
            SubmissionEvent.form_id == form.id,
            SubmissionEvent.event_type == SubmissionEventType.business_published,
        )
    )
    if existing:
        return
    now = datetime.now(UTC).replace(tzinfo=None)
    session.add(
        SubmissionEvent(
            tenant_id=form.tenant_id,
            form_id=form.id,
            idempotency_key=form.idempotency_key,
            event_type=SubmissionEventType.business_published,
            client_trace_id=uuid4().hex[:26],
            occurred_at=now,
            received_at=now,
            meta={"source": "batch_pipeline"},
        )
    )


async def write_dlq(session: AsyncSession, form: Form, stage: str, error_code: str, message: str) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    form.retry_count += 1
    form.status = FormStatus.failed
    form.updated_at = now
    delay_minutes = 2 ** min(form.retry_count, 6)
    session.add(
        DLQItem(
            tenant_id=form.tenant_id,
            form_id=form.id,
            stage=stage,
            error_code=error_code,
            error_message=message[:255],
            retry_count=form.retry_count,
            next_retry_at=now + timedelta(minutes=delay_minutes),
            created_at=now,
        )
    )


async def run_batch(session: AsyncSession, batch: Batch) -> RunSummary:
    if batch.status == BatchStatus.completed:
        checkpoints = await checkpoint_stages(session, batch.id)
        return RunSummary(batch.id, batch.status, 0, 0, 0, checkpoints)

    now = datetime.now(UTC).replace(tzinfo=None)
    batch.status = BatchStatus.processing
    batch.updated_at = now
    result = await session.execute(
        select(Form)
        .join(BatchItem, BatchItem.form_id == Form.id)
        .where(BatchItem.batch_id == batch.id)
        .order_by(Form.form_type, Form.id)
    )
    forms = list(result.scalars())
    processed = 0
    published = 0
    failed = 0

    for form in forms:
        stage = PIPELINE_STAGE[form.form_type]
        if form.status == FormStatus.published:
            continue
        if form.status == FormStatus.failed and form.retry_count >= 3:
            failed += 1
            continue
        form.status = FormStatus.processing
        form.updated_at = now
        if not payload_is_valid(form):
            await write_dlq(session, form, stage, "validation_failed", "required payload fields missing")
            batch.status = BatchStatus.failed
            batch.updated_at = now
            failed += 1
            await session.flush()
            return RunSummary(batch.id, batch.status, processed, published, failed, await checkpoint_stages(session, batch.id))
        if should_fail(form, stage):
            await write_dlq(session, form, stage, "pipeline_failed", "forced pipeline failure")
            batch.status = BatchStatus.failed
            batch.updated_at = now
            failed += 1
            await session.flush()
            return RunSummary(batch.id, batch.status, processed, published, failed, await checkpoint_stages(session, batch.id))
        form.status = FormStatus.published
        form.updated_at = now
        await ensure_business_event(session, form)
        await upsert_checkpoint(session, batch.id, stage, form.id)
        processed += 1
        published += 1

    batch.status = BatchStatus.completed if failed == 0 else BatchStatus.failed
    batch.updated_at = now
    await session.flush()
    return RunSummary(batch.id, batch.status, processed, published, failed, await checkpoint_stages(session, batch.id))


async def checkpoint_stages(session: AsyncSession, batch_id: str) -> list[str]:
    result = await session.execute(select(BatchCheckpoint.stage).where(BatchCheckpoint.batch_id == batch_id).order_by(BatchCheckpoint.stage))
    return list(result.scalars())
