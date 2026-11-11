"""Refund case use-cases: open a case, post ledger facts, manage state.

This is where Phase 1's pure engine meets persistence. Two concerns are kept
separate on purpose:

* **Financial facts** — supplier/customer money movements — are appended to the
  immutable ledger and are always allowed if they carry evidence and are not a
  duplicate (DB unique on external_ref mirrors domain invariant #1).
* **Case workflow state** — the RefundStatus lifecycle — is advanced only through
  validated transitions (domain allow-list). Posting money never silently jumps
  the workflow.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.calculation import (
    LineItem,
    LineKind,
    compute_customer_refund,
    compute_supplier_refund,
)
from app.domain.ledger import Account, EntryType
from app.domain.money import Money
from app.domain.calculation import SettlementPosition
from app.domain.refund_status import RefundStatus, assert_transition
from app.models.refund import LedgerEntryRow, RefundCase
from app.models.trip import Booking, Trip
from app.services import audit
from app.services.scoping import scoped_get


class RefundError(Exception):
    pass


class DuplicateLedgerEntry(RefundError):
    pass


def open_refund_case(
    db: Session,
    tenant_id: str,
    user_id: str,
    *,
    booking_id: str,
    deductions: Sequence[dict],
    customer_deductions: Sequence[dict] | None = None,
) -> RefundCase:
    """Open a case and compute the expected supplier (and customer) refund.

    The ORIGINAL line is taken from the persisted booking amount — never from
    caller input — so the base figure is always the real money charged.
    ``deductions`` is a list of ``{"kind","label","amount","evidence_ref"}``.
    """
    booking = scoped_get(db, Booking, tenant_id, booking_id)
    if booking is None:
        raise RefundError("booking not found")
    currency = booking.currency

    original = Money(booking.original_amount_minor, currency)
    supplier_lines = [
        LineItem(LineKind.ORIGINAL, "Original booking amount", original,
                 evidence_ref=f"booking:{booking.id}")
    ]
    supplier_lines += [_line(d, currency) for d in deductions]
    supplier_result = compute_supplier_refund(supplier_lines, currency)

    customer_result = None
    if customer_deductions is not None:
        cust_lines = [
            LineItem(LineKind.ORIGINAL, "Expected supplier refund",
                     supplier_result.total, evidence_ref="calc:supplier")
        ]
        cust_lines += [_line(d, currency) for d in customer_deductions]
        customer_result = compute_customer_refund(cust_lines, currency)

    case = RefundCase(
        tenant_id=tenant_id,
        trip_id=booking.trip_id,
        booking_id=booking.id,
        status=RefundStatus.REFUND_EXPECTED.value,
        currency=currency,
        expected_supplier_refund_minor=supplier_result.total.minor_units,
        expected_customer_refund_minor=(
            customer_result.total.minor_units if customer_result else 0
        ),
        supplier_breakdown=supplier_result.to_audit_dict(),
        customer_breakdown=customer_result.to_audit_dict() if customer_result else None,
    )
    db.add(case)
    db.flush()
    audit.record(db, tenant_id=tenant_id, user_id=user_id, action="refund_case.open",
                 entity_type="refund_case", entity_id=case.id,
                 detail={"expected_supplier": str(supplier_result.total.amount)})
    db.commit()
    return case


def _line(d: dict, currency: str) -> LineItem:
    return LineItem(
        kind=LineKind(d["kind"]),
        label=d["label"],
        amount=Money.from_decimal(str(d["amount"]), currency),
        evidence_ref=d.get("evidence_ref"),
    )


def _post_entry(
    db: Session, tenant_id: str, user_id: str, case: RefundCase, *,
    account: Account, entry_type: EntryType, amount: Money,
    evidence_ref: str, external_ref: str | None, memo: str = "",
) -> LedgerEntryRow:
    if not evidence_ref:
        raise RefundError("evidence_ref is required for a ledger entry (invariant #2)")
    if amount.currency != case.currency:
        raise RefundError("entry currency must match the case currency")
    row = LedgerEntryRow(
        tenant_id=tenant_id, trip_id=case.trip_id, refund_case_id=case.id,
        account=account.value, entry_type=entry_type.value,
        amount_minor=amount.minor_units, currency=amount.currency,
        evidence_ref=evidence_ref, external_ref=external_ref, memo=memo,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateLedgerEntry(
            f"external_ref {external_ref!r} already posted (invariant #1)"
        ) from exc
    audit.record(db, tenant_id=tenant_id, user_id=user_id, action="ledger.append",
                 entity_type="financial_ledger", entity_id=row.id,
                 detail={"account": account.value, "amount": str(amount.amount),
                         "external_ref": external_ref})
    db.commit()
    return row


def post_supplier_refund(db: Session, tenant_id: str, user_id: str, *, case_id: str,
                         amount: str, evidence_ref: str, external_ref: str | None = None,
                         memo: str = "") -> LedgerEntryRow:
    case = _require_case(db, tenant_id, case_id)
    money = Money.from_decimal(amount, case.currency)
    return _post_entry(db, tenant_id, user_id, case, account=Account.SUPPLIER,
                       entry_type=EntryType.SUPPLIER_REFUND, amount=money,
                       evidence_ref=evidence_ref, external_ref=external_ref, memo=memo)


def post_customer_refund(db: Session, tenant_id: str, user_id: str, *, case_id: str,
                         amount: str, evidence_ref: str, external_ref: str | None = None,
                         memo: str = "") -> LedgerEntryRow:
    case = _require_case(db, tenant_id, case_id)
    # Money leaves the agency to the customer -> negative on the CUSTOMER account.
    money = -Money.from_decimal(amount, case.currency)
    return _post_entry(db, tenant_id, user_id, case, account=Account.CUSTOMER,
                       entry_type=EntryType.CUSTOMER_REFUND, amount=money,
                       evidence_ref=evidence_ref, external_ref=external_ref, memo=memo)


def transition_status(db: Session, tenant_id: str, user_id: str, *, case_id: str,
                      new_status: RefundStatus) -> RefundCase:
    case = _require_case(db, tenant_id, case_id)
    current = RefundStatus(case.status)
    assert_transition(current, new_status)  # raises InvalidTransition if illegal
    case.status = new_status.value
    audit.record(db, tenant_id=tenant_id, user_id=user_id, action="refund_case.transition",
                 entity_type="refund_case", entity_id=case.id,
                 detail={"from": current.value, "to": new_status.value})
    db.commit()
    return case


def settlement(db: Session, tenant_id: str, *, case_id: str, side: str = "supplier") -> SettlementPosition:
    """Expected vs. received for a case, as a domain SettlementPosition."""
    case = _require_case(db, tenant_id, case_id)
    account = Account.SUPPLIER if side == "supplier" else Account.CUSTOMER
    expected_minor = (
        case.expected_supplier_refund_minor if side == "supplier"
        else case.expected_customer_refund_minor
    )
    rows = db.scalars(
        select(LedgerEntryRow).where(
            LedgerEntryRow.tenant_id == tenant_id,
            LedgerEntryRow.refund_case_id == case_id,
            LedgerEntryRow.account == account.value,
        )
    ).all()
    received_minor = abs(sum(r.amount_minor for r in rows))
    return SettlementPosition(
        expected=Money(expected_minor, case.currency),
        received=Money(received_minor, case.currency),
    )


def _require_case(db: Session, tenant_id: str, case_id: str) -> RefundCase:
    case = scoped_get(db, RefundCase, tenant_id, case_id)
    if case is None:
        raise RefundError("refund case not found")
    return case
