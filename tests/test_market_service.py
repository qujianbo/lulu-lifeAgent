from app.services.markets import (
    extract_market_symbols,
    is_hotspot_query,
    is_market_overview_query,
)


def test_extract_market_symbols_for_us_stock() -> None:
    assert extract_market_symbols("查一下 AAPL 股票") == ["AAPL"]


def test_extract_market_symbols_for_a_share_code() -> None:
    assert extract_market_symbols("看看 600519 现在多少钱") == ["600519.SS"]


def test_extract_market_symbols_for_known_cn_name() -> None:
    assert extract_market_symbols("贵州茅台的股票信息") == ["600519.SS"]


def test_extract_market_symbols_for_hk_code() -> None:
    assert extract_market_symbols("腾讯 00700 行情") == ["00700.HK"]


def test_extract_market_symbols_for_shanghai_index_name() -> None:
    assert extract_market_symbols("推一下今天的上证大盘指数") == ["000001.SS"]


def test_extract_market_symbols_for_shanghai_index_code_context() -> None:
    assert extract_market_symbols("对，用 000001 查询上证指数") == ["000001.SS"]


def test_hotspot_query_detection() -> None:
    assert is_hotspot_query("那今天的热门板块是哪些")
    assert is_hotspot_query("看看热点板块")
    assert not is_hotspot_query("查询今日上证指数")


def test_market_overview_query_detection() -> None:
    assert is_market_overview_query("今天市场行情如何")
    assert is_market_overview_query("A股市场怎么样")
    assert is_market_overview_query("看一下大盘行情")
    assert not is_market_overview_query("查询今日上证指数")
