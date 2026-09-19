# 自测 Quiz

1. 为什么跨租户读取表单返回 404？
2. `submit_success_rate` 和 `db_success_rate` 的分子分别是什么？
3. 为什么批次构建要按 `(tenant_id, city_code)` 分组？
4. 地图页为什么只请求 `/api/v1/clusters`，不直接拉 10w forms？
5. 文档 PATCH 为什么必须带 `If-Match`？
6. 文档回滚是否会修改历史版本？
7. 当前 RAG 证据如何证明是真实生成？失败时怎么降级？
8. Spark 同构里为什么 Python 比 Spark 快？
9. WebSocket 不可用时前端怎么继续接收增量？
10. 哪些内容必须在面试中透明说明 AI 协作？

## 参考答案

1. 避免泄露其他租户资源存在性。
2. 提交成功率分子是 `submit_api_success`；落库成功率分子是 `db_insert_success`。
3. tenant 保证隔离，city 保证地理半径语义成立。
4. 10w 点下发会拖慢网络与渲染；聚合后只返回几百个以内 features。
5. 防止并发覆盖，版本不一致返回 409。
6. 不会；回滚会从历史版本创建一个新版本。
7. `artifacts/rag/rag_demo.json` 的 `mode=deepseek`，回答来自 DeepSeek，并保留 citations；失败时脚本回退 retrieval-only，并写入脱敏错误。
8. 100k 本地 CSV 下 Spark 启动和 shuffle 成本占主导；Spark 是规模化路径。
9. 使用 `/api/v1/events?since=` 轮询降级。
10. 说明 AI 是结对助手，候选人负责理解、验证和答辩。
