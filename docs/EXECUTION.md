# 执行账本

> 唯一进度来源。Phase 只有 DoD 命令真实跑过、证据文件落盘、commit 存在三者齐备才算完成。

## 会话记录

- 2026-09-19，本次会话目标：P2 聚合域（先关闭 P1 抽查遗留：refresh、状态流转触发者、operator 区域测试；再实现网格渲染聚合、批次贪心聚合、基准脚本、EXPLAIN 与 `docs/02`）。
- 2026-09-19，本次会话目标：P1 权限+表单域（RBAC/tenant 隔离、统一 forms 模型、4 类 schema、状态机、多维过滤器、埋点中间件、统一异常、审计事件、OpenAPI 导出与需求覆盖矩阵骨架）。
- 2026-09-18 23:41，本次会话目标：P0 脚手架（compose、Makefile、环境体检、10w 合成数据生成器、P0 证据落盘与 commit）。

## Phase 状态

| Phase | 状态 | DoD | 证据 | Commit | 遗留 |
|---|---|---|---|---|---|
| P0 | 已完成 | `make env-check` pass；`make seed N=100000` pass | `artifacts/env/check.json`; `artifacts/data/seed_summary.json`; `artifacts/data/forms_seed.csv` | `6d2751d` | 无 |
| P1 | 已完成 | `backend/.venv/bin/pytest backend/tests/test_auth.py backend/tests/test_forms.py --junitxml=artifacts/test/p1.xml` pass；`backend/.venv/bin/python scripts/export_openapi.py` pass | `artifacts/test/p1.xml`; `artifacts/openapi.json`; `docs/08-需求覆盖矩阵.md` | `c47caf4` | P0 seed 遗留已修复：`4054f46`；README 后续注明 MySQL 3306 冲突 |
| P2 | 已完成 | `backend/.venv/bin/python scripts/benchmark_aggregation.py --n 100000 --seed 20260918` pass | `artifacts/bench/aggregation.json`; `artifacts/bench/explain.txt`; `docs/02-地理聚合与性能优化.md` | `5cf8343` | P1 抽查遗留 3 项已关闭：`2f37022` |
| P3 | 未开始 | - | - | - | - |
| P4 | 未开始 | - | - | - | - |
| P5 | 未开始 | - | - | - | - |
| P6 | 未开始 | - | - | - | - |
| P7 | 未开始 | - | - | - | - |

## Blocker

暂无。

## 验证记录（Claude 抽查）

### P0 抽查（2026-09-19）— PASS

独立复核（不依赖本仓 summary 自述）：
- CSV 直查：100000 行；城市权重 shanghai 30000 / beijing 25000 / shenzhen 20000 / hangzhou 15000 / chengdu 10000（与 §4.6 精确一致）；越界坐标 500 条；幂等键 99000 唯一 / 2000 行涉重。
- 工程面：Makefile DoD 命令可复现；`check_env.py` fail-closed（失败返回 1）；docker-compose 符合规格（mysql:8.0 + mongo:7）；.env 未入库；commit `6d2751d` message 含证据路径；远端已同步。

遗留 2 项（转 P1 吸收，不阻塞）：
1. `illegal_status` 注入值为 `"submitted"`——它是合法枚举值（draft→submitted 属正常流转），命名为"非法状态"名不副实。P1 做导入/校验时二选一：改成枚举外值（如 `"unknown"`，可真正测校验拒绝）或改名澄清语义（如 `in_flight_status`）。另：`seed_summary.json.status_counts` 在异常注入**前**统计（summary published=85000 vs CSV 实际 84828，差额恰为之后被覆盖的 200 条），需在生成器或文档注明口径。
2. 本机装有 MySQL 8.0.45（当前未启动）；若意外启动将占用 3306，与 compose 端口冲突。README 启动说明中注明。

### P1 抽查（2026-09-19）— PASS（2 项契约缺口 + 1 项测试缺口，建议 P2 会话开头先关闭）

独立复核：
- DoD 复跑：`backend/.venv/bin/pytest backend/tests/test_auth.py backend/tests/test_forms.py` → **10 passed**（真 MySQL 非 mock）；`artifacts/test/p1.xml` 解析 = tests 10 / failures 0 / errors 0。
- 契约对齐（§4.1/§4.2/§4.3 已实现部分）：6 张表字段/约束/索引与 §4.1 一致（含 `uq_forms_tenant_idempotency` 与复合索引）；错误信封 `{code,message,detail,trace_id}` 与错误码一致；JWT=HS256、access 30min / refresh 7d 一致；状态机流转图与 §4.3 完全一致（含 failed 重试 `retry_count<3`）。
- 隔离与埋点：tenant 作用域在 repository 层统一注入（admin 全局 / operator 叠加 region 过滤）；埋点中间件字段符合 §4.10，且日志异常不影响业务（独立 try）。跨租户访问返回 404 不泄露存在性（有测试）。
- P0 遗留 #1 已修复（`4054f46`）：注入值改为枚举外 `unknown`，summary 记录 base/actual 双口径（84828+7 分类+200 unknown，自洽）。

遗留（建议 P2 开工先关闭，均为小改动，避免后续 Phase 叠加错误假设）：
1. **`/api/v1/auth/refresh` 未实现**（§4.2 冻结契约遗漏）。补：refresh token 换新 access（校验 `type=refresh`）+ 测试（无效/过期/类型错 → 401）。
2. **状态机"触发者"未强制**（§4.3 冻结列）。现状任意登录用户可驱动任意合法流转。应改为：merchant → 403；operator → 限 validating→rejected（及失败重试）；admin 放行（演示/测试用）；worker 走 P4 内部服务函数。测试 `test_allows_legal_state_transition` 目前由 merchant 触发 submitted→validating，需随规格改为 operator/admin，并新增 merchant→403 用例。
3. **operator 区域过滤有实现无测试**：补 1 条（operator_shanghai 仅见 shanghai 的表单）。

其它备注：
- 已接受偏差（不改码，随 01/02 文档注明）：`forms.lng/lat` 实际为 float64（§4.1 文本写 decimal(10,7)）；城市尺度 float64 误差 ≪1m，远小于等距圆柱近似与 Haversine 的误差量级。
- 次要：并发同键 create 竞态（IntegrityError→500）可留作已知限制或加兜底；`config.py` JWT_SECRET 带默认值兜底，README 注明演示必须配置 `.env`。
- mongo 容器尚未创建（仅 mysql 在跑）；P6 前执行 `docker compose -f deploy/docker-compose.yml up -d` 补起。
- 给 P3 的输入提示：seed 四类异常样本（unknown 200 / 越界 500 / 缺必填 1000 / 重复键 1000）在导入与事件生成时需显式分类处理，直接喂三口径统计。

### P2 抽查（2026-09-19）— 有条件通过：DoD 达标，但 R1 核心基准对比不成立，需修复

独立复核（可复现性 ✓）：
- DoD 复跑 `benchmark_aggregation.py --n 100000 --seed 20260918` → 7 行；p50 波动 <6%，features/payload/correctness 完全一致（确定性脚本 ✓）。
- 全量测试 13 passed；`p1.xml` = 13/0/0；P1 遗留三项确认关闭（refresh 类型校验、触发者权限含 region 校验、operator 区域过滤），均有测试。
- 网格参数与 §4.4 一致（zoom 映射 / 容量 50 / 半径 3000 / 等距圆柱排序 + Haversine 终判）；n=99304 构成可解释（500 越界 + 200 unknown − 4 重叠）。
- payload 工作负载站得住：1.566MB / 25351 features → 3.3KB / 34 features（≈471×）——"数据不下发"证据有效。

【必须修复】核心对比不成立（R1 证据链，面试官读脚本即穿帮）：
1. render_aggregation 的 `full_scan` 与 `grid` **跑的是同一个函数**（`grid_aggregate`），仅 filter 不同（grid 多一个 `status=published`）——不存在"全扫描 vs 网格分桶"对比；两行数字几乎相同（37.1 vs 37.6ms），无法支撑"网格分桶=渲染主路径"。
   修法：三者必须算法上真正不同：
   - full_scan：全量点 mask + 聚合（无索引）
   - grid：**按 zoom 预建网格索引**（点→cell 分桶缓存一次），查询 = 取 bbox 命中的格子 → 聚合
   - cKDTree：预建树 `query_ball_point` 取候选
   三者同一组 filter；正确性断言 cluster_id 集合**与计数**一致（centroid 容差内）。
2. cKDTree 计时不公平：`kd_mask` 构建在 timed 之外，而 full_scan/grid 的 `filter_mask` 在 timed 之内 → 25ms 有水分。修法：所有算法的候选/过滤构建一律计入计时。
3. 聚合器本身未优化：`grid_aggregate` 内 per-cell Python 循环（`inverse == idx`，O(cells×n)）是单查询 37ms 的主要成本——这正是"优化聚合效率"该拿下的点。修法：`np.bincount` + `np.add.at` 向量化分组。
   验收：grid 应显著快于 full_scan（数量级改善）；若实测达不到需在 docs/02 诚实解释，**禁止给 grid 喂更少数据制造优势**。
4. batch_build 的 `greedy_batches_grid` 名为 grid 实为全距离暴力（对全部未分配点算距离，O(n²)），与 §4.4"网格候选+距离排序"不符。修法：实现真·网格候选版并如实命名，基准改三方对比（暴力 / 网格候选 / KDTree 候选）。
   批次正确性口径改为**不变量断言**：全部点恰被分配一次、每批 ≤ 容量、成员距 seed ≤ 半径（Haversine 复算）；另报告批次数作为质量指标（三种算法不必逐位相同——贪心对候选集敏感，写进文档是加分项）。
   顺带：内层逐点标量 Haversine 调用改一次性向量化（可写进文档作为优化点）。
5. `peak_memory_mb` 三行同值（进程级 `ru_maxrss`，非算法级）→ 误导。修法：tracemalloc 逐算法测量，或改名 `process_peak_mb` 并注明口径。
6. `explain.txt` 证据太薄：rows=1（dev 库近空表）+ FORCE INDEX 掩盖优化器选择。修法：P3 导入 10w 后重跑（不加 FORCE，附 IGNORE INDEX 对照），docs/02 说明 FORCE 动机（低基数统计下优化器可能误判）。
7. 补 `backend/tests/test_aggregation.py`：合批不变量单测（容量/半径/唯一分配/不跨城市）+ 聚合结果与暴力基线一致性——这是"你怎么证明批次合法"的面试证据。
8. docs/02 补充口径：批次半径语义 = 成员距 **seed** ≤3000m（非两两、非质心）；n=99304 的构成；batch 工作负载 2000 样本的生产解释（按城市按日的批次工作集量级）。
9. payload 工作负载的 `p50_ms=0.001` 是手写占位——要么实测 JSON 序列化耗时（1.5MB vs 3KB 本身有意义），要么置 null。§6 禁止手写数字，不留把柄。

建议：下一个会话开头先做本修复（1–3 必做，4–9 顺手），再进 P3；修复后 docs/02 结论段按新数据重写。
