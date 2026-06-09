from dataclasses import dataclass
from xml.etree import ElementTree

import httpx


@dataclass(frozen=True)
class BriefingArticle:
    title: str
    link: str | None
    source: str


async def fetch_rss_articles(
    *,
    rss_urls: list[str],
    limit: int = 5,
    timeout_seconds: int = 10,
) -> list[BriefingArticle]:
    # Fetch configured RSS feeds; failures from one source do not block other sources.
    articles: list[BriefingArticle] = []
    per_source_limit = max(1, limit // max(len(rss_urls), 1) + 1)
    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
        for url in rss_urls:
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            try:
                articles.extend(parse_rss_articles(response.text, source=url)[:per_source_limit])
            except ElementTree.ParseError:
                continue
    return articles[:limit]


def parse_rss_articles(xml_text: str, *, source: str) -> list[BriefingArticle]:
    root = ElementTree.fromstring(xml_text)
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    articles: list[BriefingArticle] = []
    for item in items:
        title = _text(item, "title")
        link = _text(item, "link") or _atom_link(item)
        if title:
            articles.append(BriefingArticle(title=title.strip(), link=link, source=source))
    return articles


def split_rss_urls(raw_urls: str | None) -> list[str]:
    if not raw_urls:
        return []
    return [item.strip() for item in raw_urls.split(",") if item.strip()]


def _text(item: ElementTree.Element, tag: str) -> str | None:
    node = item.find(tag)
    if node is None:
        node = item.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
    return node.text if node is not None else None


def _atom_link(item: ElementTree.Element) -> str | None:
    node = item.find("{http://www.w3.org/2005/Atom}link")
    if node is None:
        return None
    return node.attrib.get("href")
