FROM python:3.11.15-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.30 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md alembic.ini ./
ENV UV_HTTP_TIMEOUT=120
# Use Aliyun PyPI mirror to keep builds reliable on the lightweight server.
RUN uv sync --index-url https://mirrors.aliyun.com/pypi/simple/ --frozen --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"

RUN useradd --create-home --shell /bin/bash appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
