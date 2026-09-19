from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.spatial import cKDTree


GRID_SIZES = [
    (8, 0.2),
    (10, 0.1),
    (12, 0.05),
    (14, 0.02),
    (99, 0.01),
]


@dataclass(frozen=True)
class PointSet:
    ids: np.ndarray
    tenant_ids: np.ndarray
    form_types: np.ndarray
    statuses: np.ndarray
    city_codes: np.ndarray
    industries: np.ndarray
    lng: np.ndarray
    lat: np.ndarray

    def filter_mask(
        self,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        city: str | None = None,
        status: str | None = None,
        form_type: str | None = None,
        industry: str | None = None,
    ) -> np.ndarray:
        mask = np.ones(len(self.lng), dtype=bool)
        if bbox:
            west, south, east, north = bbox
            mask &= (self.lng >= west) & (self.lng <= east) & (self.lat >= south) & (self.lat <= north)
        if city:
            mask &= self.city_codes == city
        if status:
            mask &= self.statuses == status
        if form_type:
            mask &= self.form_types == form_type
        if industry:
            mask &= self.industries == industry
        return mask

    def subset(self, mask: np.ndarray) -> "PointSet":
        return PointSet(
            ids=self.ids[mask],
            tenant_ids=self.tenant_ids[mask],
            form_types=self.form_types[mask],
            statuses=self.statuses[mask],
            city_codes=self.city_codes[mask],
            industries=self.industries[mask],
            lng=self.lng[mask],
            lat=self.lat[mask],
        )


def grid_size_for_zoom(zoom: int) -> float:
    for max_zoom, size in GRID_SIZES:
        if zoom <= max_zoom:
            return size
    return 0.01


def grid_aggregate(points: PointSet, zoom: int, mask: np.ndarray | None = None) -> list[dict]:
    mask = mask if mask is not None else np.ones(len(points.lng), dtype=bool)
    lng = points.lng[mask]
    lat = points.lat[mask]
    if len(lng) == 0:
        return []
    size = grid_size_for_zoom(zoom)
    cell_x = np.floor(lng / size).astype(np.int64)
    cell_y = np.floor(lat / size).astype(np.int64)
    cells = np.stack([cell_x, cell_y], axis=1)
    unique, inverse = np.unique(cells, axis=0, return_inverse=True)
    clusters: list[dict] = []
    for idx, (x_cell, y_cell) in enumerate(unique):
        cluster_mask = inverse == idx
        count = int(cluster_mask.sum())
        clusters.append(
            {
                "cluster_id": f"z{zoom}:{int(x_cell)}:{int(y_cell)}",
                "count": count,
                "centroid": [float(lng[cluster_mask].mean()), float(lat[cluster_mask].mean())],
            }
        )
    return clusters


class KDTreeIndex:
    def __init__(self, points: PointSet):
        self.points = points
        self.tree = cKDTree(np.column_stack([points.lng, points.lat]))

    def bbox_candidates(self, bbox: tuple[float, float, float, float]) -> np.ndarray:
        west, south, east, north = bbox
        center = np.array([(west + east) / 2, (south + north) / 2])
        radius = math.hypot(east - west, north - south) / 2
        candidate_idx = np.array(self.tree.query_ball_point(center, radius), dtype=np.int64)
        if len(candidate_idx) == 0:
            return np.array([], dtype=bool)
        mask = np.zeros(len(self.points.lng), dtype=bool)
        sub_lng = self.points.lng[candidate_idx]
        sub_lat = self.points.lat[candidate_idx]
        keep = (sub_lng >= west) & (sub_lng <= east) & (sub_lat >= south) & (sub_lat <= north)
        mask[candidate_idx[keep]] = True
        return mask


def equirectangular_meters(lng1: float, lat1: float, lng2: np.ndarray, lat2: np.ndarray) -> np.ndarray:
    avg_lat = np.radians((lat1 + lat2) / 2)
    x = (lng2 - lng1) * np.cos(avg_lat) * 111_320
    y = (lat2 - lat1) * 110_540
    return np.sqrt(x * x + y * y)


def haversine_meters(lng1: float, lat1: float, lng2: np.ndarray, lat2: np.ndarray) -> np.ndarray:
    radius = 6_371_000
    lng1_rad, lat1_rad = math.radians(lng1), math.radians(lat1)
    lng2_rad = np.radians(lng2)
    lat2_rad = np.radians(lat2)
    dlng = lng2_rad - lng1_rad
    dlat = lat2_rad - lat1_rad
    a = np.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlng / 2) ** 2
    return 2 * radius * np.arcsin(np.sqrt(a))


def greedy_batches_grid(points: PointSet, *, capacity: int = 50, radius_m: int = 3000) -> list[list[int]]:
    unassigned = set(range(len(points.lng)))
    batches: list[list[int]] = []
    while unassigned:
        seed = min(unassigned)
        unassigned.remove(seed)
        candidates = np.array(sorted(unassigned), dtype=np.int64)
        if len(candidates) == 0:
            batches.append([seed])
            break
        near = equirectangular_meters(points.lng[seed], points.lat[seed], points.lng[candidates], points.lat[candidates])
        ordered = candidates[np.argsort(near)]
        selected = [seed]
        for idx in ordered:
            if len(selected) >= capacity:
                break
            if idx not in unassigned:
                continue
            final_distance = haversine_meters(points.lng[seed], points.lat[seed], np.array([points.lng[idx]]), np.array([points.lat[idx]]))[0]
            if final_distance <= radius_m:
                selected.append(int(idx))
                unassigned.remove(int(idx))
        batches.append(selected)
    return batches


def greedy_batches_kdtree(points: PointSet, *, capacity: int = 50, radius_m: int = 3000) -> list[list[int]]:
    unassigned = set(range(len(points.lng)))
    tree = cKDTree(np.column_stack([points.lng, points.lat]))
    batches: list[list[int]] = []
    while unassigned:
        seed = min(unassigned)
        unassigned.remove(seed)
        radius_deg = radius_m / max(70_000, 110_540 * math.cos(math.radians(points.lat[seed])))
        candidates = [idx for idx in tree.query_ball_point([points.lng[seed], points.lat[seed]], radius_deg) if idx in unassigned]
        if not candidates:
            batches.append([seed])
            continue
        candidate_array = np.array(candidates, dtype=np.int64)
        distances = equirectangular_meters(points.lng[seed], points.lat[seed], points.lng[candidate_array], points.lat[candidate_array])
        selected = [seed]
        for idx in candidate_array[np.argsort(distances)]:
            if len(selected) >= capacity:
                break
            final_distance = haversine_meters(points.lng[seed], points.lat[seed], np.array([points.lng[idx]]), np.array([points.lat[idx]]))[0]
            if final_distance <= radius_m:
                selected.append(int(idx))
                unassigned.remove(int(idx))
        batches.append(selected)
    return batches


def clusters_payload_size(clusters: Iterable[dict]) -> int:
    return len(json.dumps(list(clusters), ensure_ascii=False).encode("utf-8"))
