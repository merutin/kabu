from datetime import date

from kabu.config.models import Holding, Settings, Stock, Yutai
from kabu.decision import Verdict, judge_stock
from kabu.price import compute_price_metrics
from tests.conftest import make_market_data


def _stock(**kw) -> Stock:
    base = dict(code="9999", name="テスト", dividend_per_record={3: 40, 9: 40})
    base.update(kw)
    return Stock.model_validate(base)


def _yutai(**kw) -> Yutai:
    base = dict(
        code="9999", record_months=[3, 9],
        tiers=[dict(min_shares=100, content="券", market_value=3000, personal_factor=1.0)],
    )
    base.update(kw)
    return Yutai.model_validate(base)


def test_cheap_high_income_stock_is_buy(as_of):
    # 横ばい・低ボラ・高配当・優待あり → BUY になりやすい
    data = make_market_data(annual_drift=0.0, annual_vol=0.10, seed=5, start_price=1500)
    m = compute_price_metrics(data, 80.0)
    j = judge_stock(_stock(), _yutai(), m, Settings(), as_of)
    assert j.shares == 100
    assert set(j.estimates) == {3, 6, 12}
    assert j.estimates[12].income.total_net == 80 * 100 + 3000 * 2
    assert j.verdict in {Verdict.BUY, Verdict.WAIT}
    assert any("期待トータルリターン" in r for r in j.reasons)
    assert j.timing_notes


def test_earnings_blackout_gives_wait(as_of):
    data = make_market_data(seed=5)
    m = compute_price_metrics(data, 80.0)
    j = judge_stock(_stock(earnings_dates=[date(2026, 11, 13)]), _yutai(), m, Settings(), as_of)
    assert j.verdict == Verdict.WAIT
    assert "決算" in j.reasons[0]


def test_holding_uses_holding_shares_and_hold_or_sell(as_of):
    data = make_market_data(seed=5)
    m = compute_price_metrics(data, 80.0)
    h = Holding(code="9999", shares=300, avg_cost=1000, first_bought_on=date(2026, 6, 1))
    j = judge_stock(_stock(), _yutai(holding_condition=dict(min_years=1)), m, Settings(), as_of, holding=h)
    assert j.shares == 300
    assert j.verdict in {Verdict.HOLD, Verdict.SELL}
    assert any("評価損益" in r for r in j.reasons)
    if j.verdict == Verdict.SELL:
        assert any("リセット" in w for w in j.warnings)


def test_downtrend_blocks_buy(as_of):
    data = make_market_data(annual_drift=-0.6, annual_vol=0.05, seed=2)
    m = compute_price_metrics(data, 10.0)
    assert m.trend_label == "下降"
    j = judge_stock(_stock(dividend_per_record={3: 5, 9: 5}), None, m, Settings(), as_of)
    assert j.verdict == Verdict.WAIT


def test_taxable_account_reduces_dividend(as_of):
    data = make_market_data(seed=5)
    m = compute_price_metrics(data, 80.0)
    nisa = judge_stock(_stock(), None, m, Settings(account="nisa"), as_of)
    tax = judge_stock(_stock(), None, m, Settings(account="taxable"), as_of)
    assert tax.estimates[12].income.dividend_net < nisa.estimates[12].income.dividend_net
