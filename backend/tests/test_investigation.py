"""Tests for the pure investigation engine (spec Module H)."""
from decimal import Decimal

from app.domain.money import Money
from app.domain.investigation import (
    CaseDossier,
    DiscrepancyFact,
    Severity,
    investigate,
    supplier_followup_draft,
)


def _dossier(**kw):
    base = dict(
        case_id="C1", currency="INR",
        status="REFUND_REQUESTED",
        expected_supplier=Money.from_decimal("10000", "INR"),
        supplier_received=Money.zero("INR"),
        expected_customer=Money.zero("INR"),
        customer_paid=Money.zero("INR"),
        has_documents=True, supplier_name="IndiGo",
    )
    base.update(kw)
    return CaseDossier(**base)


def test_shortfall_flagged_with_action():
    inv = investigate(_dossier(supplier_received=Money.from_decimal("6000", "INR")))
    codes = {f.code for f in inv.findings}
    assert "SUPPLIER_SHORTFALL" in codes
    assert inv.severity in (Severity.MEDIUM, Severity.HIGH)
    assert any("IndiGo" in a and "4000" in a for a in inv.recommended_actions)


def test_high_severity_for_large_shortfall():
    inv = investigate(_dossier(expected_supplier=Money.from_decimal("50000", "INR"),
                               supplier_received=Money.zero("INR")))
    assert inv.severity is Severity.HIGH


def test_never_claims_customer_paid_without_supplier_funds():
    inv = investigate(_dossier(supplier_received=Money.zero("INR"),
                               customer_paid=Money.from_decimal("5000", "INR")))
    assert any(f.code == "CUSTOMER_PAID_BEFORE_SUPPLIER" for f in inv.findings)


def test_customer_payout_pending():
    inv = investigate(_dossier(expected_supplier=Money.from_decimal("8000", "INR"),
                               supplier_received=Money.from_decimal("8000", "INR"),
                               customer_paid=Money.from_decimal("5000", "INR")))
    assert any(f.code == "CUSTOMER_PAYOUT_PENDING" for f in inv.findings)


def test_clean_case_has_no_findings():
    inv = investigate(_dossier(expected_supplier=Money.from_decimal("8000", "INR"),
                               supplier_received=Money.from_decimal("8000", "INR"),
                               customer_paid=Money.from_decimal("8000", "INR")))
    assert inv.findings == ()
    assert inv.severity is Severity.LOW
    assert "reconciles cleanly" in inv.summary


def test_missing_documents_flagged():
    inv = investigate(_dossier(expected_supplier=Money.from_decimal("8000", "INR"),
                               supplier_received=Money.from_decimal("8000", "INR"),
                               customer_paid=Money.from_decimal("8000", "INR"),
                               has_documents=False))
    assert any(f.code == "MISSING_EVIDENCE" for f in inv.findings)


def test_discrepancy_facts_become_findings():
    inv = investigate(_dossier(discrepancies=(
        DiscrepancyFact("AMOUNT_MISMATCH", Money.from_decimal("500", "INR"),
                        "Shortfall vs policy", "discrepancy:1"),)))
    assert any(f.code == "DISCREPANCY_AMOUNT_MISMATCH" for f in inv.findings)


def test_followup_draft_contains_numbers_and_no_fake_contact():
    d = _dossier(supplier_received=Money.from_decimal("6000", "INR"))
    draft = supplier_followup_draft(d)
    assert "10000" in draft and "6000" in draft and "4000" in draft
    assert "IndiGo" in draft
    assert "@" not in draft  # invents no email address
