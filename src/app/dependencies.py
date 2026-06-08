from collections.abc import AsyncIterator

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings, get_settings


def get_database_engine(settings: Settings | None = None) -> AsyncEngine | None:
    settings = settings or get_settings()
    if not settings.database_url:
        return None
    return create_async_engine(settings.database_url, pool_pre_ping=True)


async def ping_database(settings: Settings | None = None) -> bool | None:
    engine = get_database_engine(settings)
    if engine is None:
        return None
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("select 1")
        return True
    except Exception:
        # Readiness should report dependency failure instead of crashing the endpoint.
        return False
    finally:
        await engine.dispose()


async def get_redis(settings: Settings | None = None) -> AsyncIterator[Redis | None]:
    settings = settings or get_settings()
    if not settings.redis_url:
        yield None
        return
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def ping_redis(settings: Settings | None = None) -> bool | None:
    settings = settings or get_settings()
    if not settings.redis_url:
        return None
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        return bool(await client.ping())
    except Exception:
        # Redis may be absent in local debug mode; expose it as failed in readyz.
        return False
    finally:
        await client.aclose()
