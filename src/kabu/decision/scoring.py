"""保有期間ごとの期待トータルリターン（レンジ）の算出。

株価部分は「割安度」「トレンド」で年率の期待値を小さく補正し、
ボラティリティから幅（±1σ）を出すだけの控えめなモデルにしている。
点推定ではなくレンジで扱うこと。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from kabu.config.models import Holding, Settings, Stock, Yutai
from kabu.income import IncomeSummary, estimate_income
from kabu.price import PriceMetrics


@dataclass
class HorizonEstimate:
    horizon_months: int
    invested: float  # 株価 × 株数
    income: IncomeSummary
    income_return: float  # インカム / 投資額
    price_return_mid: float
    price_return_low: float
    price_return_high: float
    cost_return: float  # 売買コスト（往復）

    @property
    def total_mid(self) -> float:
        return self.income_return + self.price_return_mid - self.cost_return

    @property
    def total_low(self) -> float:
        return self.income_return + self.price_return_low - self.cost_return

    @property
    def total_high(self) -> float:
        return self.income_return + self.price_return_high - self.cost_return

    @property
    def total_mid_annual(self) -> float:
        return self.total_mid * 12 / self.horizon_months

    @property
    def income_return_annual(self) -> float:
        return self.income_return * 12 / self.horizon_months


def price_adjustment_annual(metrics: PriceMetrics, settings: Settings) -> tuple[float, float]:
    """(割安度による年率補正, トレンドによる年率補正)。"""
    val_adj = 0.0
    if metrics.yield_percentile is not None:
        # 利回りが過去レンジの上位（割安）ならプラス、下位（割高）ならマイナス
        val_adj = (metrics.yield_percentile - 0.5) * 2 * settings.valuation_max_adj_annual

    trend_score = 0.0
    n = 0
    if metrics.sma200_ratio is not None:
        trend_score += max(-1.0, min(1.0, metrics.sma200_ratio / 0.10))
        n += 1
    if metrics.momentum_12_1 is not None:
        trend_score += max(-1.0, min(1.0, metrics.momentum_12_1 / 0.20))
        n += 1
    if metrics.relative_strength_6m is not None:
        trend_score += max(-1.0, min(1.0, metrics.relative_strength_6m / 0.15))
        n += 1
    trend_adj = (trend_score / n) * settings.trend_max_adj_annual if n else 0.0
    return val_adj, trend_adj


def estimate_horizon(
    stock: Stock,
    yutai: Yutai | None,
    metrics: PriceMetrics,
    settings: Settings,
    shares: int,
    as_of: date,
    horizon_months: int,
    holding: Holding | None = None,
) -> HorizonEstimate:
    invested = metrics.last_close * shares
    income = estimate_income(
        stock, yutai, shares, as_of, horizon_months, settings.dividend_tax_rate, holding=holding
    )
    income_return = income.total_net / invested if invested else 0.0

    val_adj, trend_adj = price_adjustment_annual(metrics, settings)
    years = horizon_months / 12
    # 株価リターンの期待値 = 市場全体の控えめな期待リターン + 割安度補正 + トレンド補正
    #                        − 期間内の配当落ち（配当はインカム側で計上するので二重計上を防ぐ）
    mid = (settings.base_return_annual + val_adj + trend_adj) * years
    if invested:
        mid -= income.dividend_gross / invested
    sigma = (metrics.volatility_annual or 0.25) * math.sqrt(years)
    cost = settings.commission_rate * 2
    return HorizonEstimate(
        horizon_months=horizon_months,
        invested=invested,
        income=income,
        income_return=income_return,
        price_return_mid=mid,
        price_return_low=mid - sigma,
        price_return_high=mid + sigma,
        cost_return=cost,
    )
