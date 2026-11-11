"""Reconciliation batch, record and discrepancy models (spec §8, Modules E/G).

Match information is stored on the record (one-to-one matching), avoiding a
separate join table while keeping every matched pair auditable. Discrepancies are
first-class rows with severity, evidence and a resolution status so operations can
work them like a queue.
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy import BigInteger, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base
from app.models.base import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ReconciliationBatch(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "reconciliation_batches"

    source: Mapped[str] = mapped_column(String(20), default="BANK")  # BANK/GATEWAY/SUPPLIER/OTHER
    filename: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="COMPLETED")
    record_count: Mapped[int] = mapped_column(BigInteger, default=0)
    matched_count: Mapped[int] = mapped_column(BigInteger, default=0)
    discrepancy_count: Mapped[int] = mapped_column(BigInteger, default=0)
    accuracy: Mapped[str] = mapped_column(String(8), default="1.00")


class ReconciliationRecord(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "reconciliation_records"

    batch_id: Mapped[str] = mapped_column(String(32), ForeignKey("reconciliation_batches.id"),
                                          index=True, nullable=False)
    row_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(255))
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    value_date: Mapped[_dt.date | None] = mapped_column(Date)
    counterparty: Mapped[str | None] = mapped_column(String(200))
    booking_ref: Mapped[str | None] = mapped_column(String(64))
    raw: Mapped[dict | None] = mapped_column(JSON)
    # match outcome
    matched: Mapped[bool] = mapped_column(default=False)
    match_strategy: Mapped[str | None] = mapped_column(String(20))
    match_confidence: Mapped[str | None] = mapped_column(String(8))
    matched_entry_id: Mapped[str | None] = mapped_column(String(32))


class Discrepancy(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "discrepancies"

    batch_id: Mapped[str | None] = mapped_column(String(32),
                                                 ForeignKey("reconciliation_batches.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="MEDIUM")  # LOW/MEDIUM/HIGH
    external_row_id: Mapped[str | None] = mapped_column(String(32))
    expected_entry_id: Mapped[str | None] = mapped_column(String(32))
    expected_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    observed_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    difference_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    detail: Mapped[str] = mapped_column(Text, default="")
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN/RESOLVED/IGNORED
