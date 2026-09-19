#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
VALID_STATUSES = {"draft", "submitted", "validating", "validated", "rejected", "batched", "processing", "published", "failed"}


def is_valid(row: dict) -> bool:
    lng = float(row["lng"])
    lat = float(row["lat"])
    return 73 <= lng <= 135 and 18 <= lat <= 54 and row["status"] in VALID_STATUSES and bool(row["payload_required_name"])


def load_daily_counts(csv_path: Path) -> dict[str, dict[date, int]]:
    seen: set[str] = set()
    daily: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))
    with csv_path.open(newline="", encoding="utf-8") as fp:
        for row in csv.DictReader(fp):
            if not is_valid(row):
                continue
            if row["idempotency_key"] in seen:
                continue
            seen.add(row["idempotency_key"])
            if row["form_type"] != "report":
                continue
            day = datetime.fromisoformat(row["created_at"]).date()
            daily[row["city_code"]][day] += 1
    return daily


def dense_series(values: dict[date, int]) -> tuple[list[date], np.ndarray]:
    start = min(values)
    end = max(values)
    days = [start + timedelta(days=index) for index in range((end - start).days + 1)]
    series = np.array([values.get(day, 0) for day in days], dtype=float)
    return days, series


def forecast_city(values: dict[date, int], horizon: int) -> dict:
    days, series = dense_series(values)
    x = np.arange(len(series), dtype=float)
    holdout = min(3, max(1, len(series) // 5))
    train_x = x[:-holdout]
    train_y = series[:-holdout]
    test_y = series[-holdout:]
    slope, intercept = np.polyfit(train_x, train_y, 1)
    trend_pred = slope * x[-holdout:] + intercept
    ma7 = float(np.mean(train_y[-7:]))
    blend_pred = np.maximum(0, np.round((trend_pred + ma7) / 2, 2))
    mae = float(np.mean(np.abs(blend_pred - test_y)))
    mape = float(np.mean(np.abs(blend_pred - test_y) / np.maximum(test_y, 1)) * 100)

    future = []
    for offset in range(1, horizon + 1):
        next_x = len(series) - 1 + offset
        trend = slope * next_x + intercept
        value = max(0.0, round((trend + float(np.mean(series[-7:]))) / 2, 2))
        future.append({"date": (days[-1] + timedelta(days=offset)).isoformat(), "predicted_reports": value})

    return {
        "history_days": len(series),
        "history_total_reports": int(series.sum()),
        "last_observed_date": days[-1].isoformat(),
        "model": "0.5 * linear_trend + 0.5 * trailing_7day_mean",
        "backtest": {"holdout_days": holdout, "mae": round(mae, 3), "mape_percent": round(mape, 3)},
        "forecast": future,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="artifacts/data/forms_seed.csv")
    parser.add_argument("--horizon", type=int, default=7)
    parser.add_argument("--out", default="artifacts/bench/report_forecast.json")
    args = parser.parse_args()

    daily = load_daily_counts(ROOT / args.csv)
    forecasts = {city: forecast_city(values, args.horizon) for city, values in sorted(daily.items())}
    payload = {
        "source": args.csv,
        "target": "daily report-form submissions by city",
        "horizon_days": args.horizon,
        "cities": forecasts,
        "note": "This is a lightweight, explainable trend baseline for the JD's 'a little ML' signal; it is not used for business decisions.",
    }
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "evidence": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
