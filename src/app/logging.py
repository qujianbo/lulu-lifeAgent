import logging
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger as loguru_logger

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class InterceptHandler(logging.Handler):
    """Route stdlib logging (including dependencies) through Loguru sinks."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        extra = {key[1:]: value for key, value in record.__dict__.items() if key.startswith("_")}
        extra["request_id"] = request_id_var.get()
        extra["stdlib_logger"] = record.name
        loguru_logger.bind(**extra).opt(exception=record.exc_info).log(level, record.getMessage())


class AppLogger:
    """SLF4J-style facade retaining compatibility with existing stdlib callers."""

    @staticmethod
    def get(name: str) -> logging.Logger:
        return logging.getLogger(name)


def configure_logging(
    level: str = "INFO",
    *,
    log_dir: str = "logs",
    service_name: str = "web",
    max_bytes: int = 20 * 1024 * 1024,
    retention: str = "10 days",
) -> None:
    """Configure Loguru-owned asynchronous, serialized and rotating sinks."""
    loguru_logger.remove()
    logging.basicConfig(
        handlers=[InterceptHandler()],
        level=level.upper(),
        force=True,
    )
    target_dir = Path(log_dir) / service_name
    target_dir.mkdir(parents=True, exist_ok=True)

    common: dict[str, Any] = {
        "serialize": True,
        "enqueue": True,
        "backtrace": False,
        "diagnose": False,
        "catch": True,
    }
    loguru_logger.add(sys.stdout, level=level.upper(), **common)
    for filename, sink_level, level_filter in (
        ("debug.log", "DEBUG", lambda record: record["level"].name == "DEBUG"),
        ("info.log", "INFO", lambda record: record["level"].name == "INFO"),
        ("warning.log", "WARNING", lambda record: record["level"].name == "WARNING"),
        ("error.log", "ERROR", lambda record: record["level"].no >= logging.ERROR),
    ):
        loguru_logger.add(
            target_dir / filename,
            level=sink_level,
            filter=level_filter,
            rotation=max_bytes,
            retention=retention,
            encoding="utf-8",
            **common,
        )


def shutdown_logging() -> None:
    loguru_logger.complete()
    loguru_logger.remove()


def new_request_id() -> str:
    return uuid4().hex
