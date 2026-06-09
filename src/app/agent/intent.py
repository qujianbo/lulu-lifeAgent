from app.agent.state import AgentIntent


def infer_intent(message: str) -> AgentIntent:
    # Rule-based MVP router; later this can be replaced by an LLM classifier node.
    normalized = message.strip().lower()
    if not normalized:
        return "unknown"
    if any(keyword in normalized for keyword in ("提醒", "叫我", "闹钟", "待办")):
        if any(keyword in normalized for keyword in ("删除", "取消", "删掉")):
            return "delete_reminder"
        if any(keyword in normalized for keyword in ("完成", "做完", "已办", "办完")):
            return "complete_reminder"
        if any(keyword in normalized for keyword in ("查", "看看", "有哪些", "列表", "今天")):
            return "query_reminder"
        return "create_reminder"
    if any(keyword in normalized for keyword in ("新闻", "资讯", "早报", "简报", "天气")):
        return "briefing"
    if len(normalized) <= 2 and normalized not in {"hi", "哈", "嗯"}:
        return "unknown"
    return "general_qa"
