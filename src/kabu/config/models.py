"""設定ファイル（YAML）のスキーマ定義。

人が編集するファイルなので、pydantic で読み込み時に検証し、
間違いは実行前に気付けるようにする。
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class AccountType(str, Enum):
    NISA = "nisa"
    TAXABLE = "taxable"


# 配当・売却益にかかる税率（所得税 15% + 復興特別所得税 0.315% + 住民税 5%）
TAX_RATE_TAXABLE = 0.20315


class Settings(BaseModel):
    """全体設定（config/settings.yaml）。"""

    account: AccountType = AccountType.NISA
    # 判定に使う保有期間（月）。primary のものを最終判定に使う。
    horizons_months: list[int] = Field(default=[3, 6, 12])
    primary_horizons_months: list[int] = Field(default=[6, 12])
    # BUY と判断する年率期待トータルリターンの下限（例: 0.05 = 5%）
    buy_threshold_annual: float = 0.05
    # 株価部分の基礎期待リターン（年率、配当込みの市場平均を控えめに見た値）
    base_return_annual: float = 0.03
    # 割安度・トレンドが株価期待リターンに与える補正の上限（年率）
    valuation_max_adj_annual: float = 0.06
    trend_max_adj_annual: float = 0.04
    # 割安度の評価に使う過去期間（年）
    valuation_lookback_years: int = 5
    # 決算発表の前後この日数以内は新規買いを WAIT にする
    earnings_blackout_days: int = 3
    # 権利付き最終日までこの日数以内なら「権利取り直前」として注記する
    record_notice_days: int = 14
    # 売買コスト（片道、約定代金に対する比率）。NISA でも証券会社により 0 でない場合がある
    commission_rate: float = 0.0
    # ベンチマーク（yfinance ティッカー）。TOPIX 連動 ETF を既定にする
    benchmark_ticker: str = "1306.T"
    # データキャッシュ
    cache_dir: str = "data/cache"
    cache_max_age_hours: int = 20
    # 通知
    notify: NotifySettings = Field(default_factory=lambda: NotifySettings())

    @property
    def dividend_tax_rate(self) -> float:
        return 0.0 if self.account == AccountType.NISA else TAX_RATE_TAXABLE

    @model_validator(mode="after")
    def _check_horizons(self) -> "Settings":
        missing = [h for h in self.primary_horizons_months if h not in self.horizons_months]
        if missing:
            raise ValueError(f"primary_horizons_months {missing} は horizons_months に含めてください")
        return self


class NotifySettings(BaseModel):
    """通知先。実際の URL やパスワードは環境変数で渡す（YAML に書かない）。"""

    # webhook: Slack / Discord の Incoming Webhook。URL は env KABU_WEBHOOK_URL
    # email:   SMTP 送信。env KABU_SMTP_HOST / KABU_SMTP_PORT / KABU_SMTP_USER /
    #          KABU_SMTP_PASSWORD / KABU_MAIL_TO
    channels: list[Literal["webhook", "email", "stdout"]] = Field(default=["stdout"])
    webhook_format: Literal["slack", "discord"] = "slack"
    # 判定が前回から変わったときだけ通知する（False なら毎回通知）
    only_on_change: bool = False


class Stock(BaseModel):
    """対象銘柄マスタ（config/stocks.yaml）。"""

    code: str = Field(pattern=r"^[0-9][0-9A-Z][0-9][0-9A-Z]$", description="4桁の証券コード")
    name: str
    # 配当の権利確定月と、その回ごとの 1 株あたり予想配当（円）。
    # 例: {3: 25, 9: 25}。会社予想を IR で確認して手で更新する。
    dividend_per_record: dict[int, float] = Field(default_factory=dict)
    # 上記のうち一時的な配当（特別配当・記念配当）の年間合計（円）。
    # インカムには含めるが、割安度（配当利回りの過去比較）からは除く
    non_recurring_dividend: float = Field(default=0, ge=0)
    # 権利確定日。null なら月末、整数なら「その日」（20 日決算の会社など）
    record_day: int | None = None
    # 決算発表予定日（分かっている範囲で）。直前の新規買いを避けるため
    earnings_dates: list[date] = Field(default_factory=list)
    # yfinance 用ティッカー。省略時は "{code}.T"
    ticker: str | None = None
    notes: str = ""

    @property
    def yf_ticker(self) -> str:
        return self.ticker or f"{self.code}.T"

    @property
    def annual_dividend_forecast(self) -> float:
        return float(sum(self.dividend_per_record.values()))

    @property
    def recurring_dividend_forecast(self) -> float:
        """特別配当などを除いた、来期以降も見込める年間配当。割安度の判定に使う。"""
        return max(0.0, self.annual_dividend_forecast - self.non_recurring_dividend)

    @field_validator("dividend_per_record")
    @classmethod
    def _check_months(cls, v: dict[int, float]) -> dict[int, float]:
        for m, amt in v.items():
            if not 1 <= m <= 12:
                raise ValueError(f"権利確定月が不正です: {m}")
            if amt < 0:
                raise ValueError(f"配当額が負です: {amt}")
        return v


class HoldingCondition(BaseModel):
    """優待の継続保有条件。"""

    # 「○年以上継続保有」
    min_years: float = 0
    # 「同一株主番号で○回連続記載」。優待の権利確定日ベースで数える
    consecutive_records: int = 0

    @property
    def is_none(self) -> bool:
        return self.min_years <= 0 and self.consecutive_records <= 0


class YutaiTier(BaseModel):
    min_shares: int = Field(gt=0)
    content: str
    # 市場換算額（円）。金券ならほぼ額面、割引券なら換金相場の目安
    market_value: float = Field(default=0, ge=0)
    # 買物額に対する還元率（イオンのオーナーズカードなど）。指定時は
    # Yutai.assumed_spend_per_record × rate を市場換算額として使う
    rate: float | None = Field(default=None, ge=0)
    # 自分にとっての価値係数。使わない優待なら 0、確実に使うなら 1.0
    personal_factor: float = Field(default=1.0, ge=0, le=1.5)
    # この段階に必要な連続記載回数（トヨタの「1 年以上 = 3 回連続」など）。0 なら条件なし
    min_consecutive_records: int = Field(default=0, ge=0)

    def value_for(self, spend: float | None) -> float:
        if self.rate is not None and spend is not None:
            return spend * self.rate
        return self.market_value

    def personal_value_for(self, spend: float | None) -> float:
        return self.value_for(spend) * self.personal_factor


class Yutai(BaseModel):
    """株主優待（config/yutai.yaml）。1 銘柄 1 エントリ。"""

    code: str
    record_months: list[int]
    record_day: int | None = None
    tiers: list[YutaiTier]
    holding_condition: HoldingCondition = Field(default_factory=HoldingCondition)
    # 連続記載回数を数える基準月。省略時は record_months。
    # 例: トヨタは優待の基準日は 3 月末だけだが、継続保有は 3 月末と 9 月末の名簿で数える
    holding_check_months: list[int] | None = None
    # True なら「最初に名簿に載った基準日の月」にしか進呈しない（年 1 回）。
    # 例: ソフトバンクは 3 月末 or 9 月末のうち保有開始後に先に来た方を起点に年 1 回
    anniversary_only: bool = False
    # rate 指定の段階で使う、1 回（半年など）あたりの想定利用額（円）
    assumed_spend_per_record: float | None = Field(default=None, ge=0)
    # 長期保有で優待が増額される場合など、補足を書く
    notes: str = ""

    @field_validator("record_months")
    @classmethod
    def _check_months(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("record_months は 1 つ以上必要です")
        for m in v:
            if not 1 <= m <= 12:
                raise ValueError(f"権利確定月が不正です: {m}")
        return sorted(set(v))

    @model_validator(mode="after")
    def _sort_tiers(self) -> "Yutai":
        self.tiers = sorted(self.tiers, key=lambda t: (t.min_shares, t.min_consecutive_records))
        if self.holding_check_months is not None:
            self.holding_check_months = sorted(set(self.holding_check_months))
        return self

    @property
    def check_months(self) -> list[int]:
        return self.holding_check_months or self.record_months

    def tier_for(self, shares: int, consecutive_records: int | None = None) -> YutaiTier | None:
        """保有株数（と連続記載回数）を満たす段階のうち、価値が最大のもの。

        consecutive_records が None なら回数条件を無視する（株数条件だけで判定）。
        """
        matched = [
            t
            for t in self.tiers
            if shares >= t.min_shares
            and (consecutive_records is None or consecutive_records >= t.min_consecutive_records)
        ]
        if not matched:
            return None
        return max(matched, key=lambda t: (t.personal_value_for(self.assumed_spend_per_record), t.min_shares))

    @property
    def min_shares(self) -> int:
        return self.tiers[0].min_shares


class Holding(BaseModel):
    code: str
    shares: int = Field(gt=0)
    avg_cost: float = Field(gt=0, description="取得単価（円）")
    # 継続保有判定に使う。株主番号が途切れていない最初の取得日
    first_bought_on: date


class Portfolio(BaseModel):
    """保有状況（config/portfolio.yaml）。"""

    cash: float = 0
    holdings: list[Holding] = Field(default_factory=list)

    def holding_for(self, code: str) -> Holding | None:
        for h in self.holdings:
            if h.code == code:
                return h
        return None
