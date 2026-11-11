"""Deterministic refund calculation engine (spec Module D).

This is the financial core. It is a *pure* module: given the same inputs it
always produces the same output, with no I/O, no clock, no randomness, no LLM.
Every expected-refund figure the platform shows is produced here and can be
re-derived and audited line by line.

The spec's formula (§Module D):

    Original amount
      - Valid cancellation deductions
      - Applicable non-refundable charges
      + Eligible refundable taxes and components
      = Expected supplier refund

Customer refund is computed *separately* (§Module D: "Keep customer refund
calculations separate from supplier refund calculations") and is derived from
what the agency actually owes the customer, net of agency service fees and
payment-gateway fees that the agency is entitled to retain per contract.

Nothing here invents amounts: callers pass concrete line items taken from
documents, policies and transactions. The engine only arranges and sums them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import List, Sequence

from .money import Money, money_sum


class LineKind(str, Enum):
    """What a line item does to the running total."""

    ORIGINAL = "ORIGINAL"                    # the base amount paid for the component
    CANCELLATION_DEDUCTION = "CANCELLATION_DEDUCTION"  # penalty withheld by supplier
    NON_REFUNDABLE = "NON_REFUNDABLE"        # component that is never returned
    REFUNDABLE_TAX = "REFUNDABLE_TAX"        # tax/component that IS returned
    GATEWAY_FEE = "GATEWAY_FEE"              # payment-gateway fee (customer side)
    AGENCY_SERVICE_FEE = "AGENCY_SERVICE_FEE"  # agency's own fee (customer side)


# Sign that each kind contributes to a refund total (+1 adds, -1 subtracts).
_SIGN = {
    LineKind.ORIGINAL: +1,
    LineKind.REFUNDABLE_TAX: +1,
    LineKind.CANCELLATION_DEDUCTION: -1,
    LineKind.NON_REFUNDABLE: -1,
    LineKind.GATEWAY_FEE: -1,
    LineKind.AGENCY_SERVICE_FEE: -1,
}


@dataclass(frozen=True, slots=True)
class LineItem:
    """One auditable component of a calculation.

    ``evidence_ref`` ties the line to its source (a policy version, a document
    extraction, a transaction id). The spec requires every figure to be
    traceable; an engine result with an unsourced line is a bug, not a feature.
    """

    kind: LineKind
    label: str
    amount: Money            # always a non-negative magnitude; sign comes from kind
    evidence_ref: str | None = None

    def signed(self) -> Money:
        amt = self.amount.abs()
        return amt if _SIGN[self.kind] > 0 else -amt


@dataclass(frozen=True, slots=True)
class RefundBreakdown:
    """Immutable, itemised result of a refund calculation."""

    currency: str
    scope: str                      # "supplier" or "customer"
    lines: Sequence[LineItem]
    total: Money
    clamped: bool = False           # True if a negative raw total was floored to zero

    def to_audit_dict(self) -> dict:
        """A plain, serialisable representation for the audit log / API."""
        return {
            "scope": self.scope,
            "currency": self.currency,
            "total": str(self.total.amount),
            "clamped": self.clamped,
            "lines": [
                {
                    "kind": li.kind.value,
                    "label": li.label,
                    "amount": str(li.amount.amount),
                    "signed": str(li.signed().amount),
                    "evidence_ref": li.evidence_ref,
                }
                for li in self.lines
            ],
        }


class CalculationError(Exception):
    """Raised when inputs to the engine are inconsistent."""


def _sum_lines(lines: Sequence[LineItem], currency: str) -> Money:
    return money_sum((li.signed() for li in lines), currency)


def _validate(lines: Sequence[LineItem], currency: str) -> None:
    if not lines:
        raise CalculationError("A calculation needs at least one line item")
    for li in lines:
        if li.amount.currency != currency:
            raise CalculationError(
                f"Line {li.label!r} is in {li.amount.currency}, expected {currency}"
            )
        if li.amount.is_negative:
            raise CalculationError(
                f"Line {li.label!r} amount must be a non-negative magnitude; "
                "direction is expressed by its kind"
            )


def compute_supplier_refund(
    lines: Sequence[LineItem], currency: str, *, allow_negative: bool = False
) -> RefundBreakdown:
    """Expected refund owed by a *supplier* for a cancelled component.

    Uses only supplier-side kinds. Gateway/agency fees are rejected here because
    they belong to the customer-side calculation, keeping the two tracks clean.
    """
    _validate(lines, currency)
    for li in lines:
        if li.kind in (LineKind.GATEWAY_FEE, LineKind.AGENCY_SERVICE_FEE):
            raise CalculationError(
                f"{li.kind.value} is a customer-side line and cannot appear in a "
                "supplier refund calculation"
            )
    raw = _sum_lines(lines, currency)
    clamped = False
    if raw.is_negative and not allow_negative:
        # A supplier can withhold at most everything paid; it cannot claw back
        # more than the original. A negative expected refund signals bad inputs,
        # so we floor to zero and flag it for review rather than show a negative.
        raw = Money.zero(currency)
        clamped = True
    return RefundBreakdown(
        currency=currency, scope="supplier", lines=tuple(lines), total=raw, clamped=clamped
    )


def compute_customer_refund(
    lines: Sequence[LineItem], currency: str, *, allow_negative: bool = False
) -> RefundBreakdown:
    """Amount the *agency* should return to the customer.

    This is deliberately separate from the supplier calculation. Typically its
    ORIGINAL lines are the supplier refunds actually expected/received, and the
    deductions are the fees the agency legitimately retains.
    """
    _validate(lines, currency)
    raw = _sum_lines(lines, currency)
    clamped = False
    if raw.is_negative and not allow_negative:
        raw = Money.zero(currency)
        clamped = True
    return RefundBreakdown(
        currency=currency, scope="customer", lines=tuple(lines), total=raw, clamped=clamped
    )


# --------------------------------------------------------------------------- #
# Settlement reconciliation helpers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class SettlementPosition:
    """How an *expected* figure compares to what was actually received so far.

    ``received`` is the sum of verified refund transactions (each backed by
    evidence). ``outstanding`` is expected minus received, floored at zero on the
    over-paid side so the two directions are never conflated.
    """

    expected: Money
    received: Money

    def __post_init__(self) -> None:
        if self.expected.currency != self.received.currency:
            raise CalculationError("expected/received currency mismatch")

    @property
    def currency(self) -> str:
        return self.expected.currency

    @property
    def outstanding(self) -> Money:
        diff = self.expected - self.received
        return diff if diff.is_positive else Money.zero(self.currency)

    @property
    def overpaid(self) -> Money:
        diff = self.received - self.expected
        return diff if diff.is_positive else Money.zero(self.currency)

    @property
    def is_settled(self) -> bool:
        return self.expected == self.received

    @property
    def is_short(self) -> bool:
        return self.received < self.expected

    @property
    def is_over(self) -> bool:
        return self.received > self.expected
