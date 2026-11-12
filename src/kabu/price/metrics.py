"""株価評価: 割安度（自社の過去レンジ比較）、トレンド、リスク。

いずれも「株価を当てる」ためではなく、期待リターンの向きとばらつきを
控えめに補正するための材料として使う。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from kabu.data.prices import MarketData

TRADING_DAYS = 245  # 東証の年間営業日数の目安


@dataclass
class PriceMetrics:
    last_close: float
    # --- 割安度 ---
    dividend_yield_forecast: float | None  # 予想配当ベースの利回り
    dividend_yield_trailing: float | None  # 実績配当ベース
    yield_percentile: float | None  # 過去レンジ内での現在利回りの位置（1.0 = 最も割安）
    per: float | None
    pbr: float | None
    payout_ratio: float | None
    # --- トレンド ---
    sma200_ratio: float | None  # 終値 / 200 日移動平均 − 1
    momentum_12_1: float | None  # 12 ヶ月リターン（直近 1 ヶ月を除く）
    relative_strength_6m: float | None  # 6 ヶ月リターン − ベンチマークの 6 ヶ月リターン
    # --- リスク ---
    volatility_annual: float | None  # 日次リターン標準偏差 × √245
    max_drawdown_1y: float | None  # 直近 1 年の最大ドローダウン（負の値）
    return_1y: float | None

    @property
    def trend_label(self) -> str:
        if self.sma200_ratio is None:
            return "不明"
        if self.sma200_ratio > 0.02 and (self.momentum_12_1 or 0) >= 0:
            return "上昇"
        if self.sma200_ratio < -0.02 and (self.momentum_12_1 or 0) < 0:
            return "下降"
        return "横ばい"

    @property
    def valuation_label(self) -> str:
        p = self.yield_percentile
        if p is None:
            return "不明"
        if p >= 0.8:
            return "割安（過去レンジ上位20%の利回り）"
        if p <= 0.2:
            return "割高（過去レンジ下位20%の利回り）"
        return "中立"


def _pct_return(s: pd.Series, days: int, skip_last: int = 0) -> float | None:
    s = s.dropna()
    if len(s) <= days + skip_last:
        return None
    end = s.iloc[-1 - skip_last] if skip_last else s.iloc[-1]
    start = s.iloc[-1 - skip_last - days]
    return float(end / start - 1) if start else None


def _max_drawdown(s: pd.Series) -> float | None:
    if s.empty:
        return None
    peak = s.cummax()
    return float(((s / peak) - 1).min())


def _yield_history(close: pd.Series, dividends: pd.Series) -> pd.Series:
    """各日時点の実績配当利回り（直近 12 ヶ月の配当 / 終値）。"""
    if dividends.empty:
        return pd.Series(dtype=float)
    d = dividends.sort_index()
    daily = d.reindex(close.index, fill_value=0.0)
    trailing = daily.rolling(f"{365}D").sum()
    return (trailing / close).dropna()


def compute_price_metrics(
    data: MarketData,
    annual_dividend_forecast: float,
    benchmark: MarketData | None = None,
    lookback_years: int = 5,
) -> PriceMetrics:
    close = data.close
    last = float(close.iloc[-1])
    lookback_start = close.index[-1] - pd.DateOffset(years=lookback_years)
    window = close[close.index >= lookback_start]

    trailing_div = data.trailing_annual_dividend()
    y_forecast = annual_dividend_forecast / last if annual_dividend_forecast > 0 else None
    y_trailing = trailing_div / last if trailing_div > 0 else None

    # 割安度: 現在の利回り（予想があれば予想）を、過去の実績利回りの分布と比較
    yield_pct: float | None = None
    yh = _yield_history(window, data.dividends)
    yh = yh[yh > 0]
    current_yield = y_forecast if y_forecast is not None else y_trailing
    if current_yield is not None and len(yh) >= TRADING_DAYS:  # 1 年分以上ある場合のみ
        yield_pct = float((yh < current_yield).mean())

    sma200 = close.rolling(200).mean()
    sma_ratio = float(last / sma200.iloc[-1] - 1) if len(close) >= 200 and not math.isnan(sma200.iloc[-1]) else None

    mom = _pct_return(close, TRADING_DAYS - 21, skip_last=21)
    r6 = _pct_return(close, TRADING_DAYS // 2)
    rs = None
    if benchmark is not None and r6 is not None:
        b6 = _pct_return(benchmark.close, TRADING_DAYS // 2)
        rs = r6 - b6 if b6 is not None else None

    rets = close.pct_change().dropna()
    rets_1y = rets.iloc[-TRADING_DAYS:]
    vol = float(rets_1y.std() * np.sqrt(TRADING_DAYS)) if len(rets_1y) >= 60 else None

    info = data.info or {}
    per = info.get("trailingPE") or info.get("forwardPE")
    pbr = info.get("priceToBook")
    payout = info.get("payoutRatio")
    if payout is None and info.get("trailingEps") and annual_dividend_forecast > 0:
        eps = float(info["trailingEps"])
        payout = annual_dividend_forecast / eps if eps > 0 else None

    return PriceMetrics(
        last_close=last,
        dividend_yield_forecast=y_forecast,
        dividend_yield_trailing=y_trailing,
        yield_percentile=yield_pct,
        per=float(per) if per else None,
        pbr=float(pbr) if pbr else None,
        payout_ratio=float(payout) if payout is not None else None,
        sma200_ratio=sma_ratio,
        momentum_12_1=mom,
        relative_strength_6m=rs,
        volatility_annual=vol,
        max_drawdown_1y=_max_drawdown(close.iloc[-TRADING_DAYS:]),
        return_1y=_pct_return(close, TRADING_DAYS),
    )
