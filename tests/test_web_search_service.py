from app.services.web_search.service import WebSearchService, _parse_google_items


async def test_web_search_requires_google_config() -> None:
    service = WebSearchService()

    result = await service.search("LangGraph 最新资料")

    assert result.status == "not_configured"
    assert result.items == []


def test_parse_google_search_items() -> None:
    items = _parse_google_items(
        {
            "items": [
                {
                    "title": "LangGraph",
                    "link": "https://langchain-ai.github.io/langgraph/",
                    "snippet": "Build stateful, multi-actor applications with LLMs.",
                    "displayLink": "langchain-ai.github.io",
                },
                {
                    "title": "",
                    "link": "https://example.com/empty",
                    "snippet": "缺少标题的结果会被过滤。",
                },
            ]
        },
        limit=5,
    )

    assert len(items) == 1
    assert items[0].title == "LangGraph"
    assert items[0].source == "langchain-ai.github.io"
