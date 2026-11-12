"""ネットワーク無しで動作確認するための合成データ。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from kabu.data.prices import MarketData


def make_market_data(
    ticker: str = "9999.T",
    start: str = "2020-01-06",
    end: str = "2026-11-12",
    start_price: float = 2000.0,
    annual_drift: float = 0.05,
    annual_vol: float = 0.20,
    dividend_per_half: float = 20.0,
    seed: int = 1,
) -> MarketData:
    """ドリフト付きランダムウォークと半期配当（3 月・9 月）の合成データ。"""
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    n = len(idx)
    daily = annual_drift / 245 + annual_vol / np.sqrt(245) * rng.standard_normal(n)
    close = start_price * np.exp(np.cumsum(daily))
    prices = pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 100000},
        index=idx,
    )
    div_dates = [d for d in idx if d.month in (3, 9) and d == idx[idx.to_period("M") == d.to_period("M")][-2]]
    dividends = pd.Series(dividend_per_half, index=pd.DatetimeIndex(div_dates), dtype=float)
    return MarketData(ticker=ticker, prices=prices, dividends=dividends, info={"trailingEps": 150.0})


class DemoSource:
    def __init__(self, end: str | None = None):
        self.end = end

    def fetch(self, ticker: str, years: int) -> MarketData:
        seed = sum(ord(c) for c in ticker)
        kw = {"end": self.end} if self.end else {}
        return make_market_data(ticker=ticker, seed=seed, **kw)
