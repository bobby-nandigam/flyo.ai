"""Refund case, persisted ledger entries, and audit log (spec Modules D/F, §8).

``LedgerEntryRow`` is the durable form of ``domain.ledger.LedgerEntry``. The table
is **append-only**: the application role is granted INSERT/SELECT only (see
docs/ARCHITECTURE.md §Security). Corrections are new REVERSAL rows, never UPDATEs.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base
from app.models.base import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class RefundCase(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "refund_cases"

    trip_id: Mapped[str] = mapped_column(String(32), ForeignKey("trips.id"), nullable=False, index=True)
    booking_id: Mapped[str] = mapped_column(String(32), ForeignKey("bookings.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    expected_supplier_refund_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    expected_customer_refund_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    # Itemised, evidence-tagged breakdown from the domain engine, stored verbatim
    # for audit (spec §4: every conclusion must have supporting evidence).
    supplier_breakdown: Mapped[dict | None] = mapped_column(JSON)
    customer_breakdown: Mapped[dict | None] = mapped_column(JSON)


class LedgerEntryRow(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "financial_ledger"
    __table_args__ = (
        # Idempotency guard mirroring domain invariant #1 at the storage layer.
        UniqueConstraint("tenant_id", "external_ref", name="uq_ledger_tenant_external_ref"),
    )

    trip_id: Mapped[str] = mapped_column(String(32), ForeignKey("trips.id"), nullable=False, index=True)
    refund_case_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("refund_cases.id"), index=True)
    account: Mapped[str] = mapped_column(String(20), nullable=False)       # SUPPLIER / CUSTOMER
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)  # signed
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(255))
    reverses_id: Mapped[str | None] = mapped_column(String(32))
    memo: Mapped[str] = mapped_column(String(500), default="")


class AuditLog(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
