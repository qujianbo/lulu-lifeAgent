import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

DEFAULT_TIMEOUT_SECONDS = 8
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
GOLD_API_URL = "https://api.gold-api.com/price"
USD_RATE_URL = "https://open.er-api.com/v6/latest/USD"
TROY_OUNCE_GRAMS = Decimal("31.1034768")
COMMODITY_ALIASES: dict[str, str] = {
    "金价": "XAU",
    "黄金": "XAU",
    "国际金价": "XAU",
    "现货黄金": "XAU",
    "白银": "XAG",
    "银价": "XAG",
    "铜价": "HG",
    "国际铜": "HG",
    "铂金": "XPT",
    "钯金": "XPD",
    "原油": "CL=F",
    "油价": "CL=F",
    "wti": "CL=F",
    "WTI": "CL=F",
}
# 服务器环境访问 Yahoo 商品期货容易被拒绝，贵金属先走已验证可用的现货源。
GOLD_API_SYMBOLS = {"XAU", "XAG", "HG", "XPT", "XPD"}


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
        gold_api_url: str = GOLD_API_URL,
        usd_rate_url: str = USD_RATE_URL,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.chart_url = chart_url
        self.gold_api_url = gold_api_url
        self.usd_rate_url = usd_rate_url
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
            items = _apply_requested_unit(await self.fetch_quotes(symbols), text)
            if _asks_for_cny_price(text):
                rate = await asyncio.to_thread(
                    _fetch_usd_cny_rate,
                    self.usd_rate_url,
                    self.timeout_seconds,
                )
                items = _apply_requested_currency(items, rate)
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
                # 按标的选择稳定数据源，避免让用户关心具体行情代码。
                if symbol in GOLD_API_SYMBOLS:
                    payload = await asyncio.to_thread(
                        _fetch_gold_api_quote,
                        self.gold_api_url,
                        symbol,
                        self.timeout_seconds,
                    )
                    quote_item = _parse_gold_api_commodity(payload, fallback_symbol=symbol)
                else:
                    payload = await asyncio.to_thread(
                        _fetch_yahoo_chart,
                        self.chart_url,
                        symbol,
                        self.timeout_seconds,
                    )
                    quote_item = _parse_yahoo_commodity(payload, fallback_symbol=symbol)
            except CommodityFetchError:
                failures += 1
                continue
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


def _apply_requested_unit(items: list[CommodityQuote], text: str) -> list[CommodityQuote]:
    if not _asks_for_gram_price(text):
        return items
    converted: list[CommodityQuote] = []
    for item in items:
        # 贵金属行情源按金衡盎司报价，用户问“每克”时在工具层直接换算。
        if item.symbol in {"XAU", "XAG", "XPT", "XPD"} and item.price is not None:
            converted.append(
                replace(
                    item,
                    price=(item.price / TROY_OUNCE_GRAMS).quantize(Decimal("0.000001")),
                    unit="美元/克",
                )
            )
        else:
            converted.append(item)
    return converted


def _apply_requested_currency(
    items: list[CommodityQuote],
    usd_cny_rate: Decimal,
) -> list[CommodityQuote]:
    converted: list[CommodityQuote] = []
    for item in items:
        if item.currency == "USD" and item.price is not None:
            converted.append(
                replace(
                    item,
                    price=(item.price * usd_cny_rate).quantize(Decimal("0.01")),
                    currency="CNY",
                    unit=_convert_unit_to_cny(item.unit),
                )
            )
        else:
            converted.append(item)
    return converted


def _asks_for_gram_price(text: str) -> bool:
    normalized = text.lower()
    return any(keyword in normalized for keyword in ("一克", "每克", "克", "/g", " g"))


def _asks_for_cny_price(text: str) -> bool:
    normalized = text.lower()
    return any(keyword in normalized for keyword in ("人民币", "元", "cny", "rmb"))


def _convert_unit_to_cny(unit: str) -> str:
    return (
        unit.replace("美元", "元")
        .replace("USD", "CNY")
        .replace("usd", "CNY")
    )


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


def _fetch_gold_api_quote(url: str, symbol: str, timeout_seconds: int) -> dict[str, Any]:
    request_url = f"{url.rstrip('/')}/{quote(symbol, safe='')}"
    request = Request(request_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise CommodityFetchError(exc.__class__.__name__) from exc


def _fetch_usd_cny_rate(url: str, timeout_seconds: int) -> Decimal:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise CommodityFetchError(exc.__class__.__name__) from exc
    rate = _decimal((payload.get("rates") or {}).get("CNY"))
    if rate is None:
        raise CommodityFetchError("usd_cny_rate_missing")
    return rate


def _parse_gold_api_commodity(
    payload: dict[str, Any],
    *,
    fallback_symbol: str,
) -> CommodityQuote | None:
    symbol = str(payload.get("symbol") or fallback_symbol).upper()
    price = _decimal(payload.get("price"))
    if price is None:
        return None
    return CommodityQuote(
        symbol=symbol,
        name=_commodity_name(symbol, {}),
        price=price,
        currency=payload.get("currency"),
        unit=_commodity_unit(symbol),
        exchange="gold-api.com",
        exchange_time=payload.get("updatedAt"),
    )


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
        "XAU": "国际黄金现货",
        "XAG": "国际白银现货",
        "HG": "国际铜价",
        "XPT": "国际铂金现货",
        "XPD": "国际钯金现货",
    }
    return known.get(symbol) or meta.get("shortName") or meta.get("longName") or symbol


def _commodity_unit(symbol: str) -> str:
    if symbol in {"GC=F", "SI=F", "XAU", "XAG", "XPT", "XPD"}:
        return "美元/盎司"
    if symbol == "HG":
        return "美元/磅"
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
