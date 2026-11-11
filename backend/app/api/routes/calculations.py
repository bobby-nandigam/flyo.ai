"""Refund calculation API — a thin HTTP layer over the pure domain engine.

Deliberately stateless: it validates input, calls the deterministic engine, and
returns the itemised, auditable breakdown. No database row is written here; the
calculation is a preview that the caller can later commit to a refund case.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.domain.money import Money, MoneyError
from app.domain.calculation import (
    LineItem,
    CalculationError,
    compute_supplier_refund,
    compute_customer_refund,
)
from app.schemas.calculation import RefundCalcRequest, RefundCalcResponse

router = APIRouter(prefix="/calculations", tags=["calculations"])


@router.post("/refund", response_model=RefundCalcResponse)
def calculate_refund(req: RefundCalcRequest) -> RefundCalcResponse:
    try:
        lines = [
            LineItem(
                kind=li.kind,
                label=li.label,
                amount=Money.from_decimal(li.amount, req.currency),
                evidence_ref=li.evidence_ref,
            )
            for li in req.lines
        ]
        engine = (
            compute_supplier_refund if req.scope == "supplier" else compute_customer_refund
        )
        result = engine(lines, req.currency)
    except (CalculationError, MoneyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    audit = result.to_audit_dict()
    return RefundCalcResponse(**audit)
