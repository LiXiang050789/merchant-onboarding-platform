from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, Index, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class TenantStatus(StrEnum):
    active = "active"
    disabled = "disabled"


class UserRole(StrEnum):
    merchant = "merchant"
    operator = "operator"
    admin = "admin"


class FormType(StrEnum):
    merchant_info = "merchant_info"
    property = "property"
    product = "product"
    report = "report"


class FormStatus(StrEnum):
    draft = "draft"
    submitted = "submitted"
    validating = "validating"
    validated = "validated"
    rejected = "rejected"
    batched = "batched"
    processing = "processing"
    published = "published"
    failed = "failed"


class SubmissionEventType(StrEnum):
    submit_attempt = "submit_attempt"
    submit_api_success = "submit_api_success"
    submit_api_failed = "submit_api_failed"
    db_insert_success = "db_insert_success"
    validation_failed = "validation_failed"
    business_published = "business_published"


class BatchStatus(StrEnum):
    created = "created"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[TenantStatus] = mapped_column(Enum(TenantStatus), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(26), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    region_code: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Form(Base):
    __tablename__ = "forms"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_forms_tenant_idempotency"),
        Index("ix_forms_tenant_status_type_city_lng_lat", "tenant_id", "status", "form_type", "city_code", "lng", "lat"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(26), index=True, nullable=False)
    form_type: Mapped[FormType] = mapped_column(Enum(FormType), nullable=False)
    status: Mapped[FormStatus] = mapped_column(Enum(FormStatus), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    city_code: Mapped[str] = mapped_column(String(32), nullable=False)
    district_code: Mapped[str] = mapped_column(String(32), nullable=False)
    industry: Mapped[str] = mapped_column(String(64), nullable=False)
    lng: Mapped[float] = mapped_column(nullable=False)
    lat: Mapped[float] = mapped_column(nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(26), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class FormAuditEvent(Base):
    __tablename__ = "form_audit_events"
    __table_args__ = (Index("ix_form_audit_tenant_form_created", "tenant_id", "form_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(26), nullable=False)
    form_id: Mapped[str] = mapped_column(String(26), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(26), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class SubmissionEvent(Base):
    __tablename__ = "submission_events"
    __table_args__ = (
        Index("ix_submission_tenant_idempotency", "tenant_id", "idempotency_key"),
        Index("ix_submission_tenant_event_received", "tenant_id", "event_type", "received_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(26), nullable=False)
    form_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[SubmissionEventType] = mapped_column(Enum(SubmissionEventType), nullable=False)
    client_trace_id: Mapped[str] = mapped_column(String(26), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(26), index=True, nullable=False)
    city_code: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[BatchStatus] = mapped_column(Enum(BatchStatus), nullable=False)
    center_lng: Mapped[float] = mapped_column(nullable=False)
    center_lat: Mapped[float] = mapped_column(nullable=False)
    capacity: Mapped[int] = mapped_column(nullable=False)
    item_count: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class BatchItem(Base):
    __tablename__ = "batch_items"

    batch_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    form_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    distance_m: Mapped[int] = mapped_column(nullable=False)


class BatchCheckpoint(Base):
    __tablename__ = "batch_checkpoints"

    batch_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    stage: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_form_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class DLQItem(Base):
    __tablename__ = "dlq_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(26), nullable=False)
    form_id: Mapped[str] = mapped_column(String(26), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    error_message: Mapped[str] = mapped_column(String(255), nullable=False)
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    next_retry_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
