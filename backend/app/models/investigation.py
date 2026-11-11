"""Investigation report and supplier communication models (spec Modules H/I, §8)."""
from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base
from app.models.base import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class InvestigationReport(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "investigation_reports"

    refund_case_id: Mapped[str] = mapped_column(String(32), ForeignKey("refund_cases.id"),
                                                index=True, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(10), default="LOW")
    evidence_complete: Mapped[bool] = mapped_column(default=False)
    findings: Mapped[list | None] = mapped_column(JSON)
    recommended_actions: Mapped[list | None] = mapped_column(JSON)
    engine: Mapped[str] = mapped_column(String(20), default="deterministic")  # or "llm"


class SupplierCommunication(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "supplier_communications"

    refund_case_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("refund_cases.id"),
                                                       index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(32))
    channel: Mapped[str] = mapped_column(String(20), default="EMAIL")  # EMAIL/WHATSAPP
    audience: Mapped[str] = mapped_column(String(20), default="SUPPLIER")  # SUPPLIER/CUSTOMER
    body: Mapped[str] = mapped_column(Text, default="")
    # Drafts are never auto-sent; a human approves first (spec Module I).
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")  # DRAFT/APPROVED/SENT
