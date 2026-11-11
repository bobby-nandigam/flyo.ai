"""Tests for the deterministic document extraction engine (spec Module B)."""
from decimal import Decimal

from app.domain.extraction import extract

AIRLINE_DOC = """
IndiGo - Cancellation Confirmation
PNR: 6E-ABC123
Dear customer, your booking has been cancelled.
Original fare: INR 12,500.00
Cancellation charge: Rs. 3,000.00
Refund amount payable: ₹9,500.00
Cancellation date: 2026-03-01
"""


def test_extracts_refund_amount_with_highest_confidence():
    r = extract(AIRLINE_DOC, known_suppliers=["IndiGo", "Air India"])
    best = r.best_amount()
    assert best.value == "9500.00"  # the 'refund payable' line wins on confidence
    assert best.confidence >= Decimal("0.9")


def test_extracts_booking_reference():
    r = extract(AIRLINE_DOC)
    refs = [c.value for c in r.booking_refs]
    assert "6E-ABC123" in refs or "ABC123" in refs


def test_extracts_date_iso_normalised():
    r = extract(AIRLINE_DOC)
    assert "2026-03-01" in [c.value for c in r.dates]


def test_identifies_supplier_from_known_list():
    r = extract(AIRLINE_DOC, known_suppliers=["Air India", "IndiGo"])
    assert r.supplier is not None and r.supplier.value == "IndiGo"


def test_no_amount_when_none_present():
    r = extract("This document has no financial figures.")
    assert r.best_amount() is None


def test_handles_various_currency_markers():
    r = extract("Total: Rs 5000 and also INR 7,800.50 refund credited")
    vals = [c.value for c in r.amounts]
    assert "7800.50" in vals and "5000" in vals
    # the 'refund credited' amount should rank first
    assert r.best_amount().value == "7800.50"


def test_reproducible():
    assert extract(AIRLINE_DOC).to_dict() == extract(AIRLINE_DOC).to_dict()
