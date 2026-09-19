from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_session
from .dependencies import current_user
from .models import FormStatus, SubmissionEvent, SubmissionEventType, User
from .repositories import FormRepository
from .schemas import FormCreate, FormListResponse, FormOut, LoginRequest, RefreshRequest, StatusPatch, SuccessRateResponse, TokenResponse
from .security import create_access_token, create_refresh_token, decode_token, verify_password
from .stats import compute_success_rate, default_window
from .state_machine import can_transition


logger = logging.getLogger("merchant.telemetry")
app = FastAPI(title="Merchant Onboarding Platform", version="0.1.0")


@app.middleware("http")
async def trace_and_telemetry(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id", uuid4().hex[:26])
    request.state.trace_id = trace_id
    started = time.perf_counter()
    status_code = 500
    error_code = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Trace-Id"] = trace_id
        return response
    except Exception:
        error_code = "internal_error"
        raise
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        try:
            logger.info(
                "request",
                extra={
                    "trace_id": trace_id,
                    "tenant_id": getattr(request.state, "tenant_id", None),
                    "user_id": getattr(request.state, "user_id", None),
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "error_code": error_code,
                },
            )
        except Exception:  # pragma: no cover - telemetry must never affect business
            logger.exception("telemetry_write_failed")


def error_payload(request: Request, status_code: int, code: str, message: str, detail=None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "detail": detail,
            "trace_id": getattr(request.state, "trace_id", ""),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return error_payload(request, 422, "validation_error", "request validation failed", json_safe_errors(exc.errors()))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    code = detail.get("code", "http_error")
    return error_payload(request, exc.status_code, code, code, detail)


def json_safe_errors(errors: list[dict]) -> list[dict]:
    safe: list[dict] = []
    for error in errors:
        item = dict(error)
        if "ctx" in item:
            item["ctx"] = {key: str(value) for key, value in item["ctx"].items()}
        safe.append(item)
    return safe


@app.post("/api/v1/auth/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    user = await session.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "unauthorized"})
    return TokenResponse(
        access_token=create_access_token(user.id, user.tenant_id, user.role.value),
        refresh_token=create_refresh_token(user.id, user.tenant_id, user.role.value),
        expires_in=settings.access_token_minutes * 60,
    )


@app.post("/api/v1/auth/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    try:
        claims = decode_token(payload.refresh_token)
    except InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "unauthorized"})
    if claims.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "unauthorized"})
    user = await session.scalar(select(User).where(User.id == claims["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "unauthorized"})
    return TokenResponse(
        access_token=create_access_token(user.id, user.tenant_id, user.role.value),
        refresh_token=create_refresh_token(user.id, user.tenant_id, user.role.value),
        expires_in=settings.access_token_minutes * 60,
    )


@app.get("/api/v1/forms", response_model=FormListResponse)
async def list_forms(
    city: str | None = None,
    status_filter: FormStatus | None = Query(None, alias="status"),
    form_type: str | None = None,
    industry: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    actor: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FormListResponse:
    repo = FormRepository(session, actor)
    result = await repo.list(
        city=city,
        status=status_filter,
        form_type=form_type,
        industry=industry,
        page=page,
        size=size,
    )
    return FormListResponse(items=[FormOut.model_validate(item, from_attributes=True) for item in result.items], total=result.total, page=page, size=size)


@app.post("/api/v1/forms", response_model=FormOut)
async def create_form(
    payload: FormCreate,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    actor: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FormOut:
    repo = FormRepository(session, actor)
    form, created = await repo.create(payload, idempotency_key)
    if created:
        session.add(
            SubmissionEvent(
                tenant_id=form.tenant_id,
                form_id=form.id,
                idempotency_key=idempotency_key,
                event_type=SubmissionEventType.db_insert_success,
                client_trace_id=uuid4().hex[:26],
                occurred_at=datetime.now(UTC).replace(tzinfo=None),
                meta={},
            )
        )
    await session.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return FormOut.model_validate(form, from_attributes=True)


@app.get("/api/v1/forms/{form_id}", response_model=FormOut)
async def get_form(
    form_id: str,
    actor: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FormOut:
    form = await FormRepository(session, actor).get(form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "not_found"})
    return FormOut.model_validate(form, from_attributes=True)


@app.patch("/api/v1/forms/{form_id}/status", response_model=FormOut)
async def patch_status(
    form_id: str,
    payload: StatusPatch,
    actor: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FormOut:
    repo = FormRepository(session, actor)
    form = await repo.get(form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "not_found"})
    previous = form.status
    if not actor_can_transition(actor, form.city_code, previous, payload.target_status):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "forbidden"})
    if not can_transition(previous, payload.target_status, form.retry_count):
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "illegal_transition"})
    form.status = payload.target_status
    form.updated_at = datetime.now(UTC).replace(tzinfo=None)
    if previous == FormStatus.processing and payload.target_status == FormStatus.failed:
        form.retry_count += 1
    await repo.audit(form, "status_changed", previous, payload.target_status)
    await session.commit()
    return FormOut.model_validate(form, from_attributes=True)


def actor_can_transition(actor: User, city_code: str, previous: FormStatus, target: FormStatus) -> bool:
    if actor.role.value == "admin":
        return True
    if actor.role.value == "operator" and actor.region_code == city_code:
        return (previous, target) in {
            (FormStatus.validating, FormStatus.rejected),
            (FormStatus.failed, FormStatus.processing),
        }
    return False


@app.get("/api/v1/stats/success-rate", response_model=SuccessRateResponse)
async def success_rate(
    from_time: datetime | None = Query(None, alias="from"),
    to_time: datetime | None = Query(None, alias="to"),
    actor: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if from_time and to_time:
        start, end = from_time.replace(tzinfo=None), to_time.replace(tzinfo=None)
    else:
        start, end, _ = default_window()
    if start >= end:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_window"})
    payload = await compute_success_rate(session, actor.tenant_id, start=start, end=end)
    payload.pop("cache_hit", None)
    return payload
