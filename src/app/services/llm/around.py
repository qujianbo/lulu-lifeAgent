import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from time import perf_counter
from typing import Any, TypeVar, cast
from uuid import uuid4

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_random_exponential

from app.observability.metrics import record_llm_attempt

logger = logging.getLogger(__name__)
ResultT = TypeVar("ResultT")


def around_llm_call(
    function: Callable[..., Awaitable[ResultT]],
) -> Callable[..., Awaitable[ResultT]]:
    """Around-style provider boundary with safe logs and bounded retries."""

    @wraps(function)
    async def wrapped(self: Any, *args: Any, **kwargs: Any) -> ResultT:
        provider = getattr(self, "provider_name", "unknown")
        model = getattr(self, "model", "unknown")
        max_attempts = getattr(self, "max_attempts", 3)
        invocation_id = uuid4().hex
        messages = args[0] if args else kwargs.get("messages") or []
        retrying = AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_random_exponential(
                multiplier=getattr(self, "retry_base_seconds", 0.5),
                max=getattr(self, "retry_max_seconds", 8.0),
            ),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )

        async for attempt in retrying:
            attempt_number = attempt.retry_state.attempt_number
            started = perf_counter()
            logger.debug(
                "llm_call_started",
                extra={
                    "_provider": provider,
                    "_model": model,
                    "_invocation_id": invocation_id,
                    "_attempt": attempt_number,
                    "_message_count": len(messages),
                    "_max_tokens": kwargs.get("max_tokens"),
                },
            )
            with attempt:
                try:
                    result = await function(self, *args, **kwargs)
                except Exception as exc:
                    retryable = _is_retryable(exc)
                    record_llm_attempt(
                        provider=provider,
                        model=model,
                        outcome="retryable_error" if retryable else "error",
                    )
                    logger.warning(
                        "llm_call_failed",
                        extra={
                            "_provider": provider,
                            "_model": model,
                            "_invocation_id": invocation_id,
                            "_attempt": attempt_number,
                            "_error_type": type(exc).__name__,
                            "_status_code": getattr(exc, "status_code", None),
                            "_retryable": retryable,
                            "_elapsed_ms": round((perf_counter() - started) * 1000),
                        },
                        exc_info=not retryable,
                    )
                    raise

                record_llm_attempt(provider=provider, model=model, outcome="success")
                logger.info(
                    "llm_call_succeeded",
                    extra={
                        "_provider": provider,
                        "_model": model,
                        "_invocation_id": invocation_id,
                        "_attempt": attempt_number,
                        "_elapsed_ms": round((perf_counter() - started) * 1000),
                        "_input_tokens": getattr(result, "input_tokens", 0),
                        "_output_tokens": getattr(result, "output_tokens", 0),
                        "_total_tokens": getattr(result, "total_tokens", 0),
                        "_finish_reason": getattr(result, "finish_reason", None),
                    },
                )
                return result
        raise RuntimeError("LLM retry loop completed without a result")  # pragma: no cover

    return cast(Callable[..., Awaitable[ResultT]], wrapped)


def _is_retryable(exc: BaseException) -> bool:
    explicit = getattr(exc, "retryable", None)
    if explicit is not None:
        return bool(explicit)
    return isinstance(
        exc,
        (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ),
    )
