"""Document intelligence + policy routes (spec Modules B/C)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, get_current_principal, require_roles
from app.domain.money import Money
from app.models.document import CancellationPolicyRow, Document, DocumentExtraction
from app.models.tenant import Role
from app.schemas.document import (
    DocumentIngestRequest,
    DocumentOut,
    ExtractionOut,
    PolicyCreate,
    PolicyOut,
    PolicyQuoteRequest,
    VerifyRequest,
)
from app.services import document_service
from app.services.scoping import scoped_get, scoped_list

router = APIRouter(tags=["documents"])
_ops = require_roles(Role.OWNER, Role.FINANCE, Role.OPS)


@router.post("/documents", response_model=DocumentOut, status_code=201)
def ingest(req: DocumentIngestRequest, p: Principal = Depends(_ops),
           db: Session = Depends(get_db)) -> DocumentOut:
    try:
        doc, extraction = document_service.ingest_text_document(
            db, p.tenant_id, p.user_id, content_text=req.content_text, filename=req.filename,
            doc_type=req.doc_type, trip_id=req.trip_id, currency=req.currency)
    except document_service.DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _doc_out(doc, extraction)


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(p: Principal = Depends(get_current_principal),
                   db: Session = Depends(get_db)) -> list[DocumentOut]:
    out = []
    for doc in scoped_list(db, Document, p.tenant_id):
        ex = db.scalar(select(DocumentExtraction).where(
            DocumentExtraction.tenant_id == p.tenant_id,
            DocumentExtraction.document_id == doc.id))
        out.append(_doc_out(doc, ex))
    return out


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, p: Principal = Depends(get_current_principal),
                 db: Session = Depends(get_db)) -> DocumentOut:
    doc = scoped_get(db, Document, p.tenant_id, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    ex = db.scalar(select(DocumentExtraction).where(
        DocumentExtraction.tenant_id == p.tenant_id,
        DocumentExtraction.document_id == doc.id))
    return _doc_out(doc, ex)


@router.post("/documents/{document_id}/verify", response_model=DocumentOut)
def verify(document_id: str, req: VerifyRequest, p: Principal = Depends(_ops),
           db: Session = Depends(get_db)) -> DocumentOut:
    try:
        document_service.verify_extraction(
            db, p.tenant_id, p.user_id, document_id=document_id, amount=req.amount,
            booking_ref=req.booking_ref, currency=req.currency)
    except document_service.DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return get_document(document_id, p, db)


# ----------------------- policies ----------------------- #
@router.post("/policies", response_model=PolicyOut, status_code=201)
def create_policy(req: PolicyCreate, p: Principal = Depends(require_roles(Role.OWNER, Role.FINANCE)),
                  db: Session = Depends(get_db)) -> PolicyOut:
    try:
        row = document_service.create_policy(
            db, p.tenant_id, p.user_id, version=req.version,
            tiers=[t.model_dump() for t in req.tiers], currency=req.currency,
            non_refundable_fixed=req.non_refundable_fixed,
            non_refundable_label=req.non_refundable_label, supplier_id=req.supplier_id)
    except document_service.DocumentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _policy_out(row)


@router.get("/policies", response_model=list[PolicyOut])
def list_policies(p: Principal = Depends(get_current_principal),
                  db: Session = Depends(get_db)) -> list[PolicyOut]:
    return [_policy_out(r) for r in scoped_list(db, CancellationPolicyRow, p.tenant_id)]


@router.post("/policies/quote")
def quote(req: PolicyQuoteRequest, p: Principal = Depends(require_roles(Role.OWNER, Role.FINANCE)),
          db: Session = Depends(get_db)) -> dict:
    try:
        return document_service.quote_from_policy(
            db, p.tenant_id, booking_id=req.booking_id, policy_version=req.policy_version,
            days_before_travel=req.days_before_travel)
    except document_service.DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _doc_out(doc: Document, ex: DocumentExtraction | None) -> DocumentOut:
    extraction = None
    if ex is not None:
        amt = (str(Money(ex.verified_amount_minor, ex.verified_currency or "INR").amount)
               if ex.verified_amount_minor is not None else None)
        extraction = ExtractionOut(document_id=doc.id, extracted=ex.extracted,
                                   verified=ex.verified, verified_amount=amt,
                                   verified_booking_ref=ex.verified_booking_ref)
    return DocumentOut(id=doc.id, filename=doc.filename, doc_type=doc.doc_type,
                       status=doc.status, trip_id=doc.trip_id, extraction=extraction)


def _policy_out(r: CancellationPolicyRow) -> PolicyOut:
    return PolicyOut(id=r.id, version=r.version, currency=r.currency, tiers=r.tiers,
                     non_refundable_fixed=r.non_refundable_fixed)
