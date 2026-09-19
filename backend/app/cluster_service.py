from __future__ import annotations

import hashlib
import json

import numpy as np
from redis.asyncio import from_url
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .aggregation import PointSet, grid_aggregate
from .config import settings
from .models import Form, FormStatus, FormType, User, UserRole


def bbox_tuple(value: str) -> tuple[float, float, float, float]:
    try:
        west, south, east, north = [float(item) for item in value.split(",")]
    except ValueError as exc:
        raise ValueError("bbox must be west,south,east,north") from exc
    if not (west < east and south < north):
        raise ValueError("bbox bounds are invalid")
    return west, south, east, north


def filter_token(filters: dict) -> str:
    return hashlib.sha1(json.dumps(filters, sort_keys=True, default=str).encode()).hexdigest()[:12]


def etag_for(filters: dict, row_count: int, max_updated_at: str) -> str:
    token = filter_token({**filters, "row_count": row_count, "max_updated_at": max_updated_at})
    return f'W/"v1:clusters:{token}:{row_count}"'


def cache_key(tenant_id: str, bbox: tuple[float, float, float, float], zoom: int, filters: dict) -> str:
    bbox_hash = hashlib.sha1(",".join(f"{item:.6f}" for item in bbox).encode()).hexdigest()[:12]
    return f"clusters:v1:{tenant_id}:{bbox_hash}:{zoom}:{filter_token(filters)}"


async def get_cached(key: str) -> dict | None:
    try:
        redis = from_url(settings.redis_url, decode_responses=True)
        value = await redis.get(key)
        await redis.aclose()
        return json.loads(value) if value else None
    except Exception:
        return None


async def set_cached(key: str, payload: dict) -> None:
    try:
        redis = from_url(settings.redis_url, decode_responses=True)
        await redis.set(key, json.dumps(payload, ensure_ascii=False), ex=60)
        await redis.aclose()
    except Exception:
        return


async def cluster_geojson(
    session: AsyncSession,
    actor: User,
    *,
    bbox: tuple[float, float, float, float],
    zoom: int,
    city: str | None,
    status: FormStatus | None,
    form_type: FormType | None,
    industry: str | None,
) -> tuple[dict, str, bool]:
    filters = {
        "city": city,
        "status": status.value if status else None,
        "form_type": form_type.value if form_type else None,
        "industry": industry,
    }
    cache = cache_key(actor.tenant_id, bbox, zoom, filters)
    cached = await get_cached(cache)
    if cached:
        return cached["payload"], cached["etag"], True

    west, south, east, north = bbox
    stmt = select(Form).where(Form.lng >= west, Form.lng <= east, Form.lat >= south, Form.lat <= north)
    if actor.role != UserRole.admin:
        stmt = stmt.where(Form.tenant_id == actor.tenant_id)
    if actor.role == UserRole.operator and actor.region_code:
        stmt = stmt.where(Form.city_code == actor.region_code)
    if city:
        stmt = stmt.where(Form.city_code == city)
    if status:
        stmt = stmt.where(Form.status == status)
    if form_type:
        stmt = stmt.where(Form.form_type == form_type)
    if industry:
        stmt = stmt.where(Form.industry == industry)
    result = await session.execute(stmt)
    forms = list(result.scalars())
    if forms:
        points = PointSet(
            ids=np.array([item.id for item in forms], dtype=object),
            tenant_ids=np.array([item.tenant_id for item in forms], dtype=object),
            form_types=np.array([item.form_type.value for item in forms], dtype=object),
            statuses=np.array([item.status.value for item in forms], dtype=object),
            city_codes=np.array([item.city_code for item in forms], dtype=object),
            industries=np.array([item.industry for item in forms], dtype=object),
            lng=np.array([item.lng for item in forms], dtype=np.float64),
            lat=np.array([item.lat for item in forms], dtype=np.float64),
        )
        clusters = grid_aggregate(points, zoom)
        max_updated_at = max(item.updated_at.isoformat() for item in forms)
    else:
        clusters = []
        max_updated_at = "0"
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": cluster["centroid"]},
                "properties": {
                    "cluster_id": cluster["cluster_id"],
                    "count": cluster["count"],
                    "centroid": cluster["centroid"],
                },
            }
            for cluster in clusters
        ],
    }
    etag = etag_for({**filters, "bbox": bbox, "zoom": zoom}, len(forms), max_updated_at)
    await set_cached(cache, {"payload": geojson, "etag": etag})
    return geojson, etag, False
