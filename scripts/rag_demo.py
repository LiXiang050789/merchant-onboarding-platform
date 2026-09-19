#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import settings  # noqa: E402
from backend.app.docs_store import DocsRepository, tokenize  # noqa: E402


DEMO_DOCS = [
    {
        "title": "入驻审核规则",
        "content": "商户入驻必须校验证照、地址、经营类目三类数据。证照编号不能为空，地址需要与经纬度所在城市一致。",
    },
    {
        "title": "房源资料口径",
        "content": "商户房源需要提供房源名称、详细地址和城市坐标。房源批处理前必须处于 validated 状态。",
    },
    {
        "title": "批处理失败处理",
        "content": "批处理采用 checkpoint 和 DLQ 记录失败项。修复后重跑同一批次，已发布记录会跳过，未完成记录继续推进。",
    },
]


def ensure_demo_docs(repo: DocsRepository, tenant_id: str, user_id: str) -> None:
    for item in DEMO_DOCS:
        if repo.docs.count_documents({"tenant_id": tenant_id, "status": "active", "title": item["title"]}) == 0:
            repo.create(tenant_id=tenant_id, user_id=user_id, title=item["title"], content=item["content"])


def retrieve(repo: DocsRepository, tenant_id: str, question: str, limit: int) -> list[dict]:
    query_tokens = set(tokenize(question))
    docs = list(repo.docs.find({"tenant_id": tenant_id, "status": "active"}))
    scored: list[tuple[int, dict]] = []
    for doc in docs:
        overlap = len(query_tokens & set(doc.get("tokens", [])))
        if overlap:
            scored.append((overlap, repo._join_current(doc)))
    scored.sort(key=lambda item: (-item[0], item[1]["updated_at"]))
    citations: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for score, doc in scored:
        excerpt = doc["content"][:180]
        signature = (doc["title"], excerpt)
        if signature in seen:
            continue
        seen.add(signature)
        citations.append(
            {
                "doc_id": doc["id"],
                "title": doc["title"],
                "version": doc["current_version"],
                "score": score,
                "excerpt": excerpt,
            }
        )
        if len(citations) >= limit:
            break
    return citations


def extractive_answer(question: str, citations: list[dict]) -> str:
    if not citations:
        return "没有检索到可引用的知识文档。"
    lines = [f"问题：{question}", "回答："]
    for index, item in enumerate(citations, start=1):
        lines.append(f"{index}. {item['excerpt']}（引用：{item['title']} v{item['version']}）")
    return "\n".join(lines)


def call_deepseek(question: str, citations: list[dict]) -> str | None:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    context = "\n\n".join(f"[{idx}] {item['title']} v{item['version']}: {item['excerpt']}" for idx, item in enumerate(citations, start=1))
    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": "你是商户入驻平台的知识库助手。只能基于给定引用回答，并在回答中标注引用编号。"},
            {"role": "user", "content": f"问题：{question}\n\n引用材料：\n{context}"},
        ],
        "temperature": 0.2,
    }
    request = urllib.request.Request(
        os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", default="tenant_01")
    parser.add_argument("--user-id", default="demo_admin")
    parser.add_argument("--question", default="商户入驻审核时必须校验哪些数据？")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--out", default="artifacts/rag/rag_demo.json")
    args = parser.parse_args()

    started = time.perf_counter()
    repo = DocsRepository.from_settings()
    ensure_demo_docs(repo, args.tenant_id, args.user_id)
    citations = retrieve(repo, args.tenant_id, args.question, args.limit)
    llm_answer = call_deepseek(args.question, citations)
    mode = "deepseek" if llm_answer else "retrieval_only"
    payload = {
        "question": args.question,
        "mode": mode,
        "answer": llm_answer or extractive_answer(args.question, citations),
        "citations": citations,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "note": "DEEPSEEK_API_KEY was not present, so the run used retrieval-only mode." if mode == "retrieval_only" else "DeepSeek response generated from retrieved citations.",
    }
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "mode": mode, "evidence": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
