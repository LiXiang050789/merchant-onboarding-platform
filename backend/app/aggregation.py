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

    def subset_indices(self, indices: np.ndarray) -> "PointSet":
        return PointSet(
            ids=self.ids[indices],
            tenant_ids=self.tenant_ids[indices],
            form_types=self.form_types[indices],
            statuses=self.statuses[indices],
            city_codes=self.city_codes[indices],
            industries=self.industries[indices],
            lng=self.lng[indices],
            lat=self.lat[indices],
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
    return aggregate_cells(zoom, lng, lat, cells)


def aggregate_cells(zoom: int, lng: np.ndarray, lat: np.ndarray, cells: np.ndarray) -> list[dict]:
    unique, inverse = np.unique(cells, axis=0, return_inverse=True)
    counts = np.bincount(inverse)
    lng_sum = np.bincount(inverse, weights=lng)
    lat_sum = np.bincount(inverse, weights=lat)
    clusters: list[dict] = []
    for idx, (x_cell, y_cell) in enumerate(unique):
        count = int(counts[idx])
        clusters.append(
            {
                "cluster_id": f"z{zoom}:{int(x_cell)}:{int(y_cell)}",
                "count": count,
                "centroid": [float(lng_sum[idx] / count), float(lat_sum[idx] / count)],
            }
        )
    return clusters


class GridIndex:
    def __init__(self, points: PointSet, zoom: int):
        self.points = points
        self.zoom = zoom
        self.size = grid_size_for_zoom(zoom)
        self.cell_x = np.floor(points.lng / self.size).astype(np.int64)
        self.cell_y = np.floor(points.lat / self.size).astype(np.int64)
        self.cells = np.stack([self.cell_x, self.cell_y], axis=1)
        self.index: dict[tuple[int, int], list[int]] = {}
        for idx, key in enumerate(zip(self.cell_x, self.cell_y)):
            self.index.setdefault((int(key[0]), int(key[1])), []).append(idx)

    def bbox_candidates(self, bbox: tuple[float, float, float, float]) -> np.ndarray:
        west, south, east, north = bbox
        min_x = math.floor(west / self.size)
        max_x = math.floor(east / self.size)
        min_y = math.floor(south / self.size)
        max_y = math.floor(north / self.size)
        indices: list[int] = []
        for x_cell in range(min_x, max_x + 1):
            for y_cell in range(min_y, max_y + 1):
                indices.extend(self.index.get((x_cell, y_cell), []))
        if not indices:
            return np.array([], dtype=np.int64)
        return np.array(indices, dtype=np.int64)

    def aggregate(
        self,
        *,
        bbox: tuple[float, float, float, float],
        city: str | None = None,
        status: str | None = None,
        form_type: str | None = None,
        industry: str | None = None,
    ) -> list[dict]:
        candidates = self.bbox_candidates(bbox)
        if len(candidates) == 0:
            return []
        west, south, east, north = bbox
        mask = (
            (self.points.lng[candidates] >= west)
            & (self.points.lng[candidates] <= east)
            & (self.points.lat[candidates] >= south)
            & (self.points.lat[candidates] <= north)
        )
        if city:
            mask &= self.points.city_codes[candidates] == city
        if status:
            mask &= self.points.statuses[candidates] == status
        if form_type:
            mask &= self.points.form_types[candidates] == form_type
        if industry:
            mask &= self.points.industries[candidates] == industry
        if not mask.any():
            return []
        selected = candidates[mask]
        return aggregate_cells(self.zoom, self.points.lng[selected], self.points.lat[selected], self.cells[selected])


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

    def aggregate(
        self,
        *,
        bbox: tuple[float, float, float, float],
        zoom: int,
        city: str | None = None,
        status: str | None = None,
        form_type: str | None = None,
        industry: str | None = None,
    ) -> list[dict]:
        mask = self.bbox_candidates(bbox) & self.points.filter_mask(
            city=city,
            status=status,
            form_type=form_type,
            industry=industry,
        )
        return grid_aggregate(self.points, zoom, mask)


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
    cell_size = radius_m / 110_540
    cell_x = np.floor(points.lng / cell_size).astype(np.int64)
    cell_y = np.floor(points.lat / cell_size).astype(np.int64)
    index: dict[tuple[int, int], set[int]] = {}
    for idx, key in enumerate(zip(cell_x, cell_y)):
        index.setdefault((int(key[0]), int(key[1])), set()).add(idx)
    unassigned = set(range(len(points.lng)))
    batches: list[list[int]] = []
    while unassigned:
        seed = min(unassigned)
        unassigned.remove(seed)
        candidate_set: set[int] = set()
        for x_cell in range(int(cell_x[seed]) - 2, int(cell_x[seed]) + 3):
            for y_cell in range(int(cell_y[seed]) - 2, int(cell_y[seed]) + 3):
                candidate_set.update(index.get((x_cell, y_cell), set()))
        candidates = np.array(sorted(candidate_set & unassigned), dtype=np.int64)
        if len(candidates) == 0:
            batches.append([seed])
            continue
        near = equirectangular_meters(points.lng[seed], points.lat[seed], points.lng[candidates], points.lat[candidates])
        ordered = candidates[np.argsort(near)]
        selected = [seed]
        final_distances = haversine_meters(points.lng[seed], points.lat[seed], points.lng[ordered], points.lat[ordered])
        for idx, final_distance in zip(ordered, final_distances):
            if len(selected) >= capacity:
                break
            if idx not in unassigned:
                continue
            if final_distance <= radius_m:
                selected.append(int(idx))
                unassigned.remove(int(idx))
        batches.append(selected)
    return batches


def greedy_batches_bruteforce(points: PointSet, *, capacity: int = 50, radius_m: int = 3000) -> list[list[int]]:
    unassigned = set(range(len(points.lng)))
    batches: list[list[int]] = []
    while unassigned:
        seed = min(unassigned)
        unassigned.remove(seed)
        candidates = np.array(sorted(unassigned), dtype=np.int64)
        if len(candidates) == 0:
            batches.append([seed])
            continue
        distances = equirectangular_meters(points.lng[seed], points.lat[seed], points.lng[candidates], points.lat[candidates])
        ordered = candidates[np.argsort(distances)]
        final_distances = haversine_meters(points.lng[seed], points.lat[seed], points.lng[ordered], points.lat[ordered])
        selected = [seed]
        for idx, final_distance in zip(ordered, final_distances):
            if len(selected) >= capacity:
                break
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
        ordered = candidate_array[np.argsort(distances)]
        final_distances = haversine_meters(points.lng[seed], points.lat[seed], points.lng[ordered], points.lat[ordered])
        for idx, final_distance in zip(ordered, final_distances):
            if len(selected) >= capacity:
                break
            if final_distance <= radius_m:
                selected.append(int(idx))
                unassigned.remove(int(idx))
        batches.append(selected)
    return batches


def clusters_payload_size(clusters: Iterable[dict]) -> int:
    return len(json.dumps(list(clusters), ensure_ascii=False).encode("utf-8"))


def validate_batches(points: PointSet, batches: list[list[int]], *, capacity: int = 50, radius_m: int = 3000) -> bool:
    assigned = [idx for batch in batches for idx in batch]
    if sorted(assigned) != list(range(len(points.lng))):
        return False
    for batch in batches:
        if not batch or len(batch) > capacity:
            return False
        seed = batch[0]
        members = np.array(batch, dtype=np.int64)
        distances = haversine_meters(points.lng[seed], points.lat[seed], points.lng[members], points.lat[members])
        if bool(np.any(distances > radius_m + 1e-6)):
            return False
    return True
