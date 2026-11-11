"""Pydantic request/response schemas for the refund calculation API.

Amounts cross the wire as strings (e.g. ``"10000.00"``) so no float ever touches
a monetary value, matching the domain layer's Decimal-only rule.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.domain.calculation import LineKind


class LineItemIn(BaseModel):
    kind: LineKind
    label: str = Field(min_length=1, max_length=200)
    amount: str = Field(description="Non-negative magnitude as a decimal string")
    evidence_ref: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def _valid_decimal(cls, v: str) -> str:
        try:
            dec = Decimal(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"amount {v!r} is not a valid decimal") from exc
        if dec < 0:
            raise ValueError("amount must be a non-negative magnitude")
        return v


class RefundCalcRequest(BaseModel):
    currency: str = Field(default="INR", min_length=3, max_length=3)
    scope: Literal["supplier", "customer"] = "supplier"
    lines: List[LineItemIn] = Field(min_length=1)


class LineItemOut(BaseModel):
    kind: str
    label: str
    amount: str
    signed: str
    evidence_ref: Optional[str]


class RefundCalcResponse(BaseModel):
    scope: str
    currency: str
    total: str
    clamped: bool
    lines: List[LineItemOut]
