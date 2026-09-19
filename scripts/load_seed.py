#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import settings  # noqa: E402
from backend.app.db import Base  # noqa: E402
from backend.app.models import (  # noqa: E402
    Batch,
    BatchCheckpoint,
    BatchItem,
    DLQItem,
    Form,
    FormAuditEvent,
    SubmissionEvent,
    SubmissionEventType,
    Tenant,
    TenantStatus,
    User,
    UserRole,
)
from backend.app.schemas import REQUIRED_BY_TYPE  # noqa: E402
from backend.app.security import hash_password  # noqa: E402


VALID_STATUSES = {"draft", "submitted", "validating", "validated", "rejected", "batched", "processing", "published", "failed"}
DEMO_BATCH_WORKSET_SIZE = 1500


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def shift_seed_timeline(rows: list[dict], anchor_end: datetime) -> dict:
    created_values = [parse_time(row["created_at"]) for row in rows]
    original_min = min(created_values)
    original_max = max(created_values)
    shift = anchor_end - original_max
    for row, created_at in zip(rows, created_values):
        row["created_at"] = (created_at + shift).isoformat()
    return {
        "original_min": original_min.isoformat(),
        "original_max": original_max.isoformat(),
        "shifted_min": (original_min + shift).isoformat(),
        "shifted_max": anchor_end.isoformat(),
        "shift_seconds": int(shift.total_seconds()),
    }


def chunked(rows: list[dict], size: int):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def row_payload(row: dict) -> dict:
    form_type = row["form_type"]
    required_name = row["payload_required_name"]
    payload = {"source": "seed"}
    if required_name:
        first, second = sorted(REQUIRED_BY_TYPE[form_type])
        payload[first] = required_name
        payload[second] = f"{form_type}_required_{row['id']}"
    return payload


def classify(row: dict, seen_keys: set[str]) -> str | None:
    lng = float(row["lng"])
    lat = float(row["lat"])
    global_key = row["idempotency_key"]
    if not (73 <= lng <= 135 and 18 <= lat <= 54):
        return "invalid_coordinates"
    if row["status"] not in VALID_STATUSES:
        return "illegal_status"
    if not row["payload_required_name"]:
        return "missing_required"
    if global_key in seen_keys:
        return "duplicate_idempotency_key"
    seen_keys.add(global_key)
    return None


def events_for_row(row: dict, inserted: bool, reason: str | None) -> list[dict]:
    created_at = parse_time(row["created_at"])
    trace = f"trace_{row['id']}"[:26]
    base = {
        "tenant_id": row["tenant_id"],
        "form_id": row["id"] if inserted else None,
        "idempotency_key": row["idempotency_key"],
        "client_trace_id": trace,
        "meta": {"source": "seed", "reason": reason} if reason else {"source": "seed"},
    }
    events = [
        {
            **base,
            "event_type": SubmissionEventType.submit_attempt.value,
            "occurred_at": created_at,
            "received_at": created_at,
        }
    ]
    if reason:
        events.append(
            {
                **base,
                "event_type": SubmissionEventType.validation_failed.value,
                "occurred_at": created_at + timedelta(seconds=1),
                "received_at": created_at + timedelta(seconds=1),
            }
        )
        return events
    if int(row["id"].removeprefix("form_")) % 33 == 0:
        events.append(
            {
                **base,
                "event_type": SubmissionEventType.submit_api_failed.value,
                "occurred_at": created_at + timedelta(seconds=1),
                "received_at": created_at + timedelta(seconds=1),
            }
        )
    events.extend(
        [
            {
                **base,
                "event_type": SubmissionEventType.submit_api_success.value,
                "occurred_at": created_at + timedelta(seconds=2),
                "received_at": created_at + timedelta(seconds=2),
            },
            {
                **base,
                "event_type": SubmissionEventType.db_insert_success.value,
                "occurred_at": created_at + timedelta(seconds=3),
                "received_at": created_at + timedelta(seconds=3),
            },
        ]
    )
    if row["status"] == "published":
        events.append(
            {
                **base,
                "event_type": SubmissionEventType.business_published.value,
                "occurred_at": created_at + timedelta(minutes=10),
                "received_at": created_at + timedelta(minutes=10),
            }
        )
    return events


async def reset_tables(conn) -> None:
    for table in [DLQItem, BatchCheckpoint, BatchItem, Batch, FormAuditEvent, SubmissionEvent, Form, User, Tenant]:
        await conn.execute(delete(table))


async def bulk_insert(conn, model, rows: list[dict], chunk_size: int = 2000) -> None:
    if not rows:
        return
    for part in chunked(rows, chunk_size):
        await conn.execute(insert(model), part)


async def main_async(args) -> int:
    csv_path = ROOT / args.csv
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    timeline = shift_seed_timeline(rows, datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))
    tenants = sorted({row["tenant_id"] for row in rows})
    tenant_rows = [{"id": tenant_id, "name": tenant_id.replace("_", " ").title(), "status": TenantStatus.active.value} for tenant_id in tenants]
    user_rows = [
        {
            "id": f"user_{idx + 1:02d}",
            "tenant_id": tenant_id,
            "email": f"{tenant_id}@example.com",
            "password_hash": hash_password("seed-pass", salt=f"seed-{tenant_id}"),
            "role": UserRole.merchant.value,
            "region_code": None,
        }
        for idx, tenant_id in enumerate(tenants)
    ]
    user_rows.extend(
        [
            {
                "id": "demo_admin",
                "tenant_id": "tenant_01",
                "email": "admin@example.com",
                "password_hash": hash_password("seed-pass", salt="seed-admin"),
                "role": UserRole.admin.value,
                "region_code": None,
            },
            {
                "id": "demo_operator_shanghai",
                "tenant_id": "tenant_01",
                "email": "operator-shanghai@example.com",
                "password_hash": hash_password("seed-pass", salt="seed-operator-shanghai"),
                "role": UserRole.operator.value,
                "region_code": "shanghai",
            },
        ]
    )

    seen_keys: set[str] = set()
    reason_counts: Counter[str] = Counter()
    form_rows: list[dict] = []
    event_rows: list[dict] = []
    validated_workset: Counter[str] = Counter()
    for row in rows:
        reason = classify(row, seen_keys)
        if reason:
            reason_counts[reason] += 1
            event_rows.extend(events_for_row(row, inserted=False, reason=reason))
            continue
        created_at = parse_time(row["created_at"])
        status = row["status"]
        if status == "draft" and sum(validated_workset.values()) < DEMO_BATCH_WORKSET_SIZE:
            status = "validated"
            validated_workset[f"{row['tenant_id']}:{row['city_code']}:{row['form_type']}"] += 1
        form_rows.append(
            {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "form_type": row["form_type"],
                "status": status,
                "idempotency_key": row["idempotency_key"],
                "city_code": row["city_code"],
                "district_code": row["district_code"],
                "industry": row["industry"],
                "lng": float(row["lng"]),
                "lat": float(row["lat"]),
                "payload": row_payload(row),
                "batch_id": None,
                "retry_count": 0,
                "created_by": row["created_by"],
                "created_at": created_at,
                "updated_at": created_at,
            }
        )
        event_rows.extend(events_for_row(row, inserted=True, reason=None))

    engine = create_async_engine(settings.mysql_dsn, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if args.reset:
            await reset_tables(conn)
        await bulk_insert(conn, Tenant, tenant_rows)
        await bulk_insert(conn, User, user_rows)
        await bulk_insert(conn, Form, form_rows)
        await bulk_insert(conn, SubmissionEvent, event_rows)
        total_forms = int(await conn.scalar(select(func.count()).select_from(Form)) or 0)
        total_events = int(await conn.scalar(select(func.count()).select_from(SubmissionEvent)) or 0)

    summary = {
        "source": str(csv_path.relative_to(ROOT)),
        "input_rows": len(rows),
        "inserted_forms": total_forms,
        "submission_events": total_events,
        "skipped_rows": sum(reason_counts.values()),
        "skip_reasons": dict(reason_counts),
        "validated_workset_rows": sum(validated_workset.values()),
        "validated_workset_distribution": dict(sorted(validated_workset.items())),
        "time_anchor": timeline,
        "tenants": len(tenants),
        "demo_accounts": {
            "merchant": "tenant_01@example.com / seed-pass",
            "admin": "admin@example.com / seed-pass",
            "operator_shanghai": "operator-shanghai@example.com / seed-pass",
        },
        "note": "duplicate_idempotency_key is classified globally in the synthetic seed to make retry/dedup evidence explicit.",
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "evidence": str(out), **summary}, ensure_ascii=False))
    await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="artifacts/data/forms_seed.csv")
    parser.add_argument("--out", default="artifacts/data/load_summary.json")
    parser.add_argument("--reset", action="store_true")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
