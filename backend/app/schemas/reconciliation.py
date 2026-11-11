from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ImportRow(BaseModel):
    row_ref: Optional[str] = None
    external_ref: Optional[str] = None
    amount: str
    currency: str = "INR"
    value_date: Optional[str] = None
    counterparty: Optional[str] = None
    booking_ref: Optional[str] = None


class ImportRequest(BaseModel):
    source: str = Field(default="BANK")
    filename: str = ""
    # Provide either structured rows or raw CSV text.
    rows: Optional[List[ImportRow]] = None
    csv_text: Optional[str] = None
    date_window_days: int = 5


class BatchOut(BaseModel):
    id: str
    source: str
    filename: str
    status: str
    record_count: int
    matched_count: int
    discrepancy_count: int
    accuracy: str


class RecordOut(BaseModel):
    id: str
    row_ref: str
    external_ref: Optional[str]
    amount: str
    currency: str
    matched: bool
    match_strategy: Optional[str]
    match_confidence: Optional[str]
    matched_entry_id: Optional[str]


class DiscrepancyOut(BaseModel):
    id: str
    kind: str
    severity: str
    expected_amount: Optional[str]
    observed_amount: Optional[str]
    difference: Optional[str]
    currency: str
    detail: str
    recommended_action: str
    status: str


class BatchDetailOut(BatchOut):
    records: List[RecordOut]
    discrepancies: List[DiscrepancyOut]


class ResolveDiscrepancyRequest(BaseModel):
    status: str = Field(pattern="^(OPEN|RESOLVED|IGNORED)$")
