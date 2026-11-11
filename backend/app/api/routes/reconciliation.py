"""Reconciliation routes: import & reconcile, list batches, view, resolve."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, get_current_principal, require_roles
from app.domain.money import Money
from app.models.tenant import Role
from app.models.reconciliation import Discrepancy, ReconciliationBatch, ReconciliationRecord
from app.schemas.reconciliation import (
    BatchDetailOut,
    BatchOut,
    DiscrepancyOut,
    ImportRequest,
    RecordOut,
    ResolveDiscrepancyRequest,
)
from app.services import reconciliation_service
from app.services.scoping import scoped_get, scoped_list

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])
_finance = require_roles(Role.OWNER, Role.FINANCE)


@router.post("/import", response_model=BatchDetailOut, status_code=201)
def import_records(req: ImportRequest, p: Principal = Depends(_finance),
                   db: Session = Depends(get_db)) -> BatchDetailOut:
    if req.csv_text:
        rows = reconciliation_service.parse_csv(req.csv_text)
    elif req.rows:
        rows = [r.model_dump() for r in req.rows]
    else:
        raise HTTPException(status_code=422, detail="provide rows or csv_text")
    try:
        batch = reconciliation_service.import_and_reconcile(
            db, p.tenant_id, p.user_id, rows=rows, source=req.source,
            filename=req.filename, date_window_days=req.date_window_days,
        )
    except reconciliation_service.ReconciliationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _batch_detail(db, p.tenant_id, batch)


@router.get("/batches", response_model=list[BatchOut])
def list_batches(p: Principal = Depends(get_current_principal),
                 db: Session = Depends(get_db)) -> list[BatchOut]:
    return [_batch_out(b) for b in scoped_list(db, ReconciliationBatch, p.tenant_id)]


@router.get("/batches/{batch_id}", response_model=BatchDetailOut)
def get_batch(batch_id: str, p: Principal = Depends(get_current_principal),
              db: Session = Depends(get_db)) -> BatchDetailOut:
    batch = scoped_get(db, ReconciliationBatch, p.tenant_id, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    return _batch_detail(db, p.tenant_id, batch)


@router.get("/discrepancies", response_model=list[DiscrepancyOut])
def list_discrepancies(status: str | None = None,
                       p: Principal = Depends(get_current_principal),
                       db: Session = Depends(get_db)) -> list[DiscrepancyOut]:
    rows = scoped_list(db, Discrepancy, p.tenant_id)
    if status:
        rows = [d for d in rows if d.status == status]
    # Highest financial exposure first (spec Module G: prioritise exposure).
    rows.sort(key=lambda d: abs(d.observed_amount_minor or d.expected_amount_minor or 0),
              reverse=True)
    return [_disc_out(d) for d in rows]


@router.post("/discrepancies/{disc_id}/resolve", response_model=DiscrepancyOut)
def resolve_discrepancy(disc_id: str, req: ResolveDiscrepancyRequest,
                        p: Principal = Depends(_finance),
                        db: Session = Depends(get_db)) -> DiscrepancyOut:
    d = scoped_get(db, Discrepancy, p.tenant_id, disc_id)
    if d is None:
        raise HTTPException(status_code=404, detail="discrepancy not found")
    d.status = req.status
    db.commit()
    return _disc_out(d)


# ---------- serialisers ----------
def _money(minor, currency) -> str | None:
    return None if minor is None else str(Money(int(minor), currency).amount)


def _batch_out(b: ReconciliationBatch) -> BatchOut:
    return BatchOut(id=b.id, source=b.source, filename=b.filename, status=b.status,
                    record_count=b.record_count, matched_count=b.matched_count,
                    discrepancy_count=b.discrepancy_count, accuracy=b.accuracy)


def _batch_detail(db: Session, tenant_id: str, b: ReconciliationBatch) -> BatchDetailOut:
    records = db.scalars(select(ReconciliationRecord).where(
        ReconciliationRecord.tenant_id == tenant_id,
        ReconciliationRecord.batch_id == b.id).order_by(ReconciliationRecord.row_ref)).all()
    discs = db.scalars(select(Discrepancy).where(
        Discrepancy.tenant_id == tenant_id, Discrepancy.batch_id == b.id)).all()
    return BatchDetailOut(
        **_batch_out(b).model_dump(),
        records=[_rec_out(r) for r in records],
        discrepancies=[_disc_out(d) for d in discs],
    )


def _rec_out(r: ReconciliationRecord) -> RecordOut:
    return RecordOut(id=r.id, row_ref=r.row_ref, external_ref=r.external_ref,
                     amount=str(Money(r.amount_minor, r.currency).amount), currency=r.currency,
                     matched=r.matched, match_strategy=r.match_strategy,
                     match_confidence=r.match_confidence, matched_entry_id=r.matched_entry_id)


def _disc_out(d: Discrepancy) -> DiscrepancyOut:
    return DiscrepancyOut(
        id=d.id, kind=d.kind, severity=d.severity,
        expected_amount=_money(d.expected_amount_minor, d.currency),
        observed_amount=_money(d.observed_amount_minor, d.currency),
        difference=_money(d.difference_minor, d.currency),
        currency=d.currency, detail=d.detail, recommended_action=d.recommended_action,
        status=d.status,
    )
