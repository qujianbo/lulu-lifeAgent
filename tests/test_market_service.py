from app.services.markets import extract_market_symbols


def test_extract_market_symbols_for_us_stock() -> None:
    assert extract_market_symbols("查一下 AAPL 股票") == ["AAPL"]


def test_extract_market_symbols_for_a_share_code() -> None:
    assert extract_market_symbols("看看 600519 现在多少钱") == ["600519.SS"]


def test_extract_market_symbols_for_known_cn_name() -> None:
    assert extract_market_symbols("贵州茅台的股票信息") == ["600519.SS"]


def test_extract_market_symbols_for_hk_code() -> None:
    assert extract_market_symbols("腾讯 00700 行情") == ["00700.HK"]
