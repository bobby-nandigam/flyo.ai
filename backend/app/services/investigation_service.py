"""Investigation + communication use-cases (spec Modules H/I).

Gathers a factual dossier for a refund case from the database, runs the pure
deterministic investigation engine, and persists the report. The agent is
read-only over financial data: it can create an investigation report and a *draft*
communication, but it never writes the ledger, changes a refund amount, or sends a
message — consequential actions require explicit human steps.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.investigation import (
    CaseDossier,
    DiscrepancyFact,
    investigate,
    supplier_followup_draft,
)
from app.domain.money import Money
from app.models.document import Document
from app.models.investigation import InvestigationReport, SupplierCommunication
from app.models.reconciliation import Discrepancy
from app.models.refund import LedgerEntryRow, RefundCase
from app.models.trip import Booking, Supplier
from app.services import audit
from app.services.scoping import scoped_get


class InvestigationError(Exception):
    pass


def _build_dossier(db: Session, tenant_id: str, case: RefundCase) -> CaseDossier:
    currency = case.currency

    def _received(account: str) -> Money:
        rows = db.scalars(select(LedgerEntryRow).where(
            LedgerEntryRow.tenant_id == tenant_id,
            LedgerEntryRow.refund_case_id == case.id,
            LedgerEntryRow.account == account)).all()
        return Money(abs(sum(r.amount_minor for r in rows)), currency)

    supplier_name = None
    booking = scoped_get(db, Booking, tenant_id, case.booking_id)
    if booking is not None:
        sup = scoped_get(db, Supplier, tenant_id, booking.supplier_id)
        supplier_name = sup.name if sup else None

    # Discrepancies linked to this case's trip (by expected_entry on its ledger).
    case_entry_ids = {r.id for r in db.scalars(select(LedgerEntryRow).where(
        LedgerEntryRow.tenant_id == tenant_id,
        LedgerEntryRow.refund_case_id == case.id)).all()}
    disc_rows = db.scalars(select(Discrepancy).where(
        Discrepancy.tenant_id == tenant_id, Discrepancy.status == "OPEN")).all()
    facts = []
    for dr in disc_rows:
        # Link only discrepancies that point at one of this case's ledger entries.
        if dr.expected_entry_id in case_entry_ids:
            amt = Money(dr.observed_amount_minor or dr.expected_amount_minor or 0, dr.currency)
            facts.append(DiscrepancyFact(dr.kind, amt, dr.detail,
                                         evidence_ref=f"discrepancy:{dr.id}"))

    has_docs = db.scalar(select(Document).where(
        Document.tenant_id == tenant_id, Document.trip_id == case.trip_id)) is not None

    return CaseDossier(
        case_id=case.id, currency=currency, status=case.status,
        expected_supplier=Money(case.expected_supplier_refund_minor, currency),
        supplier_received=_received("SUPPLIER"),
        expected_customer=Money(case.expected_customer_refund_minor, currency),
        customer_paid=_received("CUSTOMER"),
        discrepancies=tuple(facts), has_documents=has_docs, supplier_name=supplier_name,
    )


def run_investigation(db: Session, tenant_id: str, user_id: str, *, case_id: str) -> InvestigationReport:
    case = scoped_get(db, RefundCase, tenant_id, case_id)
    if case is None:
        raise InvestigationError("refund case not found")

    dossier = _build_dossier(db, tenant_id, case)
    result = investigate(dossier)

    report = InvestigationReport(
        tenant_id=tenant_id, refund_case_id=case.id, summary=result.summary,
        severity=result.severity.value, evidence_complete=result.evidence_complete,
        findings=result.to_dict()["findings"],
        recommended_actions=list(result.recommended_actions), engine="deterministic",
    )
    db.add(report)
    audit.record(db, tenant_id=tenant_id, user_id=user_id, action="investigation.run",
                 entity_type="investigation_report", entity_id=case.id,
                 detail={"severity": result.severity.value, "findings": len(result.findings)})
    db.commit()
    return report


def draft_supplier_followup(db: Session, tenant_id: str, user_id: str, *, case_id: str
                            ) -> SupplierCommunication:
    case = scoped_get(db, RefundCase, tenant_id, case_id)
    if case is None:
        raise InvestigationError("refund case not found")
    dossier = _build_dossier(db, tenant_id, case)
    body = supplier_followup_draft(dossier)
    booking = scoped_get(db, Booking, tenant_id, case.booking_id)
    comm = SupplierCommunication(
        tenant_id=tenant_id, refund_case_id=case.id,
        supplier_id=(booking.supplier_id if booking else None),
        channel="EMAIL", audience="SUPPLIER", body=body, status="DRAFT",
    )
    db.add(comm)
    audit.record(db, tenant_id=tenant_id, user_id=user_id, action="communication.draft",
                 entity_type="supplier_communication", entity_id=case.id, detail={})
    db.commit()
    return comm


def set_communication_status(db: Session, tenant_id: str, user_id: str, *, comm_id: str,
                             status: str) -> SupplierCommunication:
    comm = scoped_get(db, SupplierCommunication, tenant_id, comm_id)
    if comm is None:
        raise InvestigationError("communication not found")
    # "SENT" here records that a human sent it out of band; we do not transmit.
    comm.status = status
    audit.record(db, tenant_id=tenant_id, user_id=user_id, action="communication.status",
                 entity_type="supplier_communication", entity_id=comm.id, detail={"status": status})
    db.commit()
    return comm
