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

## Docker Compose

```bash
docker compose up --build
```

MVP 初期目标是在阿里云轻量应用服务器上用 Docker Compose 部署所有服务。

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
