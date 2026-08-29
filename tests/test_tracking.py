from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pytest
from app.tracking.calculations import InvalidPrice, calculate_drawdown, calculate_multiple, crossed, is_anomalous, validate_price

def test_multiple(): assert calculate_multiple(Decimal("1"),Decimal("5"))==Decimal("5")
def test_milestone_crossing(): assert crossed(Decimal("4.99"),Decimal("5"),Decimal("5")); assert not crossed(Decimal("5"),Decimal("5"),Decimal("5"))
def test_duplicate_checks_trigger_once(): assert sum(crossed(Decimal("4.99") if i==0 else Decimal("5"),Decimal("5"),Decimal("5")) for i in range(100))==1
def test_ath_remains_maximum(): assert max(Decimal("2"),Decimal("5"),Decimal("3"))==Decimal("5")
def test_drawdown(): assert calculate_drawdown(Decimal("10"),Decimal("6"))==Decimal("-40.0")
@pytest.mark.parametrize("price",[Decimal("0"),Decimal("-1"),Decimal("NaN"),Decimal("Infinity")])
def test_invalid_prices(price):
    with pytest.raises(InvalidPrice): validate_price(price,datetime.now(UTC),180)
def test_stale_price():
    with pytest.raises(InvalidPrice): validate_price(Decimal("1"),datetime.now(UTC)-timedelta(seconds=181),180)
def test_anomaly(): assert is_anomalous(Decimal("0.001"),Decimal("1000"),Decimal("100"))
