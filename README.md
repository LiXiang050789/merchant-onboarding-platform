# Merchant Onboarding Platform

全栈技术作业实现仓库。执行进度以 `docs/EXECUTION.md` 为准，冻结规格见 `docs/00-施工书.md`。

项目主线：商户入驻表单 → 地理聚合 → 批处理 → 成功率统计 → 知识文档 CRUD/RAG → Spark 同构与轻量报表预测。

## 技术栈

- 后端：FastAPI、SQLAlchemy async、MySQL 8、MongoDB 7、Redis、PySpark demo。
- 前端：Next.js 15、React、TanStack Query、MapLibre、Zustand、Playwright。
- 数据：10w 合成表单、真实 MySQL/Mongo 集成测试、证据落盘到 `artifacts/`。

## 关键文档

- `docs/01-系统架构设计.md`：架构与技术取舍。
- `docs/02-地理聚合与性能优化.md`：10w 聚合、benchmark、payload 对比。
- `docs/03-提交成功率统计设计.md`：三口径成功率。
- `docs/04-知识文档存储与RAG设计.md`：Mongo CRUD、RAG、Spark、预测。
- `docs/05-跨端适配方案.md`：Web/移动/小程序/大屏/PWA。
- `docs/10-AI协作声明.md`：AI 协作边界。

## 本地演示账号

`scripts/load_seed.py --reset` 会写入以下演示账号：

| 角色 | 账号 | 密码 | 用途 |
|---|---|---|---|
| merchant | `tenant_01@example.com` | `seed-pass` | 表单、地图、统计的 tenant 视角 |
| admin | `admin@example.com` | `seed-pass` | 构建/运行批次 |
| operator | `operator-shanghai@example.com` | `seed-pass` | 上海区域运营视角 |

## 启动顺序

```bash
docker compose -f deploy/docker-compose.yml up -d mysql mongo
redis-server
backend/.venv/bin/python scripts/load_seed.py --reset
backend/.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev
```

前端地址：`http://127.0.0.1:3000`。后端地址：`http://127.0.0.1:8000`。

`next build` 和 `next dev` 都会写 `.next`，演示时不要让二者同时操作同一目录；如果刚跑过 `npm run build`，请重启 `npm run dev`。

## 演示动线

1. 用 `admin@example.com / seed-pass` 登录。
2. `/map` 查看上海聚合 marker，切换状态为 `validated`。
3. `/stats` 查看近 24h 成功率，确认 attempts 非 0。
4. `/batches` 构建/运行批次，观察状态变化。
5. `/docs` 创建知识文档、生成新版本、软删除。
6. 查看证据文件：
   - `artifacts/frontend/perf.json`
   - `artifacts/test/backend_all.xml`
   - `artifacts/test/p6_docs.xml`
   - `artifacts/bench/spark_compare.json`
   - `artifacts/rag/rag_demo.json`
   - `artifacts/bench/report_forecast.json`
   - `artifacts/audit/requirements.json`

## 常用命令

```bash
backend/.venv/bin/pytest backend/tests --junitxml=artifacts/test/backend_all.xml
backend/.venv/bin/python scripts/export_openapi.py
PYTHONPATH=/home/lx/spark/python/lib/pyspark.zip:/home/lx/spark/python/lib/py4j-0.10.9.7-src.zip SPARK_HOME=/home/lx/spark backend/.venv/bin/python scripts/compare_spark_python.py
backend/.venv/bin/python scripts/rag_demo.py
backend/.venv/bin/python scripts/forecast_reports.py
backend/.venv/bin/python scripts/audit_requirements.py
```

一键演示辅助：

```bash
bash scripts/demo.sh
```

## 已知说明

- RAG 证据已通过 `.env` 中的 `DEEPSEEK_API_KEY` 完成真实 DeepSeek 生成；脚本仍保留无 key/调用失败时的 retrieval-only 降级，并在 JSON 证据中标注。
- 100k 本地 CSV 下 Spark 慢于 Python，原因是 JVM 启动和 shuffle 成本；本项目用 Spark 证明规模化同构路径。
- 合成数据仅用于演示和性能/正确性证据，不代表真实商户数据。
- 本项目使用 AI 作为结对工程助手，协作边界见 `docs/10-AI协作声明.md`。
