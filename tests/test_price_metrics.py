import pandas as pd

from kabu.price import compute_price_metrics
from tests.conftest import make_market_data


def test_metrics_basic(market_data):
    m = compute_price_metrics(market_data, annual_dividend_forecast=40.0)
    assert m.last_close > 0
    assert m.dividend_yield_forecast == 40.0 / m.last_close
    assert m.dividend_yield_trailing is not None and abs(m.dividend_yield_trailing - 40.0 / m.last_close) < 1e-9
    assert m.yield_percentile is not None and 0 <= m.yield_percentile <= 1
    assert m.volatility_annual is not None and 0.1 < m.volatility_annual < 0.4
    assert m.max_drawdown_1y is not None and m.max_drawdown_1y <= 0
    assert m.sma200_ratio is not None
    assert m.payout_ratio == 40.0 / 150.0
    assert m.trend_label in {"上昇", "下降", "横ばい"}


def test_yield_percentile_direction():
    # 価格が長期で下がった銘柄 → 現在利回りは過去より高い → 割安側（1 に近い）
    down = make_market_data(annual_drift=-0.30, annual_vol=0.05, seed=3)
    m = compute_price_metrics(down, annual_dividend_forecast=40.0)
    assert m.yield_percentile > 0.8
    up = make_market_data(annual_drift=0.30, annual_vol=0.05, seed=3)
    m2 = compute_price_metrics(up, annual_dividend_forecast=40.0)
    assert m2.yield_percentile < 0.2


def test_relative_strength_uses_benchmark(market_data):
    bench = make_market_data(ticker="1306.T", annual_drift=0.0, seed=7)
    m = compute_price_metrics(market_data, 40.0, benchmark=bench)
    assert m.relative_strength_6m is not None


def test_short_history_gives_none():
    short = make_market_data(start="2026-09-01")
    m = compute_price_metrics(short, 40.0)
    assert m.sma200_ratio is None
    assert m.momentum_12_1 is None
    assert m.yield_percentile is None
