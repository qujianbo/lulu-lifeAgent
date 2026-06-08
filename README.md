# 生活管家 Agent

微信公众号生活管家 Agent 后端工程。

## 本地启动

```bash
cp .env.example .env
uv sync --dev
uv run uvicorn app.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
```

本地后端调试接口：

```bash
curl http://127.0.0.1:8000/api/local/deepseek/ping

curl -X POST http://127.0.0.1:8000/api/local/chat \
  -H 'content-type: application/json' \
  -d '{"message":"明早 8 点提醒我带身份证"}'
```

如果 `.env` 配置了 `ADMIN_TOKEN`，调试接口需要增加：

```bash
-H "x-admin-token: $ADMIN_TOKEN"
```

本机没有 Docker 或数据库时，`/readyz` 里的 `database`、`redis` 可能显示 `failed`；这表示依赖未连通，不影响先调通 DeepSeek 和本地 Agent 接口。

## Docker Compose

```bash
docker compose up --build
```

MVP 初期目标是在阿里云轻量应用服务器上用 Docker Compose 部署所有服务。

## 阿里云服务器部署

服务器首次部署：

```bash
git clone git@github.com:qujianbo/lulu-lifeAgent.git
cd lulu-lifeAgent
cp .env.example .env
```

编辑服务器本地 `.env`，至少补充：

```text
APP_ENV=prod
POSTGRES_PASSWORD=换成强密码
DATABASE_URL=postgresql+asyncpg://life_agent:同一个强密码@postgres:5432/life_agent
REDIS_URL=redis://redis:6379/0
DEEPSEEK_API_KEY=你的 key
DEEPSEEK_MODEL=deepseek-v4-pro
ADMIN_TOKEN=换成强 token
PUBLIC_BASE_URL=https://你的域名
```

启动和迁移：

```bash
docker compose up -d --build postgres redis
docker compose run --rm migrate
docker compose up -d --build app scheduler
```

验证：

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
curl -H "x-admin-token: $ADMIN_TOKEN" http://127.0.0.1:8000/api/local/deepseek/ping
curl -H "x-admin-token: $ADMIN_TOKEN" \
  -H 'content-type: application/json' \
  -X POST http://127.0.0.1:8000/api/local/chat \
  -d '{"message":"明早 8 点提醒我带身份证"}'
```

后续更新代码：

```bash
git pull
docker compose run --rm migrate
docker compose up -d --build app scheduler
```

PostgreSQL 和 Redis 只绑定服务器本机 `127.0.0.1`，不要对公网开放。FastAPI 当前暴露 `8000` 端口，正式接入域名时建议放到 Nginx/Caddy 后面。

## 成本口径

MVP 启动成本需要单独计入微信公众号认证费用：300 元/年。云资源费用另算，包括阿里云轻量应用服务器、域名/证书、备份空间，以及后续 DeepSeek API 调用费用。

## 接入顺序

当前优先在本地调通后端接口、DeepSeek 调用、数据库迁移和核心业务功能。微信公众号服务器回调、菜单、标签和主动推送放到后续联调阶段接入。

## 镜像版本策略

生产镜像锁定到小版本，避免浮动 tag 自动变化导致构建或运行行为漂移。

当前基础镜像：

- `python:3.11.15-slim-bookworm`
- `postgres:16.14-alpine`
- `redis:7.4.9-alpine`
- `ghcr.io/astral-sh/uv:0.5.30`

升级策略：

- Patch 版本可在本地测试、迁移测试和冒烟测试通过后升级。
- Minor/Major 版本升级需要单独评估兼容性，尤其是 PostgreSQL 和 Redis。
- 数据库镜像升级前必须先备份数据卷。
- 生产发布时保留上一版镜像和数据库备份，便于回滚。
