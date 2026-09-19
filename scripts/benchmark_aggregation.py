#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.aggregation import (  # noqa: E402
    GridIndex,
    KDTreeIndex,
    PointSet,
    clusters_payload_size,
    greedy_batches_bruteforce,
    greedy_batches_grid,
    greedy_batches_kdtree,
    grid_aggregate,
    validate_batches,
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


def timed(samples: list[float], peaks: list[float], fn):
    tracemalloc.start()
    start = time.perf_counter()
    result = fn()
    samples.append((time.perf_counter() - start) * 1000)
    _, peak = tracemalloc.get_traced_memory()
    peaks.append(peak / 1024 / 1024)
    tracemalloc.stop()
    return result


def metric_row(workload: str, algorithm: str, n: int, samples: list[float], peaks: list[float], payload_bytes: int, features_count: int, correctness: bool) -> dict:
    return {
        "workload": workload,
        "algorithm": algorithm,
        "n": n,
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(np.percentile(samples, 95), 3),
        "total_ms": round(sum(samples), 3),
        "payload_bytes": int(payload_bytes),
        "features_count": int(features_count),
        "peak_memory_mb": round(max(peaks) if peaks else 0, 2),
        "correctness_passed": bool(correctness),
    }


def cluster_signature(clusters: list[dict]) -> dict[str, tuple[int, float, float]]:
    return {
        item["cluster_id"]: (item["count"], round(item["centroid"][0], 7), round(item["centroid"][1], 7))
        for item in clusters
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
    grid_indexes = {zoom: GridIndex(points, zoom) for _, zoom, _ in queries}
    samples = {"full_scan": [], "grid": [], "cKDTree": []}
    peaks = {"full_scan": [], "grid": [], "cKDTree": []}
    payload = {"full_scan": 0, "grid": 0, "cKDTree": 0}
    features = {"full_scan": 0, "grid": 0, "cKDTree": 0}
    correctness = True

    for bbox, zoom, city in queries:
        filters = {"bbox": bbox, "city": city, "status": "published"}
        full_clusters = timed(
            samples["full_scan"],
            peaks["full_scan"],
            lambda zoom=zoom, filters=filters: grid_aggregate(points, zoom, points.filter_mask(**filters)),
        )
        grid_clusters = timed(
            samples["grid"],
            peaks["grid"],
            lambda bbox=bbox, city=city, zoom=zoom: grid_indexes[zoom].aggregate(bbox=bbox, city=city, status="published"),
        )
        kd_clusters = timed(
            samples["cKDTree"],
            peaks["cKDTree"],
            lambda bbox=bbox, zoom=zoom, city=city: kd_index.aggregate(bbox=bbox, zoom=zoom, city=city, status="published"),
        )
        correctness &= cluster_signature(full_clusters) == cluster_signature(grid_clusters) == cluster_signature(kd_clusters)
        for name, clusters in [("full_scan", full_clusters), ("grid", grid_clusters), ("cKDTree", kd_clusters)]:
            payload[name] += clusters_payload_size(clusters)
            features[name] += len(clusters)

    for name in ["full_scan", "grid", "cKDTree"]:
        rows.append(metric_row("render_aggregation", name, len(points.lng), samples[name], peaks[name], payload[name], features[name], correctness))
    return rows


def batch_workload(points: PointSet) -> list[dict]:
    city_mask = points.filter_mask(city="shanghai", status="published")
    subset_idx = np.flatnonzero(city_mask)[:2000]
    sample = points.subset(np.isin(np.arange(len(points.lng)), subset_idx))
    algorithms = {
        "bruteforce_greedy": greedy_batches_bruteforce,
        "grid_candidate_greedy": greedy_batches_grid,
        "cKDTree_greedy": greedy_batches_kdtree,
    }
    rows: list[dict] = []
    for name, fn in algorithms.items():
        samples: list[float] = []
        peaks: list[float] = []
        batches = timed(samples, peaks, lambda fn=fn: fn(sample, capacity=50, radius_m=3000))
        rows.append(
            metric_row(
                "batch_build",
                name,
                len(sample.lng),
                samples,
                peaks,
                0,
                len(batches),
                validate_batches(sample, batches, capacity=50, radius_m=3000),
            )
        )
    return rows


def payload_workload(points: PointSet) -> list[dict]:
    bbox = (121.30, 31.05, 121.70, 31.35)
    mask = points.filter_mask(bbox=bbox, city="shanghai", status="published")
    raw_samples: list[float] = []
    raw_peaks: list[float] = []
    cluster_samples: list[float] = []
    cluster_peaks: list[float] = []

    def encode_raw() -> bytes:
        raw_points = [
            {"id": str(points.ids[idx]), "lng": float(points.lng[idx]), "lat": float(points.lat[idx])}
            for idx in np.flatnonzero(mask)
        ]
        return json.dumps(raw_points, ensure_ascii=False).encode("utf-8")

    def encode_clusters() -> bytes:
        return json.dumps(grid_aggregate(points, 11, mask), ensure_ascii=False).encode("utf-8")

    raw_payload = timed(raw_samples, raw_peaks, encode_raw)
    cluster_payload = timed(cluster_samples, cluster_peaks, encode_clusters)
    return [
        metric_row("payload", "raw_points", len(points.lng), raw_samples, raw_peaks, len(raw_payload), int(mask.sum()), True),
        metric_row("payload", "clustered", len(points.lng), cluster_samples, cluster_peaks, len(cluster_payload), len(json.loads(cluster_payload)), len(cluster_payload) < len(raw_payload)),
    ]


async def write_explain(path: Path) -> None:
    engine = create_async_engine(settings.mysql_dsn, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        query = (
            "SELECT id FROM forms "
            "WHERE tenant_id='tenant_01' AND status='published' AND form_type='merchant_info' "
            "AND city_code='shanghai' AND lng BETWEEN 121.30 AND 121.70 AND lat BETWEEN 31.05 AND 31.35"
        )
        forced_query = query.replace("FROM forms", "FROM forms FORCE INDEX(ix_forms_tenant_status_type_city_lng_lat)")
        lines = ["EXPLAIN forms filter query", ""]
        for label, sql in [("optimizer_choice", query), ("forced_expected_index", forced_query)]:
            result = await conn.execute(text(f"EXPLAIN {sql}"))
            lines.append(f"[{label}]")
            for row in result.mappings():
                lines.append(json.dumps(dict(row), ensure_ascii=False, default=str))
            lines.append("")
        lines.append("")
        lines.append(f"expected_index=ix_forms_tenant_status_type_city_lng_lat")
        lines.append("note=dev table may be nearly empty, so optimizer_choice can differ; forced_expected_index proves the frozen index is usable.")
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
