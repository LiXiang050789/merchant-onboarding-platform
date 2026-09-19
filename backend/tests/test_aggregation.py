from __future__ import annotations

import numpy as np

from backend.app.aggregation import (
    GridIndex,
    KDTreeIndex,
    PointSet,
    greedy_batches_grid,
    grid_aggregate,
    validate_batches,
)


def sample_points() -> PointSet:
    lng = np.array([121.470, 121.471, 121.472, 121.520, 121.521, 116.400], dtype=np.float64)
    lat = np.array([31.230, 31.231, 31.232, 31.250, 31.251, 39.900], dtype=np.float64)
    return PointSet(
        ids=np.array([f"form_{idx}" for idx in range(len(lng))], dtype=object),
        tenant_ids=np.array(["tenant_a"] * len(lng), dtype=object),
        form_types=np.array(["merchant_info"] * len(lng), dtype=object),
        statuses=np.array(["published"] * len(lng), dtype=object),
        city_codes=np.array(["shanghai", "shanghai", "shanghai", "shanghai", "shanghai", "beijing"], dtype=object),
        industries=np.array(["restaurant"] * len(lng), dtype=object),
        lng=lng,
        lat=lat,
    )


def cluster_signature(clusters: list[dict]) -> dict[str, int]:
    return {item["cluster_id"]: item["count"] for item in clusters}


def test_grid_and_kdtree_aggregation_match_full_scan():
    points = sample_points()
    bbox = (121.45, 31.20, 121.54, 31.27)
    zoom = 13

    full = grid_aggregate(points, zoom, points.filter_mask(bbox=bbox, city="shanghai", status="published"))
    grid = GridIndex(points, zoom).aggregate(bbox=bbox, city="shanghai", status="published")
    kdtree = KDTreeIndex(points).aggregate(bbox=bbox, zoom=zoom, city="shanghai", status="published")

    assert cluster_signature(full) == cluster_signature(grid) == cluster_signature(kdtree)


def test_grid_candidate_batches_satisfy_invariants():
    points = sample_points().subset(np.array([True, True, True, True, True, False]))

    batches = greedy_batches_grid(points, capacity=3, radius_m=6000)

    assert validate_batches(points, batches, capacity=3, radius_m=6000)
    assert all(len(batch) <= 3 for batch in batches)
