import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

DEFAULT_TIMEOUT_SECONDS = 8
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
COMMODITY_ALIASES: dict[str, str] = {
    "金价": "GC=F",
    "黄金": "GC=F",
    "国际金价": "GC=F",
    "现货黄金": "GC=F",
    "白银": "SI=F",
    "银价": "SI=F",
    "原油": "CL=F",
    "油价": "CL=F",
    "wti": "CL=F",
    "WTI": "CL=F",
}


@dataclass(frozen=True)
class CommodityQuote:
    symbol: str
    name: str
    price: Decimal | None
    currency: str | None
    unit: str
    exchange: str | None
    exchange_time: str | None


@dataclass(frozen=True)
class CommodityQuoteResult:
    status: str
    message: str
    items: list[CommodityQuote]


class CommodityService:
    def __init__(
        self,
        *,
        chart_url: str = YAHOO_CHART_URL,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.chart_url = chart_url
        self.timeout_seconds = timeout_seconds

    async def query_from_text(self, text: str) -> CommodityQuoteResult:
        symbols = extract_commodity_symbols(text)
        if not symbols:
            return CommodityQuoteResult(
                status="needs_clarification",
                message="请告诉我要查询的商品，例如黄金、白银或原油。",
                items=[],
            )
        try:
            items = await self.fetch_quotes(symbols)
        except CommodityFetchError as exc:
            return CommodityQuoteResult(
                status="unavailable",
                message=f"商品行情暂时获取失败：{exc}",
                items=[],
            )
        if not items:
            return CommodityQuoteResult(
                status="not_found",
                message="没有查到对应的商品行情。",
                items=[],
            )
        return CommodityQuoteResult(
            status="success",
            message="商品行情查询成功。",
            items=items,
        )

    async def fetch_quotes(self, symbols: list[str]) -> list[CommodityQuote]:
        quotes: list[CommodityQuote] = []
        failures = 0
        for symbol in symbols:
            try:
                payload = await asyncio.to_thread(
                    _fetch_yahoo_chart,
                    self.chart_url,
                    symbol,
                    self.timeout_seconds,
                )
            except CommodityFetchError:
                failures += 1
                continue
            quote_item = _parse_yahoo_commodity(payload, fallback_symbol=symbol)
            if quote_item is not None:
                quotes.append(quote_item)
        if failures == len(symbols):
            raise CommodityFetchError("all_sources_failed")
        return quotes


def extract_commodity_symbols(text: str) -> list[str]:
    normalized = text.strip()
    symbols: list[str] = []
    for name, symbol in COMMODITY_ALIASES.items():
        if name in normalized:
            symbols.append(symbol)
    return list(dict.fromkeys(symbols))[:3]


class CommodityFetchError(RuntimeError):
    pass


def _fetch_yahoo_chart(url: str, symbol: str, timeout_seconds: int) -> dict[str, Any]:
    query = urlencode({"range": "1d", "interval": "1m"})
    request_url = f"{url}/{quote(symbol, safe='')}?{query}"
    request = Request(request_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise CommodityFetchError(exc.__class__.__name__) from exc


def _parse_yahoo_commodity(
    payload: dict[str, Any],
    *,
    fallback_symbol: str,
) -> CommodityQuote | None:
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta") or {}
    symbol = str(meta.get("symbol") or fallback_symbol)
    timestamp = meta.get("regularMarketTime")
    return CommodityQuote(
        symbol=symbol,
        name=_commodity_name(symbol, meta),
        price=_decimal(meta.get("regularMarketPrice")),
        currency=meta.get("currency"),
        unit=_commodity_unit(symbol),
        exchange=meta.get("fullExchangeName") or meta.get("exchangeName"),
        exchange_time=_timestamp_to_iso(timestamp, meta.get("exchangeTimezoneName")),
    )


def _commodity_name(symbol: str, meta: dict[str, Any]) -> str:
    known = {
        "GC=F": "COMEX 黄金期货",
        "SI=F": "COMEX 白银期货",
        "CL=F": "WTI 原油期货",
    }
    return known.get(symbol) or meta.get("shortName") or meta.get("longName") or symbol


def _commodity_unit(symbol: str) -> str:
    if symbol in {"GC=F", "SI=F"}:
        return "美元/盎司"
    if symbol == "CL=F":
        return "美元/桶"
    return "报价单位"


def _timestamp_to_iso(value: Any, timezone_name: Any) -> str | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    tz = ZoneInfo(str(timezone_name)) if timezone_name else UTC
    return datetime.fromtimestamp(timestamp, tz=tz).isoformat()


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
