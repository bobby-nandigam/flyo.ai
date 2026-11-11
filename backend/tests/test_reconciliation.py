"""Tests for the deterministic reconciliation engine (spec Module E/G)."""
import datetime as _dt
from decimal import Decimal

from app.domain.money import Money
from app.domain.reconciliation import (
    DiscrepancyType,
    ExpectedItem,
    ExternalTxn,
    MatchStrategy,
    reconcile,
)

D = _dt.date


def _ext(rid, amt, ref=None, date=None, party=None, booking=None):
    return ExternalTxn(rid, Money.from_decimal(amt, "INR"), ref, date, party, booking)


def _exp(iid, amt, ref=None, date=None, party=None, booking=None):
    return ExpectedItem(iid, Money.from_decimal(amt, "INR"), ref, date, party, booking)


def test_exact_reference_match_full_confidence():
    r = reconcile([_ext("x1", "5000.00", ref="BANK-1")],
                  [_exp("e1", "5000.00", ref="BANK-1")])
    assert r.matched_count == 1
    m = r.matches[0]
    assert m.strategy is MatchStrategy.EXACT_REF
    assert m.confidence == Decimal("1.00") and m.auto_finalizable
    assert not r.discrepancies


def test_amount_date_match_when_no_ref():
    r = reconcile([_ext("x1", "5000.00", date=D(2026, 3, 2))],
                  [_exp("e1", "5000.00", date=D(2026, 3, 1))])
    assert r.matched_count == 1
    assert r.matches[0].strategy is MatchStrategy.AMOUNT_DATE


def test_date_outside_window_not_matched():
    r = reconcile([_ext("x1", "5000.00", date=D(2026, 3, 20))],
                  [_exp("e1", "5000.00", date=D(2026, 3, 1))],
                  date_window_days=5)
    assert r.matched_count == 0
    kinds = {d.kind for d in r.discrepancies}
    assert DiscrepancyType.UNMATCHED_BANK_CREDIT in kinds
    assert DiscrepancyType.MISSING_SUPPLIER_REFUND in kinds


def test_amount_mismatch_on_reference_match_is_flagged():
    r = reconcile([_ext("x1", "4800.00", ref="BANK-1")],
                  [_exp("e1", "5000.00", ref="BANK-1")])
    assert r.matched_count == 1  # still paired by reference
    disc = [d for d in r.discrepancies if d.kind is DiscrepancyType.AMOUNT_MISMATCH]
    assert len(disc) == 1
    assert disc[0].difference.amount == Decimal("-200.00")  # observed - expected


def test_duplicate_external_transaction_detected():
    r = reconcile(
        [_ext("x1", "5000.00", ref="BANK-1"), _ext("x2", "5000.00", ref="BANK-1")],
        [_exp("e1", "5000.00", ref="BANK-1")],
    )
    dups = [d for d in r.discrepancies if d.kind is DiscrepancyType.DUPLICATE_TRANSACTION]
    assert len(dups) == 1 and dups[0].external_row_id == "x2"
    # The duplicate is excluded from matching; the first still matches.
    assert r.matched_count == 1


def test_missing_supplier_refund_when_nothing_imported():
    r = reconcile([], [_exp("e1", "7800.00", ref="SUP-1")])
    assert r.unmatched_expected == ("e1",)
    assert r.discrepancies[0].kind is DiscrepancyType.MISSING_SUPPLIER_REFUND
    assert r.accuracy() == Decimal("0.00")


def test_unmatched_bank_credit():
    r = reconcile([_ext("x1", "1234.00", ref="MYSTERY")], [])
    assert r.unmatched_external == ("x1",)
    assert r.discrepancies[0].kind is DiscrepancyType.UNMATCHED_BANK_CREDIT


def test_fuzzy_reference_match_low_confidence_not_auto_final():
    # Dates are outside the window (so AMOUNT_DATE cannot fire), but the refs are
    # near-identical and amounts equal -> fuzzy match at low confidence.
    r = reconcile([_ext("x1", "5000.00", ref="UTR12345X", date=D(2026, 3, 20))],
                  [_exp("e1", "5000.00", ref="UTR12345", date=D(2026, 3, 1))],
                  date_window_days=5)
    assert r.matched_count == 1
    m = r.matches[0]
    assert m.strategy is MatchStrategy.FUZZY_REF
    assert not m.auto_finalizable  # below the 0.80 threshold


def test_reproducible_regardless_of_input_order():
    ext = [_ext("x2", "200.00", ref="B"), _ext("x1", "100.00", ref="A")]
    exp = [_exp("e2", "200.00", ref="B"), _exp("e1", "100.00", ref="A")]
    r1 = reconcile(ext, exp)
    r2 = reconcile(list(reversed(ext)), list(reversed(exp)))
    assert [(m.external_row_id, m.expected_item_id) for m in r1.matches] == \
           [(m.external_row_id, m.expected_item_id) for m in r2.matches]


def test_accuracy_partial():
    r = reconcile(
        [_ext("x1", "100.00", ref="A")],
        [_exp("e1", "100.00", ref="A"), _exp("e2", "200.00", ref="B")],
    )
    assert r.matched_count == 1
    assert r.accuracy() == Decimal("0.50")
