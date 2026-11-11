"""Trip, customer, supplier and booking use-cases — all tenant-scoped."""
from __future__ import annotations

import datetime as _dt

from sqlalchemy.orm import Session

from app.domain.money import Money
from app.models.trip import Booking, Customer, ServiceType, Supplier, SupplierType, Trip
from app.services import audit
from app.services.scoping import scoped_get


class NotFound(Exception):
    pass


def create_customer(db: Session, tenant_id: str, *, name: str, email: str | None = None,
                    phone: str | None = None) -> Customer:
    c = Customer(tenant_id=tenant_id, name=name, email=email, phone=phone)
    db.add(c)
    db.commit()
    return c


def create_supplier(db: Session, tenant_id: str, *, name: str,
                    supplier_type: SupplierType = SupplierType.OTHER,
                    contact_email: str | None = None) -> Supplier:
    s = Supplier(tenant_id=tenant_id, name=name, supplier_type=supplier_type,
                 contact_email=contact_email)
    db.add(s)
    db.commit()
    return s


def create_trip(db: Session, tenant_id: str, user_id: str, *, reference: str,
                customer_id: str, currency: str = "INR",
                booking_date: _dt.date | None = None,
                travel_start: _dt.date | None = None,
                travel_end: _dt.date | None = None) -> Trip:
    if scoped_get(db, Customer, tenant_id, customer_id) is None:
        raise NotFound("customer not found")
    trip = Trip(
        tenant_id=tenant_id, reference=reference, customer_id=customer_id,
        currency=currency, booking_date=booking_date,
        travel_start=travel_start, travel_end=travel_end,
    )
    db.add(trip)
    db.flush()
    audit.record(db, tenant_id=tenant_id, user_id=user_id, action="trip.create",
                 entity_type="trip", entity_id=trip.id, detail={"reference": reference})
    db.commit()
    return trip


def add_booking(db: Session, tenant_id: str, user_id: str, *, trip_id: str,
                supplier_id: str, booking_reference: str,
                service_type: ServiceType, original_amount: str,
                currency: str = "INR") -> Booking:
    if scoped_get(db, Trip, tenant_id, trip_id) is None:
        raise NotFound("trip not found")
    if scoped_get(db, Supplier, tenant_id, supplier_id) is None:
        raise NotFound("supplier not found")
    amount = Money.from_decimal(original_amount, currency)  # validates/normalises
    booking = Booking(
        tenant_id=tenant_id, trip_id=trip_id, supplier_id=supplier_id,
        booking_reference=booking_reference, service_type=service_type,
        currency=currency, original_amount_minor=amount.minor_units,
    )
    db.add(booking)
    db.flush()
    audit.record(db, tenant_id=tenant_id, user_id=user_id, action="booking.create",
                 entity_type="booking", entity_id=booking.id,
                 detail={"trip_id": trip_id, "amount": str(amount.amount)})
    db.commit()
    return booking
