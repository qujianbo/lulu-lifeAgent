from app.services.memory.service import extract_memory_candidate, format_memories_for_prompt


def test_extract_briefing_topics_memory() -> None:
    candidate = extract_memory_candidate("记住我以后资讯更关注 AI 和财经")

    assert candidate is not None
    assert candidate.profile_key == "briefing.topics"
    assert candidate.profile_value == "AI,财经"
    assert candidate.merge_strategy == "merge_list"


def test_extract_preference_avoid_memory() -> None:
    candidate = extract_memory_candidate("我不喜欢太长的回答")

    assert candidate is not None
    assert candidate.profile_key == "preference.avoid"
    assert candidate.profile_value == "太长的回答"


def test_format_empty_memories_for_prompt() -> None:
    assert format_memories_for_prompt([]) == "无"
