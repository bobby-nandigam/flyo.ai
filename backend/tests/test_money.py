"""Tests for the Money value object: exactness, currency safety, no floats."""
from decimal import Decimal

import pytest

from app.domain.money import (
    Money,
    CurrencyMismatch,
    UnknownCurrency,
    MoneyError,
    money_sum,
)


def test_from_decimal_is_exact_for_inr():
    m = Money.from_decimal("1234.56", "INR")
    assert m.minor_units == 123456
    assert m.amount == Decimal("1234.56")
    assert str(m) == "1234.56 INR"


def test_zero_decimal_currency_jpy():
    m = Money.from_decimal("1500", "JPY")
    assert m.minor_units == 1500
    assert Money.exponent_of("JPY") == 0
    assert m.amount == Decimal("1500")


def test_three_decimal_currency_kwd():
    m = Money.from_decimal("12.345", "KWD")
    assert m.minor_units == 12345
    assert m.amount == Decimal("12.345")


def test_addition_is_exact_no_float_drift():
    # 0.1 + 0.2 is the classic float trap; with Decimal/int it is exact.
    a = Money.from_decimal("0.10", "INR")
    b = Money.from_decimal("0.20", "INR")
    assert (a + b).amount == Decimal("0.30")
    assert (a + b).minor_units == 30


def test_repeated_addition_stays_exact():
    total = Money.zero("INR")
    one_paisa = Money.from_decimal("0.01", "INR")
    for _ in range(1000):
        total = total + one_paisa
    assert total.amount == Decimal("10.00")
    assert total.minor_units == 1000


def test_rejects_float_construction():
    with pytest.raises(MoneyError):
        Money.from_decimal(1234.56, "INR")  # type: ignore[arg-type]


def test_currency_mismatch_raises():
    inr = Money.from_decimal("100", "INR")
    usd = Money.from_decimal("100", "USD")
    with pytest.raises(CurrencyMismatch):
        _ = inr + usd
    with pytest.raises(CurrencyMismatch):
        _ = inr < usd


def test_unknown_currency_raises():
    with pytest.raises(UnknownCurrency):
        Money.zero("XYZ")


def test_multiply_ratio_banker_rounding():
    # 5% GST on 1000.00 INR -> 50.00
    base = Money.from_decimal("1000.00", "INR")
    assert base.multiply_ratio("0.05").amount == Decimal("50.00")
    # Half-even rounding: 0.125 -> 0.12 (rounds to even)
    small = Money.from_decimal("2.50", "INR")
    assert small.multiply_ratio("0.05").amount == Decimal("0.12")


def test_money_sum_empty_is_typed_zero():
    assert money_sum([], "INR") == Money.zero("INR")


def test_frozen_and_hashable():
    m = Money.from_decimal("10", "INR")
    with pytest.raises(Exception):
        m.minor_units = 5  # type: ignore[misc]
    assert {m: 1}[m] == 1  # usable as dict key
