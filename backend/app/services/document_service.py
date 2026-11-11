"""Document ingestion + extraction, and policy quoting (spec Modules B/C)."""
from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.calculation import LineItem, LineKind, compute_supplier_refund
from app.domain.extraction import extract
from app.domain.money import Money
from app.domain.policy import (
    CancellationPolicy,
    PenaltyBasis,
    PolicyTier,
    deduction_lines,
)
from app.models.document import CancellationPolicyRow, Document, DocumentExtraction
from app.models.trip import Booking, Supplier
from app.services import audit
from app.services.scoping import scoped_get, scoped_list


class DocumentError(Exception):
    pass


def ingest_text_document(
    db: Session, tenant_id: str, user_id: str, *, content_text: str,
    filename: str = "", doc_type: str = "CANCELLATION", trip_id: str | None = None,
    currency: str = "INR",
) -> tuple[Document, DocumentExtraction]:
    if not content_text.strip():
        raise DocumentError("document has no text content")

    known = [s.name for s in scoped_list(db, Supplier, tenant_id)]
    result = extract(content_text, currency=currency, known_suppliers=known)

    doc = Document(tenant_id=tenant_id, filename=filename, doc_type=doc_type,
                   trip_id=trip_id, content_text=content_text, status="EXTRACTED")
    db.add(doc)
    db.flush()
    extraction = DocumentExtraction(tenant_id=tenant_id, document_id=doc.id,
                                    extracted=result.to_dict())
    db.add(extraction)
    audit.record(db, tenant_id=tenant_id, user_id=user_id, action="document.ingest",
                 entity_type="document", entity_id=doc.id,
                 detail={"doc_type": doc_type, "has_amount": bool(result.best_amount())})
    db.commit()
    return doc, extraction


def verify_extraction(
    db: Session, tenant_id: str, user_id: str, *, document_id: str,
    amount: str | None, booking_ref: str | None, currency: str = "INR",
) -> DocumentExtraction:
    doc = scoped_get(db, Document, tenant_id, document_id)
    if doc is None:
        raise DocumentError("document not found")
    extraction = db.scalar(
        select(DocumentExtraction).where(
            DocumentExtraction.tenant_id == tenant_id,
            DocumentExtraction.document_id == document_id,
        )
    )
    if extraction is None:
        raise DocumentError("extraction not found")
    if amount is not None:
        extraction.verified_amount_minor = Money.from_decimal(amount, currency).minor_units
        extraction.verified_currency = currency
    if booking_ref is not None:
        extraction.verified_booking_ref = booking_ref
    extraction.verified = True
    doc.status = "VERIFIED"
    audit.record(db, tenant_id=tenant_id, user_id=user_id, action="document.verify",
                 entity_type="document", entity_id=doc.id,
                 detail={"amount": amount, "booking_ref": booking_ref})
    db.commit()
    return extraction


# --------------------------- policies --------------------------- #
def create_policy(
    db: Session, tenant_id: str, user_id: str, *, version: str, tiers: Sequence[dict],
    currency: str = "INR", non_refundable_fixed: str = "0",
    non_refundable_label: str = "Non-refundable fee", supplier_id: str | None = None,
) -> CancellationPolicyRow:
    if db.scalar(select(CancellationPolicyRow).where(
            CancellationPolicyRow.tenant_id == tenant_id,
            CancellationPolicyRow.version == version)):
        raise DocumentError(f"policy version {version!r} already exists")
    row = CancellationPolicyRow(
        tenant_id=tenant_id, version=version, currency=currency, tiers=list(tiers),
        non_refundable_fixed=non_refundable_fixed, non_refundable_label=non_refundable_label,
        supplier_id=supplier_id,
    )
    db.add(row)
    audit.record(db, tenant_id=tenant_id, user_id=user_id, action="policy.create",
                 entity_type="cancellation_policy", entity_id=version, detail={"version": version})
    db.commit()
    return row


def _to_domain_policy(row: CancellationPolicyRow) -> CancellationPolicy:
    tiers = [
        PolicyTier(
            min_days_before=int(t["min_days_before"]),
            basis=PenaltyBasis(t.get("basis", "FIXED")),
            fixed_amount=str(t.get("fixed_amount", "0")),
            percent=str(t.get("percent", "0")),
            label=t.get("label", "Cancellation penalty"),
        )
        for t in row.tiers
    ]
    return CancellationPolicy(
        version=row.version, currency=row.currency, tiers=tiers,
        non_refundable_fixed=row.non_refundable_fixed,
        non_refundable_label=row.non_refundable_label,
    )


def quote_from_policy(
    db: Session, tenant_id: str, *, booking_id: str, policy_version: str,
    days_before_travel: int,
) -> dict:
    """Compute the expected supplier refund for a booking using a stored policy."""
    booking = scoped_get(db, Booking, tenant_id, booking_id)
    if booking is None:
        raise DocumentError("booking not found")
    row = db.scalar(select(CancellationPolicyRow).where(
        CancellationPolicyRow.tenant_id == tenant_id,
        CancellationPolicyRow.version == policy_version))
    if row is None:
        raise DocumentError("policy not found")

    policy = _to_domain_policy(row)
    original = Money(booking.original_amount_minor, booking.currency)
    lines = [LineItem(LineKind.ORIGINAL, "Original booking amount", original,
                      evidence_ref=f"booking:{booking.id}")]
    lines += deduction_lines(policy, original, days_before_travel)
    result = compute_supplier_refund(lines, booking.currency)
    return {
        "booking_id": booking_id,
        "policy_version": policy_version,
        "days_before_travel": days_before_travel,
        "expected_supplier_refund": str(result.total.amount),
        "breakdown": result.to_audit_dict(),
    }
