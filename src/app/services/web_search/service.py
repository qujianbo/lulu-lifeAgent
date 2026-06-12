import asyncio
import json
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT_SECONDS = 8
GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
WebSearchStatus = Literal["success", "not_configured", "unavailable", "empty"]


@dataclass(frozen=True)
class WebSearchItem:
    title: str
    link: str
    snippet: str
    source: str | None = None


@dataclass(frozen=True)
class WebSearchResult:
    status: WebSearchStatus
    message: str
    query: str
    items: list[WebSearchItem]


class WebSearchService:
    def __init__(
        self,
        *,
        google_api_key: str | None = None,
        google_cx: str | None = None,
        search_url: str = GOOGLE_SEARCH_URL,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.google_api_key = google_api_key
        self.google_cx = google_cx
        self.search_url = search_url
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, *, limit: int = 5) -> WebSearchResult:
        normalized = query.strip()
        if not normalized:
            return WebSearchResult("empty", "搜索关键词为空。", normalized, [])
        if not self.google_api_key or not self.google_cx:
            return WebSearchResult(
                "not_configured",
                "Web Search 尚未配置 Google API key 或搜索引擎 ID。",
                normalized,
                [],
            )
        try:
            payload = await asyncio.to_thread(
                _fetch_google_search,
                self.search_url,
                self.google_api_key,
                self.google_cx,
                normalized,
                limit,
                self.timeout_seconds,
            )
        except WebSearchError as exc:
            return WebSearchResult("unavailable", f"Web Search 暂时不可用：{exc}", normalized, [])
        items = _parse_google_items(payload, limit=limit)
        if not items:
            return WebSearchResult("empty", "没有搜索到可用结果。", normalized, [])
        return WebSearchResult("success", "搜索成功。", normalized, items)


class WebSearchError(RuntimeError):
    pass


def _fetch_google_search(
    url: str,
    api_key: str,
    cx: str,
    query: str,
    limit: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    params = urlencode({"key": api_key, "cx": cx, "q": query, "num": max(1, min(limit, 10))})
    request = Request(f"{url}?{params}", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise WebSearchError(exc.__class__.__name__) from exc


def _parse_google_items(payload: dict[str, Any], *, limit: int) -> list[WebSearchItem]:
    parsed: list[WebSearchItem] = []
    for item in (payload.get("items") or [])[:limit]:
        title = str(item.get("title") or "").strip()
        link = str(item.get("link") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if not title or not link:
            continue
        # 只保留回答需要的搜索摘要，避免把整页内容塞进模型上下文。
        parsed.append(
            WebSearchItem(
                title=title[:200],
                link=link,
                snippet=snippet[:500],
                source=item.get("displayLink"),
            )
        )
    return parsed
