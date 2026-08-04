from app.services.agent_memory.schemas import MemoryItem


def format_memories_for_prompt(items: list[MemoryItem]) -> str:
    if not items:
        return "无"
    lines = []
    for item in items[:5]:
        score_text = f" score={item.score:.3f}" if item.score is not None else ""
        lines.append(f"- [{item.memory_id}{score_text}] {item.content}")
    return "\n".join(lines)
