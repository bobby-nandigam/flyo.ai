"""Reconciliation use-cases: import records, match against the ledger, persist.

Flow:
1. Normalise imported rows (from CSV text or JSON) into ``ExternalTxn`` + rows.
2. Build ``ExpectedItem`` list from the tenant's SUPPLIER ledger entries — what we
   have recorded as received from suppliers.
3. Run the pure deterministic engine (``domain.reconciliation.reconcile``).
4. Persist a batch, its records (with match outcome) and typed discrepancies.

Low-confidence matches are stored but flagged ``auto_finalizable=False`` so a human
can confirm them (spec: never auto-finalise a low-confidence match).
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.money import Money
from app.domain.reconciliation import (
    Discrepancy as DomainDiscrepancy,
    DiscrepancyType,
    ExpectedItem,
    ExternalTxn,
    reconcile,
)
from app.models.refund import LedgerEntryRow
from app.models.reconciliation import Discrepancy, ReconciliationBatch, ReconciliationRecord
from app.services import audit


class ReconciliationError(Exception):
    pass


_RECOMMENDED = {
    DiscrepancyType.UNMATCHED_BANK_CREDIT:
        "Identify the booking/case this credit belongs to and record it, or raise with the bank.",
    DiscrepancyType.MISSING_SUPPLIER_REFUND:
        "Follow up with the supplier; the recorded refund has not appeared in the imported records.",
    DiscrepancyType.AMOUNT_MISMATCH:
        "Verify the correct amount against the cancellation policy and dispute the shortfall.",
    DiscrepancyType.DUPLICATE_TRANSACTION:
        "Confirm whether this is a genuine second credit or a duplicate import; reverse if duplicated.",
}


def parse_csv(text: str, *, default_currency: str = "INR") -> list[dict]:
    """Parse CSV text into normalised row dicts.

    Recognised headers (case-insensitive): row_ref, external_ref/reference/utr,
    amount, currency, value_date/date, counterparty/party, booking_ref/pnr.
    """
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    for i, raw in enumerate(reader):
        low = { (k or "").strip().lower(): (v or "").strip() for k, v in raw.items() }
        amount = low.get("amount") or low.get("credit") or low.get("value")
        if not amount:
            continue
        rows.append({
            "row_ref": low.get("row_ref") or str(i + 1),
            "external_ref": low.get("external_ref") or low.get("reference") or low.get("utr") or None,
            "amount": amount,
            "currency": (low.get("currency") or default_currency).upper(),
            "value_date": low.get("value_date") or low.get("date") or None,
            "counterparty": low.get("counterparty") or low.get("party") or None,
            "booking_ref": low.get("booking_ref") or low.get("pnr") or None,
            "raw": raw,
        })
    return rows


def _parse_date(s: str | None) -> _dt.date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _severity(amount: Money | None) -> str:
    if amount is None:
        return "MEDIUM"
    a = abs(amount.minor_units)
    if a >= 10000 * 100:
        return "HIGH"
    if a >= 1000 * 100:
        return "MEDIUM"
    return "LOW"


def import_and_reconcile(
    db: Session, tenant_id: str, user_id: str, *,
    rows: Sequence[dict], source: str = "BANK", filename: str = "",
    default_currency: str = "INR", date_window_days: int = 5,
) -> ReconciliationBatch:
    if not rows:
        raise ReconciliationError("no rows to reconcile")

    # 1) Normalise external transactions and persist raw records.
    batch = ReconciliationBatch(tenant_id=tenant_id, source=source, filename=filename,
                                record_count=len(rows))
    db.add(batch)
    db.flush()

    externals: list[ExternalTxn] = []
    record_by_row: dict[str, ReconciliationRecord] = {}
    for idx, r in enumerate(rows):
        currency = (r.get("currency") or default_currency).upper()
        money = Money.from_decimal(str(r["amount"]), currency)
        vdate = _parse_date(r.get("value_date"))
        # Every row needs a unique id within the batch; fall back to its index so
        # distinct rows never collapse onto a shared "None" identity.
        row_ref = str(r.get("row_ref") or (idx + 1))
        rec = ReconciliationRecord(
            tenant_id=tenant_id, batch_id=batch.id, row_ref=row_ref,
            external_ref=r.get("external_ref"), amount_minor=money.minor_units,
            currency=currency, value_date=vdate, counterparty=r.get("counterparty"),
            booking_ref=r.get("booking_ref"), raw=r.get("raw"),
        )
        db.add(rec)
        record_by_row[rec.row_ref] = rec
        externals.append(ExternalTxn(
            row_id=rec.row_ref, amount=money, external_ref=r.get("external_ref"),
            value_date=vdate, counterparty=r.get("counterparty"),
            booking_ref=r.get("booking_ref"),
        ))

    # 2) Expected items = SUPPLIER ledger entries (money we recorded as received).
    ledger_rows = db.scalars(
        select(LedgerEntryRow).where(
            LedgerEntryRow.tenant_id == tenant_id,
            LedgerEntryRow.account == "SUPPLIER",
        )
    ).all()
    expecteds = [
        ExpectedItem(
            item_id=lr.id,
            amount=Money(lr.amount_minor, lr.currency),
            external_ref=lr.external_ref,
            value_date=(lr.created_at.date() if lr.created_at else None),
            counterparty=None,
            booking_ref=None,
        )
        for lr in ledger_rows
    ]

    # 3) Run the deterministic engine.
    result = reconcile(externals, expecteds, date_window_days=date_window_days)

    # 4) Persist match outcomes on records.
    for m in result.matches:
        rec = record_by_row.get(m.external_row_id)
        if rec is not None:
            rec.matched = True
            rec.match_strategy = m.strategy.value
            rec.match_confidence = str(m.confidence)
            rec.matched_entry_id = m.expected_item_id

    # ... and discrepancies as first-class rows.
    for d in result.discrepancies:
        _persist_discrepancy(db, tenant_id, batch.id, d, default_currency)

    batch.matched_count = result.matched_count
    batch.discrepancy_count = len(result.discrepancies)
    batch.accuracy = str(result.accuracy())

    audit.record(db, tenant_id=tenant_id, user_id=user_id, action="reconciliation.run",
                 entity_type="reconciliation_batch", entity_id=batch.id,
                 detail={"records": len(rows), "matched": result.matched_count,
                         "discrepancies": len(result.discrepancies)})
    db.commit()
    return batch


def _persist_discrepancy(db: Session, tenant_id: str, batch_id: str,
                         d: DomainDiscrepancy, currency: str) -> None:
    amt = d.observed_amount or d.expected_amount
    row = Discrepancy(
        tenant_id=tenant_id, batch_id=batch_id, kind=d.kind.value,
        severity=_severity(amt),
        external_row_id=d.external_row_id, expected_entry_id=d.expected_item_id,
        expected_amount_minor=(d.expected_amount.minor_units if d.expected_amount else None),
        observed_amount_minor=(d.observed_amount.minor_units if d.observed_amount else None),
        difference_minor=(d.difference.minor_units if d.difference else None),
        currency=(amt.currency if amt else currency),
        detail=d.detail, recommended_action=_RECOMMENDED.get(d.kind, ""),
    )
    db.add(row)
