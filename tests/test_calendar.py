from datetime import date

from kabu.calendar import (
    add_business_days,
    add_months,
    is_business_day,
    next_record_date,
    record_date_for,
    record_dates_between,
)


def test_business_day_basics():
    assert is_business_day(date(2026, 11, 12))  # 木
    assert not is_business_day(date(2026, 11, 14))  # 土
    assert not is_business_day(date(2026, 11, 23))  # 勤労感謝の日
    assert not is_business_day(date(2026, 1, 2))  # 年始休業
    assert not is_business_day(date(2026, 12, 31))


def test_record_date_month_end_on_business_day():
    rd = record_date_for(2026, 3)
    # 2026/3/31 は火曜 → 権利付き最終日は 2 営業日前の 3/27(金)、権利落ち日 3/30(月)
    assert rd.effective == date(2026, 3, 31)
    assert rd.last_with_rights == date(2026, 3, 27)
    assert rd.ex_date == date(2026, 3, 30)


def test_record_date_month_end_on_weekend():
    # 2026/5/31 は日曜 → 実質基準日は 5/29(金)、権利付き最終日 5/27(水)
    rd = record_date_for(2026, 5)
    assert rd.effective == date(2026, 5, 29)
    assert rd.last_with_rights == date(2026, 5, 27)


def test_record_date_custom_day():
    rd = record_date_for(2026, 2, 20)
    assert rd.nominal == date(2026, 2, 20)
    assert rd.effective == date(2026, 2, 20)  # 金曜


def test_add_business_days_skips_holidays():
    # 2026/11/20(金) の 1 営業日後は 11/24(火)（11/23 は祝日）
    assert add_business_days(date(2026, 11, 20), 1) == date(2026, 11, 24)


def test_add_months_clamps_day():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 12), 6) == date(2027, 5, 12)


def test_record_dates_between_and_next():
    rds = record_dates_between(date(2026, 11, 12), date(2027, 11, 12), [3, 9])
    assert [r.nominal for r in rds] == [date(2027, 3, 31), date(2027, 9, 30)]
    nxt = next_record_date(date(2026, 3, 30), [3, 9])  # 権利落ち日 → 次は 9 月
    assert nxt.nominal == date(2026, 9, 30)
