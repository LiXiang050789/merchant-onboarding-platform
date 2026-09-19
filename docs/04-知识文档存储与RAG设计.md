# 知识文档存储与 RAG 设计

## 已实现范围

P6 当前完成知识文档主线：MongoDB 真库 CRUD、乐观锁版本、软删除、历史版本回滚、jieba 预分词检索，以及前端 `/docs` 页接入真实 API。

加分项也已补齐：

- Spark 同构：`scripts/compare_spark_python.py` 对同一份 10w CSV 做 Python 与 PySpark 对拍。
- RAG：`scripts/rag_demo.py` 基于 Mongo + jieba tokens 做检索增强问答；当前环境无 `DEEPSEEK_API_KEY`，证据为 retrieval-only。
- 报表预测：`scripts/forecast_reports.py` 对 `report` 类型表单做城市级 7 天趋势预测。

## Mongo 集合

`knowledge_docs` 保存当前态：

- `_id`：文档 id，形如 `doc_*`
- `tenant_id`：租户隔离键
- `title`：当前标题
- `current_version`：当前版本号
- `status`：`active` / `deleted`
- `deleted_at`：软删时间
- `tokens`：当前版本标题+正文的 jieba tokens
- `created_by` / `created_at` / `updated_at`

索引：

- `tenant_id,status,updated_at`
- `tenant_id,tokens` multikey

`knowledge_doc_versions` 保存不可变历史：

- `doc_id` / `tenant_id` / `version_no`
- `title` / `content`
- `etag`
- `created_by` / `created_at`
- `rollback_from_version`：仅回滚生成的新版本记录

唯一索引：`doc_id,version_no`。

## API 语义

- `POST /api/v1/docs`：创建文档，同时写当前态与 version 1。
- `GET /api/v1/docs?q=`：默认只返回当前租户 active 文档；`q` 先 jieba 分词，再用 `tokens: {$all: ...}` 匹配当前版本。
- `GET /api/v1/docs/{id}`：跨租户、软删、无此文档均返回 404。
- `PATCH /api/v1/docs/{id}`：必须带 `If-Match: <current_version>`；版本不一致返回 409 `version_conflict`；成功后创建新历史版本。
- `DELETE /api/v1/docs/{id}`：软删除，只改当前态；历史版本保留。
- `POST /api/v1/docs/{id}/rollback`：读取历史版本内容，创建一个新的当前版本；不覆盖历史。

文档写入、更新、删除都会发布 `doc.updated` / `doc.deleted` 事件，供前端增量刷新或后续 Redis PubSub 扩展。

## 测试证据

- `artifacts/test/p6_docs.xml`：4 条真 Mongo 集成测试通过。
- `artifacts/test/backend_all.xml`：后端全集 29 条通过。
- `artifacts/openapi.json`：已包含 `/api/v1/docs` 与 rollback 接口。

覆盖用例：

- CRUD + jieba token 检索
- tenant 隔离
- `If-Match` 乐观锁冲突
- 软删不可见
- 回滚生成新版本

## Spark 同构

`scripts/compare_spark_python.py` 复用 `artifacts/data/forms_seed.csv`，按 `load_seed.py` 的导入口径对拍：

- 坐标、状态、必填字段校验
- 幂等键去重
- 城市、表单类型、状态、城市×类型维度计数

证据：`artifacts/bench/spark_compare.json`。结果显示 `correctness_passed=true`，Spark 3.5.0 与 Python 结果一致；100k 本地 CSV 下 Python 更快，原因是 Spark JVM 启动与 shuffle 成本占主导。答辩口径：Spark 是规模化路径，不是这个数据量的性能炫技。

## RAG

`scripts/rag_demo.py` 会确保 demo 知识文档存在，使用 jieba tokens 做候选召回，并输出带引用回答：

- 有 `DEEPSEEK_API_KEY`：调用 DeepSeek 生成带引用回答。
- 无 key：降级为 retrieval-only，仍输出引用片段与模式说明。

当前证据：`artifacts/rag/rag_demo.json`，`mode=retrieval_only`。这符合"key 不入库、无 key 不伪造真实调用"的交付原则。

## 报表预测

`scripts/forecast_reports.py` 读取 10w 合成表单，过滤有效记录与重复幂等键后，对 `form_type=report` 的城市级每日提交量建模：

- 模型：`0.5 * linear_trend + 0.5 * trailing_7day_mean`
- 输出：未来 7 天预测、holdout MAE/MAPE

证据：`artifacts/bench/report_forecast.json`。这是轻量、可解释的趋势基线，用于回应 JD 中"一点点机器学习/数据分析"；不用于真实业务决策。
