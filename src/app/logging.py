import logging
import logging.handlers
import queue
import sys
from atexit import register
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from concurrent_log_handler import ConcurrentRotatingFileHandler
from pythonjsonlogger.json import JsonFormatter as BaseJsonFormatter

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_listener: logging.handlers.QueueListener | None = None


class JsonFormatter(BaseJsonFormatter):
    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = datetime.now(UTC).isoformat()
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["request_id"] = getattr(record, "_request_id", None)
        for key, value in record.__dict__.items():
            if key.startswith("_") and key[1:] not in log_record:
                log_record[key[1:]] = value


class ExactLevelFilter(logging.Filter):
    def __init__(self, level: int, *, include_higher: bool = False) -> None:
        super().__init__()
        self.level = level
        self.include_higher = include_higher

    def filter(self, record: logging.LogRecord) -> bool:
        if self.include_higher:
            return record.levelno >= self.level
        return record.levelno == self.level


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record._request_id = request_id_var.get()  # type: ignore[attr-defined]
        return True


class AppLogger:
    """Small logging facade; writes are delegated to the configured async queue."""

    @staticmethod
    def get(name: str) -> logging.Logger:
        return logging.getLogger(name)


def configure_logging(
    level: str = "INFO",
    *,
    log_dir: str = "logs",
    max_bytes: int = 20 * 1024 * 1024,
    backup_count: int = 10,
) -> None:
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    formatter = JsonFormatter()
    handlers: list[logging.Handler] = []

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    handlers.append(stdout_handler)

    target_dir = Path(log_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename, file_level, include_higher in (
        ("debug.log", logging.DEBUG, False),
        ("info.log", logging.INFO, False),
        ("warning.log", logging.WARNING, False),
        ("error.log", logging.ERROR, True),
    ):
        file_handler = ConcurrentRotatingFileHandler(
            target_dir / filename,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(file_level)
        file_handler.addFilter(
            ExactLevelFilter(file_level, include_higher=include_higher)
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_handler.addFilter(RequestContextFilter())
    root.addHandler(queue_handler)
    _listener = logging.handlers.QueueListener(
        log_queue, *handlers, respect_handler_level=True
    )
    _listener.start()


def shutdown_logging() -> None:
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None


def new_request_id() -> str:
    return uuid4().hex


register(shutdown_logging)
