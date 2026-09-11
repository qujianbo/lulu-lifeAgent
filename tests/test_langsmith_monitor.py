from types import SimpleNamespace

import pytest

import app.observability.langsmith as langsmith_module
from app.config import Settings
from app.observability import LangSmithMonitor


def test_langsmith_monitor_is_disabled_without_api_key() -> None:
    monitor = LangSmithMonitor(
        Settings(langsmith_enabled=True, langsmith_api_key=None, _env_file=None)
    )

    assert monitor.enabled is False
    assert monitor.client is None


def test_user_hash_is_stable_and_does_not_expose_user_id() -> None:
    monitor = LangSmithMonitor(
        Settings(langsmith_user_hash_salt="test-secret", _env_file=None)
    )

    first = monitor.hash_user_id(12345)
    second = monitor.hash_user_id(12345)

    assert first == second
    assert first is not None
    assert "12345" not in first
    assert monitor.hash_user_id(None) is None


def test_deterministic_feedback_uses_expected_metric_keys(monkeypatch) -> None:
    monitor = LangSmithMonitor(Settings(_env_file=None))
    feedback: list[tuple[str, bool | int | float]] = []

    def capture_feedback(*, trace_id, key, score, comment=None) -> None:
        assert trace_id == "trace-1"
        feedback.append((key, score))

    monkeypatch.setattr(monitor, "record_feedback", capture_feedback)
    result = SimpleNamespace(
        content="已创建待办。",
        planner={"action": "call_tool", "tool_name": "todo_create"},
        tool_trace=[{"status": "success"}],
    )

    monitor.record_deterministic_feedback(
        trace_id="trace-1",
        result=result,
        end_to_end_latency_ms=321,
    )

    assert dict(feedback) == {
        "request_success": True,
        "planner_success": True,
        "tool_success": True,
        "tool_argument_valid": True,
        "end_to_end_latency_ms": 321,
    }


@pytest.mark.asyncio
async def test_trace_setup_failure_falls_back_to_business_operation(monkeypatch) -> None:
    monitor = LangSmithMonitor(Settings(_env_file=None))
    monitor.enabled = True
    monitor.client = SimpleNamespace()
    calls = 0

    def broken_traceable(*args, **kwargs):
        def decorate(function):
            async def fail_before_call(*args, **kwargs):
                raise RuntimeError("tracing unavailable")

            return fail_before_call

        return decorate

    async def invoke_agent(state):
        nonlocal calls
        calls += 1
        return {"final_response": "正常回复"}

    monkeypatch.setattr(langsmith_module, "traceable", broken_traceable)

    result, trace_id = await monitor.invoke(
        invoke_agent,
        {"raw_message": "你好", "user_id": 1},
        session_id="session-1",
        channel="test",
    )

    assert result["final_response"] == "正常回复"
    assert trace_id is None
    assert calls == 1
