# 执行账本

> 唯一进度来源。Phase 只有 DoD 命令真实跑过、证据文件落盘、commit 存在三者齐备才算完成。

## 会话记录

- 2026-09-18 23:41，本次会话目标：P0 脚手架（compose、Makefile、环境体检、10w 合成数据生成器、P0 证据落盘与 commit）。

## Phase 状态

| Phase | 状态 | DoD | 证据 | Commit | 遗留 |
|---|---|---|---|---|---|
| P0 | 已完成 | `make env-check` pass；`make seed N=100000` pass | `artifacts/env/check.json`; `artifacts/data/seed_summary.json`; `artifacts/data/forms_seed.csv` | `6d2751d` | 无 |
| P1 | 未开始 | - | - | - | - |
| P2 | 未开始 | - | - | - | - |
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
