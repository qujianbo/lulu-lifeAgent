import logging
import time
from collections.abc import Callable

from fastapi import FastAPI, Request, Response

from app.api.beta import router as beta_router
from app.api.beta_auth import router as beta_auth_router
from app.api.debug import router as debug_router
from app.api.health import router as health_router
from app.api.local import router as local_router
from app.config import get_settings
from app.logging import configure_logging, new_request_id, request_id_var
from app.observability.metrics import record_http_request

settings = get_settings()
configure_logging(
    settings.log_level,
    log_dir=settings.log_dir,
    service_name="web",
    max_bytes=settings.log_max_bytes,
    retention=settings.log_retention,
)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next: Callable) -> Response:
    request_id = request.headers.get("x-request-id") or new_request_id()
    token = request_id_var.set(request_id)
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_seconds = time.perf_counter() - start
        elapsed_ms = round(elapsed_seconds * 1000, 2)
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        record_http_request(
            method=request.method,
            route=route_path,
            status=status_code,
            duration_seconds=elapsed_seconds,
        )
        logger.info(
            "request_completed",
            extra={
                "_method": request.method,
                "_path": request.url.path,
                "_status_code": status_code,
                "_elapsed_ms": elapsed_ms,
            },
        )
        request_id_var.reset(token)


app.include_router(health_router)
app.include_router(beta_auth_router)
app.include_router(beta_router)
app.include_router(local_router)
app.include_router(debug_router)
