from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from redis.asyncio import from_url
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Form, FormStatus, FormType, SubmissionEvent, SubmissionEventType

LATE_ARRIVAL_TOLERANCE = timedelta(minutes=10)


def metric(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else 0.0,
    }


def default_window() -> tuple[datetime, datetime, str]:
    end = datetime.now(UTC).replace(tzinfo=None)
    start = end - timedelta(hours=24)
    return start, end, "24h"


def filter_hash(*, city: str | None, status: FormStatus | None, form_type: FormType | None, industry: str | None) -> str:
    if not any([city, status, form_type, industry]):
        return "all"
    parts = {
        "city": city or "",
        "status": status.value if status else "",
        "form_type": form_type.value if form_type else "",
        "industry": industry or "",
    }
    return "|".join(f"{key}={value}" for key, value in sorted(parts.items())) or "all"


def cache_key(
    tenant_id: str,
    start: datetime,
    end: datetime,
    *,
    city: str | None,
    status: FormStatus | None,
    form_type: FormType | None,
    industry: str | None,
) -> str:
    filters = filter_hash(city=city, status=status, form_type=form_type, industry=industry)
    return f"success_rate:v1:{tenant_id}:{start.isoformat()}..{end.isoformat()}:{filters}"


async def get_cached_success_rate(
    tenant_id: str,
    start: datetime,
    end: datetime,
    *,
    city: str | None,
    status: FormStatus | None,
    form_type: FormType | None,
    industry: str | None,
) -> dict | None:
    try:
        redis = from_url(settings.redis_url, decode_responses=True)
        value = await redis.get(cache_key(tenant_id, start, end, city=city, status=status, form_type=form_type, industry=industry))
        await redis.aclose()
        return json.loads(value) if value else None
    except Exception:
        return None


async def set_cached_success_rate(
    tenant_id: str,
    start: datetime,
    end: datetime,
    payload: dict,
    *,
    city: str | None,
    status: FormStatus | None,
    form_type: FormType | None,
    industry: str | None,
) -> None:
    try:
        redis = from_url(settings.redis_url, decode_responses=True)
        await redis.set(
            cache_key(tenant_id, start, end, city=city, status=status, form_type=form_type, industry=industry),
            json.dumps(payload, ensure_ascii=False),
            ex=30,
        )
        await redis.aclose()
    except Exception:
        return


async def compute_success_rate(
    session: AsyncSession,
    tenant_id: str,
    *,
    start: datetime,
    end: datetime,
    use_cache: bool = True,
    city: str | None = None,
    status: FormStatus | None = None,
    form_type: FormType | None = None,
    industry: str | None = None,
) -> dict:
    if use_cache:
        cached = await get_cached_success_rate(
            tenant_id,
            start,
            end,
            city=city,
            status=status,
            form_type=form_type,
            industry=industry,
        )
        if cached:
            cached["cache_hit"] = True
            return cached

    stmt = select(SubmissionEvent).where(
        SubmissionEvent.tenant_id == tenant_id,
        SubmissionEvent.received_at >= start,
        SubmissionEvent.received_at <= end + LATE_ARRIVAL_TOLERANCE,
    )
    if city or status or form_type or industry:
        stmt = stmt.join(Form, Form.id == SubmissionEvent.form_id)
        if city:
            stmt = stmt.where(Form.city_code == city)
        if status:
            stmt = stmt.where(Form.status == status)
        if form_type:
            stmt = stmt.where(Form.form_type == form_type)
        if industry:
            stmt = stmt.where(Form.industry == industry)
    result = await session.execute(stmt)
    events = list(result.scalars())
    attempts: dict[str, SubmissionEvent] = {}
    by_type: dict[SubmissionEventType, set[str]] = {event_type: set() for event_type in SubmissionEventType}

    for event in events:
        by_type[event.event_type].add(event.idempotency_key)
        if event.event_type == SubmissionEventType.submit_attempt and start <= event.received_at <= end:
            current = attempts.get(event.idempotency_key)
            if current is None or event.received_at < current.received_at:
                attempts[event.idempotency_key] = event

    denominator_keys = set(attempts)
    denominator = len(denominator_keys)
    submit_success = len(denominator_keys & by_type[SubmissionEventType.submit_api_success])
    db_success = len(denominator_keys & by_type[SubmissionEventType.db_insert_success])
    end_to_end = len(denominator_keys & by_type[SubmissionEventType.business_published])

    payload = {
        "window": f"{start.isoformat()}..{end.isoformat()}",
        "submit_success_rate": metric(submit_success, denominator),
        "db_success_rate": metric(db_success, denominator),
        "end_to_end_success_rate": metric(end_to_end, denominator),
        "deduped_attempts": denominator,
        "cache_hit": False,
    }
    if use_cache:
        await set_cached_success_rate(
            tenant_id,
            start,
            end,
            payload,
            city=city,
            status=status,
            form_type=form_type,
            industry=industry,
        )
    return payload
