# 知识文档存储与 RAG 设计

## 已实现范围

P6 当前完成知识文档主线：MongoDB 真库 CRUD、乐观锁版本、软删除、历史版本回滚、jieba 预分词检索，以及前端 `/docs` 页接入真实 API。RAG、Spark 同构与报表预测仍按 v3 砍单顺序作为后续加分项。

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

## RAG 预留

RAG 不与 CRUD 主线绑定。后续可复用 `tokens` 检索得到候选文档片段，再调用 DeepSeek 生成带引用回答。若 DeepSeek key 或网络不可用，保留检索-only 并在交付文档中标注。
