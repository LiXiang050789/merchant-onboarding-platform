#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALID_STATUSES = {"draft", "submitted", "validating", "validated", "rejected", "batched", "processing", "published", "failed"}


def classify_priority(row: dict, seen: set[str]) -> str | None:
    lng = float(row["lng"])
    lat = float(row["lat"])
    if not (73 <= lng <= 135 and 18 <= lat <= 54):
        return "invalid_coordinates"
    if row["status"] not in VALID_STATUSES:
        return "illegal_status"
    if not row["payload_required_name"]:
        return "missing_required"
    if row["idempotency_key"] in seen:
        return "duplicate_idempotency_key"
    seen.add(row["idempotency_key"])
    return None


def python_baseline(csv_path: Path) -> dict:
    started = time.perf_counter()
    seen: set[str] = set()
    skip_reasons: Counter[str] = Counter()
    valid_rows: list[dict] = []
    with csv_path.open(newline="", encoding="utf-8") as fp:
        for index, row in enumerate(csv.DictReader(fp)):
            row["_row_index"] = index
            reason = classify_priority(row, seen)
            if reason:
                skip_reasons[reason] += 1
                continue
            valid_rows.append(row)

    dimensions = {
        "city_counts": Counter(row["city_code"] for row in valid_rows),
        "form_type_counts": Counter(row["form_type"] for row in valid_rows),
        "status_counts": Counter(row["status"] for row in valid_rows),
        "city_form_type_counts": Counter(f"{row['city_code']}|{row['form_type']}" for row in valid_rows),
    }
    return {
        "engine": "python",
        "rows": len(valid_rows) + sum(skip_reasons.values()),
        "valid_rows": len(valid_rows),
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "dimensions": {key: dict(sorted(value.items())) for key, value in dimensions.items()},
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def spark_compare(csv_path: Path, app_name: str = "merchant-spark-compare") -> dict:
    started = time.perf_counter()
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.window import Window

    spark = (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.hadoop.fs.defaultFS", "file:///")
        .getOrCreate()
    )
    try:
        df = spark.read.option("header", True).csv(f"file://{csv_path.resolve()}")
        indexed = df.withColumn("_row_index", F.monotonically_increasing_id()).withColumn("lng_num", F.col("lng").cast("double")).withColumn("lat_num", F.col("lat").cast("double"))
        pre_checked = indexed.withColumn(
            "pre_reason",
            F.when(~((F.col("lng_num").between(73, 135)) & (F.col("lat_num").between(18, 54))), F.lit("invalid_coordinates"))
            .when(~F.col("status").isin(sorted(VALID_STATUSES)), F.lit("illegal_status"))
            .when(F.col("payload_required_name").isNull() | (F.col("payload_required_name") == ""), F.lit("missing_required")),
        )
        clean_for_dedupe = pre_checked.where(F.col("pre_reason").isNull())
        window = Window.partitionBy("idempotency_key").orderBy("_row_index")
        deduped = clean_for_dedupe.withColumn("rn", F.row_number().over(window)).withColumn(
            "reason", F.when(F.col("rn") > 1, F.lit("duplicate_idempotency_key"))
        )
        invalid = pre_checked.where(F.col("pre_reason").isNotNull()).select(F.col("pre_reason").alias("reason"))
        skipped = invalid.unionByName(deduped.where(F.col("reason").isNotNull()).select("reason"))
        valid = deduped.where(F.col("reason").isNull())

        skip_reasons = {row["reason"]: int(row["count"]) for row in skipped.groupBy("reason").count().collect()}

        def collect_counts(*cols: str) -> dict[str, int]:
            result: dict[str, int] = {}
            for row in valid.groupBy(*cols).count().collect():
                key = "|".join(str(row[col]) for col in cols)
                result[key] = int(row["count"])
            return dict(sorted(result.items()))

        rows = int(indexed.count())
        valid_rows = int(valid.count())
        dimensions = {
            "city_counts": collect_counts("city_code"),
            "form_type_counts": collect_counts("form_type"),
            "status_counts": collect_counts("status"),
            "city_form_type_counts": collect_counts("city_code", "form_type"),
        }
        return {
            "engine": "spark",
            "rows": rows,
            "valid_rows": valid_rows,
            "skip_reasons": dict(sorted(skip_reasons.items())),
            "dimensions": dimensions,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "spark_version": spark.version,
        }
    finally:
        spark.stop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="artifacts/data/forms_seed.csv")
    parser.add_argument("--out", default="artifacts/bench/spark_compare.json")
    args = parser.parse_args()

    csv_path = ROOT / args.csv
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    python_result = python_baseline(csv_path)
    spark_result = spark_compare(csv_path)
    comparable_keys = ["rows", "valid_rows", "skip_reasons", "dimensions"]
    mismatches = {
        key: {"python": python_result[key], "spark": spark_result[key]}
        for key in comparable_keys
        if python_result[key] != spark_result[key]
    }
    payload = {
        "source": str(csv_path.relative_to(ROOT)),
        "correctness_passed": not mismatches,
        "mismatches": mismatches,
        "python": python_result,
        "spark": spark_result,
        "note": "Spark is validated as a scale-out equivalent path; for 100k local CSV, Python is expected to be faster because Spark startup dominates.",
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass" if payload["correctness_passed"] else "fail", "evidence": str(out_path)}, ensure_ascii=False))
    return 0 if payload["correctness_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
