import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SINA_QUOTE_URL = "https://hq.sinajs.cn/list="
EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EASTMONEY_FIELDS = "f43,f57,f58,f59,f60,f86,f107,f169,f170"
# The delayed host is more stable from cloud servers for board rankings.
EASTMONEY_BOARD_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
EASTMONEY_BOARD_FIELDS = "f12,f14,f2,f3,f62"
EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://quote.eastmoney.com/center/boardlist.html",
    "Connection": "close",
}
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
DEFAULT_TIMEOUT_SECONDS = 8
MARKET_OVERVIEW_SYMBOLS = ["000001.SS", "399001.SZ", "399006.SZ"]
KNOWN_SYMBOLS: dict[str, str] = {
    "上证大盘指数": "000001.SS",
    "上证大盘": "000001.SS",
    "上证指数": "000001.SS",
    "上证综指": "000001.SS",
    "上证": "000001.SS",
    "深证成指": "399001.SZ",
    "深成指": "399001.SZ",
    "创业板指": "399006.SZ",
    "沪深300": "000300.SS",
    "苹果": "AAPL",
    "特斯拉": "TSLA",
    "英伟达": "NVDA",
    "微软": "MSFT",
    "腾讯": "00700.HK",
    "阿里": "BABA",
    "阿里巴巴": "BABA",
    "贵州茅台": "600519.SS",
    "茅台": "600519.SS",
    "平安银行": "000001.SZ",
}


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    name: str | None
    market: str | None
    currency: str | None
    price: Decimal | None
    change: Decimal | None
    change_percent: Decimal | None
    exchange_time: str | None


@dataclass(frozen=True)
class MarketHotspot:
    board_type: str
    code: str
    name: str
    price: Decimal | None
    change_percent: Decimal | None
    main_net_inflow: Decimal | None


@dataclass(frozen=True)
class MarketQuoteResult:
    status: str
    message: str
    quotes: list[MarketQuote]
    hotspots: list[MarketHotspot] | None = None


class MarketService:
    def __init__(
        self,
        *,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        quote_url: str = SINA_QUOTE_URL,
        fallback_quote_url: str = EASTMONEY_QUOTE_URL,
        second_fallback_quote_url: str = TENCENT_QUOTE_URL,
        board_url: str = EASTMONEY_BOARD_URL,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.quote_url = quote_url
        self.fallback_quote_url = fallback_quote_url
        self.second_fallback_quote_url = second_fallback_quote_url
        self.board_url = board_url

    async def query_from_text(self, text: str) -> MarketQuoteResult:
        if is_market_overview_query(text):
            return await self.query_market_overview()
        if is_hotspot_query(text):
            return await self.query_hotspots()
        symbols = extract_market_symbols(text)
        if not symbols:
            return MarketQuoteResult(
                status="needs_clarification",
                message="请告诉我要查询的股票代码或名称。",
                quotes=[],
                hotspots=None,
            )
        try:
            quotes = await self.fetch_quotes(symbols)
        except MarketQuoteFetchError as exc:
            return MarketQuoteResult(
                status="unavailable",
                message=f"证券行情暂时获取失败：{exc}",
                quotes=[],
                hotspots=None,
            )
        if not quotes:
            return MarketQuoteResult(
                status="not_found",
                message="没有查到对应的股票基础信息。",
                quotes=[],
                hotspots=None,
            )
        return MarketQuoteResult(
            status="success",
            message="证券基础信息查询成功。",
            quotes=quotes,
            hotspots=None,
        )

    async def query_hotspots(self, *, limit: int = 5) -> MarketQuoteResult:
        try:
            industry = await self._fetch_eastmoney_boards(
                board_type="行业板块",
                fs="m:90+t:2",
                limit=limit,
            )
            concept = await self._fetch_eastmoney_boards(
                board_type="概念板块",
                fs="m:90+t:3",
                limit=limit,
            )
        except MarketQuoteFetchError as exc:
            return MarketQuoteResult(
                status="unavailable",
                message=f"热门板块暂时获取失败：{exc}",
                quotes=[],
                hotspots=[],
            )
        hotspots = industry + concept
        if not hotspots:
            return MarketQuoteResult(
                status="not_found",
                message="没有查到今日热门板块。",
                quotes=[],
                hotspots=[],
            )
        return MarketQuoteResult(
            status="success",
            message="热门板块查询成功。",
            quotes=[],
            hotspots=hotspots,
        )

    async def query_market_overview(self, *, hotspot_limit: int = 3) -> MarketQuoteResult:
        quotes: list[MarketQuote] = []
        hotspots: list[MarketHotspot] = []
        try:
            quotes = await self.fetch_quotes(MARKET_OVERVIEW_SYMBOLS)
        except MarketQuoteFetchError:
            pass
        hotspot_result = await self.query_hotspots(limit=hotspot_limit)
        if hotspot_result.status == "success":
            hotspots = hotspot_result.hotspots or []
        if not quotes and not hotspots:
            return MarketQuoteResult(
                status="unavailable",
                message="市场概览暂时获取失败。",
                quotes=[],
                hotspots=[],
            )
        return MarketQuoteResult(
            status="success",
            message="市场概览查询成功。",
            quotes=quotes,
            hotspots=hotspots,
        )

    async def fetch_quotes(self, symbols: list[str]) -> list[MarketQuote]:
        # Sina is the primary source; Eastmoney is a fallback for servers blocked by Sina.
        try:
            payload = await asyncio.to_thread(
                _fetch_sina_text,
                self.quote_url,
                [_sina_symbol(symbol) for symbol in symbols],
                self.timeout_seconds,
            )
            quotes = _parse_sina_quotes(payload)
            if quotes:
                return quotes
        except MarketQuoteFetchError:
            pass
        try:
            quotes = await self._fetch_eastmoney_quotes(symbols)
            if quotes:
                return quotes
        except MarketQuoteFetchError:
            pass
        return await self._fetch_tencent_quotes(symbols)

    async def _fetch_eastmoney_quotes(self, symbols: list[str]) -> list[MarketQuote]:
        quotes: list[MarketQuote] = []
        failures = 0
        for symbol in symbols:
            try:
                payload = await asyncio.to_thread(
                    _fetch_eastmoney_json,
                    self.fallback_quote_url,
                    _eastmoney_secid(symbol),
                    self.timeout_seconds,
                )
            except MarketQuoteFetchError:
                failures += 1
                continue
            quote = _parse_eastmoney_quote(payload.get("data"), fallback_symbol=symbol)
            if quote is not None:
                quotes.append(quote)
        if failures == len(symbols):
            raise MarketQuoteFetchError("all_sources_failed")
        return quotes

    async def _fetch_tencent_quotes(self, symbols: list[str]) -> list[MarketQuote]:
        payload = await asyncio.to_thread(
            _fetch_tencent_text,
            self.second_fallback_quote_url,
            [_tencent_symbol(symbol) for symbol in symbols],
            self.timeout_seconds,
        )
        return _parse_tencent_quotes(payload)

    async def _fetch_eastmoney_boards(
        self,
        *,
        board_type: str,
        fs: str,
        limit: int,
    ) -> list[MarketHotspot]:
        payload = await asyncio.to_thread(
            _fetch_eastmoney_board_json,
            self.board_url,
            fs,
            limit,
            self.timeout_seconds,
        )
        return _parse_eastmoney_boards(payload, board_type=board_type)


def is_hotspot_query(text: str) -> bool:
    normalized = text.strip()
    return any(
        keyword in normalized
        for keyword in ("热门板块", "热点板块", "强势板块", "板块热点", "板块排行")
    )


def is_market_overview_query(text: str) -> bool:
    normalized = text.strip()
    overview_keywords = (
        "市场行情",
        "市场概览",
        "大盘行情",
        "今日行情",
        "今天行情",
        "a股行情",
        "A股行情",
        "a股市场",
        "A股市场",
        "股市行情",
        "大盘怎么样",
        "市场怎么样",
        "股市怎么样",
    )
    return any(keyword in normalized for keyword in overview_keywords)


def extract_market_symbols(text: str) -> list[str]:
    normalized = text.strip()
    symbols: list[str] = []
    for name, symbol in KNOWN_SYMBOLS.items():
        if name in normalized:
            symbols.append(symbol)
    symbols.extend(_extract_prefixed_symbols(normalized))
    symbols.extend(_extract_plain_codes(normalized))
    return list(dict.fromkeys(symbols))[:5]


def _extract_prefixed_symbols(text: str) -> list[str]:
    symbols: list[str] = []
    for raw in re.findall(r"\b(?:NYSE|NASDAQ|US|HK|SH|SZ)[:：.]?([A-Za-z0-9.]{1,10})\b", text):
        symbols.append(_normalize_symbol(raw))
    for raw in re.findall(r"\b[A-Z]{1,6}(?:\.[A-Z]{1,3})?\b", text):
        symbols.append(_normalize_symbol(raw))
    return symbols


def _extract_plain_codes(text: str) -> list[str]:
    symbols: list[str] = []
    for raw in re.findall(r"(?<!\d)(\d{5,6})(?!\d)", text):
        symbols.append(_normalize_symbol(raw, context=text))
    return symbols


def _normalize_symbol(raw: str, *, context: str = "") -> str:
    symbol = raw.strip().upper()
    if re.fullmatch(r"\d{6}", symbol):
        if symbol == "000001" and any(keyword in context for keyword in ("上证", "沪指")):
            return f"{symbol}.SS"
        if symbol.startswith(("6", "9")):
            return f"{symbol}.SS"
        return f"{symbol}.SZ"
    if re.fullmatch(r"\d{5}", symbol):
        return f"{symbol}.HK"
    return symbol


def _sina_symbol(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized.endswith(".SS"):
        return f"sh{normalized.removesuffix('.SS')}"
    if normalized.endswith(".SZ"):
        return f"sz{normalized.removesuffix('.SZ')}"
    if normalized.endswith(".HK"):
        return f"hk{normalized.removesuffix('.HK')}"
    return f"gb_{normalized.lower()}"


def _eastmoney_secid(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized.endswith(".SS"):
        return f"1.{normalized.removesuffix('.SS')}"
    if normalized.endswith(".SZ"):
        return f"0.{normalized.removesuffix('.SZ')}"
    if normalized.endswith(".HK"):
        return f"116.{normalized.removesuffix('.HK')}"
    return f"105.{normalized}"


def _tencent_symbol(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized.endswith(".SS"):
        return f"sh{normalized.removesuffix('.SS')}"
    if normalized.endswith(".SZ"):
        return f"sz{normalized.removesuffix('.SZ')}"
    if normalized.endswith(".HK"):
        return f"hk{normalized.removesuffix('.HK')}"
    return f"us{normalized}"


def _parse_sina_quotes(payload: str) -> list[MarketQuote]:
    quotes: list[MarketQuote] = []
    for line in payload.splitlines():
        match = re.search(r"var hq_str_([^=]+)=\"(.*)\";", line)
        if not match:
            continue
        source_symbol = match.group(1)
        fields = match.group(2).split(",")
        quote = _parse_sina_quote(source_symbol, fields)
        if quote is not None:
            quotes.append(quote)
    return quotes


def _parse_sina_quote(source_symbol: str, fields: list[str]) -> MarketQuote | None:
    if not fields or not fields[0]:
        return None
    if source_symbol.startswith(("sh", "sz")):
        return _parse_cn_quote(source_symbol, fields)
    if source_symbol.startswith("hk"):
        return _parse_hk_quote(source_symbol, fields)
    if source_symbol.startswith("gb_"):
        return _parse_us_quote(source_symbol, fields)
    return None


def _parse_tencent_quotes(payload: str) -> list[MarketQuote]:
    quotes: list[MarketQuote] = []
    for line in payload.splitlines():
        match = re.search(r"v_([^=]+)=\"(.*)\";", line)
        if not match or match.group(1) == "pv_none_match":
            continue
        source_symbol = match.group(1)
        fields = match.group(2).split("~")
        quote = _parse_tencent_quote(source_symbol, fields)
        if quote is not None:
            quotes.append(quote)
    return quotes


def _parse_tencent_quote(source_symbol: str, fields: list[str]) -> MarketQuote | None:
    if len(fields) < 34:
        return None
    price = _decimal_or_none(fields[3])
    previous_close = _decimal_or_none(fields[4])
    change = _decimal_or_none(fields[31]) or _change(price=price, previous_close=previous_close)
    return MarketQuote(
        symbol=_display_symbol(source_symbol),
        name=fields[1],
        market=_tencent_market_name(source_symbol),
        currency=_tencent_currency(source_symbol, fields),
        price=price,
        change=change,
        change_percent=_decimal_or_none(fields[32]),
        exchange_time=_parse_tencent_datetime(fields[30]),
    )


def _parse_cn_quote(source_symbol: str, fields: list[str]) -> MarketQuote | None:
    if len(fields) < 32:
        return None
    price = _decimal_or_none(fields[3])
    previous_close = _decimal_or_none(fields[2])
    change = _change(price=price, previous_close=previous_close)
    return MarketQuote(
        symbol=_display_symbol(source_symbol),
        name=fields[0],
        market="上交所" if source_symbol.startswith("sh") else "深交所",
        currency="CNY",
        price=price,
        change=change,
        change_percent=_change_percent(change=change, previous_close=previous_close),
        exchange_time=_datetime_to_iso(fields[30], fields[31], "%Y-%m-%d %H:%M:%S"),
    )


def _parse_hk_quote(source_symbol: str, fields: list[str]) -> MarketQuote | None:
    if len(fields) < 18:
        return None
    price = _decimal_or_none(fields[6])
    change = _decimal_or_none(fields[7])
    return MarketQuote(
        symbol=_display_symbol(source_symbol),
        name=fields[1] or fields[0],
        market="港股",
        currency="HKD",
        price=price,
        change=change,
        change_percent=_decimal_or_none(fields[8]),
        exchange_time=_datetime_to_iso(
            fields[17],
            fields[18] if len(fields) > 18 else "",
            "%Y/%m/%d %H:%M",
        ),
    )


def _parse_us_quote(source_symbol: str, fields: list[str]) -> MarketQuote | None:
    if len(fields) < 5:
        return None
    return MarketQuote(
        symbol=_display_symbol(source_symbol),
        name=fields[0],
        market="美股",
        currency="USD",
        price=_decimal_or_none(fields[1]),
        change=_decimal_or_none(fields[4]),
        change_percent=_decimal_or_none(fields[2]),
        exchange_time=fields[3] or None,
    )


def _parse_eastmoney_quote(
    item: dict[str, Any] | None,
    *,
    fallback_symbol: str,
) -> MarketQuote | None:
    if not item or item.get("f43") in (None, "-"):
        return None
    market_code = item.get("f107")
    price = _scaled_decimal(item.get("f43"), item.get("f59"))
    previous_close = _scaled_decimal(item.get("f60"), item.get("f59"))
    change = _scaled_decimal(item.get("f169"), item.get("f59"))
    if change is None:
        change = _change(price=price, previous_close=previous_close)
    return MarketQuote(
        symbol=_eastmoney_display_symbol(str(item.get("f57") or fallback_symbol), market_code),
        name=item.get("f58"),
        market=_eastmoney_market_name(market_code),
        currency=_eastmoney_currency(market_code),
        price=price,
        change=change,
        change_percent=_scaled_decimal(item.get("f170"), 2),
        exchange_time=_timestamp_to_iso(item.get("f86")),
    )


def _parse_eastmoney_boards(
    payload: dict[str, Any],
    *,
    board_type: str,
) -> list[MarketHotspot]:
    rows = payload.get("data", {}).get("diff") or []
    items: list[MarketHotspot] = []
    for row in rows:
        code = str(row.get("f12") or "")
        name = str(row.get("f14") or "")
        if not code or not name:
            continue
        items.append(
            MarketHotspot(
                board_type=board_type,
                code=code,
                name=name,
                price=_decimal_or_none(row.get("f2")),
                change_percent=_decimal_or_none(row.get("f3")),
                main_net_inflow=_decimal_or_none(row.get("f62")),
            )
        )
    return items


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _scaled_decimal(value: Any, precision: Any) -> Decimal | None:
    number = _decimal_or_none(value)
    if number is None:
        return None
    try:
        places = int(precision)
    except (TypeError, ValueError):
        places = 2
    return number / (Decimal(10) ** places)


def _change(*, price: Decimal | None, previous_close: Decimal | None) -> Decimal | None:
    if price is None or previous_close is None:
        return None
    return price - previous_close


def _change_percent(
    *,
    change: Decimal | None,
    previous_close: Decimal | None,
) -> Decimal | None:
    if change is None or previous_close in (None, Decimal("0")):
        return None
    return (change / previous_close * Decimal("100")).quantize(Decimal("0.0001"))


def _datetime_to_iso(date_text: str, time_text: str, fmt: str) -> str | None:
    try:
        parsed = datetime.strptime(f"{date_text} {time_text}".strip(), fmt)
        return parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai")).isoformat()
    except (TypeError, ValueError):
        return None


def _display_symbol(source_symbol: str) -> str:
    if source_symbol.startswith("sh"):
        return f"{source_symbol[2:]}.SS"
    if source_symbol.startswith("sz"):
        return f"{source_symbol[2:]}.SZ"
    if source_symbol.startswith("hk"):
        return f"{source_symbol[2:]}.HK"
    if source_symbol.startswith("gb_"):
        return source_symbol[3:].upper()
    if source_symbol.startswith("us"):
        return source_symbol[2:].upper()
    return source_symbol


def _tencent_market_name(source_symbol: str) -> str | None:
    if source_symbol.startswith("sh"):
        return "上交所"
    if source_symbol.startswith("sz"):
        return "深交所"
    if source_symbol.startswith("hk"):
        return "港股"
    if source_symbol.startswith("us"):
        return "美股"
    return None


def _tencent_currency(source_symbol: str, fields: list[str]) -> str | None:
    if source_symbol.startswith(("sh", "sz")):
        return fields[82] if len(fields) > 82 and fields[82] else "CNY"
    if source_symbol.startswith("hk"):
        return "HKD"
    if source_symbol.startswith("us"):
        return fields[35] if len(fields) > 35 and fields[35] else "USD"
    return None


def _eastmoney_display_symbol(symbol: str, market_code: Any) -> str:
    if market_code == 1:
        return f"{symbol}.SS"
    if market_code == 0:
        return f"{symbol}.SZ"
    if market_code == 116:
        return f"{symbol}.HK"
    return symbol


def _eastmoney_market_name(code: Any) -> str | None:
    return {0: "深交所", 1: "上交所", 105: "美股", 106: "美股", 116: "港股"}.get(code)


def _eastmoney_currency(code: Any) -> str | None:
    return {0: "CNY", 1: "CNY", 105: "USD", 106: "USD", 116: "HKD"}.get(code)


def _timestamp_to_iso(value: Any) -> str | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def _parse_tencent_datetime(value: str) -> str | None:
    for fmt in ("%Y%m%d%H%M%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai")).isoformat()
        except ValueError:
            continue
    return value or None


class MarketQuoteFetchError(RuntimeError):
    pass


def _fetch_sina_text(url: str, symbols: list[str], timeout_seconds: int) -> str:
    request_url = f"{url}{','.join(symbols)}"
    request = Request(
        request_url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("gbk", errors="ignore")
    except Exception as exc:
        raise MarketQuoteFetchError(exc.__class__.__name__) from exc


def _fetch_eastmoney_json(url: str, secid: str, timeout_seconds: int) -> dict[str, Any]:
    query = urlencode({"secid": secid, "fields": EASTMONEY_FIELDS})
    return _fetch_eastmoney_json_with_retries(f"{url}?{query}", timeout_seconds)


def _fetch_eastmoney_board_json(
    url: str,
    fs: str,
    limit: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    query = urlencode(
        {
            "pn": 1,
            "pz": limit,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": fs,
            "fields": EASTMONEY_BOARD_FIELDS,
        }
    )
    return _fetch_eastmoney_json_with_retries(f"{url}?{query}", timeout_seconds)


def _fetch_eastmoney_json_with_retries(
    request_url: str,
    timeout_seconds: int,
    *,
    attempts: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = Request(request_url, headers=EASTMONEY_HEADERS)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            # Eastmoney may close idle server-side connections; retry keeps queries stable.
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(0.3)
    error_name = last_error.__class__.__name__ if last_error is not None else "unknown"
    raise MarketQuoteFetchError(error_name) from last_error


def _fetch_tencent_text(url: str, symbols: list[str], timeout_seconds: int) -> str:
    request_url = f"{url}{','.join(symbols)}"
    request = Request(
        request_url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("gbk", errors="ignore")
    except Exception as exc:
        raise MarketQuoteFetchError(exc.__class__.__name__) from exc
