"""判定結果の Markdown レポート。"""

from __future__ import annotations

from datetime import date

from kabu.config.models import Settings
from kabu.decision import Judgement

_ICON = {"BUY": "🟢", "HOLD": "🔵", "SELL": "🔴", "WAIT": "⚪"}


def _pct(x: float | None, digits: int = 1) -> str:
    return "-" if x is None else f"{x:+.{digits}%}"


def render_summary_table(judgements: list[Judgement], settings: Settings) -> str:
    h = settings.primary_horizons_months[-1]
    lines = [
        f"| 銘柄 | 判定 | 株価 | {h}ヶ月 期待TR | インカム(年率) | 割安度 | トレンド |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for j in judgements:
        e = j.estimates[h]
        lines.append(
            f"| {j.stock.code} {j.stock.name} | {_ICON[j.verdict.value]} {j.verdict.value} | {j.metrics.last_close:,.0f} "
            f"| {_pct(e.total_mid)} ({_pct(e.total_low)}〜{_pct(e.total_high)}) | {e.income_return_annual:.2%} "
            f"| {j.metrics.valuation_label.split('（')[0]} | {j.metrics.trend_label} |"
        )
    return "\n".join(lines)


def render_stock(j: Judgement, settings: Settings) -> str:
    m = j.metrics
    out = [f"## {j.stock.code} {j.stock.name}　判定: {_ICON[j.verdict.value]} **{j.verdict.value}**（信頼度: {j.confidence}）", ""]
    status = f"保有 {j.holding.shares} 株（取得 {j.holding.avg_cost:,.0f}円、{j.holding.first_bought_on} から）" if j.holding else f"未保有（{j.shares} 株で評価）"
    out.append(f"- 株価 {m.last_close:,.0f} 円 × {j.shares} 株 = {m.last_close * j.shares:,.0f} 円　{status}")
    for r in j.reasons:
        out.append(f"- {r}")
    out.append("")
    out.append("| 保有期間 | 期待トータルリターン（下限〜上限） | 年率 | 配当(税引後) | 優待(自分の価値) |")
    out.append("|---|---|---:|---:|---:|")
    for h in sorted(j.estimates):
        e = j.estimates[h]
        mark = " ★" if h in settings.primary_horizons_months else ""
        out.append(
            f"| {h}ヶ月{mark} | {_pct(e.total_mid)}（{_pct(e.total_low)} 〜 {_pct(e.total_high)}） "
            f"| {_pct(e.total_mid_annual)} | {e.income.dividend_net:,.0f}円 | {e.income.yutai_net:,.0f}円 |"
        )
    longest = j.estimates[max(j.estimates)]
    if longest.income.events:
        out.append("")
        out.append(f"インカム内訳（{longest.horizon_months}ヶ月）:")
        for ev in longest.income.events:
            flag = "" if ev.eligible else f"（対象外: {ev.reason}）"
            out.append(f"- {ev.record.nominal:%Y/%m/%d} 権利（権利付き最終日 {ev.record.last_with_rights:%m/%d}）: {ev.description} → {ev.net:,.0f}円{flag}")
    stats = []
    if m.per:
        stats.append(f"PER {m.per:.1f}倍")
    if m.pbr:
        stats.append(f"PBR {m.pbr:.2f}倍")
    if m.payout_ratio is not None:
        stats.append(f"配当性向 {m.payout_ratio:.0%}")
    if m.volatility_annual is not None:
        stats.append(f"年率ボラ {m.volatility_annual:.0%}")
    if m.max_drawdown_1y is not None:
        stats.append(f"1年最大下落 {m.max_drawdown_1y:.0%}")
    if m.return_1y is not None:
        stats.append(f"1年リターン {_pct(m.return_1y)}")
    if m.relative_strength_6m is not None:
        stats.append(f"6ヶ月の対ベンチマーク {_pct(m.relative_strength_6m)}")
    if stats:
        out.append("")
        out.append("指標: " + " / ".join(stats))
    if j.timing_notes:
        out.append("")
        out.append("タイミング:")
        out += [f"- {t}" for t in j.timing_notes]
    if j.warnings:
        out.append("")
        out.append("⚠ 注意:")
        out += [f"- {w}" for w in j.warnings]
    return "\n".join(out)


def render_report(judgements: list[Judgement], settings: Settings, as_of: date, data_date: date | None = None) -> str:
    parts = [f"# 株式判定レポート {as_of:%Y-%m-%d}", ""]
    if data_date and data_date != as_of:
        parts.append(f"株価データ基準日: {data_date:%Y-%m-%d}")
        parts.append("")
    parts.append(f"口座: {settings.account.value.upper()} / 判定の基準期間: {' / '.join(f'{h}ヶ月' for h in settings.primary_horizons_months)} / BUY 閾値: 年率 {settings.buy_threshold_annual:.0%}")
    parts.append("")
    parts.append(render_summary_table(judgements, settings))
    parts.append("")
    for j in judgements:
        parts.append(render_stock(j, settings))
        parts.append("")
    parts.append("---")
    parts.append("本レポートは設定ファイルの配当予想・優待情報と過去株価に基づく機械的な試算であり、株価部分のレンジは不確実です。最終判断はご自身で行ってください。")
    return "\n".join(parts)
