from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Form, FormStatus, FormType, SubmissionEvent, SubmissionEventType
from backend.app.stats import LATE_ARRIVAL_TOLERANCE, compute_success_rate
from backend.tests.conftest import login

pytestmark = pytest.mark.asyncio


BASE = datetime(2026, 9, 19, 0, 0, 0)


def event(
    key: str,
    event_type: SubmissionEventType,
    offset_minutes: int = 0,
    tenant_id: str = "tenant_a",
    occurred_offset_minutes: int | None = None,
) -> SubmissionEvent:
    received_at = BASE + timedelta(minutes=offset_minutes)
    occurred_at = BASE + timedelta(minutes=occurred_offset_minutes if occurred_offset_minutes is not None else offset_minutes)
    return SubmissionEvent(
        tenant_id=tenant_id,
        form_id=f"form_{key}",
        idempotency_key=key,
        event_type=event_type,
        client_trace_id=f"trace_{key}_{event_type.value}"[:26],
        occurred_at=occurred_at,
        received_at=received_at,
        meta={},
    )


def form(form_id: str, key: str, city: str) -> Form:
    return Form(
        id=form_id,
        tenant_id="tenant_a",
        form_type=FormType.merchant_info,
        status=FormStatus.published,
        idempotency_key=key,
        city_code=city,
        district_code="core",
        industry="restaurant",
        lng=121.4737 if city == "shanghai" else 116.4074,
        lat=31.2304 if city == "shanghai" else 39.9042,
        payload={"merchant_name": "青石小馆", "license_no": "LIC-001"},
        created_by="user_a",
        created_at=BASE,
        updated_at=BASE,
    )


async def seed_events(session: AsyncSession) -> None:
    session.add_all(
        [
            event("k1", SubmissionEventType.submit_attempt, 0),
            event("k1", SubmissionEventType.submit_attempt, 1),
            event("k1", SubmissionEventType.submit_api_success, 2),
            event("k1", SubmissionEventType.db_insert_success, 3),
            event("k1", SubmissionEventType.business_published, 30),
            event("k2", SubmissionEventType.submit_attempt, 0),
            event("k2", SubmissionEventType.submit_api_failed, 1),
            event("k2", SubmissionEventType.submit_api_success, 5),
            event("k2", SubmissionEventType.db_insert_success, 6),
            event("k3", SubmissionEventType.submit_attempt, 0),
            event("k3", SubmissionEventType.validation_failed, 4),
            event("k4", SubmissionEventType.submit_attempt, 0),
            event("k4", SubmissionEventType.submit_api_success, 1),
            event("k_late", SubmissionEventType.submit_attempt, 55),
            event("k_late", SubmissionEventType.business_published, 65, occurred_offset_minutes=56),
            event("k_late_drop", SubmissionEventType.submit_attempt, 59),
            event("k_late_drop", SubmissionEventType.business_published, 72, occurred_offset_minutes=60),
            event("k5", SubmissionEventType.submit_api_success, 1),
            event("k_other", SubmissionEventType.submit_attempt, 0, tenant_id="tenant_b"),
            event("k_old", SubmissionEventType.submit_attempt, -120),
        ]
    )
    await session.commit()


async def expected_from_events(session: AsyncSession, tenant_id: str, start: datetime, end: datetime) -> dict:
    result = await session.execute(
        select(SubmissionEvent).where(
            SubmissionEvent.tenant_id == tenant_id,
            SubmissionEvent.received_at >= start,
            SubmissionEvent.received_at <= end + LATE_ARRIVAL_TOLERANCE,
        )
    )
    events = list(result.scalars())
    attempts: dict[str, SubmissionEvent] = {}
    by_type: dict[SubmissionEventType, set[str]] = {event_type: set() for event_type in SubmissionEventType}
    for item in events:
        by_type[item.event_type].add(item.idempotency_key)
        if item.event_type == SubmissionEventType.submit_attempt and start <= item.received_at <= end:
            current = attempts.get(item.idempotency_key)
            if current is None or item.received_at < current.received_at:
                attempts[item.idempotency_key] = item

    denominator_keys = set(attempts)
    denominator = len(denominator_keys)

    def metric(keys: set[str]) -> dict:
        numerator = len(denominator_keys & keys)
        return {"numerator": numerator, "denominator": denominator, "rate": round(numerator / denominator, 6)}

    return {
        "deduped_attempts": denominator,
        "submit_success_rate": metric(by_type[SubmissionEventType.submit_api_success]),
        "db_success_rate": metric(by_type[SubmissionEventType.db_insert_success]),
        "end_to_end_success_rate": metric(by_type[SubmissionEventType.business_published]),
    }


async def test_success_rate_dedupes_retries_late_events_and_uses_final_business_event(session):
    await seed_events(session)
    start = BASE - timedelta(minutes=10)
    end = BASE + timedelta(minutes=60)

    result = await compute_success_rate(
        session,
        "tenant_a",
        start=start,
        end=end,
        use_cache=False,
    )
    expected = await expected_from_events(session, "tenant_a", start, end)

    assert result["deduped_attempts"] == expected["deduped_attempts"]
    assert result["submit_success_rate"] == expected["submit_success_rate"]
    assert result["db_success_rate"] == expected["db_success_rate"]
    assert result["end_to_end_success_rate"] == expected["end_to_end_success_rate"]
    assert result["end_to_end_success_rate"]["numerator"] == 2


async def test_success_rate_api_is_tenant_scoped(client, session):
    await seed_events(session)
    token = await login(client, "a@example.com", "pass-a")

    response = await client.get(
        f"/api/v1/stats/success-rate?from={BASE.isoformat()}&to={(BASE + timedelta(minutes=60)).isoformat()}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    expected = await expected_from_events(session, "tenant_a", BASE, BASE + timedelta(minutes=60))
    assert body["deduped_attempts"] == expected["deduped_attempts"]
    assert body["submit_success_rate"]["numerator"] == 3


async def test_success_rate_api_supports_form_filters(client, session):
    session.add_all([form("form_filter_sh", "k_sh", "shanghai"), form("form_filter_bj", "k_bj", "beijing")])
    session.add_all(
        [
            event("k_sh", SubmissionEventType.submit_attempt, 0),
            event("k_sh", SubmissionEventType.submit_api_success, 1),
            event("k_bj", SubmissionEventType.submit_attempt, 0),
            event("k_bj", SubmissionEventType.submit_api_success, 1),
        ]
    )
    for item in session.new:
        if isinstance(item, SubmissionEvent):
            item.form_id = "form_filter_sh" if item.idempotency_key == "k_sh" else "form_filter_bj"
    await session.commit()
    token = await login(client, "a@example.com", "pass-a")

    response = await client.get(
        f"/api/v1/stats/success-rate?from={BASE.isoformat()}&to={(BASE + timedelta(minutes=60)).isoformat()}&city=shanghai",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["deduped_attempts"] == 1
    assert body["submit_success_rate"] == {"numerator": 1, "denominator": 1, "rate": 1.0}


async def test_success_rate_cache_roundtrip(session):
    await seed_events(session)
    start = BASE - timedelta(minutes=9)
    end = BASE + timedelta(minutes=60)

    first = await compute_success_rate(session, "tenant_a", start=start, end=end, use_cache=True)
    second = await compute_success_rate(session, "tenant_a", start=start, end=end, use_cache=True)

    expected = await expected_from_events(session, "tenant_a", start, end)
    assert first["deduped_attempts"] == expected["deduped_attempts"]
    assert second["deduped_attempts"] == expected["deduped_attempts"]
    assert second["cache_hit"] is True
