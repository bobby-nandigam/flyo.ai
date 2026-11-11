"""Financial operations dashboard metrics (spec Module J).

Every figure is computed from actual rows — no hardcoded totals. All amounts are
summed in integer minor units and returned as decimal strings in the tenant's
default currency. (The demo dataset is single-currency INR; multi-currency
aggregation is a Phase-3 concern and is noted in the response as ``currency``.)
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.money import Money
from app.models.refund import LedgerEntryRow, RefundCase
from app.models.reconciliation import Discrepancy
from app.models.trip import Booking, Trip


def summary(db: Session, tenant_id: str, currency: str = "INR") -> dict:
    def _m(minor: int | None) -> str:
        return str(Money(int(minor or 0), currency).amount)

    total_trips = db.scalar(
        select(func.count()).select_from(Trip).where(Trip.tenant_id == tenant_id)
    ) or 0
    total_bookings = db.scalar(
        select(func.count()).select_from(Booking).where(Booking.tenant_id == tenant_id)
    ) or 0
    total_original = db.scalar(
        select(func.coalesce(func.sum(Booking.original_amount_minor), 0))
        .where(Booking.tenant_id == tenant_id)
    ) or 0

    cases = db.scalars(
        select(RefundCase).where(RefundCase.tenant_id == tenant_id)
    ).all()
    total_expected_supplier = sum(c.expected_supplier_refund_minor for c in cases)

    # Received per account, summed from the ledger.
    supplier_received = db.scalar(
        select(func.coalesce(func.sum(LedgerEntryRow.amount_minor), 0)).where(
            LedgerEntryRow.tenant_id == tenant_id,
            LedgerEntryRow.account == "SUPPLIER",
        )
    ) or 0
    customer_paid = db.scalar(
        select(func.coalesce(func.sum(LedgerEntryRow.amount_minor), 0)).where(
            LedgerEntryRow.tenant_id == tenant_id,
            LedgerEntryRow.account == "CUSTOMER",
        )
    ) or 0

    # Outstanding supplier refunds = per-case max(expected - received, 0).
    received_by_case: dict[str, int] = {}
    rows = db.scalars(
        select(LedgerEntryRow).where(
            LedgerEntryRow.tenant_id == tenant_id,
            LedgerEntryRow.account == "SUPPLIER",
        )
    ).all()
    for r in rows:
        received_by_case[r.refund_case_id] = received_by_case.get(r.refund_case_id, 0) + r.amount_minor

    total_outstanding = 0
    open_cases = 0
    for c in cases:
        rec = received_by_case.get(c.id, 0)
        outstanding = max(c.expected_supplier_refund_minor - rec, 0)
        total_outstanding += outstanding
        if outstanding > 0:
            open_cases += 1

    open_discrepancies = db.scalar(
        select(func.count()).select_from(Discrepancy).where(
            Discrepancy.tenant_id == tenant_id, Discrepancy.status == "OPEN")
    ) or 0

    return {
        "currency": currency,
        "total_trips": total_trips,
        "total_bookings": total_bookings,
        "total_refund_cases": len(cases),
        "open_outstanding_cases": open_cases,
        "total_original_value": _m(total_original),
        "total_expected_supplier_refund": _m(total_expected_supplier),
        "total_supplier_refund_received": _m(supplier_received),
        "total_customer_refunded": _m(abs(customer_paid)),
        "total_outstanding": _m(total_outstanding),
        "open_discrepancies": open_discrepancies,
    }
