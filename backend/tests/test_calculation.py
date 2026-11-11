"""Tests for the refund calculation engine (spec Module D)."""
from decimal import Decimal

import pytest

from app.domain.money import Money
from app.domain.calculation import (
    LineKind,
    LineItem,
    CalculationError,
    SettlementPosition,
    compute_supplier_refund,
    compute_customer_refund,
)


def _line(kind, label, amount, ref="doc:1"):
    return LineItem(kind=kind, label=label, amount=Money.from_decimal(amount, "INR"), evidence_ref=ref)


def test_supplier_refund_matches_spec_formula():
    # Original 10000, cancellation penalty 2000, non-refundable fee 500,
    # refundable tax 300 -> expected = 10000 - 2000 - 500 + 300 = 7800
    lines = [
        _line(LineKind.ORIGINAL, "Base fare", "10000.00"),
        _line(LineKind.CANCELLATION_DEDUCTION, "Cancellation penalty", "2000.00"),
        _line(LineKind.NON_REFUNDABLE, "Convenience fee", "500.00"),
        _line(LineKind.REFUNDABLE_TAX, "Refundable GST", "300.00"),
    ]
    result = compute_supplier_refund(lines, "INR")
    assert result.total.amount == Decimal("7800.00")
    assert result.scope == "supplier"
    assert not result.clamped
    # Every line carries evidence
    assert all(li.evidence_ref for li in result.lines)


def test_supplier_refund_rejects_customer_side_lines():
    lines = [
        _line(LineKind.ORIGINAL, "Base fare", "10000.00"),
        _line(LineKind.GATEWAY_FEE, "Razorpay fee", "200.00"),
    ]
    with pytest.raises(CalculationError):
        compute_supplier_refund(lines, "INR")


def test_negative_supplier_refund_is_clamped_and_flagged():
    # Penalty larger than original -> raw negative, floored to zero, flagged.
    lines = [
        _line(LineKind.ORIGINAL, "Base fare", "1000.00"),
        _line(LineKind.CANCELLATION_DEDUCTION, "Penalty", "1500.00"),
    ]
    result = compute_supplier_refund(lines, "INR")
    assert result.total.is_zero
    assert result.clamped is True


def test_customer_refund_separate_from_supplier():
    # Customer gets the supplier refund minus the agency's service fee.
    lines = [
        _line(LineKind.ORIGINAL, "Supplier refund received", "7800.00"),
        _line(LineKind.AGENCY_SERVICE_FEE, "Agency handling fee", "300.00"),
        _line(LineKind.GATEWAY_FEE, "Gateway fee retained", "100.00"),
    ]
    result = compute_customer_refund(lines, "INR")
    assert result.total.amount == Decimal("7400.00")
    assert result.scope == "customer"


def test_mixed_currency_line_rejected():
    lines = [
        LineItem(LineKind.ORIGINAL, "Base", Money.from_decimal("100", "INR")),
        LineItem(LineKind.REFUNDABLE_TAX, "Tax", Money.from_decimal("10", "USD")),
    ]
    with pytest.raises(CalculationError):
        compute_supplier_refund(lines, "INR")


def test_negative_magnitude_line_rejected():
    bad = LineItem(LineKind.ORIGINAL, "Base", Money.from_decimal("-100", "INR"))
    with pytest.raises(CalculationError):
        compute_supplier_refund([bad], "INR")


def test_audit_dict_is_serialisable_and_complete():
    lines = [
        _line(LineKind.ORIGINAL, "Base fare", "10000.00"),
        _line(LineKind.CANCELLATION_DEDUCTION, "Penalty", "2000.00"),
    ]
    d = compute_supplier_refund(lines, "INR").to_audit_dict()
    assert d["total"] == "8000.00"
    assert len(d["lines"]) == 2
    assert d["lines"][0]["signed"] == "10000.00"
    assert d["lines"][1]["signed"] == "-2000.00"


# -------------------- Settlement position -------------------- #
def test_settlement_outstanding_when_short():
    pos = SettlementPosition(
        expected=Money.from_decimal("7800.00", "INR"),
        received=Money.from_decimal("5000.00", "INR"),
    )
    assert pos.outstanding.amount == Decimal("2800.00")
    assert pos.overpaid.is_zero
    assert pos.is_short and not pos.is_settled


def test_settlement_overpaid_detected():
    pos = SettlementPosition(
        expected=Money.from_decimal("5000.00", "INR"),
        received=Money.from_decimal("5200.00", "INR"),
    )
    assert pos.overpaid.amount == Decimal("200.00")
    assert pos.outstanding.is_zero
    assert pos.is_over


def test_settlement_settled_exact():
    pos = SettlementPosition(
        expected=Money.from_decimal("5000.00", "INR"),
        received=Money.from_decimal("5000.00", "INR"),
    )
    assert pos.is_settled
    assert pos.outstanding.is_zero and pos.overpaid.is_zero
