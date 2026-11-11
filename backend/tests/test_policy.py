"""Tests for the cancellation policy engine (spec Module C)."""
from decimal import Decimal

import pytest

from app.domain.calculation import LineKind, compute_supplier_refund
from app.domain.money import Money
from app.domain.policy import (
    CancellationPolicy,
    PenaltyBasis,
    PolicyTier,
    deduction_lines,
    select_tier,
)

POLICY = CancellationPolicy(
    version="indigo-domestic-v3",
    currency="INR",
    tiers=[
        PolicyTier(min_days_before=15, basis=PenaltyBasis.FIXED, fixed_amount="2000", label=">=15 days"),
        PolicyTier(min_days_before=2, basis=PenaltyBasis.GREATER_OF, fixed_amount="3000",
                   percent="25", label="2-14 days"),
        PolicyTier(min_days_before=0, basis=PenaltyBasis.PERCENT, percent="100", label="<2 days / no-show"),
    ],
    non_refundable_fixed="250",
    non_refundable_label="Convenience fee",
)


def test_select_tier_by_days_before_travel():
    assert select_tier(POLICY, 30).min_days_before == 15
    assert select_tier(POLICY, 10).min_days_before == 2
    assert select_tier(POLICY, 1).min_days_before == 0
    assert select_tier(POLICY, -1).min_days_before == 0  # no-show -> most penal


def test_greater_of_picks_percentage_when_larger():
    # 25% of 20000 = 5000 > fixed 3000 -> penalty 5000
    lines = deduction_lines(POLICY, Money.from_decimal("20000", "INR"), days_before_travel=10)
    penalty = next(l for l in lines if l.kind is LineKind.CANCELLATION_DEDUCTION)
    assert penalty.amount.amount == Decimal("5000.00")


def test_greater_of_picks_fixed_when_larger():
    # 25% of 8000 = 2000 < fixed 3000 -> penalty 3000
    lines = deduction_lines(POLICY, Money.from_decimal("8000", "INR"), days_before_travel=10)
    penalty = next(l for l in lines if l.kind is LineKind.CANCELLATION_DEDUCTION)
    assert penalty.amount.amount == Decimal("3000.00")


def test_lines_feed_refund_engine_with_policy_evidence():
    original = Money.from_decimal("12500", "INR")
    lines = [
        # ORIGINAL line + policy deductions
        __import__("app.domain.calculation", fromlist=["LineItem"]).LineItem(
            LineKind.ORIGINAL, "Original", original, evidence_ref="booking:1"),
        *deduction_lines(POLICY, original, days_before_travel=20),
    ]
    result = compute_supplier_refund(lines, "INR")
    # 12500 - 2000 (>=15 day fixed) - 250 (convenience) = 10250
    assert result.total.amount == Decimal("10250.00")
    assert all(l.evidence_ref for l in result.lines)


def test_penalty_never_exceeds_original():
    lines = deduction_lines(POLICY, Money.from_decimal("1000", "INR"), days_before_travel=0)
    penalty = next(l for l in lines if l.kind is LineKind.CANCELLATION_DEDUCTION)
    assert penalty.amount.amount <= Decimal("1000.00")


def test_currency_mismatch_rejected():
    with pytest.raises(Exception):
        deduction_lines(POLICY, Money.from_decimal("100", "USD"), days_before_travel=5)
