from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import BatchStatus, FormStatus, FormType


REQUIRED_BY_TYPE = {
    FormType.merchant_info: {"merchant_name", "license_no"},
    FormType.property: {"property_name", "address"},
    FormType.product: {"product_name", "sku"},
    FormType.report: {"report_name", "period"},
}


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class FormCreate(BaseModel):
    form_type: FormType
    city_code: str = Field(min_length=1, max_length=32)
    district_code: str = Field(min_length=1, max_length=32)
    industry: str = Field(min_length=1, max_length=64)
    lng: float
    lat: float
    payload: dict[str, Any]

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, value: float) -> float:
        if not 73 <= value <= 135:
            raise ValueError("lng must be inside China longitude bounds")
        return value

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, value: float) -> float:
        if not 18 <= value <= 54:
            raise ValueError("lat must be inside China latitude bounds")
        return value

    @model_validator(mode="after")
    def validate_payload(self) -> "FormCreate":
        missing = REQUIRED_BY_TYPE[self.form_type] - self.payload.keys()
        if missing:
            raise ValueError(f"missing required payload fields: {sorted(missing)}")
        return self


class FormOut(BaseModel):
    id: str
    tenant_id: str
    form_type: FormType
    status: FormStatus
    idempotency_key: str
    city_code: str
    district_code: str
    industry: str
    lng: float
    lat: float
    payload: dict[str, Any]
    retry_count: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class FormListResponse(BaseModel):
    items: list[FormOut]
    total: int
    page: int
    size: int


class StatusPatch(BaseModel):
    target_status: FormStatus


class SuccessRateMetric(BaseModel):
    numerator: int
    denominator: int
    rate: float


class SuccessRateResponse(BaseModel):
    window: str
    submit_success_rate: SuccessRateMetric
    db_success_rate: SuccessRateMetric
    end_to_end_success_rate: SuccessRateMetric
    deduped_attempts: int


class BatchBuildRequest(BaseModel):
    city: str | None = None
    form_type: FormType | None = None
    capacity: int = Field(default=50, ge=1, le=200)
    radius_m: int = Field(default=3000, ge=100, le=20000)


class BatchOut(BaseModel):
    id: str
    tenant_id: str
    city_code: str
    status: BatchStatus
    center_lng: float
    center_lat: float
    capacity: int
    item_count: int
    created_at: datetime
    updated_at: datetime


class BatchBuildResponse(BaseModel):
    batches: list[BatchOut]
    total_forms: int


class BatchListResponse(BaseModel):
    items: list[BatchOut]
    total: int
    page: int
    size: int


class BatchRunResponse(BaseModel):
    batch_id: str
    status: BatchStatus
    processed: int
    published: int
    failed: int
    checkpoint_stages: list[str]


class ErrorResponse(BaseModel):
    code: str
    message: str
    detail: Any | None = None
    trace_id: str
