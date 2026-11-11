"""Refund case routes: open, inspect, post refunds, transition state, settlement."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, get_current_principal, require_roles
from app.domain.money import Money
from app.domain.refund_status import InvalidTransition
from app.models.refund import LedgerEntryRow, RefundCase
from app.models.tenant import Role
from app.schemas.refund import (
    LedgerEntryOut,
    OpenCaseRequest,
    PostRefundRequest,
    RefundCaseOut,
    SettlementOut,
    TransitionRequest,
)
from app.services import refund_service
from app.services.scoping import scoped_get

router = APIRouter(prefix="/refund-cases", tags=["refund-cases"])

# Posting money and transitioning state are finance actions.
_finance = require_roles(Role.OWNER, Role.FINANCE)


@router.post("", response_model=RefundCaseOut, status_code=201)
def open_case(req: OpenCaseRequest, p: Principal = Depends(_finance),
              db: Session = Depends(get_db)) -> RefundCaseOut:
    try:
        case = refund_service.open_refund_case(
            db, p.tenant_id, p.user_id, booking_id=req.booking_id,
            deductions=[d.model_dump() for d in req.deductions],
            customer_deductions=(
                [d.model_dump() for d in req.customer_deductions]
                if req.customer_deductions is not None else None
            ),
        )
    except refund_service.RefundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _case_out(case)


@router.get("", response_model=list[RefundCaseOut])
def list_cases(p: Principal = Depends(get_current_principal),
               db: Session = Depends(get_db)) -> list[RefundCaseOut]:
    from app.services.scoping import scoped_list
    return [_case_out(c) for c in scoped_list(db, RefundCase, p.tenant_id)]


@router.get("/{case_id}", response_model=RefundCaseOut)
def get_case(case_id: str, p: Principal = Depends(get_current_principal),
             db: Session = Depends(get_db)) -> RefundCaseOut:
    case = scoped_get(db, RefundCase, p.tenant_id, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="refund case not found")
    return _case_out(case)


@router.post("/{case_id}/supplier-refund", response_model=LedgerEntryOut, status_code=201)
def post_supplier_refund(case_id: str, req: PostRefundRequest,
                         p: Principal = Depends(_finance),
                         db: Session = Depends(get_db)) -> LedgerEntryOut:
    return _post(db, p, case_id, req, supplier=True)


@router.post("/{case_id}/customer-refund", response_model=LedgerEntryOut, status_code=201)
def post_customer_refund(case_id: str, req: PostRefundRequest,
                         p: Principal = Depends(_finance),
                         db: Session = Depends(get_db)) -> LedgerEntryOut:
    return _post(db, p, case_id, req, supplier=False)


@router.post("/{case_id}/transition", response_model=RefundCaseOut)
def transition(case_id: str, req: TransitionRequest, p: Principal = Depends(_finance),
               db: Session = Depends(get_db)) -> RefundCaseOut:
    try:
        case = refund_service.transition_status(db, p.tenant_id, p.user_id,
                                                case_id=case_id, new_status=req.new_status)
    except refund_service.RefundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _case_out(case)


@router.get("/{case_id}/ledger", response_model=list[LedgerEntryOut])
def ledger(case_id: str, p: Principal = Depends(get_current_principal),
           db: Session = Depends(get_db)) -> list[LedgerEntryOut]:
    if scoped_get(db, RefundCase, p.tenant_id, case_id) is None:
        raise HTTPException(status_code=404, detail="refund case not found")
    rows = db.scalars(
        select(LedgerEntryRow).where(
            LedgerEntryRow.tenant_id == p.tenant_id,
            LedgerEntryRow.refund_case_id == case_id,
        ).order_by(LedgerEntryRow.created_at)
    ).all()
    return [_entry_out(r) for r in rows]


@router.get("/{case_id}/settlement", response_model=SettlementOut)
def settlement(case_id: str, side: str = "supplier",
               p: Principal = Depends(get_current_principal),
               db: Session = Depends(get_db)) -> SettlementOut:
    if side not in ("supplier", "customer"):
        raise HTTPException(status_code=422, detail="side must be 'supplier' or 'customer'")
    try:
        pos = refund_service.settlement(db, p.tenant_id, case_id=case_id, side=side)
    except refund_service.RefundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SettlementOut(
        side=side, expected=str(pos.expected.amount), received=str(pos.received.amount),
        outstanding=str(pos.outstanding.amount), overpaid=str(pos.overpaid.amount),
        is_settled=pos.is_settled,
    )


def _post(db, p, case_id, req, *, supplier: bool) -> LedgerEntryOut:
    fn = refund_service.post_supplier_refund if supplier else refund_service.post_customer_refund
    try:
        row = fn(db, p.tenant_id, p.user_id, case_id=case_id, amount=req.amount,
                 evidence_ref=req.evidence_ref, external_ref=req.external_ref, memo=req.memo)
    except refund_service.DuplicateLedgerEntry as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except refund_service.RefundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _entry_out(row)


def _case_out(case: RefundCase) -> RefundCaseOut:
    cur = case.currency
    return RefundCaseOut(
        id=case.id, trip_id=case.trip_id, booking_id=case.booking_id, status=case.status,
        currency=cur,
        expected_supplier_refund=str(Money(case.expected_supplier_refund_minor, cur).amount),
        expected_customer_refund=str(Money(case.expected_customer_refund_minor, cur).amount),
        supplier_breakdown=case.supplier_breakdown, customer_breakdown=case.customer_breakdown,
    )


def _entry_out(r: LedgerEntryRow) -> LedgerEntryOut:
    return LedgerEntryOut(
        id=r.id, account=r.account, entry_type=r.entry_type,
        amount=str(Money(r.amount_minor, r.currency).amount), currency=r.currency,
        evidence_ref=r.evidence_ref, external_ref=r.external_ref,
    )
