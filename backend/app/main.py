from __future__ import annotations

import logging
import time
import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from jwt import InvalidTokenError
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .batch_pipeline import build_batches, get_batch_for_actor, list_batches, run_batch
from .cluster_service import bbox_tuple, cluster_geojson
from .config import settings
from .db import get_session
from .dependencies import current_user
from .docs_store import DocNotFoundError, DocsRepository, DocVersionConflictError, get_docs_repo
from .models import Batch, BatchItem, BatchStatus, Form, FormAuditEvent, FormStatus, FormType, SubmissionEvent, SubmissionEventType, User
from .repositories import FormRepository
from .realtime import event_to_dict, events_since, publish_event, subscribe, unsubscribe
from .schemas import (
    BatchBuildRequest,
    BatchBuildResponse,
    BatchListResponse,
    BatchOut,
    BatchRunResponse,
    DocCreate,
    DocListResponse,
    DocOut,
    DocRollbackRequest,
    DocUpdate,
    FormCreate,
    FormListResponse,
    FormOut,
    LoginRequest,
    RefreshRequest,
    StatusPatch,
    SuccessRateResponse,
    TokenResponse,
    WithdrawRequest,
)
from .security import create_access_token, create_refresh_token, decode_token, verify_password
from .stats import compute_success_rate, default_window
from .state_machine import can_transition
from .status_worker import start_status_worker, stop_status_worker


logger = logging.getLogger("merchant.telemetry")


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = start_status_worker(settings.validate_worker_interval_seconds)
    try:
        yield
    finally:
        await stop_status_worker(worker_task)


app = FastAPI(title="Merchant Onboarding Platform", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000", "http://127.0.0.1:3001", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["ETag", "X-Cache", "X-Trace-Id"],
)


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
    if created:
        await publish_event(form.tenant_id, "form.status_changed", {"form_id": form.id, "status": form.status.value})
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


@app.get("/api/v1/forms/{form_id}/audit")
async def list_form_audit(
    form_id: str,
    actor: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    form = await FormRepository(session, actor).get(form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "not_found"})
    result = await session.execute(
        select(FormAuditEvent)
        .where(FormAuditEvent.tenant_id == form.tenant_id, FormAuditEvent.form_id == form.id)
        .order_by(FormAuditEvent.created_at.asc(), FormAuditEvent.id.asc())
    )
    items = [
        {
            "id": item.id,
            "event_type": item.event_type,
            "from_status": item.from_status,
            "to_status": item.to_status,
            "actor_id": item.actor_id,
            "created_at": item.created_at.isoformat(),
        }
        for item in result.scalars()
    ]
    return {"items": items}


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
    await publish_event(form.tenant_id, "form.status_changed", {"form_id": form.id, "status": form.status.value})
    return FormOut.model_validate(form, from_attributes=True)


WITHDRAWABLE_STATUSES = {
    FormStatus.draft,
    FormStatus.submitted,
    FormStatus.validating,
    FormStatus.validated,
    FormStatus.batched,
}


@app.post("/api/v1/forms/{form_id}/withdraw", response_model=FormOut)
async def withdraw_form(
    form_id: str,
    payload: WithdrawRequest,
    actor: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FormOut:
    form = await session.scalar(select(Form).where(Form.id == form_id, Form.tenant_id == actor.tenant_id))
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "not_found"})
    if form.created_by != actor.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "forbidden"})
    previous = form.status
    if previous not in WITHDRAWABLE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "not_withdrawable"})

    now = datetime.now(UTC).replace(tzinfo=None)
    reason = (payload.reason or "").strip()[:255] or None
    batch: Batch | None = None
    if previous == FormStatus.batched:
        if not form.batch_id:
            raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "batch_locked"})
        batch = await session.get(Batch, form.batch_id, with_for_update=True)
        if batch is None or batch.status != BatchStatus.created:
            raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "batch_locked"})

    result = await session.execute(
        update(Form)
        .where(
            Form.id == form.id,
            Form.tenant_id == actor.tenant_id,
            Form.created_by == actor.id,
            Form.status == previous,
        )
        .values(
            status=FormStatus.withdrawn,
            batch_id=None,
            withdrawn_at=now,
            withdraw_reason=reason,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "not_withdrawable"})

    if previous == FormStatus.batched and batch is not None:
        await session.execute(delete(BatchItem).where(BatchItem.batch_id == batch.id, BatchItem.form_id == form.id))
        batch.item_count = max(0, batch.item_count - 1)
        batch.updated_at = now
        if batch.item_count == 0:
            batch.status = BatchStatus.canceled

    updated_form = await session.scalar(select(Form).where(Form.id == form.id))
    if updated_form is None:  # pragma: no cover - impossible after rowcount=1
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "not_found"})
    await FormRepository(session, actor).audit(updated_form, "form_withdrawn", previous, FormStatus.withdrawn)
    session.add(
        SubmissionEvent(
            tenant_id=updated_form.tenant_id,
            form_id=updated_form.id,
            idempotency_key=updated_form.idempotency_key,
            event_type=SubmissionEventType.form_withdrawn,
            client_trace_id=uuid4().hex[:26],
            occurred_at=now,
            received_at=now,
            meta={"reason": reason} if reason else {"reason": None},
        )
    )
    await session.commit()
    await publish_event(updated_form.tenant_id, "form.status_changed", {"form_id": updated_form.id, "status": updated_form.status.value})
    if batch is not None:
        await publish_event(batch.tenant_id, "batch.status_changed", {"batch_id": batch.id, "status": batch.status.value})
    return FormOut.model_validate(updated_form, from_attributes=True)


def actor_can_transition(actor: User, city_code: str, previous: FormStatus, target: FormStatus) -> bool:
    if actor.role.value == "admin":
        return True
    if actor.role.value == "operator" and actor.region_code == city_code:
        return (previous, target) in {
            (FormStatus.validating, FormStatus.rejected),
            (FormStatus.failed, FormStatus.processing),
        }
    return False


def parse_doc_version(value: str) -> int:
    normalized = value.strip().strip('"')
    if normalized.startswith("W/"):
        normalized = normalized[2:].strip().strip('"')
    try:
        version = int(normalized)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_if_match"})
    if version < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_if_match"})
    return version


def doc_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DocNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "not_found"})
    if isinstance(exc, DocVersionConflictError):
        return HTTPException(status.HTTP_409_CONFLICT, detail={"code": "version_conflict"})
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"code": "internal_error"})


@app.post("/api/v1/docs", response_model=DocOut, status_code=status.HTTP_201_CREATED)
async def create_doc(
    payload: DocCreate,
    actor: User = Depends(current_user),
    repo: DocsRepository = Depends(get_docs_repo),
) -> DocOut:
    try:
        doc = repo.create(tenant_id=actor.tenant_id, user_id=actor.id, title=payload.title, content=payload.content)
    except (DocNotFoundError, DocVersionConflictError) as exc:
        raise doc_http_error(exc)
    await publish_event(actor.tenant_id, "doc.updated", {"doc_id": doc["id"], "version": doc["current_version"]})
    return DocOut.model_validate(doc)


@app.get("/api/v1/docs", response_model=DocListResponse)
async def list_docs(
    q: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    actor: User = Depends(current_user),
    repo: DocsRepository = Depends(get_docs_repo),
) -> DocListResponse:
    result = repo.list(tenant_id=actor.tenant_id, query=q, page=page, size=size)
    return DocListResponse(items=[DocOut.model_validate(item) for item in result.items], total=result.total, page=page, size=size)


@app.get("/api/v1/docs/{doc_id}", response_model=DocOut)
async def get_doc(
    doc_id: str,
    actor: User = Depends(current_user),
    repo: DocsRepository = Depends(get_docs_repo),
) -> DocOut:
    try:
        return DocOut.model_validate(repo.get(tenant_id=actor.tenant_id, doc_id=doc_id))
    except DocNotFoundError as exc:
        raise doc_http_error(exc)


@app.patch("/api/v1/docs/{doc_id}", response_model=DocOut)
async def update_doc(
    doc_id: str,
    payload: DocUpdate,
    if_match: str = Header(..., alias="If-Match"),
    actor: User = Depends(current_user),
    repo: DocsRepository = Depends(get_docs_repo),
) -> DocOut:
    expected_version = parse_doc_version(if_match)
    try:
        doc = repo.update(
            tenant_id=actor.tenant_id,
            user_id=actor.id,
            doc_id=doc_id,
            expected_version=expected_version,
            title=payload.title,
            content=payload.content,
        )
    except (DocNotFoundError, DocVersionConflictError) as exc:
        raise doc_http_error(exc)
    await publish_event(actor.tenant_id, "doc.updated", {"doc_id": doc["id"], "version": doc["current_version"]})
    return DocOut.model_validate(doc)


@app.delete("/api/v1/docs/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doc(
    doc_id: str,
    actor: User = Depends(current_user),
    repo: DocsRepository = Depends(get_docs_repo),
) -> Response:
    try:
        repo.delete(tenant_id=actor.tenant_id, doc_id=doc_id)
    except DocNotFoundError as exc:
        raise doc_http_error(exc)
    await publish_event(actor.tenant_id, "doc.deleted", {"doc_id": doc_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/docs/{doc_id}/rollback", response_model=DocOut)
async def rollback_doc(
    doc_id: str,
    payload: DocRollbackRequest,
    actor: User = Depends(current_user),
    repo: DocsRepository = Depends(get_docs_repo),
) -> DocOut:
    try:
        doc = repo.rollback(tenant_id=actor.tenant_id, user_id=actor.id, doc_id=doc_id, version_no=payload.version_no)
    except DocNotFoundError as exc:
        raise doc_http_error(exc)
    await publish_event(actor.tenant_id, "doc.updated", {"doc_id": doc["id"], "version": doc["current_version"]})
    return DocOut.model_validate(doc)


@app.get("/api/v1/stats/success-rate", response_model=SuccessRateResponse)
async def success_rate(
    from_time: datetime | None = Query(None, alias="from"),
    to_time: datetime | None = Query(None, alias="to"),
    city: str | None = None,
    status_filter: FormStatus | None = Query(None, alias="status"),
    form_type: FormType | None = None,
    industry: str | None = None,
    actor: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if from_time and to_time:
        start, end = from_time.replace(tzinfo=None), to_time.replace(tzinfo=None)
    else:
        start, end, _ = default_window()
    if start >= end:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_window"})
    payload = await compute_success_rate(
        session,
        actor.tenant_id,
        start=start,
        end=end,
        city=city,
        status=status_filter,
        form_type=form_type,
        industry=industry,
    )
    payload.pop("cache_hit", None)
    return payload


@app.get("/api/v1/clusters", response_model=None)
async def clusters(
    response: Response,
    bbox: str,
    zoom: int = Query(..., ge=1, le=20),
    city: str | None = None,
    status_filter: FormStatus | None = Query(None, alias="status"),
    form_type: FormType | None = None,
    industry: str | None = None,
    if_none_match: str | None = Header(None, alias="If-None-Match"),
    actor: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        parsed_bbox = bbox_tuple(bbox)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_bbox", "message": str(exc)})
    payload, etag, cache_hit = await cluster_geojson(
        session,
        actor,
        bbox=parsed_bbox,
        zoom=zoom,
        city=city,
        status=status_filter,
        form_type=form_type,
        industry=industry,
    )
    if if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag, "Cache-Control": "no-cache"})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Cache"] = "HIT" if cache_hit else "MISS"
    return payload


@app.post("/api/v1/batches/build", response_model=BatchBuildResponse)
async def build_batch_endpoint(
    payload: BatchBuildRequest,
    actor: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> BatchBuildResponse:
    if actor.role.value == "merchant":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "forbidden"})
    batches, total_forms = await build_batches(
        session,
        actor,
        city=payload.city,
        form_type=payload.form_type,
        capacity=payload.capacity,
        radius_m=payload.radius_m,
    )
    await session.commit()
    for batch in batches:
        await publish_event(batch.tenant_id, "batch.status_changed", {"batch_id": batch.id, "status": batch.status.value})
    return BatchBuildResponse(
        batches=[BatchOut.model_validate(item, from_attributes=True) for item in batches],
        total_forms=total_forms,
    )


@app.get("/api/v1/batches", response_model=BatchListResponse)
async def list_batch_endpoint(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    actor: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> BatchListResponse:
    batches, total = await list_batches(session, actor, page=page, size=size)
    return BatchListResponse(
        items=[BatchOut.model_validate(item, from_attributes=True) for item in batches],
        total=total,
        page=page,
        size=size,
    )


async def run_batch_background(session: AsyncSession, batch_id: str) -> None:
    batch = await session.get(Batch, batch_id)
    if batch is None or batch.status == BatchStatus.canceled:
        return

    async def progress(processed: int, total: int, current_status: BatchStatus) -> None:
        await publish_event(
            batch.tenant_id,
            "batch.progress",
            {"batch_id": batch.id, "processed": processed, "total": total, "status": current_status.value},
        )

    try:
        summary = await run_batch(session, batch, progress_callback=progress)
        await session.commit()
        await publish_event(batch.tenant_id, "batch.status_changed", {"batch_id": batch.id, "status": summary.status.value})
    except Exception:
        await session.rollback()
        logger.exception("batch_background_failed", extra={"batch_id": batch_id})


@app.post("/api/v1/batches/{batch_id}/run", response_model=BatchRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_batch_endpoint(
    batch_id: str,
    background_tasks: BackgroundTasks,
    actor: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> BatchRunResponse:
    if actor.role.value == "merchant":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "forbidden"})
    batch = await get_batch_for_actor(session, actor, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "not_found"})
    if batch.status == BatchStatus.canceled:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "batch_canceled"})
    if batch.status == BatchStatus.completed:
        return BatchRunResponse(batch_id=batch.id, status=batch.status, processed=0, published=0, failed=0, checkpoint_stages=[])

    batch.status = BatchStatus.processing
    batch.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()
    await publish_event(batch.tenant_id, "batch.status_changed", {"batch_id": batch.id, "status": batch.status.value})
    background_tasks.add_task(run_batch_background, session, batch.id)
    return BatchRunResponse(batch_id=batch.id, status=batch.status, processed=0, published=0, failed=0, checkpoint_stages=[])


@app.get("/api/v1/events")
async def poll_events(
    since: int = Query(0, ge=0),
    actor: User = Depends(current_user),
) -> dict:
    return {"events": events_since(actor.tenant_id, since)}


@app.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket, token: str) -> None:
    try:
        claims = decode_token(token)
    except InvalidTokenError:
        await websocket.close(code=4401)
        return
    tenant_id = claims.get("tenant_id")
    if not tenant_id:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    queue = await subscribe(tenant_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event_to_dict(event))
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        unsubscribe(tenant_id, queue)
