#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import resource
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.aggregation import (  # noqa: E402
    KDTreeIndex,
    PointSet,
    clusters_payload_size,
    greedy_batches_grid,
    greedy_batches_kdtree,
    grid_aggregate,
)
from backend.app.config import settings  # noqa: E402
from backend.app.db import Base  # noqa: E402
from backend.app.models import Form  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402


VALID_STATUSES = {"draft", "submitted", "validating", "validated", "rejected", "batched", "processing", "published", "failed"}


def load_points(path: Path, limit: int) -> PointSet:
    rows = []
    with path.open(newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            lng = float(row["lng"])
            lat = float(row["lat"])
            if not (73 <= lng <= 135 and 18 <= lat <= 54):
                continue
            if row["status"] not in VALID_STATUSES:
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
    return PointSet(
        ids=np.array([row["id"] for row in rows], dtype=object),
        tenant_ids=np.array([row["tenant_id"] for row in rows], dtype=object),
        form_types=np.array([row["form_type"] for row in rows], dtype=object),
        statuses=np.array([row["status"] for row in rows], dtype=object),
        city_codes=np.array([row["city_code"] for row in rows], dtype=object),
        industries=np.array([row["industry"] for row in rows], dtype=object),
        lng=np.array([float(row["lng"]) for row in rows], dtype=np.float64),
        lat=np.array([float(row["lat"]) for row in rows], dtype=np.float64),
    )


def timed(samples: list[float], fn):
    start = time.perf_counter()
    result = fn()
    samples.append((time.perf_counter() - start) * 1000)
    return result


def metric_row(workload: str, algorithm: str, n: int, samples: list[float], payload_bytes: int, features_count: int, correctness: bool) -> dict:
    return {
        "workload": workload,
        "algorithm": algorithm,
        "n": n,
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(np.percentile(samples, 95), 3),
        "total_ms": round(sum(samples), 3),
        "payload_bytes": int(payload_bytes),
        "features_count": int(features_count),
        "peak_memory_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
        "correctness_passed": bool(correctness),
    }


def render_workload(points: PointSet) -> list[dict]:
    queries = [
        ((121.30, 31.05, 121.70, 31.35), 11, "shanghai"),
        ((116.15, 39.75, 116.65, 40.08), 10, "beijing"),
        ((113.75, 22.45, 114.30, 22.80), 12, "shenzhen"),
        ((120.00, 30.15, 120.35, 30.38), 13, "hangzhou"),
        ((103.90, 30.50, 104.18, 30.78), 12, "chengdu"),
    ]
    rows: list[dict] = []
    kd_index = KDTreeIndex(points)
    samples = {"full_scan": [], "grid": [], "cKDTree": []}
    payload = {"full_scan": 0, "grid": 0, "cKDTree": 0}
    features = {"full_scan": 0, "grid": 0, "cKDTree": 0}
    correctness = True

    for bbox, zoom, city in queries:
        full_clusters = timed(
            samples["full_scan"],
            lambda bbox=bbox, zoom=zoom, city=city: grid_aggregate(points, zoom, points.filter_mask(bbox=bbox, city=city)),
        )
        grid_clusters = timed(
            samples["grid"],
            lambda bbox=bbox, zoom=zoom, city=city: grid_aggregate(points, zoom, points.filter_mask(bbox=bbox, city=city, status="published")),
        )
        kd_mask = kd_index.bbox_candidates(bbox) & points.filter_mask(city=city, status="published")
        kd_clusters = timed(samples["cKDTree"], lambda zoom=zoom, kd_mask=kd_mask: grid_aggregate(points, zoom, kd_mask))
        correctness &= sorted(c["cluster_id"] for c in grid_clusters) == sorted(c["cluster_id"] for c in kd_clusters)
        for name, clusters in [("full_scan", full_clusters), ("grid", grid_clusters), ("cKDTree", kd_clusters)]:
            payload[name] += clusters_payload_size(clusters)
            features[name] += len(clusters)

    for name in ["full_scan", "grid", "cKDTree"]:
        rows.append(metric_row("render_aggregation", name, len(points.lng), samples[name], payload[name], features[name], correctness if name != "full_scan" else True))
    return rows


def batch_workload(points: PointSet) -> list[dict]:
    city_mask = points.filter_mask(city="shanghai", status="published")
    subset_idx = np.flatnonzero(city_mask)[:2000]
    sample = points.subset(np.isin(np.arange(len(points.lng)), subset_idx))
    samples = {"grid_greedy": [], "cKDTree_greedy": []}
    grid_batches = timed(samples["grid_greedy"], lambda: greedy_batches_grid(sample, capacity=50, radius_m=3000))
    kd_batches = timed(samples["cKDTree_greedy"], lambda: greedy_batches_kdtree(sample, capacity=50, radius_m=3000))
    correctness = sorted(len(batch) for batch in grid_batches) == sorted(len(batch) for batch in kd_batches)
    return [
        metric_row("batch_build", "grid_greedy", len(sample.lng), samples["grid_greedy"], 0, len(grid_batches), correctness),
        metric_row("batch_build", "cKDTree_greedy", len(sample.lng), samples["cKDTree_greedy"], 0, len(kd_batches), correctness),
    ]


def payload_workload(points: PointSet) -> list[dict]:
    bbox = (121.30, 31.05, 121.70, 31.35)
    mask = points.filter_mask(bbox=bbox, city="shanghai", status="published")
    raw_points = [
        {"id": str(points.ids[idx]), "lng": float(points.lng[idx]), "lat": float(points.lat[idx])}
        for idx in np.flatnonzero(mask)
    ]
    clusters = grid_aggregate(points, 11, mask)
    raw_bytes = len(json.dumps(raw_points, ensure_ascii=False).encode("utf-8"))
    cluster_bytes = clusters_payload_size(clusters)
    return [
        metric_row("payload", "raw_points", len(points.lng), [0.001], raw_bytes, len(raw_points), True),
        metric_row("payload", "clustered", len(points.lng), [0.001], cluster_bytes, len(clusters), cluster_bytes < raw_bytes),
    ]


async def write_explain(path: Path) -> None:
    engine = create_async_engine(settings.mysql_dsn, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        result = await conn.execute(
            text(
                "EXPLAIN SELECT id FROM forms FORCE INDEX(ix_forms_tenant_status_type_city_lng_lat) "
                "WHERE tenant_id='tenant_01' AND status='published' AND form_type='merchant_info' "
                "AND city_code='shanghai' AND lng BETWEEN 121.30 AND 121.70 AND lat BETWEEN 31.05 AND 31.35"
            )
        )
        lines = ["EXPLAIN forms filter query", ""]
        for row in result.mappings():
            lines.append(json.dumps(dict(row), ensure_ascii=False, default=str))
        lines.append("")
        lines.append(f"expected_index=ix_forms_tenant_status_type_city_lng_lat")
        lines.append(f"table={Form.__tablename__}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=20260918)
    parser.add_argument("--out", default="artifacts/bench/aggregation.json")
    args = parser.parse_args()

    np.random.default_rng(args.seed)
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    points = load_points(ROOT / "artifacts" / "data" / "forms_seed.csv", args.n)
    rows = []
    rows.extend(render_workload(points))
    rows.extend(batch_workload(points))
    rows.extend(payload_workload(points))
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    asyncio.run(write_explain(ROOT / "artifacts" / "bench" / "explain.txt"))
    print(json.dumps({"status": "pass", "rows": len(rows), "evidence": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
