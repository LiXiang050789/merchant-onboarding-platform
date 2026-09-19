# 执行账本

> 唯一进度来源。Phase 只有 DoD 命令真实跑过、证据文件落盘、commit 存在三者齐备才算完成。

## 会话记录

- 2026-09-19，本次会话目标：P4 批处理（先补 P3 抽查遗留的 10w seed 导入与 EXPLAIN 证据；再实现批次构建/运行、4 类管线、幂等/checkpoint/DLQ、测试与 `docs/06`）。
- 2026-09-19，本次会话目标：P3 统计域（先确认 P2 抽查修复已提交；再实现 6 类事件三口径统计、Redis 窗口缓存、成功率 API、测试证据与覆盖矩阵）。
- 2026-09-19，本次会话目标：P2 聚合域（先关闭 P1 抽查遗留：refresh、状态流转触发者、operator 区域测试；再实现网格渲染聚合、批次贪心聚合、基准脚本、EXPLAIN 与 `docs/02`）。
- 2026-09-19，本次会话目标：P1 权限+表单域（RBAC/tenant 隔离、统一 forms 模型、4 类 schema、状态机、多维过滤器、埋点中间件、统一异常、审计事件、OpenAPI 导出与需求覆盖矩阵骨架）。
- 2026-09-18 23:41，本次会话目标：P0 脚手架（compose、Makefile、环境体检、10w 合成数据生成器、P0 证据落盘与 commit）。

## Phase 状态

| Phase | 状态 | DoD | 证据 | Commit | 遗留 |
|---|---|---|---|---|---|
| P0 | 已完成 | `make env-check` pass；`make seed N=100000` pass | `artifacts/env/check.json`; `artifacts/data/seed_summary.json`; `artifacts/data/forms_seed.csv` | `6d2751d` | 无 |
| P1 | 已完成 | `backend/.venv/bin/pytest backend/tests/test_auth.py backend/tests/test_forms.py --junitxml=artifacts/test/p1.xml` pass；`backend/.venv/bin/python scripts/export_openapi.py` pass | `artifacts/test/p1.xml`; `artifacts/openapi.json`; `docs/08-需求覆盖矩阵.md` | `c47caf4` | P0 seed 遗留已修复：`4054f46`；README 后续注明 MySQL 3306 冲突 |
| P2 | 已完成 | `backend/.venv/bin/python scripts/benchmark_aggregation.py --n 100000 --seed 20260918` pass | `artifacts/bench/aggregation.json`; `artifacts/bench/explain.txt`; `docs/02-地理聚合与性能优化.md` | `5cf8343` | P1 抽查遗留 3 项已关闭：`2f37022`；P2 抽查修复已关闭：`3c474c6` |
| P3 | 已完成 | `backend/.venv/bin/pytest backend/tests/test_success_rate.py --junitxml=artifacts/test/p3.xml` pass；`backend/.venv/bin/python scripts/export_openapi.py` pass | `artifacts/test/p3.xml`; `docs/03-提交成功率统计设计.md`; `artifacts/openapi.json`; `docs/08-需求覆盖矩阵.md` | `6ec34e5` | 无 |
| P4 | 已完成 | `backend/.venv/bin/pytest backend/tests/test_batch_pipeline.py --junitxml=artifacts/test/p4.xml` pass；`backend/.venv/bin/pytest backend/tests --junitxml=artifacts/test/backend_all.xml` pass；`backend/.venv/bin/python scripts/load_seed.py --reset` pass | `artifacts/test/p4.xml`; `artifacts/test/backend_all.xml`; `artifacts/data/load_summary.json`; `docs/06-批处理流程设计.md` | `eb0b825` | P3 抽查遗留已关闭：seed 导入 + 10w EXPLAIN `41e14a7`；stats filters 已补入 `eb0b825` |
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

### P2 修复抽查（2026-09-19）— PASS（9 项逐项核销）

核销（对照上文 9 项）：
1 ✓ 三算法已真独立：full_scan（全量 mask+向量化聚合）/ grid（`GridIndex` 预建索引，仅 O(候选)）/ cKDTree（`KDTreeIndex`）；三者同 filter；正确性断言升级为 cluster_id→(count, centroid) 全量签名一致。
2 ✓ 计时已公平：三个 lambda 都含各自的候选/过滤构建（kd_mask 不再预计算在外）。
3 ✓ 聚合器向量化：`aggregate_cells` 用 bincount + 加权和，per-cell Python 循环只剩"组 dict"的 O(格数)。
4 ✓ 批次三方对比 + 如实命名（`greedy_batches_bruteforce` / `greedy_batches_grid` 真网格候选 ±2 格 / `greedy_batches_kdtree`）；新增 `validate_batches` 不变量校验（唯一分配 / ≤容量 / 距 seed ≤半径 Haversine）；内层 Haversine 已向量化。
5 ✓ 内存改 tracemalloc 逐算法测量（各行数值已分化、可信）。
6 ✓（部分）EXPLAIN 增加 optimizer_choice vs FORCE INDEX 对照 + 空表免责说明；10w 量级版按 docs/02 承诺留给导入数据后补（见 P3 备注 1）。
7 ✓ `test_aggregation.py` 存在（三实现聚合一致性 + 批次不变量）；覆盖面比要求薄一点（bruteforce/kdtree 的不变量未直接测），可接受。
8 ✓ docs/02 补了口径段：n=99304 构成、批次半径=距 seed 语义、小样本上网格候选可能更慢的诚实说明。
9 ✓ payload 负载改为真实 JSON 序列化计时（1.56MB/626ms vs 3.3KB/35.6ms），features 由数据推导而非手写。

修复后数据（我为核对公平性复跑过，可复现）：render 全扫 33.6ms / grid 28.1ms / cKDTree 54.7ms；batch 2000 条：暴力 61.8ms / 网格候选 117.6ms / cKDTree 66.8ms；payload 626ms→35.6ms（471×）。

【必做·文档】docs/02 算法对比表与实测矛盾：表中 cKDTree 写"查询候选更快"，实测它最慢（54.7ms，因候选 mask 需 O(n) 重建）；grid 28.1 vs 全扫 33.6 的 16% 差距也未解读。补一段"实测解读"：城市级视野候选率高→索引收益有限；grid 是端到端 O(候选) 且零依赖；主收益在 payload 471× 与 Redis 缓存；网格索引优势场景是小 bbox/高 zoom。

可选增强（不阻塞）：① 批次规模探针（暴力 O(n²) 在单城 2.5 万量级的实测/外推数字——"为什么不做全距离暴力"的答辩弹药）；② `np.unique(axis=0)` 换一维复合整数键（潜在 ~2×，也是好谈资）。

### P3 抽查（2026-09-19）— PASS

- DoD 复跑：全套 18 passed；`p3.xml` = 3/0/0；OpenAPI 已含 `/api/v1/stats/success-rate`。
- 口径对齐 §4.5（逐条核实）：按 `received_at` 归集；10 分钟迟到容忍有**边界用例**（k_late 计入、k_late_drop 丢弃）；`(tenant_id, idempotency_key)` 去重取窗口内首次 attempt；三口径分子 = 去重分母 ∩ 对应事件集合（无 attempt 的 success 事件 k5 被正确排除）；跨租户隔离有效。
- 缓存：key `success_rate:v1:{tenant}:{from}..{to}:all`、TTL 30s、Redis 故障 fail-open 回退实时计算（有 try 保护）；roundtrip + cache_hit 测试通过。
- 测试设计质量高：造数覆盖重试去重 / 失败后重试成功 / 校验失败 / 窗口外旧事件 / 迟到边界；断言与"由事件表重算的期望"对拍并留有绝对数锚点（端到端分子=2，我已手算复核）。

备注（转 P4）：
1. **`load_seed.py` 必须归入 P4 开头**（否则 P4 管线无数据可消费、P5 地图/统计页全为 0、10w 版 EXPLAIN 无法补）。要求：导入 99.3k 有效表单到 MySQL；按 §4.6 口径生成事件历史（published 表单 → business_published 等，使三口径数值有意义）；四类异常样本显式分类（越界/缺必填/unknown → validation_failed 路径；重复幂等键 → 去重证据）；产出 evidence（各计数 + 三口径实测值）。导入后**立即补跑 10w 版 EXPLAIN**（docs/02 已承诺）并更新 explain.txt。
2. stats 接口 filters 未实现（§4.2 冻结含 filters）：二选一——P4+ 补实现（可经 form_id 关联 forms 维度），或在 docs/03 显式写明当前范围与扩展路径；不留模糊。
3. 次要：Redis 每次调用新建连接（可改共享连接池）；缓存测试 key 在多次 pytest 运行间残留（建议 fixture 清理，当前不影响断言）；批次"不跨城市"由调用方保证——P4 的批次服务必须按 city 分组，且补对应测试。

### P4 抽查（2026-09-19）— PASS（2 项演示阻断 + 2 项小修，转 P5 会话开头）

独立复核：
- DoD 复跑 `pytest backend/tests -q` → **22 passed**；`p4.xml` 3/0/0；`backend_all.xml` 22/0/0。
- load_seed 直查 MySQL（不信 summary）：97354 表单 / 383040 事件；状态分布 published 82738、batched 3901、processing 3894、rejected 2916、failed 1954、draft 1951；事件类型齐全（attempt 100000、api_success=db_insert=97354、published=82738、api_failed 2948、validation_failed 2646）。跳过分类逐行单因、计数自洽（500+196+994+956=2646，含交叉重叠）。三口径在覆盖窗口内数值合理（约 98% / 98% / 84%）。
- **10w 级 EXPLAIN 兑现**：优化器自然选中冻结复合索引（type=range、key=ix_forms_tenant_status_type_city_lng_lat、rows=288、Using index），FORCE 组保留作对照 ✓。
- 批次域：四张表与 §4.1 对齐；build 只消费 validated + tenant/region 作用域 + 按城市分组 + 复用 P2 网格贪心 + 写 batch_items(含距离)；run 幂等（completed 直接返回、不重复写 business_published，有事件数断言）、published 跳过、retry_count<3、DLQ 2^n 退避、逐 stage checkpoint；四类管线映射符合 §4.3。测试覆盖不跨城/四类管线/幂等/DLQ 修复后续跑。
- stats filters 落地（join forms 施加 city/status/form_type/industry，filter_hash 进缓存 key，符合 §4.1 key 规范）✓。

【演示阻断·必做（P5 会话开头先做）】
1. **库里 0 条 `validated` 表单**：build 只消费 validated，导入后的分布里没有 → 批次演示空跑。修法：load_seed 增加显式"待批处理工作集"（如把约 1500 条 draft 均匀转 validated，跨城市/跨类型），load_summary 记录；**不改冻结 CSV**。
2. **事件时间线过旧**：received_at 全在 2026-09-01~09-15，而 §4.2 冻结默认窗口"近 24h" → 统计看板默认查询全 0。修法：load_seed 把时间轴整体平移到"导入时刻为末点"（保持相对分布），load_summary 记录 anchor；README 说明。（benchmark 用 CSV，不受影响。）

【小修·必做（同批处理）】
3. **跨租户合批**：admin 全局构建只按 city 分组、batch.tenant_id 取首条表单租户 → 产生跨租户批次，其他租户在列表看不到自己的表单所在批次。修法：按 `(tenant_id, city_code)` 分组。
4. **demo 账号缺失**：load_seed 只建 merchant；build/run 需要 admin/operator → 演示无法驱动批次。修法：补 admin + operator(region_code=shanghai)，README 演示动线写明（本机演示限定）。
5. 文档小漂移：docs/06 写"后端全集 21 条"实际 22；`force_dlq_stage` 故障注入钩子未说明（补一句，面试被问时有话答）；管线失败为**整批 fail-fast + 重跑续传**语义建议明写。
6. 次要：stats 带 filters 时 INNER JOIN 会排除 form_id 为空的跳过行事件（无 filters 时包含）——口径差异在 docs/03 一句带过。
