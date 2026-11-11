from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class InvestigationOut(BaseModel):
    id: str
    refund_case_id: str
    summary: str
    severity: str
    evidence_complete: bool
    findings: list
    recommended_actions: list
    engine: str


class CommunicationOut(BaseModel):
    id: str
    refund_case_id: Optional[str]
    audience: str
    channel: str
    body: str
    status: str


class CommunicationStatusRequest(BaseModel):
    status: str = Field(pattern="^(DRAFT|APPROVED|SENT)$")
