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

TEXT_LIMITS = {
    "merchant_name": 128, "license_no": 128, "legal_person": 128,
    "contact_phone": 64, "contact_email": 255, "business_scope": 2000,
    "intro": 5000, "property_name": 128, "address": 255, "contact": 128,
    "product_name": 128, "sku": 128, "category": 128,
    "report_name": 128, "period": 64, "remark": 5000,
}
NUMBER_FIELDS = {"reg_capital", "area_sqm", "rent_monthly", "price", "revenue", "order_count", "customer_count"}
FILE_FIELDS = {"license_photo", "file_id"}
FILE_LIST_FIELDS = {"attachments", "photos", "lease_files", "cert_files", "report_files", "chart_images", "file_ids"}


class FileOut(BaseModel):
    file_id: str
    filename: str
    mime_type: str
    size_bytes: int


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class ShopOut(BaseModel):
    id: str
    name: str
    city_code: str
    district_code: str
    address: str
    lng: float
    lat: float


class FormCreate(BaseModel):
    form_type: FormType
    city_code: str = Field(min_length=1, max_length=32)
    district_code: str = Field(min_length=1, max_length=32)
    industry: str = Field(min_length=1, max_length=64)
    lng: float
    lat: float
    payload: dict[str, Any]
    shop_id: str | None = Field(default=None, min_length=1, max_length=64)

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
        for key, value in self.payload.items():
            if key in TEXT_LIMITS:
                if not isinstance(value, str) or len(value) > TEXT_LIMITS[key]:
                    raise ValueError(f"{key} must be a string of at most {TEXT_LIMITS[key]} characters")
                if key in REQUIRED_BY_TYPE[self.form_type] and not value.strip():
                    raise ValueError(f"{key} must not be blank")
            if key in NUMBER_FIELDS:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1e15:
                    raise ValueError(f"{key} must be a finite number between 0 and 1e15")
                if key in {"order_count", "customer_count"} and value != int(value):
                    raise ValueError(f"{key} must be an integer")
            if key in FILE_FIELDS and (not isinstance(value, str) or not value.startswith("f_") or len(value) > 26):
                raise ValueError(f"{key} must be a file id")
            if key in FILE_LIST_FIELDS:
                if not isinstance(value, list) or len(value) > 20 or any(not isinstance(item, str) or not item.startswith("f_") or len(item) > 26 for item in value):
                    raise ValueError(f"{key} must be a list of at most 20 file ids")
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
    withdrawn_at: datetime | None = None
    withdraw_reason: str | None = None
    shop_id: str | None = None
    shop_name: str | None = None


class FormDetailOut(FormOut):
    batch_id: str | None = None


class FormListResponse(BaseModel):
    items: list[FormOut]
    total: int
    page: int
    size: int


class StatusPatch(BaseModel):
    target_status: FormStatus


class WithdrawRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class SuccessRateMetric(BaseModel):
    numerator: int
    denominator: int
    rate: float


class SuccessRateResponse(BaseModel):
    window: str
    submit_success_rate: SuccessRateMetric
    db_success_rate: SuccessRateMetric
    end_to_end_success_rate: SuccessRateMetric
    withdrawal_rate: SuccessRateMetric
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


class DocCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1)


class DocUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1)


class DocRollbackRequest(BaseModel):
    version_no: int = Field(ge=1)


class DocOut(BaseModel):
    id: str
    tenant_id: str
    title: str
    content: str
    current_version: int
    etag: str
    status: str
    tokens: list[str]
    created_by: str
    created_at: datetime
    updated_at: datetime


class DocListResponse(BaseModel):
    items: list[DocOut]
    total: int
    page: int
    size: int


class ErrorResponse(BaseModel):
    code: str
    message: str
    detail: Any | None = None
    trace_id: str
