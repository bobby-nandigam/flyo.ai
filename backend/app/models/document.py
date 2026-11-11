"""Document, extraction and cancellation-policy models (spec Modules B/C, §8)."""
from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base
from app.models.base import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Document(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    filename: Mapped[str] = mapped_column(String(255), default="")
    doc_type: Mapped[str] = mapped_column(String(40), default="OTHER")  # CANCELLATION/INVOICE/...
    trip_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("trips.id"), index=True)
    content_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="EXTRACTED")  # EXTRACTED/VERIFIED


class DocumentExtraction(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "document_extractions"

    document_id: Mapped[str] = mapped_column(String(32), ForeignKey("documents.id"),
                                             index=True, nullable=False)
    extracted: Mapped[dict | None] = mapped_column(JSON)
    verified: Mapped[bool] = mapped_column(default=False)
    verified_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    verified_currency: Mapped[str | None] = mapped_column(String(3))
    verified_booking_ref: Mapped[str | None] = mapped_column(String(64))


class CancellationPolicyRow(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "cancellation_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version", name="uq_policy_tenant_version"),
    )

    version: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("suppliers.id"))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    tiers: Mapped[list] = mapped_column(JSON)  # list of tier dicts
    non_refundable_fixed: Mapped[str] = mapped_column(String(20), default="0")
    non_refundable_label: Mapped[str] = mapped_column(String(120), default="Non-refundable fee")
    source_document_id: Mapped[str | None] = mapped_column(String(32))
