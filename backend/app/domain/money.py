"""Money value object.

Financial rule (spec §4, §13): never use floating-point arithmetic for money.
All monetary values are represented as integer *minor units* (e.g. paise for INR,
cents for USD) internally, and exposed as :class:`decimal.Decimal` with explicit
currency precision. This makes every amount exact, comparable, and serialisable
without rounding surprises.

Design notes
------------
* Internally we store an integer count of minor units. Integer arithmetic is
  exact, so addition/subtraction never introduces error.
* Currency precision (number of decimal places) comes from a small ISO-4217
  table. INR, USD, EUR etc. use 2 places; JPY uses 0; some currencies use 3.
* Operations between different currencies raise ``CurrencyMismatch`` — you can
  never accidentally add rupees to dollars.
* Rounding is explicit and only ever applied when converting a ratio/percentage
  result back into money, using banker's rounding (ROUND_HALF_EVEN) by default,
  which is the least-biased choice for repeated financial calculations.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
from typing import Dict, Iterable

# ISO-4217 minor-unit exponents for currencies we support. Extend as needed.
# The exponent is the number of digits after the decimal point.
_CURRENCY_EXPONENTS: Dict[str, int] = {
    "INR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "AED": 2,
    "SGD": 2,
    "JPY": 0,
    "KWD": 3,
    "BHD": 3,
}


class MoneyError(Exception):
    """Base class for all money-related errors."""


class UnknownCurrency(MoneyError):
    """Raised when a currency code is not in the supported ISO-4217 table."""


class CurrencyMismatch(MoneyError):
    """Raised when an operation mixes two different currencies."""


def _normalise_currency(code: str) -> str:
    code = code.strip().upper()
    if code not in _CURRENCY_EXPONENTS:
        raise UnknownCurrency(
            f"Unsupported currency {code!r}. Known: {sorted(_CURRENCY_EXPONENTS)}"
        )
    return code


@dataclass(frozen=True, slots=True)
class Money:
    """An exact, immutable monetary amount in a single currency.

    Stored as an integer number of minor units plus an ISO-4217 code. Frozen so
    that it can be used as a dict key and is safe to share across the codebase.
    """

    minor_units: int
    currency: str

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    def __post_init__(self) -> None:
        if not isinstance(self.minor_units, int):
            raise MoneyError("minor_units must be an int")
        object.__setattr__(self, "currency", _normalise_currency(self.currency))

    @classmethod
    def exponent_of(cls, currency: str) -> int:
        return _CURRENCY_EXPONENTS[_normalise_currency(currency)]

    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(0, currency)

    @classmethod
    def from_decimal(
        cls, amount: Decimal | str | int, currency: str, *, rounding: str = ROUND_HALF_EVEN
    ) -> "Money":
        """Build Money from a human-facing decimal amount (e.g. ``"1234.50"``).

        The amount is quantised to the currency's precision using ``rounding``.
        We accept ``str``/``int`` directly and convert; we deliberately do *not*
        accept ``float`` to avoid silent binary-float contamination.
        """
        if isinstance(amount, float):  # pragma: no cover - guard rail
            raise MoneyError(
                "Refusing to build Money from float; pass a str or Decimal instead"
            )
        exponent = cls.exponent_of(currency)
        dec = Decimal(amount) if not isinstance(amount, Decimal) else amount
        quant = Decimal(1).scaleb(-exponent)  # e.g. Decimal('0.01')
        scaled = (dec / quant).quantize(Decimal(1), rounding=rounding)
        return cls(int(scaled), currency)

    # ------------------------------------------------------------------ #
    # Conversion / display
    # ------------------------------------------------------------------ #
    @property
    def amount(self) -> Decimal:
        """The value as a Decimal at the currency's native precision."""
        exponent = self.exponent_of(self.currency)
        quant = Decimal(1).scaleb(-exponent)
        return (Decimal(self.minor_units) * quant).quantize(quant)

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    def __repr__(self) -> str:
        return f"Money('{self.amount}', '{self.currency}')"

    # ------------------------------------------------------------------ #
    # Arithmetic (exact integer math on minor units)
    # ------------------------------------------------------------------ #
    def _check(self, other: "Money") -> None:
        if not isinstance(other, Money):
            raise MoneyError(f"Expected Money, got {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(
                f"Cannot combine {self.currency} with {other.currency}"
            )

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.minor_units + other.minor_units, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.minor_units - other.minor_units, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.minor_units, self.currency)

    def multiply_ratio(
        self, ratio: Decimal | str, *, rounding: str = ROUND_HALF_EVEN
    ) -> "Money":
        """Multiply by a dimensionless ratio (e.g. a tax or penalty rate).

        Rounding is applied once, explicitly, to return whole minor units.
        """
        r = Decimal(ratio) if not isinstance(ratio, Decimal) else ratio
        result = (Decimal(self.minor_units) * r).quantize(Decimal(1), rounding=rounding)
        return Money(int(result), self.currency)

    # ------------------------------------------------------------------ #
    # Comparisons
    # ------------------------------------------------------------------ #
    def __lt__(self, other: "Money") -> bool:
        self._check(other)
        return self.minor_units < other.minor_units

    def __le__(self, other: "Money") -> bool:
        self._check(other)
        return self.minor_units <= other.minor_units

    def __gt__(self, other: "Money") -> bool:
        self._check(other)
        return self.minor_units > other.minor_units

    def __ge__(self, other: "Money") -> bool:
        self._check(other)
        return self.minor_units >= other.minor_units

    @property
    def is_zero(self) -> bool:
        return self.minor_units == 0

    @property
    def is_negative(self) -> bool:
        return self.minor_units < 0

    @property
    def is_positive(self) -> bool:
        return self.minor_units > 0

    def abs(self) -> "Money":
        return Money(abs(self.minor_units), self.currency)


def money_sum(items: Iterable[Money], currency: str) -> Money:
    """Sum an iterable of Money, starting from zero in ``currency``.

    Requiring an explicit currency means summing an empty iterable still yields a
    well-typed zero rather than an ambiguous bare ``0``.
    """
    total = Money.zero(currency)
    for item in items:
        total = total + item
    return total
