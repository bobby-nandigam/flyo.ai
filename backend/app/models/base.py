"""Shared model mixins: UUID primary keys, timestamps, tenant scoping."""
from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column


def new_uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class UUIDPrimaryKeyMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TenantScopedMixin:
    """Every tenant-owned row carries ``tenant_id``.

    This column is the spine of tenant isolation (invariant #7). The service layer
    never issues a query against a tenant-scoped table without filtering on it; see
    ``app/services/scoping.py``.
    """

    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), index=True, nullable=False
    )
