from datetime import date

from kabu.config.models import Holding, HoldingCondition, Stock, Yutai, YutaiTier
from kabu.income import estimate_income


def make_stock(**kw) -> Stock:
    base = dict(code="9999", name="テスト", dividend_per_record={3: 20, 9: 10})
    base.update(kw)
    return Stock.model_validate(base)


def make_yutai(**kw) -> Yutai:
    base = dict(
        code="9999",
        record_months=[3, 9],
        tiers=[
            dict(min_shares=100, content="商品券1000円", market_value=1000, personal_factor=0.5),
            dict(min_shares=500, content="商品券3000円", market_value=3000, personal_factor=0.5),
        ],
    )
    base.update(kw)
    return Yutai.model_validate(base)


def test_new_buy_counts_records_within_horizon():
    s = estimate_income(make_stock(), make_yutai(), 100, date(2026, 11, 12), 6, 0.0)
    # 6 ヶ月（〜2027/5/12）に入る権利確定は 2027/3 のみ
    assert [e.record.month for e in s.events] == [3, 3]
    assert s.dividend_net == 20 * 100
    assert s.yutai_net == 1000 * 0.5
    assert s.total_net == 2500


def test_new_buy_after_last_with_rights_excludes_that_record():
    # 2026/3/30 は権利落ち日。3 月の権利は取れない
    s = estimate_income(make_stock(), None, 100, date(2026, 3, 30), 3, 0.0)
    assert s.events == []
    s2 = estimate_income(make_stock(), None, 100, date(2026, 3, 27), 3, 0.0)
    assert [e.record.month for e in s2.events] == [3]


def test_tax_applied_to_dividends_only():
    s = estimate_income(make_stock(), make_yutai(), 100, date(2026, 11, 12), 12, 0.20315)
    assert round(s.dividend_net, 2) == round((20 + 10) * 100 * (1 - 0.20315), 2)
    assert s.yutai_net == 1000  # 2 回 × 500


def test_yutai_tier_by_shares_and_below_minimum():
    y = make_yutai()
    s = estimate_income(make_stock(), y, 500, date(2026, 11, 12), 6, 0.0)
    assert s.yutai_net == 1500
    s = estimate_income(make_stock(), y, 50, date(2026, 11, 12), 6, 0.0)
    assert s.yutai_net == 0
    assert any("必要株数" in e.reason for e in s.ineligible)


def test_min_years_condition_blocks_short_holding():
    y = make_yutai(holding_condition=dict(min_years=1))
    # 新規買いで 6 ヶ月保有 → 1 年条件を満たさない
    s = estimate_income(make_stock(), y, 100, date(2026, 11, 12), 6, 0.0)
    assert s.yutai_net == 0
    assert "継続保有" in s.ineligible[0].reason
    # 2025/1 から保有中なら 2027/3 は満たす
    h = Holding(code="9999", shares=100, avg_cost=1000, first_bought_on=date(2025, 1, 10))
    s = estimate_income(make_stock(), y, 100, date(2026, 11, 12), 6, 0.0, holding=h)
    assert s.yutai_net == 500


def test_consecutive_records_condition():
    y = make_yutai(holding_condition=dict(consecutive_records=3))
    # 2026/2 取得 → 2026/3, 2026/9, 2027/3 で 3 回目
    h = Holding(code="9999", shares=100, avg_cost=1000, first_bought_on=date(2026, 2, 1))
    s = estimate_income(make_stock(), y, 100, date(2026, 11, 12), 12, 0.0, holding=h)
    months = [(e.record.nominal, e.eligible) for e in s.events if e.kind == "yutai"]
    assert months == [(date(2027, 3, 31), True), (date(2027, 9, 30), True)]
    # 2026/4 取得なら 2027/3 は 2 回目で不適格、2027/9 で適格
    h2 = Holding(code="9999", shares=100, avg_cost=1000, first_bought_on=date(2026, 4, 1))
    s2 = estimate_income(make_stock(), y, 100, date(2026, 11, 12), 12, 0.0, holding=h2)
    months2 = [(e.record.nominal, e.eligible) for e in s2.events if e.kind == "yutai"]
    assert months2 == [(date(2027, 3, 31), False), (date(2027, 9, 30), True)]


def test_toyota_style_tiers_by_consecutive_records():
    # 3 月末のみ基準日、継続保有は 3 月末・9 月末の名簿で数える。1 年未満 500 / 3 回以上 1000 / 7 回以上 3000
    y = Yutai.model_validate(
        dict(
            code="9999", record_months=[3], holding_check_months=[3, 9],
            tiers=[
                dict(min_shares=100, content="500円", market_value=500),
                dict(min_shares=100, content="1000円", market_value=1000, min_consecutive_records=3),
                dict(min_shares=100, content="3000円", market_value=3000, min_consecutive_records=7),
            ],
        )
    )
    stock = make_stock(dividend_per_record={})
    # 新規買い（2026/11）→ 2027/3 は 1 回目 → 500 円
    s = estimate_income(stock, y, 100, date(2026, 11, 13), 12, 0.0)
    assert [(e.record.nominal, e.net, e.eligible) for e in s.events] == [(date(2027, 3, 31), 500.0, True)]
    # 2026/2 から保有 → 2027/3 時点で 3/26, 9/26, 3/27 の 3 回 → 1000 円
    h = Holding(code="9999", shares=100, avg_cost=1000, first_bought_on=date(2026, 2, 1))
    s = estimate_income(stock, y, 100, date(2026, 11, 13), 12, 0.0, holding=h)
    assert s.events[0].net == 1000.0
    # 2023/1 から保有 → 2027/3 時点で 9 回 → 3000 円
    h = Holding(code="9999", shares=100, avg_cost=1000, first_bought_on=date(2023, 1, 1))
    s = estimate_income(stock, y, 100, date(2026, 11, 13), 12, 0.0, holding=h)
    assert s.events[0].net == 3000.0


def test_softbank_style_anniversary_once_a_year():
    y = Yutai.model_validate(
        dict(
            code="9999", record_months=[3, 9], anniversary_only=True,
            tiers=[dict(min_shares=100, content="PayPay 1000円", market_value=1000)],
            holding_condition=dict(consecutive_records=3),
        )
    )
    stock = make_stock(dividend_per_record={})
    # 2026/3/20 に取得（3 月の権利付き最終日前）→ 起点 2026/3 → 2027/3 に初回、2027/9 は対象外
    h = Holding(code="9999", shares=100, avg_cost=100, first_bought_on=date(2026, 3, 20))
    s = estimate_income(stock, y, 100, date(2026, 11, 13), 12, 0.0, holding=h)
    got = [(e.record.nominal, e.eligible) for e in s.events]
    assert got == [(date(2027, 3, 31), True), (date(2027, 9, 30), False)]
    assert s.yutai_net == 1000
    # 新規買い（2026/11）→ 起点 2027/3 → 2028/3 まで受け取れない
    s = estimate_income(stock, y, 100, date(2026, 11, 13), 12, 0.0)
    assert s.yutai_net == 0
    assert all(not e.eligible for e in s.events)


def test_rate_based_value_uses_assumed_spend():
    y = Yutai.model_validate(
        dict(
            code="9999", record_months=[2, 8], assumed_spend_per_record=150000,
            tiers=[
                dict(min_shares=100, content="1%還元", rate=0.01),
                dict(min_shares=300, content="3%還元", rate=0.03),
            ],
        )
    )
    stock = make_stock(dividend_per_record={})
    s = estimate_income(stock, y, 100, date(2026, 11, 13), 12, 0.0)
    assert s.yutai_net == 1500 * 2
    s = estimate_income(stock, y, 300, date(2026, 11, 13), 12, 0.0)
    assert s.yutai_net == 4500 * 2


def test_dividend_overrides_apply_to_specific_record_only():
    s = make_stock(dividend_per_record={6: 0, 12: 93}, dividend_overrides={"2026-12": 167})
    assert s.recurring_dividend_forecast == 93
    inc = estimate_income(s, None, 100, date(2026, 11, 13), 14, 0.0)
    got = {(e.record.nominal.year, e.record.month): e.gross for e in inc.events}
    assert got[(2026, 12)] == 16700
    assert got[(2027, 6)] == 0
    assert got[(2027, 12)] == 9300
