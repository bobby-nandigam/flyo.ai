from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.domain.calculation import LineKind
from app.domain.refund_status import RefundStatus


class DeductionLine(BaseModel):
    kind: LineKind
    label: str = Field(min_length=1, max_length=200)
    amount: str
    evidence_ref: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def _non_negative(cls, v: str) -> str:
        if Decimal(v) < 0:
            raise ValueError("amount must be a non-negative magnitude")
        return v


class OpenCaseRequest(BaseModel):
    booking_id: str
    deductions: List[DeductionLine] = Field(default_factory=list)
    customer_deductions: Optional[List[DeductionLine]] = None


class RefundCaseOut(BaseModel):
    id: str
    trip_id: str
    booking_id: str
    status: str
    currency: str
    expected_supplier_refund: str
    expected_customer_refund: str
    supplier_breakdown: Optional[dict] = None
    customer_breakdown: Optional[dict] = None


class PostRefundRequest(BaseModel):
    amount: str
    evidence_ref: str = Field(min_length=1)
    external_ref: Optional[str] = None
    memo: str = ""


class TransitionRequest(BaseModel):
    new_status: RefundStatus


class LedgerEntryOut(BaseModel):
    id: str
    account: str
    entry_type: str
    amount: str
    currency: str
    evidence_ref: str
    external_ref: Optional[str] = None


class SettlementOut(BaseModel):
    side: str
    expected: str
    received: str
    outstanding: str
    overpaid: str
    is_settled: bool
