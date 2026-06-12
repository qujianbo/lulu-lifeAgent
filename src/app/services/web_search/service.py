import asyncio
import json
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT_SECONDS = 8
GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
WebSearchProvider = Literal["tavily", "google"]
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
        provider: WebSearchProvider = "tavily",
        tavily_api_key: str | None = None,
        google_api_key: str | None = None,
        google_cx: str | None = None,
        tavily_search_url: str = TAVILY_SEARCH_URL,
        google_search_url: str = GOOGLE_SEARCH_URL,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.provider = provider
        self.tavily_api_key = tavily_api_key
        self.google_api_key = google_api_key
        self.google_cx = google_cx
        self.tavily_search_url = tavily_search_url
        self.google_search_url = google_search_url
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, *, limit: int = 5) -> WebSearchResult:
        normalized = query.strip()
        if not normalized:
            return WebSearchResult("empty", "搜索关键词为空。", normalized, [])
        try:
            if self.provider == "tavily":
                result = await self._search_tavily(normalized, limit=limit)
            elif self.provider == "google":
                result = await self._search_google(normalized, limit=limit)
            else:
                return WebSearchResult(
                    "not_configured",
                    f"Web Search provider 不支持：{self.provider}",
                    normalized,
                    [],
                )
        except WebSearchError as exc:
            return WebSearchResult("unavailable", f"Web Search 暂时不可用：{exc}", normalized, [])
        if result.status != "success":
            return result
        if not result.items:
            return WebSearchResult("empty", "没有搜索到可用结果。", normalized, [])
        return result

    async def _search_tavily(self, query: str, *, limit: int) -> WebSearchResult:
        if not self.tavily_api_key:
            return WebSearchResult(
                "not_configured",
                "Web Search 尚未配置 Tavily API key。",
                query,
                [],
            )
        payload = await asyncio.to_thread(
            _fetch_tavily_search,
            self.tavily_search_url,
            self.tavily_api_key,
            query,
            limit,
            self.timeout_seconds,
        )
        return WebSearchResult(
            "success",
            "搜索成功。",
            query,
            _parse_tavily_items(payload, limit=limit),
        )

    async def _search_google(self, query: str, *, limit: int) -> WebSearchResult:
        if not self.google_api_key or not self.google_cx:
            return WebSearchResult(
                "not_configured",
                "Web Search 尚未配置 Google API key 或搜索引擎 ID。",
                query,
                [],
            )
        payload = await asyncio.to_thread(
            _fetch_google_search,
            self.google_search_url,
            self.google_api_key,
            self.google_cx,
            query,
            limit,
            self.timeout_seconds,
        )
        return WebSearchResult(
            "success",
            "搜索成功。",
            query,
            _parse_google_items(payload, limit=limit),
        )


class WebSearchError(RuntimeError):
    pass


def _fetch_tavily_search(
    url: str,
    api_key: str,
    query: str,
    limit: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    payload = json.dumps(
        {
            "query": query,
            "search_depth": "basic",
            "max_results": max(1, min(limit, 10)),
            "include_answer": False,
            "include_raw_content": False,
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise WebSearchError(exc.__class__.__name__) from exc


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


def _parse_tavily_items(payload: dict[str, Any], *, limit: int) -> list[WebSearchItem]:
    parsed: list[WebSearchItem] = []
    for item in (payload.get("results") or [])[:limit]:
        title = str(item.get("title") or "").strip()
        link = str(item.get("url") or "").strip()
        snippet = str(item.get("content") or "").strip()
        if not title or not link:
            continue
        # 只保留回答需要的搜索摘要，避免把整页内容塞进模型上下文。
        parsed.append(
            WebSearchItem(
                title=title[:200],
                link=link,
                snippet=snippet[:500],
                source=_source_from_url(link),
            )
        )
    return parsed


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


def _source_from_url(url: str) -> str | None:
    without_scheme = url.split("://", 1)[-1]
    host = without_scheme.split("/", 1)[0].strip()
    return host or None
