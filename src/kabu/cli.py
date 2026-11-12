"""コマンドライン入口。

  kabu judge  [--as-of YYYY-MM-DD] [--source yfinance|demo] [--out reports] [--notify] [--config DIR]
  kabu fetch  [--force] [--config DIR]
  kabu income [--as-of YYYY-MM-DD] [--config DIR]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from kabu.config import AppConfig, load_config
from kabu.data.prices import CachedSource, MarketData, YFinanceSource
from kabu.decision import Judgement, judge_stock
from kabu.income import estimate_income
from kabu.price import compute_price_metrics
from kabu.report import render_report, send_notifications


def _source(cfg: AppConfig, kind: str, as_of: date):
    if kind == "demo":
        from kabu.data.demo import DemoSource

        return DemoSource(end=as_of.isoformat())
    return CachedSource(YFinanceSource(), cfg.config_dir.parent / cfg.settings.cache_dir, cfg.settings.cache_max_age_hours)


def _fetch_all(cfg: AppConfig, source, force: bool = False) -> tuple[dict[str, MarketData], MarketData | None]:
    years = cfg.settings.valuation_lookback_years + 1
    kw = {"force": force} if isinstance(source, CachedSource) else {}
    data: dict[str, MarketData] = {}
    for s in cfg.stocks:
        try:
            data[s.code] = source.fetch(s.yf_ticker, years, **kw)
        except Exception as e:  # 1 銘柄の失敗で全体を止めない
            print(f"[warn] {s.code} {s.name}: 取得失敗 {e}", file=sys.stderr)
    bench = None
    try:
        bench = source.fetch(cfg.settings.benchmark_ticker, years, **kw)
    except Exception as e:
        print(f"[warn] ベンチマーク {cfg.settings.benchmark_ticker}: 取得失敗 {e}", file=sys.stderr)
    return data, bench


def cmd_fetch(args) -> int:
    cfg = load_config(args.config)
    data, bench = _fetch_all(cfg, _source(cfg, "yfinance", date.today()), force=args.force)
    for code, d in data.items():
        print(f"{code}: {d.last_date} 終値 {d.last_close:,.0f} 円、配当実績 {len(d.dividends)} 件、株価 {len(d.prices)} 日分")
    if bench is not None:
        print(f"benchmark {bench.ticker}: {bench.last_date} {bench.last_close:,.0f}")
    return 0 if data else 1


def run_judge(cfg: AppConfig, as_of: date, source_kind: str) -> tuple[list[Judgement], date | None]:
    data, bench = _fetch_all(cfg, _source(cfg, source_kind, as_of))
    judgements: list[Judgement] = []
    data_date = None
    for s in cfg.stocks:
        if s.code not in data:
            continue
        md = data[s.code]
        data_date = md.last_date
        metrics = compute_price_metrics(md, s.annual_dividend_forecast, bench, cfg.settings.valuation_lookback_years)
        j = judge_stock(s, cfg.yutai.get(s.code), metrics, cfg.settings, as_of, holding=cfg.portfolio.holding_for(s.code))
        judgements.append(j)
    return judgements, data_date


def cmd_judge(args) -> int:
    cfg = load_config(args.config)
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    judgements, data_date = run_judge(cfg, as_of, args.source)
    if not judgements:
        print("判定できる銘柄がありません（データ取得に失敗）", file=sys.stderr)
        return 1
    report = render_report(judgements, cfg.settings, as_of, data_date)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report_{as_of:%Y%m%d}.md"
    path.write_text(report, encoding="utf-8")
    (out_dir / "latest.md").write_text(report, encoding="utf-8")
    print(report)
    if args.notify:
        sent = send_notifications(
            judgements, cfg.settings.notify, f"株式判定 {as_of:%Y-%m-%d}", report, out_dir / ".last_verdicts.json"
        )
        print(f"\n通知: {', '.join(sent) if sent else '変化なしのため送信せず'}", file=sys.stderr)
    print(f"\nレポート: {path}", file=sys.stderr)
    return 0


def cmd_income(args) -> int:
    """株価を使わず、設定だけで期間内の配当・優待を一覧する（設定確認用）。"""
    cfg = load_config(args.config)
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    for s in cfg.stocks:
        h = cfg.portfolio.holding_for(s.code)
        y = cfg.yutai.get(s.code)
        shares = h.shares if h else (y.min_shares if y else 100)
        print(f"\n## {s.code} {s.name}（{shares} 株）")
        for months in cfg.settings.horizons_months:
            inc = estimate_income(s, y, shares, as_of, months, cfg.settings.dividend_tax_rate, holding=h)
            print(f"- {months:>2}ヶ月: 配当 {inc.dividend_net:,.0f}円 + 優待 {inc.yutai_net:,.0f}円 = {inc.total_net:,.0f}円")
        inc = estimate_income(s, y, shares, as_of, max(cfg.settings.horizons_months), cfg.settings.dividend_tax_rate, holding=h)
        for ev in inc.events:
            flag = "" if ev.eligible else f"（対象外: {ev.reason}）"
            print(f"    {ev.record.nominal} 権利付き最終日 {ev.record.last_with_rights}: {ev.description} → {ev.net:,.0f}円{flag}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kabu", description="配当・優待・株価でトータルリターンを試算し売買判断を支援する")
    sub = p.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config", help="設定ディレクトリ（既定: config）")

    pj = sub.add_parser("judge", parents=[common], help="判定を実行しレポートを出力")
    pj.add_argument("--as-of", help="判定基準日 YYYY-MM-DD（既定: 今日）")
    pj.add_argument("--source", choices=["yfinance", "demo"], default="yfinance")
    pj.add_argument("--out", default="reports")
    pj.add_argument("--notify", action="store_true", help="settings.yaml の notify.channels に通知する")
    pj.set_defaults(func=cmd_judge)

    pf = sub.add_parser("fetch", parents=[common], help="株価データを取得してキャッシュ")
    pf.add_argument("--force", action="store_true")
    pf.set_defaults(func=cmd_fetch)

    pi = sub.add_parser("income", parents=[common], help="設定だけで配当・優待の受取予定を一覧")
    pi.add_argument("--as-of")
    pi.set_defaults(func=cmd_income)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
