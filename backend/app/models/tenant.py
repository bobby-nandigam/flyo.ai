"""Tenant and user models (spec §8: tenants, users, roles)."""
from __future__ import annotations

from enum import Enum

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Role(str, Enum):
    OWNER = "OWNER"          # full control of the tenant
    FINANCE = "FINANCE"      # ledger, reconciliation, refunds
    OPS = "OPS"              # trips, bookings, documents
    SUPPORT = "SUPPORT"      # read + customer comms
    READ_ONLY = "READ_ONLY"  # dashboards only


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)

    # Not using TenantScopedMixin's FK-only column here because we also index email
    # per tenant; declare tenant_id explicitly.
    tenant_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(String(20), default=Role.OWNER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
