"""The seven financial invariants from spec §11.

These are the acceptance tests for financial correctness. If any of these fail,
the platform is not safe to show money to a user.
"""
from decimal import Decimal

import pytest

from app.domain.money import Money
from app.domain.ledger import (
    TripLedger,
    LedgerEntry,
    Account,
    EntryType,
    DuplicateEntry,
    LedgerError,
)


def _ledger():
    return TripLedger(trip_id="TRIP-1", currency="INR")


def _entry(eid, account, etype, amount, *, evidence="doc:x", external=None, reverses=None):
    return LedgerEntry(
        entry_id=eid,
        account=account,
        entry_type=etype,
        amount=Money.from_decimal(amount, "INR"),
        evidence_ref=evidence,
        external_ref=external,
        reverses=reverses,
    )


def test_invariant_1_no_transaction_counted_twice():
    led = _ledger()
    led.append(_entry("e1", Account.SUPPLIER, EntryType.SUPPLIER_REFUND, "5000.00",
                      external="BANK-TXN-9001"))
    with pytest.raises(DuplicateEntry):
        led.append(_entry("e2", Account.SUPPLIER, EntryType.SUPPLIER_REFUND, "5000.00",
                          external="BANK-TXN-9001"))
    assert led.supplier_refund_total().amount == Decimal("5000.00")


def test_invariant_2_every_entry_has_evidence():
    with pytest.raises(LedgerError):
        _entry("e1", Account.SUPPLIER, EntryType.SUPPLIER_REFUND, "5000.00", evidence="")


def test_invariant_3_supplier_and_customer_refunds_distinct():
    led = _ledger()
    led.append(_entry("s1", Account.SUPPLIER, EntryType.SUPPLIER_REFUND, "7800.00",
                      external="SUP-1"))
    # Agency has NOT yet paid the customer; customer account stays empty.
    assert led.supplier_refund_total().amount == Decimal("7800.00")
    assert led.customer_refund_total().is_zero
    # Now the agency pays the customer (money leaves -> negative on CUSTOMER).
    led.append(_entry("c1", Account.CUSTOMER, EntryType.CUSTOMER_REFUND, "-7500.00",
                      external="UPI-1"))
    assert led.customer_refund_total().amount == Decimal("7500.00")
    # The two totals are independent, not the same figure.
    assert led.supplier_refund_total() != led.customer_refund_total()


def test_invariant_4_balances_reconcile_to_entries():
    led = _ledger()
    led.append(_entry("s1", Account.SUPPLIER, EntryType.SUPPLIER_REFUND, "3000.00", external="A"))
    led.append(_entry("s2", Account.SUPPLIER, EntryType.SUPPLIER_REFUND, "2000.00", external="B"))
    assert led.reconciles()
    assert led.balance(Account.SUPPLIER).amount == Decimal("5000.00")


def test_invariant_5_calculations_are_reproducible():
    # Building the same ledger twice yields identical balances.
    def build():
        led = _ledger()
        led.append(_entry("s1", Account.SUPPLIER, EntryType.SUPPLIER_REFUND, "1234.56", external="A"))
        led.append(_entry("s2", Account.SUPPLIER, EntryType.SUPPLIER_REFUND, "6543.21", external="B"))
        return led.supplier_refund_total()
    assert build() == build()
    assert build().amount == Decimal("7777.77")


def test_invariant_6_adjustment_is_a_new_audited_entry_not_a_mutation():
    led = _ledger()
    original = _entry("s1", Account.SUPPLIER, EntryType.SUPPLIER_REFUND, "5000.00", external="A")
    led.append(original)
    # Correcting a wrong entry means appending a reversal, never editing in place.
    reversal = _entry("s1r", Account.SUPPLIER, EntryType.REVERSAL, "-5000.00",
                      evidence="ticket:42", reverses="s1")
    led.append(reversal)
    assert led.supplier_refund_total().is_zero
    # The original entry still exists in the immutable history.
    assert len(led.entries) == 2
    assert led.entries[0].entry_id == "s1"


def test_reversal_must_reference_existing_entry():
    led = _ledger()
    with pytest.raises(LedgerError):
        led.append(_entry("x", Account.SUPPLIER, EntryType.REVERSAL, "-100.00",
                          reverses="does-not-exist"))


def test_ledger_rejects_wrong_currency():
    led = _ledger()
    with pytest.raises(LedgerError):
        led.append(LedgerEntry(
            entry_id="e1", account=Account.SUPPLIER, entry_type=EntryType.SUPPLIER_REFUND,
            amount=Money.from_decimal("100", "USD"), evidence_ref="doc:x",
        ))

# Invariant #7 (tenant isolation) is enforced at the data-access layer and is
# covered by the API/security test suite (see docs/ARCHITECTURE.md §Security),
# not by the pure domain layer, which has no concept of tenants.
