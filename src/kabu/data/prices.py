"""株価・配当実績・簡易指標の取得層。

取得元（yfinance / 将来の J-Quants）を差し替えられるよう Protocol で抽象化し、
API を叩きすぎないようディスクキャッシュを挟む。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

import pandas as pd


@dataclass
class MarketData:
    ticker: str
    # index: 日付(Timestamp), columns: Open High Low Close Volume
    prices: pd.DataFrame
    # index: 権利落ち日, value: 1 株あたり配当（実績）
    dividends: pd.Series
    # yfinance の info から拾える範囲の指標（無ければ None）
    info: dict = field(default_factory=dict)

    @property
    def close(self) -> pd.Series:
        return self.prices["Close"].dropna()

    @property
    def last_close(self) -> float:
        return float(self.close.iloc[-1])

    @property
    def last_date(self) -> date:
        return self.close.index[-1].date()

    def trailing_annual_dividend(self, asof: pd.Timestamp | None = None) -> float:
        """直近 12 ヶ月の配当実績合計。"""
        if self.dividends.empty:
            return 0.0
        end = asof or self.close.index[-1]
        start = end - pd.DateOffset(years=1)
        return float(self.dividends[(self.dividends.index > start) & (self.dividends.index <= end)].sum())


class PriceSource(Protocol):
    def fetch(self, ticker: str, years: int) -> MarketData: ...


class YFinanceSource:
    """yfinance（非公式ライブラリ）経由。日本株は '7203.T' 形式。"""

    INFO_KEYS = (
        "trailingPE", "forwardPE", "priceToBook", "trailingEps", "forwardEps",
        "bookValue", "payoutRatio", "dividendRate", "marketCap", "shortName",
    )

    def fetch(self, ticker: str, years: int) -> MarketData:
        import yfinance as yf  # 遅延 import（テスト時に不要）

        t = yf.Ticker(ticker)
        hist = t.history(period=f"{years}y", auto_adjust=False, actions=True)
        if hist.empty:
            raise RuntimeError(f"{ticker}: 株価を取得できませんでした")
        hist.index = pd.to_datetime(hist.index).tz_localize(None)
        prices = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
        divs = hist["Dividends"][hist["Dividends"] > 0] if "Dividends" in hist else pd.Series(dtype=float)
        info: dict = {}
        try:
            raw = t.info or {}
            info = {k: raw.get(k) for k in self.INFO_KEYS if raw.get(k) is not None}
        except Exception:  # info は失敗しやすいので致命的扱いにしない
            info = {}
        return MarketData(ticker=ticker, prices=prices, dividends=divs, info=info)


class CachedSource:
    """ディスクキャッシュ付きラッパー。max_age_hours 以内なら再取得しない。"""

    def __init__(self, inner: PriceSource, cache_dir: str | Path, max_age_hours: float = 20):
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.max_age = max_age_hours * 3600

    def _paths(self, ticker: str) -> tuple[Path, Path, Path]:
        safe = ticker.replace("^", "_").replace("/", "_")
        d = self.cache_dir / safe
        return d / "prices.csv", d / "dividends.csv", d / "info.json"

    def fetch(self, ticker: str, years: int, force: bool = False) -> MarketData:
        p_prices, p_divs, p_info = self._paths(ticker)
        if not force and p_prices.exists() and time.time() - p_prices.stat().st_mtime < self.max_age:
            return self._load(ticker, p_prices, p_divs, p_info)
        data = self.inner.fetch(ticker, years)
        self._save(data, p_prices, p_divs, p_info)
        return data

    @staticmethod
    def _load(ticker: str, p_prices: Path, p_divs: Path, p_info: Path) -> MarketData:
        prices = pd.read_csv(p_prices, index_col=0, parse_dates=True)
        if p_divs.exists() and p_divs.stat().st_size > 0:
            d = pd.read_csv(p_divs, index_col=0, parse_dates=True)
            divs = d.iloc[:, 0] if not d.empty else pd.Series(dtype=float)
        else:
            divs = pd.Series(dtype=float)
        info = json.loads(p_info.read_text(encoding="utf-8")) if p_info.exists() else {}
        return MarketData(ticker=ticker, prices=prices, dividends=divs, info=info)

    @staticmethod
    def _save(data: MarketData, p_prices: Path, p_divs: Path, p_info: Path) -> None:
        p_prices.parent.mkdir(parents=True, exist_ok=True)
        data.prices.to_csv(p_prices)
        data.dividends.rename("Dividends").to_csv(p_divs)
        p_info.write_text(json.dumps(data.info, ensure_ascii=False, indent=1), encoding="utf-8")
