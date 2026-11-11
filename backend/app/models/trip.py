"""Customer, supplier, trip and booking models (spec Module A, §8).

Money is persisted as integer *minor units* + an ISO currency code — the exact
same representation the domain `Money` object uses — so no float ever reaches the
database and values round-trip losslessly.
"""
from __future__ import annotations

import datetime as _dt
from enum import Enum

from sqlalchemy import BigInteger, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SupplierType(str, Enum):
    AIRLINE = "AIRLINE"
    HOTEL = "HOTEL"
    TRANSPORT = "TRANSPORT"
    OTA = "OTA"
    OTHER = "OTHER"


class ServiceType(str, Enum):
    FLIGHT = "FLIGHT"
    HOTEL = "HOTEL"
    CAB = "CAB"
    BUS = "BUS"
    OTHER = "OTHER"


class TripStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class Customer(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))


class Supplier(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_type: Mapped[SupplierType] = mapped_column(String(20), default=SupplierType.OTHER)
    contact_email: Mapped[str | None] = mapped_column(String(255))


class Trip(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "trips"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_trip_tenant_reference"),
    )

    reference: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(String(32), ForeignKey("customers.id"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[TripStatus] = mapped_column(String(20), default=TripStatus.ACTIVE)
    booking_date: Mapped[_dt.date | None] = mapped_column(Date)
    travel_start: Mapped[_dt.date | None] = mapped_column(Date)
    travel_end: Mapped[_dt.date | None] = mapped_column(Date)
    cancellation_date: Mapped[_dt.date | None] = mapped_column(Date)


class Booking(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "bookings"

    trip_id: Mapped[str] = mapped_column(String(32), ForeignKey("trips.id"), nullable=False, index=True)
    supplier_id: Mapped[str] = mapped_column(String(32), ForeignKey("suppliers.id"), nullable=False)
    booking_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    service_type: Mapped[ServiceType] = mapped_column(String(20), default=ServiceType.OTHER)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    original_amount_minor: Mapped[int] = mapped_column(BigInteger, default=0)
