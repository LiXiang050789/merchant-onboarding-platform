from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Form, FormAuditEvent, FormStatus, User, UserRole
from .schemas import FormCreate


@dataclass(frozen=True)
class Page:
    items: list[Form]
    total: int


class FormRepository:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    def scoped(self, stmt: Select[tuple[Form]]) -> Select[tuple[Form]]:
        if self.actor.role == UserRole.admin:
            return stmt
        stmt = stmt.where(Form.tenant_id == self.actor.tenant_id)
        if self.actor.role == UserRole.operator and self.actor.region_code:
            stmt = stmt.where(Form.city_code == self.actor.region_code)
        return stmt

    async def get(self, form_id: str) -> Form | None:
        result = await self.session.execute(self.scoped(select(Form).where(Form.id == form_id)))
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        city: str | None,
        status: FormStatus | None,
        form_type: str | None,
        industry: str | None,
        page: int,
        size: int,
    ) -> Page:
        stmt = self.scoped(select(Form))
        if city:
            stmt = stmt.where(Form.city_code == city)
        if status:
            stmt = stmt.where(Form.status == status)
        if form_type:
            stmt = stmt.where(Form.form_type == form_type)
        if industry:
            stmt = stmt.where(Form.industry == industry)

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = int(await self.session.scalar(total_stmt) or 0)
        result = await self.session.execute(
            stmt.order_by(Form.created_at.desc(), Form.id.desc()).offset((page - 1) * size).limit(size)
        )
        return Page(items=list(result.scalars()), total=total)

    async def create(self, payload: FormCreate, idempotency_key: str) -> tuple[Form, bool]:
        existing = await self.session.scalar(
            self.scoped(select(Form).where(Form.idempotency_key == idempotency_key))
        )
        if existing:
            return existing, False

        now = datetime.now(UTC).replace(tzinfo=None)
        form = Form(
            id=f"form_{uuid4().hex[:20]}",
            tenant_id=self.actor.tenant_id,
            form_type=payload.form_type,
            status=FormStatus.submitted,
            idempotency_key=idempotency_key,
            city_code=payload.city_code,
            district_code=payload.district_code,
            industry=payload.industry,
            lng=payload.lng,
            lat=payload.lat,
            payload=payload.payload,
            created_by=self.actor.id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(form)
        await self.session.flush()
        await self.audit(form, "form_created", None, FormStatus.submitted)
        return form, True

    async def audit(
        self,
        form: Form,
        event_type: str,
        from_status: FormStatus | None,
        to_status: FormStatus | None,
    ) -> None:
        digest = hashlib.sha256(json.dumps(form.payload, sort_keys=True).encode()).hexdigest()
        self.session.add(
            FormAuditEvent(
                tenant_id=form.tenant_id,
                form_id=form.id,
                actor_id=self.actor.id,
                event_type=event_type,
                from_status=from_status.value if from_status else None,
                to_status=to_status.value if to_status else None,
                payload_hash=digest,
            )
        )
