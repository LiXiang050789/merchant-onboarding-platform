#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SEED = 20260918
CITY_WEIGHTS = {
    "shanghai": 0.30,
    "beijing": 0.25,
    "shenzhen": 0.20,
    "hangzhou": 0.15,
    "chengdu": 0.10,
}
CITY_CENTERS = {
    "shanghai": [(121.4737, 31.2304), (121.4998, 31.2397), (121.3890, 31.1206), (121.6150, 31.1976), (121.4480, 31.2222)],
    "beijing": [(116.4074, 39.9042), (116.4551, 39.9440), (116.3120, 39.9840), (116.5430, 39.8700), (116.2317, 40.2208)],
    "shenzhen": [(114.0579, 22.5431), (114.1010, 22.5470), (113.9304, 22.5333), (114.2640, 22.7210), (113.8140, 22.7470)],
    "hangzhou": [(120.1551, 30.2741), (120.2100, 30.2084), (120.0890, 30.3040), (120.2700, 30.3120), (119.9850, 30.2740)],
    "chengdu": [(104.0665, 30.5723), (104.0815, 30.6570), (104.0430, 30.6420), (104.1010, 30.6300), (103.9230, 30.7610)],
}
STATUS_WEIGHTS = {
    "published": 0.85,
    "processing": 0.04,
    "batched": 0.04,
    "rejected": 0.03,
    "failed": 0.02,
    "draft": 0.02,
}
FORM_TYPES = ["merchant_info", "property", "product", "report"]
INDUSTRIES = ["restaurant", "retail", "hotel", "education", "service"]
DISTRICTS = ["core", "north", "south", "east", "west"]


def exact_counts(n: int, ratios: dict[str, float]) -> dict[str, int]:
    items = list(ratios.items())
    raw = [(key, n * ratio) for key, ratio in items]
    counts = {key: int(value) for key, value in raw}
    remaining = n - sum(counts.values())
    fractions = sorted(((value - int(value), key) for key, value in raw), reverse=True)
    for _, key in fractions[:remaining]:
        counts[key] += 1
    return counts


def repeated_values(values: list[str], counts: dict[str, int], rng: np.random.Generator) -> np.ndarray:
    out: list[str] = []
    for value in values:
        out.extend([value] * counts[value])
    arr = np.array(out, dtype=object)
    rng.shuffle(arr)
    return arr


def build_rows(n: int) -> tuple[list[dict], dict]:
    rng = np.random.default_rng(SEED)
    city_counts = exact_counts(n, CITY_WEIGHTS)
    status_counts = exact_counts(n, STATUS_WEIGHTS)
    cities = repeated_values(list(CITY_WEIGHTS), city_counts, rng)
    statuses = repeated_values(list(STATUS_WEIGHTS), status_counts, rng)
    form_types = rng.choice(FORM_TYPES, size=n)
    industries = rng.choice(INDUSTRIES, size=n)
    districts = rng.choice(DISTRICTS, size=n)

    lng = np.empty(n)
    lat = np.empty(n)
    center_counter: Counter[str] = Counter()
    for i, city in enumerate(cities):
        center_idx = int(rng.integers(0, len(CITY_CENTERS[city])))
        center_lng, center_lat = CITY_CENTERS[city][center_idx]
        center_counter[f"{city}:{center_idx}"] += 1
        lng[i] = rng.normal(center_lng, 0.02)
        lat[i] = rng.normal(center_lat, 0.02)

    anomaly_counts = {
        "invalid_coordinates": round(n * 0.005),
        "missing_required": round(n * 0.01),
        "duplicate_idempotency_key": round(n * 0.01),
        "illegal_status": round(n * 0.002),
    }
    invalid_idx = rng.choice(n, size=anomaly_counts["invalid_coordinates"], replace=False)
    lng[invalid_idx] = 999.0
    lat[invalid_idx] = 999.0

    missing_required_idx = set(rng.choice(n, size=anomaly_counts["missing_required"], replace=False).tolist())
    illegal_status_idx = set(rng.choice(n, size=anomaly_counts["illegal_status"], replace=False).tolist())
    duplicate_count = anomaly_counts["duplicate_idempotency_key"]
    duplicate_sources = rng.choice(np.arange(0, n // 2), size=duplicate_count, replace=False)
    duplicate_targets = rng.choice(np.arange(n // 2, n), size=duplicate_count, replace=False)

    idempotency_keys = np.array([f"idem_{i:06d}" for i in range(n)], dtype=object)
    for source_idx, target_idx in zip(duplicate_sources, duplicate_targets):
        idempotency_keys[target_idx] = idempotency_keys[source_idx]

    base_time = datetime(2026, 9, 1, tzinfo=timezone.utc)
    created_offsets = rng.integers(0, 14 * 24 * 3600, size=n)
    rows: list[dict] = []
    for i in range(n):
        form_type = str(form_types[i])
        required_value = "" if i in missing_required_idx else f"{form_type}_{i:06d}"
        status = "unknown" if i in illegal_status_idx else str(statuses[i])
        created_at = base_time + timedelta(seconds=int(created_offsets[i]))
        tenant_num = (i % 20) + 1
        row = {
            "id": f"form_{i:06d}",
            "tenant_id": f"tenant_{tenant_num:02d}",
            "form_type": form_type,
            "status": status,
            "idempotency_key": str(idempotency_keys[i]),
            "city_code": str(cities[i]),
            "district_code": str(districts[i]),
            "industry": str(industries[i]),
            "lng": f"{float(lng[i]):.7f}",
            "lat": f"{float(lat[i]):.7f}",
            "payload_required_name": required_value,
            "created_by": f"user_{tenant_num:02d}",
            "created_at": created_at.isoformat(),
        }
        rows.append(row)

    summary = {
        "seed": SEED,
        "total": n,
        "city_counts": dict(Counter(cities.tolist())),
        "base_status_counts": dict(Counter(statuses.tolist())),
        "actual_status_counts": dict(Counter(row["status"] for row in rows)),
        "form_type_counts": dict(Counter(form_types.tolist())),
        "industry_counts": dict(Counter(industries.tolist())),
        "center_counts": dict(sorted(center_counter.items())),
        "anomaly_counts": anomaly_counts,
        "duplicate_idempotency_key_unique_count": len(set(idempotency_keys.tolist())),
        "files": {
            "csv": "artifacts/data/forms_seed.csv",
            "summary": "artifacts/data/seed_summary.json",
        },
    }
    return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100000)
    parser.add_argument("--out-dir", default="artifacts/data")
    args = parser.parse_args()

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, summary = build_rows(args.n)

    csv_path = out_dir / "forms_seed.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary_path = out_dir / "seed_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "rows": args.n, "evidence": str(summary_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
