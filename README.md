# Merchant Onboarding Platform

全栈技术作业实现仓库。执行进度以 `docs/EXECUTION.md` 为准，冻结规格见 `docs/00-施工书.md`。

## 本地演示账号

`scripts/load_seed.py --reset` 会写入以下演示账号：

| 角色 | 账号 | 密码 | 用途 |
|---|---|---|---|
| merchant | `tenant_01@example.com` | `seed-pass` | 表单、地图、统计的 tenant 视角 |
| admin | `admin@example.com` | `seed-pass` | 构建/运行批次 |
| operator | `operator-shanghai@example.com` | `seed-pass` | 上海区域运营视角 |

## 启动顺序

```bash
docker compose -f deploy/docker-compose.yml up -d mysql
redis-server
backend/.venv/bin/python scripts/load_seed.py --reset
backend/.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev
```

前端地址：`http://127.0.0.1:3000`。后端地址：`http://127.0.0.1:8000`。

`next build` 和 `next dev` 都会写 `.next`，演示时不要让二者同时操作同一目录；如果刚跑过 `npm run build`，请重启 `npm run dev`。
