"""東証の営業日と権利確定日まわりの日付計算。

- 権利確定日（基準日）が休日なら、株主名簿は直前営業日時点で確定する扱いにする
- 権利付き最終日 = 権利確定日（営業日調整後）の 2 営業日前（T+2 決済）
- 権利落ち日   = 権利確定日（営業日調整後）の 1 営業日前
"""

from __future__ import annotations

import calendar as _cal
from dataclasses import dataclass
from datetime import date, timedelta

import jpholiday


def is_business_day(d: date) -> bool:
    """東証の営業日か。土日・祝日・年末年始（12/31〜1/3）は休業。"""
    if d.weekday() >= 5:
        return False
    if (d.month == 12 and d.day == 31) or (d.month == 1 and d.day <= 3):
        return False
    return not jpholiday.is_holiday(d)


def prev_business_day(d: date, include_self: bool = True) -> date:
    if not include_self:
        d -= timedelta(days=1)
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def next_business_day(d: date, include_self: bool = True) -> date:
    if not include_self:
        d += timedelta(days=1)
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def add_business_days(d: date, n: int) -> date:
    """d から n 営業日後（n<0 なら前）。d 自身は数えない。"""
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    while remaining > 0:
        d += timedelta(days=step)
        if is_business_day(d):
            remaining -= 1
    return d


def month_end(year: int, month: int) -> date:
    return date(year, month, _cal.monthrange(year, month)[1])


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    last = _cal.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


@dataclass(frozen=True)
class RecordDate:
    """1 回分の権利確定日と関連日。"""

    nominal: date  # 名目上の基準日（例: 3/31）
    effective: date  # 営業日調整後の基準日
    last_with_rights: date  # 権利付き最終日
    ex_date: date  # 権利落ち日

    @property
    def month(self) -> int:
        return self.nominal.month


def record_date_for(year: int, month: int, day: int | None = None) -> RecordDate:
    nominal = month_end(year, month) if day is None else date(year, month, day)
    effective = prev_business_day(nominal)
    return RecordDate(
        nominal=nominal,
        effective=effective,
        last_with_rights=add_business_days(effective, -2),
        ex_date=add_business_days(effective, -1),
    )


def record_dates_between(
    start: date, end: date, months: list[int], day: int | None = None
) -> list[RecordDate]:
    """start <= 名目基準日 <= end の権利確定日を昇順で返す。"""
    out: list[RecordDate] = []
    for y in range(start.year - 1, end.year + 2):
        for m in months:
            rd = record_date_for(y, m, day)
            if start <= rd.nominal <= end:
                out.append(rd)
    return sorted(out, key=lambda r: r.nominal)


def next_record_date(after: date, months: list[int], day: int | None = None) -> RecordDate:
    """after より後（権利付き最終日 >= after）で最初の権利確定日。"""
    for rd in record_dates_between(after, add_months(after, 13), months, day):
        if rd.last_with_rights >= after:
            return rd
    raise ValueError("権利確定日が見つかりません")
