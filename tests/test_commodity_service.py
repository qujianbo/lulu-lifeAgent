from decimal import Decimal

from app.services.commodities.service import (
    CommodityService,
    _parse_gold_api_commodity,
    extract_commodity_symbols,
)


def test_extract_gold_symbol_from_natural_language() -> None:
    assert extract_commodity_symbols("今日金价") == ["XAU"]
    assert extract_commodity_symbols("黄金多少钱一克") == ["XAU"]


def test_extract_multiple_commodity_symbols_without_duplicates() -> None:
    assert extract_commodity_symbols("看看黄金和白银价格，金价也一起看") == ["XAU", "XAG"]


def test_parse_gold_api_quote() -> None:
    quote = _parse_gold_api_commodity(
        {
            "symbol": "XAU",
            "price": 4174.100098,
            "currency": "USD",
            "updatedAt": "2026-06-12T06:00:52Z",
        },
        fallback_symbol="XAU",
    )

    assert quote is not None
    assert quote.symbol == "XAU"
    assert quote.name == "国际黄金现货"
    assert quote.price == Decimal("4174.100098")
    assert quote.currency == "USD"
    assert quote.unit == "美元/盎司"
    assert quote.exchange == "gold-api.com"


async def test_query_gold_price_with_injected_gold_api(monkeypatch) -> None:
    def fake_fetch(url: str, symbol: str, timeout_seconds: int) -> dict[str, object]:
        return {
            "symbol": symbol,
            "price": 4174.10,
            "currency": "USD",
            "updatedAt": "2026-06-12T06:00:52Z",
        }

    monkeypatch.setattr("app.services.commodities.service._fetch_gold_api_quote", fake_fetch)
    service = CommodityService()

    result = await service.query_from_text("今日金价")

    assert result.status == "success"
    assert result.items[0].symbol == "XAU"
    assert result.items[0].name == "国际黄金现货"
