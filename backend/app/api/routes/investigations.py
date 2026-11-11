"""Investigation + supplier communication routes (spec Modules H/I)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, get_current_principal, require_roles
from app.models.investigation import InvestigationReport, SupplierCommunication
from app.models.tenant import Role
from app.schemas.investigation import (
    CommunicationOut,
    CommunicationStatusRequest,
    InvestigationOut,
)
from app.services import investigation_service
from app.services.scoping import scoped_get

router = APIRouter(tags=["investigations"])
_finance = require_roles(Role.OWNER, Role.FINANCE)


@router.post("/refund-cases/{case_id}/investigate", response_model=InvestigationOut, status_code=201)
def investigate(case_id: str, p: Principal = Depends(_finance),
                db: Session = Depends(get_db)) -> InvestigationOut:
    try:
        report = investigation_service.run_investigation(db, p.tenant_id, p.user_id, case_id=case_id)
    except investigation_service.InvestigationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _report_out(report)


@router.get("/refund-cases/{case_id}/investigations", response_model=list[InvestigationOut])
def list_investigations(case_id: str, p: Principal = Depends(get_current_principal),
                        db: Session = Depends(get_db)) -> list[InvestigationOut]:
    rows = db.scalars(select(InvestigationReport).where(
        InvestigationReport.tenant_id == p.tenant_id,
        InvestigationReport.refund_case_id == case_id).order_by(
        InvestigationReport.created_at.desc())).all()
    return [_report_out(r) for r in rows]


@router.post("/refund-cases/{case_id}/followup-draft", response_model=CommunicationOut, status_code=201)
def followup_draft(case_id: str, p: Principal = Depends(_finance),
                   db: Session = Depends(get_db)) -> CommunicationOut:
    try:
        comm = investigation_service.draft_supplier_followup(db, p.tenant_id, p.user_id, case_id=case_id)
    except investigation_service.InvestigationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _comm_out(comm)


@router.get("/communications", response_model=list[CommunicationOut])
def list_communications(p: Principal = Depends(get_current_principal),
                        db: Session = Depends(get_db)) -> list[CommunicationOut]:
    from app.services.scoping import scoped_list
    return [_comm_out(c) for c in scoped_list(db, SupplierCommunication, p.tenant_id)]


@router.post("/communications/{comm_id}/status", response_model=CommunicationOut)
def set_status(comm_id: str, req: CommunicationStatusRequest, p: Principal = Depends(_finance),
               db: Session = Depends(get_db)) -> CommunicationOut:
    try:
        comm = investigation_service.set_communication_status(
            db, p.tenant_id, p.user_id, comm_id=comm_id, status=req.status)
    except investigation_service.InvestigationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _comm_out(comm)


def _report_out(r: InvestigationReport) -> InvestigationOut:
    return InvestigationOut(id=r.id, refund_case_id=r.refund_case_id, summary=r.summary,
                            severity=r.severity, evidence_complete=r.evidence_complete,
                            findings=r.findings or [], recommended_actions=r.recommended_actions or [],
                            engine=r.engine)


def _comm_out(c: SupplierCommunication) -> CommunicationOut:
    return CommunicationOut(id=c.id, refund_case_id=c.refund_case_id, audience=c.audience,
                            channel=c.channel, body=c.body, status=c.status)
