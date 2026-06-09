from app.services.briefing.service import _extract_topics, _wants_subscription


def test_extract_briefing_topics() -> None:
    assert _extract_topics("每天早上订阅 AI 和财经简报") == ["AI", "财经"]


def test_wants_subscription() -> None:
    assert _wants_subscription("每天早上 8 点订阅 AI 简报")
    assert not _wants_subscription("今天有什么科技新闻")
