from typing import Any

from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "life_agent_http_requests_total",
    "HTTP requests by method, route and status.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "life_agent_http_request_duration_seconds",
    "HTTP request duration by method and route.",
    ("method", "route"),
)
AGENT_REQUESTS = Counter(
    "life_agent_chat_requests_total",
    "Completed agent chat requests by channel and intent.",
    ("channel", "intent"),
)
AGENT_DURATION = Histogram(
    "life_agent_chat_duration_seconds",
    "End-to-end agent chat duration by channel.",
    ("channel",),
)
LLM_CALLS = Counter(
    "life_agent_llm_calls_total",
    "LLM calls by provider and model.",
    ("provider", "model"),
)
LLM_TOKENS = Counter(
    "life_agent_llm_tokens_total",
    "LLM tokens by provider, model and token type.",
    ("provider", "model", "type"),
)
LLM_COST = Counter(
    "life_agent_llm_estimated_cost_usd_total",
    "Estimated LLM cost in USD using configured model prices.",
    ("provider", "model"),
)
TOOL_CALLS = Counter(
    "life_agent_tool_calls_total",
    "Agent tool calls by tool and status.",
    ("tool", "status"),
)


def record_http_request(*, method: str, route: str, status: int, duration_seconds: float) -> None:
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_DURATION.labels(method=method, route=route).observe(duration_seconds)


def record_agent_result(
    *, channel: str, result: Any, llm_provider: str, llm_model: str
) -> None:
    metrics = result.llm_metrics or {}
    provider = llm_provider or "unknown"
    model = llm_model or "unknown"
    AGENT_REQUESTS.labels(channel=channel, intent=result.intent or "unknown").inc()
    AGENT_DURATION.labels(channel=channel).observe(result.end_to_end_latency_ms / 1000)
    LLM_CALLS.labels(provider=provider, model=model).inc(metrics.get("llm_calls", 0))
    for token_type in ("input", "output", "total"):
        LLM_TOKENS.labels(provider=provider, model=model, type=token_type).inc(
            metrics.get(f"{token_type}_tokens", 0)
        )
    LLM_COST.labels(provider=provider, model=model).inc(
        metrics.get("estimated_cost_usd", 0)
    )
    for trace in result.tool_trace or []:
        TOOL_CALLS.labels(
            tool=trace.get("tool_name") or "unknown",
            status=trace.get("status") or "unknown",
        ).inc()
