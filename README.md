# Merchant Onboarding Platform

## 我如何理解这道题

这道题表面上要求 Python/Next.js/Spark/RAG/WebSocket，核心其实是一个 B 端入驻平台：企业提交商户、房源、商品、报表四类表单后，平台要保证权限边界、数据准确性、地理聚合效率、批处理可追踪，以及统计口径可解释。UI 不是重点，重点是数据是否可信、流程是否能自动推进、异常和撤回是否有业务语义。

我的设计主线是：商户入驻表单 -> 按坐标做渲染聚合与业务批次 -> 四类表单进入批处理管线 -> 用事件表统计成功率和撤回率 -> 用知识文档 CRUD/RAG 承载规则说明。所有重要结论都落到代码、测试和 `artifacts/` 证据里，面试时可以逐条追问。

## 关键设计判断

| 题目关注点 | 我的理解 | 对应设计 | 证据入口 |
|---|---|---|---|
| 权限和数据准确性 | B 端系统先保护租户边界，再谈效率 | JWT/RBAC、tenant scope、operator region、跨租户 404、审计事件 | `docs/01-系统架构设计.md`, `backend/tests/test_auth.py`, `backend/tests/test_forms.py` |
| 10w+ 表单聚合 | 地图渲染聚合和业务批次不是一件事 | bbox/zoom 网格簇用于渲染；tenant/city 分区批次用于处理 | `docs/02-地理聚合与性能优化.md`, `artifacts/bench/aggregation.json` |
| 查询和渲染性能 | 不把 10w 点下发给前端 | Redis cluster cache、ETag/304、TanStack Query、MapLibre marker 对拍 | `docs/07-前端性能与缓存报告.md`, `artifacts/frontend/perf.json` |
| 成功率统计 | 成功率要说明是谁的视角 | 提交成功率、落库成功率、端到端成功率、撤回率 | `docs/03-提交成功率统计设计.md`, `backend/tests/test_success_rate.py` |
| 四类表单批处理 | 批处理要可重跑、可追责、可失败续跑 | checkpoint、DLQ、指数退避、202 异步运行、实时进度 | `docs/06-批处理流程设计.md`, `artifacts/test/p9.xml` |
| 知识文档 CRUD/RAG | CRUD 是主线，RAG 是加分 | Mongo 版本/软删/回滚；DeepSeek 真实生成，失败降级 retrieval-only | `docs/04-知识文档存储与RAG设计.md`, `artifacts/rag/rag_demo.json` |
| 跨端适配 | 交互密度随终端变化，不是简单响应式 | Web/移动 Web/小程序/大屏/PWA 的职责切分 | `docs/05-跨端适配方案.md` |

逐题映射与证据见 `docs/08-需求覆盖矩阵.md`。

## 交付文档

- `docs/01-系统架构设计.md`：系统分层、技术取舍、数据准确性策略。
- `docs/02-地理聚合与性能优化.md`：10w 聚合、payload 对比、实时缓存边界。
- `docs/03-提交成功率统计设计.md`：事件模型、三口径成功率、撤回率。
- `docs/04-知识文档存储与RAG设计.md`：Mongo CRUD、版本、RAG、Spark、预测。
- `docs/05-跨端适配方案.md`：Web、移动、小程序、大屏、PWA。
- `docs/06-批处理流程设计.md`：批次构建、异步运行、DLQ、实时进度。
- `docs/07-前端性能与缓存报告.md`：MVVM、缓存、E2E 性能数字。
- `docs/08-需求覆盖矩阵.md`：原题要求到代码/证据的映射。

过程性施工书、评审记录、执行账本已移出仓库保留在本地存档，避免交付仓库重心偏向过程材料。

## 技术栈

- 后端：FastAPI、SQLAlchemy async、MySQL 8、MongoDB 7、Redis。
- 前端：Next.js 15、React、TanStack Query、MapLibre、Zustand、Playwright。
- 数据与扩展：10w 合成表单、PySpark 同构对拍、DeepSeek RAG demo、轻量报表趋势预测。

## 本地演示账号

`scripts/load_seed.py --reset` 会写入以下演示账号：

| 角色 | 账号 | 密码 | 用途 |
|---|---|---|---|
| merchant | `tenant_01@example.com` | `seed-pass` | 表单、地图、统计的 tenant 视角 |
| admin | `admin@example.com` | `seed-pass` | 构建/运行批次、全局管理视角 |
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
3. `/forms` 查看表单，撤回本人表单，观察状态时间线。
4. `/batches` 构建/运行批次，观察 `202 Accepted`、实时进度与终态变化。
5. `/stats` 查看近 24h 成功率、端到端成功率和撤回率。
6. `/docs` 创建知识文档、生成新版本、软删除。

## 常用验证命令

```bash
backend/.venv/bin/pytest backend/tests --junitxml=artifacts/test/backend_all.xml
backend/.venv/bin/python scripts/export_openapi.py
backend/.venv/bin/python scripts/audit_requirements.py
PYTHONPATH=/home/lx/spark/python/lib/pyspark.zip:/home/lx/spark/python/lib/py4j-0.10.9.7-src.zip SPARK_HOME=/home/lx/spark backend/.venv/bin/python scripts/compare_spark_python.py
backend/.venv/bin/python scripts/rag_demo.py
backend/.venv/bin/python scripts/forecast_reports.py
```

一键演示辅助：

```bash
bash scripts/demo.sh
```

## 关键证据

- `artifacts/audit/requirements.json`：需求覆盖审计。
- `artifacts/test/backend_all.xml`：后端真库集成测试。
- `artifacts/frontend/perf.json`、`artifacts/playwright/map.png`：前端性能与地图证据。
- `artifacts/playwright/realtime_before.png`、`artifacts/playwright/realtime_after.png`、`artifacts/playwright/realtime_admin_batch.png`：不刷新实时流转与 admin 跨租户批次实时进度证据。
- `artifacts/rag/rag_demo.json`：DeepSeek 真实生成或 retrieval-only 降级证据。
- `artifacts/bench/spark_compare.json`、`artifacts/bench/report_forecast.json`：Spark 同构与报表预测证据。

## 已知说明

- RAG key 只从本地 `.env` 读取，不入库、不写证据；无 key 或调用失败时自动降级 retrieval-only。
- 100k 本地 CSV 下 Spark 慢于 Python，原因是 JVM 启动和 shuffle 成本；这里用 Spark 证明规模化同构路径。
- 实时流转由 FastAPI lifespan worker 驱动，当前演示为单实例前提，多实例生产部署需分布式锁或独立任务队列。
- 合成数据仅用于演示和性能/正确性证据，不代表真实商户数据。

AI 作为结对工程助手参与实现与审查，最终交付以代码、测试、文档和可复验证据为准。
