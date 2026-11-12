from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from kabu.config.models import Portfolio, Settings, Stock, Yutai


@dataclass
class AppConfig:
    settings: Settings
    stocks: list[Stock]
    yutai: dict[str, Yutai]
    portfolio: Portfolio
    config_dir: Path

    def stock(self, code: str) -> Stock:
        for s in self.stocks:
            if s.code == code:
                return s
        raise KeyError(code)


def _read_yaml(path: Path):
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(config_dir: str | Path = "config") -> AppConfig:
    config_dir = Path(config_dir)
    settings = Settings.model_validate(_read_yaml(config_dir / "settings.yaml") or {})

    stocks_raw = _read_yaml(config_dir / "stocks.yaml") or []
    stocks = [Stock.model_validate(s) for s in stocks_raw]
    if len(stocks) > 5:
        raise ValueError("対象銘柄は最大 5 銘柄の想定です（stocks.yaml）")
    codes = [s.code for s in stocks]
    if len(codes) != len(set(codes)):
        raise ValueError("stocks.yaml に重複した証券コードがあります")

    yutai_raw = _read_yaml(config_dir / "yutai.yaml") or []
    yutai = {y.code: y for y in (Yutai.model_validate(y) for y in yutai_raw)}
    unknown = set(yutai) - set(codes)
    if unknown:
        raise ValueError(f"yutai.yaml に stocks.yaml にない銘柄があります: {sorted(unknown)}")

    portfolio = Portfolio.model_validate(_read_yaml(config_dir / "portfolio.yaml") or {})
    unknown = {h.code for h in portfolio.holdings} - set(codes)
    if unknown:
        raise ValueError(f"portfolio.yaml に stocks.yaml にない銘柄があります: {sorted(unknown)}")

    return AppConfig(settings=settings, stocks=stocks, yutai=yutai, portfolio=portfolio, config_dir=config_dir)
