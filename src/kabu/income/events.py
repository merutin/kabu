"""保有期間内に受け取れる配当・優待（インカム）の計算。

ここが本ツールの土台。配当予想・優待条件は設定ファイルの値をそのまま使い、
「いつ・いくら・条件を満たすか」をカレンダーで厳密に扱う。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from kabu.calendar import RecordDate, add_months, next_record_date, record_dates_between
from kabu.config.models import Holding, HoldingCondition, Stock, Yutai


@dataclass
class IncomeEvent:
    kind: str  # "dividend" | "yutai"
    record: RecordDate
    gross: float  # 税引前（円）。優待は personal_value × 1
    net: float  # 税引後（円）
    description: str
    eligible: bool = True  # 継続保有条件などを満たすか
    reason: str = ""  # 不適格の理由


@dataclass
class IncomeSummary:
    horizon_months: int
    start: date
    end: date
    events: list[IncomeEvent] = field(default_factory=list)

    @property
    def dividend_gross(self) -> float:
        return sum(e.gross for e in self.events if e.kind == "dividend" and e.eligible)

    @property
    def dividend_net(self) -> float:
        return sum(e.net for e in self.events if e.kind == "dividend" and e.eligible)

    @property
    def yutai_net(self) -> float:
        return sum(e.net for e in self.events if e.kind == "yutai" and e.eligible)

    @property
    def total_net(self) -> float:
        return self.dividend_net + self.yutai_net

    @property
    def ineligible(self) -> list[IncomeEvent]:
        return [e for e in self.events if not e.eligible]


def _consecutive_records_held(
    first_bought_on: date, target: RecordDate, months: list[int], day: int | None
) -> int:
    """first_bought_on から target までで、連続して名簿に載った回数（target を含む）。"""
    rds = record_dates_between(first_bought_on, target.nominal, months, day)
    return sum(1 for rd in rds if rd.last_with_rights >= first_bought_on and rd.nominal <= target.nominal)


def _first_record_month(first_bought_on: date, months: list[int], day: int | None) -> int:
    """保有開始後、最初に名簿に載る基準日の月（年 1 回優待の起点）。"""
    return next_record_date(first_bought_on, months, day).month


def yutai_eligibility(
    cond: HoldingCondition,
    first_bought_on: date,
    target: RecordDate,
    months: list[int],
    day: int | None,
) -> tuple[bool, str]:
    """優待の継続保有条件を満たすか。"""
    if cond.is_none:
        return True, ""
    reasons: list[str] = []
    if cond.min_years > 0:
        held_days = (target.effective - first_bought_on).days
        if held_days < cond.min_years * 365:
            reasons.append(f"継続保有 {cond.min_years:g} 年未満（{held_days} 日）")
    if cond.consecutive_records > 0:
        n = _consecutive_records_held(first_bought_on, target, months, day)
        if n < cond.consecutive_records:
            reasons.append(f"連続記載 {n}/{cond.consecutive_records} 回")
    return (not reasons), "、".join(reasons)


def estimate_income(
    stock: Stock,
    yutai: Yutai | None,
    shares: int,
    as_of: date,
    horizon_months: int,
    dividend_tax_rate: float,
    holding: Holding | None = None,
) -> IncomeSummary:
    """as_of から horizon_months 保有した場合に得られる配当・優待。

    - 新規買いの場合（holding=None）は as_of に買うものとして、
      権利付き最終日 >= as_of の回だけ数える（継続保有の起点は as_of）。
    - 保有中の場合は、権利付き最終日 >= as_of の回を「今売ると失う分」として数える。
    """
    end = add_months(as_of, horizon_months)
    first_bought_on = holding.first_bought_on if holding else as_of
    summary = IncomeSummary(horizon_months=horizon_months, start=as_of, end=end)

    # 配当
    div_months = sorted(stock.dividend_per_record)
    for rd in record_dates_between(as_of, end, div_months, stock.record_day):
        if rd.last_with_rights < as_of:
            continue
        per_share = stock.dividend_for(rd.nominal.year, rd.month)
        gross = per_share * shares
        net = gross * (1 - dividend_tax_rate)
        summary.events.append(
            IncomeEvent(
                kind="dividend",
                record=rd,
                gross=gross,
                net=net,
                description=f"{rd.month}月権利 配当 {per_share:g}円 × {shares}株"
                + ("（特別配当等を含む今回限りの額）" if f"{rd.nominal.year:04d}-{rd.month:02d}" in stock.dividend_overrides else ""),
            )
        )

    # 優待
    if yutai is not None:
        check_months = yutai.check_months
        anniversary_month = (
            _first_record_month(first_bought_on, yutai.record_months, yutai.record_day)
            if yutai.anniversary_only
            else None
        )
        spend = yutai.assumed_spend_per_record
        for rd in record_dates_between(as_of, end, yutai.record_months, yutai.record_day):
            if rd.last_with_rights < as_of:
                continue
            if yutai.tier_for(shares) is None:
                summary.events.append(
                    IncomeEvent(
                        kind="yutai", record=rd, gross=0, net=0,
                        description=f"{rd.month}月権利 優待",
                        eligible=False, reason=f"必要株数 {yutai.min_shares} 株未満",
                    )
                )
                continue
            n_records = _consecutive_records_held(first_bought_on, rd, check_months, yutai.record_day)
            tier = yutai.tier_for(shares, n_records)
            ok, why = yutai_eligibility(
                yutai.holding_condition, first_bought_on, rd, check_months, yutai.record_day
            )
            if anniversary_month is not None and rd.month != anniversary_month:
                ok, why = False, f"年 1 回（{anniversary_month}月基準）のため対象外"
            if tier is None:
                ok, why = False, f"連続記載 {n_records} 回では対象段階なし"
                tier = yutai.tier_for(shares)
                assert tier is not None
            gross = tier.value_for(spend)
            value = tier.personal_value_for(spend)
            desc = f"{rd.month}月権利 優待 {tier.content}"
            if tier.rate is not None:
                desc += f"（想定利用額 {spend or 0:,.0f}円 × {tier.rate:.1%}）"
            if tier.personal_factor != 1:
                desc += f"（換算 {gross:,.0f}円 × {tier.personal_factor:g}）"
            summary.events.append(
                IncomeEvent(kind="yutai", record=rd, gross=gross, net=value, description=desc, eligible=ok, reason=why)
            )
    summary.events.sort(key=lambda e: e.record.nominal)
    return summary


def selling_resets_condition(yutai: Yutai | None) -> bool:
    """全株売却で継続保有条件がリセットされる銘柄か。"""
    return yutai is not None and not yutai.holding_condition.is_none
