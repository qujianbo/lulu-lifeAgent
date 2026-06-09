import logging
import time
from collections.abc import Callable

from fastapi import FastAPI, Request, Response

from app.api.debug import router as debug_router
from app.api.health import router as health_router
from app.api.local import router as local_router
from app.config import get_settings
from app.logging import configure_logging, new_request_id, request_id_var

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next: Callable) -> Response:
    request_id = request.headers.get("x-request-id") or new_request_id()
    token = request_id_var.set(request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        return response
    finally:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "request_completed",
            extra={
                "_method": request.method,
                "_path": request.url.path,
                "_elapsed_ms": elapsed_ms,
            },
        )
        request_id_var.reset(token)


app.include_router(health_router)
app.include_router(local_router)
app.include_router(debug_router)
