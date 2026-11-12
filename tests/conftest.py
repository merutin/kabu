from datetime import date

import pytest

from kabu.data.demo import make_market_data  # noqa: F401  (tests import from here)
from kabu.data.prices import MarketData


@pytest.fixture
def market_data() -> MarketData:
    return make_market_data()


@pytest.fixture
def as_of() -> date:
    return date(2026, 11, 12)
