import asyncio
import hashlib
import hmac
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langsmith import Client, traceable
from langsmith.run_helpers import get_current_run_tree

from app.config import Settings

logger = logging.getLogger(__name__)

AgentInvoke = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class LangSmithMonitor:
    """Optional LangSmith adapter that never makes observability a business dependency."""

    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.langsmith_enabled and bool(settings.langsmith_api_key)
        self.project = settings.langsmith_project
        self.environment = settings.app_env
        self.agent_version = settings.langsmith_agent_version or "development"
        self.user_hash_salt = settings.langsmith_user_hash_salt
        self.client: Client | None = None
        if self.enabled:
            try:
                self.client = Client(
                    api_key=settings.langsmith_api_key,
                    api_url=settings.langsmith_endpoint,
                )
            except Exception as exc:
                self.enabled = False
                logger.warning("langsmith_client_disabled", extra={"_error": str(exc)})

    async def invoke(
        self,
        invoke_agent: AgentInvoke,
        state: dict[str, Any],
        *,
        session_id: str,
        channel: str,
    ) -> tuple[dict[str, Any], str | None]:
        if not self.enabled or self.client is None:
            return await invoke_agent(state), None

        metadata = {
            "thread_id": session_id,
            "environment": self.environment,
            "agent_version": self.agent_version,
            "channel": channel,
        }
        user_hash = self.hash_user_id(state.get("user_id"))
        if user_hash is not None:
            metadata["user_id_hash"] = user_hash

        business_started = False
        business_completed = False
        completed_result: dict[str, Any] | None = None

        async def traced_call(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
            nonlocal business_started, business_completed, completed_result
            business_started = True
            run = get_current_run_tree()
            result = await invoke_agent(payload)
            completed_result = result
            business_completed = True
            if run is not None:
                planner = result.get("planner") or {}
                tool_trace = result.get("tool_trace") or []
                llm_metrics = result.get("llm_metrics") or {}
                run.add_metadata(
                    {
                        "intent": result.get("intent", "unknown"),
                        "planner_action": planner.get("action"),
                        "tool_name": planner.get("tool_name"),
                        "tool_status": tool_trace[-1].get("status") if tool_trace else None,
                        "model": result.get("model", "none"),
                        "provider": result.get("provider", "local"),
                        **llm_metrics,
                        "tool_calls": len(tool_trace),
                    }
                )
            trace_id = str(run.trace_id or run.id) if run is not None else ""
            return result, trace_id

        traced = traceable(
            name="life_agent_chat",
            run_type="chain",
            client=self.client,
            project_name=self.project,
            enabled=True,
            process_inputs=lambda inputs: {
                "user_message": (inputs.get("payload") or {}).get("raw_message", "")
            },
            process_outputs=_trace_outputs,
        )(traced_call)
        try:
            result, trace_id = await traced(
                state,
                langsmith_extra={
                    "metadata": metadata,
                    "tags": [self.environment, channel, f"agent:{self.agent_version}"],
                },
            )
            return result, trace_id or None
        except Exception as exc:
            if business_completed and completed_result is not None:
                logger.warning("langsmith_trace_finalize_failed", extra={"_error": str(exc)})
                return completed_result, None
            if not business_started:
                logger.warning("langsmith_trace_setup_failed", extra={"_error": str(exc)})
                return await invoke_agent(state), None
            # The business operation itself failed; preserve its exception and traceback.
            raise

    def record_deterministic_feedback(
        self,
        *,
        trace_id: str | None,
        result: Any,
        end_to_end_latency_ms: int,
    ) -> None:
        if not trace_id:
            return
        planner = result.planner or {}
        tool_trace = result.tool_trace or []
        tool_success: bool | None = None
        if planner.get("action") == "call_tool":
            tool_success = bool(tool_trace and tool_trace[-1].get("status") == "success")

        scores: dict[str, bool | int | None] = {
            "request_success": bool(result.content.strip()),
            "planner_success": bool(planner),
            "tool_success": tool_success,
            "tool_argument_valid": True if planner.get("action") == "call_tool" else None,
            "end_to_end_latency_ms": end_to_end_latency_ms,
            **(result.llm_metrics or {}),
            "tool_calls": len(tool_trace),
        }
        for key, score in scores.items():
            if score is not None:
                self.record_feedback(trace_id=trace_id, key=key, score=score)

    def record_feedback(
        self,
        *,
        trace_id: str | None,
        key: str,
        score: bool | int | float,
        comment: str | None = None,
    ) -> None:
        if not self.enabled or self.client is None or not trace_id:
            return

        async def send() -> None:
            try:
                await asyncio.to_thread(
                    self.client.create_feedback,
                    trace_id=trace_id,
                    key=key,
                    score=score,
                    comment=comment,
                    stop_after_attempt=1,
                )
            except Exception as exc:
                logger.warning(
                    "langsmith_feedback_failed",
                    extra={"_trace_id": trace_id, "_feedback_key": key, "_error": str(exc)},
                )

        try:
            task = asyncio.create_task(send())
            task.add_done_callback(_consume_task_exception)
        except RuntimeError:
            logger.warning("langsmith_feedback_skipped_without_event_loop")

    def hash_user_id(self, user_id: int | None) -> str | None:
        if user_id is None or not self.user_hash_salt:
            return None
        return hmac.new(
            self.user_hash_salt.encode(),
            str(user_id).encode(),
            hashlib.sha256,
        ).hexdigest()


def _trace_outputs(output: tuple[dict[str, Any], str]) -> dict[str, Any]:
    state, _trace_id = output
    planner = state.get("planner") or {}
    tool_trace = state.get("tool_trace") or []
    llm_metrics = state.get("llm_metrics") or {}
    return {
        "final_response": state.get("final_response", ""),
        "intent": state.get("intent", "unknown"),
        "planner_action": planner.get("action"),
        "tool_name": planner.get("tool_name"),
        "tool_status": tool_trace[-1].get("status") if tool_trace else None,
        "tool_calls": len(tool_trace),
        **llm_metrics,
    }


def _consume_task_exception(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except Exception as exc:
        logger.warning("langsmith_background_task_failed", extra={"_error": str(exc)})
