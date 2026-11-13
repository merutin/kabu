"""BUY / HOLD / SELL / WAIT の判定と理由文の生成。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from kabu.calendar import next_record_date
from kabu.config.models import Holding, Settings, Stock, Yutai
from kabu.decision.scoring import HorizonEstimate, estimate_horizon
from kabu.income.events import selling_resets_condition
from kabu.price import PriceMetrics


class Verdict(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    WAIT = "WAIT"


@dataclass
class Judgement:
    stock: Stock
    as_of: date
    shares: int
    holding: Holding | None
    metrics: PriceMetrics
    estimates: dict[int, HorizonEstimate]
    verdict: Verdict = Verdict.WAIT
    confidence: str = "低"
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timing_notes: list[str] = field(default_factory=list)

    @property
    def primary(self) -> list[HorizonEstimate]:
        return [self.estimates[h] for h in sorted(self.estimates)]


def _days_to(d: date, as_of: date) -> int:
    return (d - as_of).days


def judge_stock(
    stock: Stock,
    yutai: Yutai | None,
    metrics: PriceMetrics,
    settings: Settings,
    as_of: date,
    holding: Holding | None = None,
    default_shares: int | None = None,
) -> Judgement:
    # 評価株数: 保有中なら保有株数、新規なら優待の最低株数（無ければ 100）
    if holding:
        shares = holding.shares
    else:
        shares = default_shares or (yutai.min_shares if yutai else 100)

    estimates = {
        h: estimate_horizon(stock, yutai, metrics, settings, shares, as_of, h, holding=holding)
        for h in settings.horizons_months
    }
    j = Judgement(stock=stock, as_of=as_of, shares=shares, holding=holding, metrics=metrics, estimates=estimates)

    prim = [estimates[h] for h in settings.primary_horizons_months]
    mids_annual = [e.total_mid_annual for e in prim]
    all_positive = all(e.total_mid > 0 for e in prim)
    all_above = all(m >= settings.buy_threshold_annual for m in mids_annual)
    all_negative = all(e.total_mid < 0 for e in prim)
    trend = metrics.trend_label
    rich = metrics.yield_percentile is not None and metrics.yield_percentile <= 0.1

    # --- 理由（共通） ---
    longest = prim[-1]
    j.reasons.append(
        f"{longest.horizon_months}ヶ月の期待トータルリターン "
        f"{longest.total_low:+.1%} 〜 {longest.total_high:+.1%}（中央値 {longest.total_mid:+.1%}、年率 {longest.total_mid_annual:+.1%}）"
    )
    j.reasons.append(
        f"インカム利回り（年率換算）{longest.income_return_annual:.2%}"
        f"（配当 {longest.income.dividend_net:,.0f}円 + 優待 {longest.income.yutai_net:,.0f}円 / {longest.horizon_months}ヶ月）"
    )
    j.reasons.append(f"割安度: {metrics.valuation_label}" + (f"、予想配当利回り {metrics.dividend_yield_forecast:.2%}" if metrics.dividend_yield_forecast else ""))
    j.reasons.append(f"トレンド: {trend}" + (f"（200日線比 {metrics.sma200_ratio:+.1%}）" if metrics.sma200_ratio is not None else ""))

    # --- 警告（リスク） ---
    if stock.non_recurring_dividend > 0:
        j.warnings.append(
            f"予想配当 {stock.annual_dividend_forecast:g}円のうち {stock.non_recurring_dividend:g}円は特別・記念配当（来期は見込めない）"
        )
    if metrics.payout_ratio is not None and metrics.payout_ratio > 0.8:
        j.warnings.append(f"配当性向 {metrics.payout_ratio:.0%} と高く、減配リスクに注意")
    if metrics.max_drawdown_1y is not None and metrics.max_drawdown_1y < -0.3:
        j.warnings.append(f"直近1年の最大下落率 {metrics.max_drawdown_1y:.0%}")
    for e in longest.income.ineligible:
        j.warnings.append(f"{e.record.month}月の優待は対象外: {e.reason}")

    # --- タイミング ---
    months = sorted(set(stock.dividend_per_record) | set(yutai.record_months if yutai else []))
    if months:
        nxt = next_record_date(as_of, months, stock.record_day)
        d = _days_to(nxt.last_with_rights, as_of)
        if 0 <= d <= settings.record_notice_days:
            j.timing_notes.append(
                f"権利付き最終日 {nxt.last_with_rights:%m/%d} まで {d} 日。権利落ち後は配当・優待分の下落が見込まれる"
            )
        else:
            j.timing_notes.append(f"次回権利付き最終日 {nxt.last_with_rights:%Y/%m/%d}")
    near_earnings = [
        ed for ed in stock.earnings_dates if abs(_days_to(ed, as_of)) <= settings.earnings_blackout_days
    ]
    if near_earnings:
        j.timing_notes.append(f"決算発表 {near_earnings[0]:%m/%d} が直近。発表後に判断するのが無難")

    # --- 判定 ---
    if holding:
        resets = selling_resets_condition(yutai)
        if all_negative or (rich and trend == "下降"):
            j.verdict = Verdict.SELL
            j.reasons.insert(0, "主要期間の期待トータルリターンがマイナス" if all_negative else "割高かつ下降トレンド")
            if resets:
                j.warnings.append("全株売却すると優待の継続保有条件がリセットされる")
        else:
            j.verdict = Verdict.HOLD
            if resets:
                j.reasons.insert(0, "優待の継続保有条件を維持するため保有継続が有利")
        pnl = (metrics.last_close / holding.avg_cost - 1)
        j.reasons.append(f"評価損益 {pnl:+.1%}（取得単価 {holding.avg_cost:,.0f}円）")
    else:
        if near_earnings:
            j.verdict = Verdict.WAIT
            j.reasons.insert(0, "決算発表直前のため新規買いは見送り")
        elif all_above and trend != "下降":
            j.verdict = Verdict.BUY
            j.reasons.insert(0, f"主要期間すべてで年率 {settings.buy_threshold_annual:.0%} 以上の期待リターン")
        elif all_positive and trend != "下降":
            j.verdict = Verdict.WAIT
            j.reasons.insert(0, "期待リターンはプラスだが閾値未満")
        else:
            j.verdict = Verdict.WAIT
            j.reasons.insert(0, "下降トレンドまたは期待リターンが不足")

    # --- 信頼度: データの揃い具合と下限がプラスかで決める ---
    missing = sum(x is None for x in (metrics.yield_percentile, metrics.sma200_ratio, metrics.volatility_annual))
    if missing == 0 and all(e.total_low > -0.05 for e in prim):
        j.confidence = "中"
    elif missing >= 2:
        j.confidence = "低（データ不足）"
    else:
        j.confidence = "低"
    return j
