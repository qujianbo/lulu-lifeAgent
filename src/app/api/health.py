from fastapi import APIRouter

from app.config import get_settings
from app.dependencies import ping_database, ping_redis

router = APIRouter(tags=["health"])


def _check_status(value: bool | None) -> str:
    if value is True:
        return "ok"
    if value is None:
        return "not_configured"
    return "failed"


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name, "environment": settings.app_env}


@router.get("/readyz")
async def readyz() -> dict[str, object]:
    settings = get_settings()
    database = await ping_database(settings)
    redis = await ping_redis(settings)
    deepseek = "configured" if settings.deepseek_api_key else "not_configured"
    wechat = "configured" if settings.wechat_app_id and settings.wechat_token else "not_configured"

    checks = {
        "database": _check_status(database),
        "redis": _check_status(redis),
        "deepseek": deepseek,
        "wechat": wechat,
    }
    ready = all(value in {"ok", "configured", "not_configured"} for value in checks.values())
    return {"ready": ready, "checks": checks}
