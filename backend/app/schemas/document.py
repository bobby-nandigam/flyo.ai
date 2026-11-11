from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.domain.policy import PenaltyBasis


class DocumentIngestRequest(BaseModel):
    content_text: str = Field(min_length=1)
    filename: str = ""
    doc_type: str = "CANCELLATION"
    trip_id: Optional[str] = None
    currency: str = "INR"


class ExtractionOut(BaseModel):
    document_id: str
    extracted: Optional[dict]
    verified: bool
    verified_amount: Optional[str] = None
    verified_booking_ref: Optional[str] = None


class DocumentOut(BaseModel):
    id: str
    filename: str
    doc_type: str
    status: str
    trip_id: Optional[str] = None
    extraction: Optional[ExtractionOut] = None


class VerifyRequest(BaseModel):
    amount: Optional[str] = None
    booking_ref: Optional[str] = None
    currency: str = "INR"


class PolicyTierIn(BaseModel):
    min_days_before: int
    basis: PenaltyBasis = PenaltyBasis.FIXED
    fixed_amount: str = "0"
    percent: str = "0"
    label: str = "Cancellation penalty"


class PolicyCreate(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    currency: str = "INR"
    tiers: List[PolicyTierIn] = Field(min_length=1)
    non_refundable_fixed: str = "0"
    non_refundable_label: str = "Non-refundable fee"
    supplier_id: Optional[str] = None


class PolicyOut(BaseModel):
    id: str
    version: str
    currency: str
    tiers: list
    non_refundable_fixed: str


class PolicyQuoteRequest(BaseModel):
    booking_id: str
    policy_version: str
    days_before_travel: int
