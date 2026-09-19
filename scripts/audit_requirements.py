#!/usr/bin/env python
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


REQUIREMENTS = {
    "R0": {
        "requirement": "权限和数据要素准确性",
        "evidence": [
            ("backend/tests/test_auth.py", "test_login_issues_access_and_refresh_tokens"),
            ("backend/tests/test_forms.py", "test_tenant_scope_hides_other_tenant_form"),
            ("backend/tests/test_forms.py", "test_operator_region_scope_lists_only_own_city"),
        ],
    },
    "R1": {
        "requirement": "10w+ 地理聚合与查询/渲染优化",
        "evidence": [
            ("scripts/benchmark_aggregation.py", "render_workload"),
            ("artifacts/bench/aggregation.json", "correctness_passed"),
            ("docs/02-地理聚合与性能优化.md", "payload"),
        ],
    },
    "R2": {
        "requirement": "前端缓存与网络请求",
        "evidence": [
            ("backend/app/cluster_service.py", "etag_for"),
            ("frontend/src/features/map/view-model/use-map-view-model.ts", "staleTime"),
            ("frontend/tests/e2e/golden.spec.ts", "toHaveCount"),
        ],
    },
    "R3": {
        "requirement": "成功率统计代码",
        "evidence": [
            ("backend/app/stats.py", "compute_success_rate"),
            ("backend/tests/test_success_rate.py", "dedupes_retries_late_events"),
            ("docs/03-提交成功率统计设计.md", "三种口径"),
        ],
    },
    "R4": {
        "requirement": "知识文档 CRUD 逻辑代码",
        "evidence": [
            ("backend/app/docs_store.py", "class DocsRepository"),
            ("backend/tests/test_docs.py", "test_doc_rollback_creates_new_version_from_history"),
            ("artifacts/test/p6_docs.xml", "test_doc_soft_delete_is_invisible"),
        ],
    },
    "R5": {
        "requirement": "跨端适配方案",
        "evidence": [
            ("docs/05-跨端适配方案.md", "移动端"),
            ("docs/05-跨端适配方案.md", "小程序"),
            ("docs/05-跨端适配方案.md", "PWA"),
        ],
    },
    "R6": {
        "requirement": "四类表单流程、多维过滤器、埋点、异常处理",
        "evidence": [
            ("backend/app/schemas.py", "REQUIRED_BY_TYPE"),
            ("backend/app/main.py", "trace_and_telemetry"),
            ("backend/tests/test_forms.py", "test_filter_combination_respects_tenant_scope"),
        ],
    },
    "R7": {
        "requirement": "批处理流程构建",
        "evidence": [
            ("backend/app/batch_pipeline.py", "run_batch"),
            ("backend/tests/test_batch_pipeline.py", "test_run_batch_writes_dlq_and_retry_can_resume"),
            ("docs/06-批处理流程设计.md", "checkpoint"),
        ],
    },
    "R8": {
        "requirement": "WebSocket + RAG 技术栈点名",
        "evidence": [
            ("backend/app/main.py", "websocket_endpoint"),
            ("scripts/rag_demo.py", "call_deepseek"),
            ("artifacts/rag/rag_demo.json", "retrieval_only"),
        ],
    },
    "JD": {
        "requirement": "数据分析、轻 ML、会 JS 优先",
        "evidence": [
            ("scripts/forecast_reports.py", "linear_trend"),
            ("scripts/compare_spark_python.py", "spark_compare"),
            ("frontend/src/features/map/view/map-view.tsx", "MapView"),
        ],
    },
}


def find_line(path: Path, pattern: str) -> int | None:
    if not path.exists():
        return None
    for index, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        if pattern in line:
            return index
    return None


def main() -> int:
    results = {}
    passed = True
    for key, item in REQUIREMENTS.items():
        evidence = []
        for relative, pattern in item["evidence"]:
            line = find_line(ROOT / relative, pattern)
            ok = line is not None
            passed = passed and ok
            evidence.append({"path": relative, "pattern": pattern, "line": line, "ok": ok})
        results[key] = {"requirement": item["requirement"], "ok": all(row["ok"] for row in evidence), "evidence": evidence}
    payload = {"status": "pass" if passed else "fail", "requirements": results}
    out = ROOT / "artifacts/audit/requirements.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "evidence": str(out)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
