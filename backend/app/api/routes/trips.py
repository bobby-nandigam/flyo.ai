"""Customer, supplier, trip and booking routes — all tenant-scoped."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, get_current_principal
from app.domain.money import Money
from app.models.trip import Booking, Customer, Supplier, Trip
from app.schemas.trip import (
    BookingCreate,
    BookingOut,
    CustomerCreate,
    CustomerOut,
    SupplierCreate,
    SupplierOut,
    TripCreate,
    TripOut,
)
from app.services import trip_service
from app.services.scoping import scoped_get, scoped_list

router = APIRouter(tags=["trips"])


# -- customers -- #
@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(req: CustomerCreate, p: Principal = Depends(get_current_principal),
                    db: Session = Depends(get_db)) -> CustomerOut:
    c = trip_service.create_customer(db, p.tenant_id, name=req.name, email=req.email,
                                     phone=req.phone)
    return CustomerOut(id=c.id, name=c.name, email=c.email, phone=c.phone)


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(p: Principal = Depends(get_current_principal),
                   db: Session = Depends(get_db)) -> list[CustomerOut]:
    return [CustomerOut(id=c.id, name=c.name, email=c.email, phone=c.phone)
            for c in scoped_list(db, Customer, p.tenant_id)]


# -- suppliers -- #
@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(req: SupplierCreate, p: Principal = Depends(get_current_principal),
                    db: Session = Depends(get_db)) -> SupplierOut:
    s = trip_service.create_supplier(db, p.tenant_id, name=req.name,
                                     supplier_type=req.supplier_type,
                                     contact_email=req.contact_email)
    return SupplierOut(id=s.id, name=s.name, supplier_type=s.supplier_type.value
                       if hasattr(s.supplier_type, "value") else str(s.supplier_type),
                       contact_email=s.contact_email)


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(p: Principal = Depends(get_current_principal),
                   db: Session = Depends(get_db)) -> list[SupplierOut]:
    return [SupplierOut(id=s.id, name=s.name,
                        supplier_type=str(s.supplier_type.value if hasattr(s.supplier_type, "value") else s.supplier_type),
                        contact_email=s.contact_email)
            for s in scoped_list(db, Supplier, p.tenant_id)]


# -- trips -- #
@router.post("/trips", response_model=TripOut, status_code=201)
def create_trip(req: TripCreate, p: Principal = Depends(get_current_principal),
                db: Session = Depends(get_db)) -> TripOut:
    try:
        t = trip_service.create_trip(db, p.tenant_id, p.user_id, reference=req.reference,
                                     customer_id=req.customer_id, currency=req.currency,
                                     booking_date=req.booking_date,
                                     travel_start=req.travel_start, travel_end=req.travel_end)
    except trip_service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _trip_out(t)


@router.get("/trips", response_model=list[TripOut])
def list_trips(p: Principal = Depends(get_current_principal),
               db: Session = Depends(get_db)) -> list[TripOut]:
    return [_trip_out(t) for t in scoped_list(db, Trip, p.tenant_id)]


@router.get("/trips/{trip_id}", response_model=TripOut)
def get_trip(trip_id: str, p: Principal = Depends(get_current_principal),
             db: Session = Depends(get_db)) -> TripOut:
    t = scoped_get(db, Trip, p.tenant_id, trip_id)
    if t is None:
        raise HTTPException(status_code=404, detail="trip not found")
    return _trip_out(t)


# -- bookings -- #
@router.post("/trips/{trip_id}/bookings", response_model=BookingOut, status_code=201)
def add_booking(trip_id: str, req: BookingCreate,
                p: Principal = Depends(get_current_principal),
                db: Session = Depends(get_db)) -> BookingOut:
    try:
        b = trip_service.add_booking(db, p.tenant_id, p.user_id, trip_id=trip_id,
                                     supplier_id=req.supplier_id,
                                     booking_reference=req.booking_reference,
                                     service_type=req.service_type,
                                     original_amount=req.original_amount,
                                     currency=req.currency)
    except trip_service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _booking_out(b)


@router.get("/trips/{trip_id}/bookings", response_model=list[BookingOut])
def list_bookings(trip_id: str, p: Principal = Depends(get_current_principal),
                  db: Session = Depends(get_db)) -> list[BookingOut]:
    if scoped_get(db, Trip, p.tenant_id, trip_id) is None:
        raise HTTPException(status_code=404, detail="trip not found")
    rows = [b for b in scoped_list(db, Booking, p.tenant_id) if b.trip_id == trip_id]
    return [_booking_out(b) for b in rows]


def _trip_out(t: Trip) -> TripOut:
    return TripOut(id=t.id, reference=t.reference, customer_id=t.customer_id,
                   currency=t.currency,
                   status=t.status.value if hasattr(t.status, "value") else str(t.status))


def _booking_out(b: Booking) -> BookingOut:
    return BookingOut(id=b.id, trip_id=b.trip_id, supplier_id=b.supplier_id,
                      booking_reference=b.booking_reference,
                      service_type=b.service_type.value if hasattr(b.service_type, "value") else str(b.service_type),
                      original_amount=str(Money(b.original_amount_minor, b.currency).amount),
                      currency=b.currency)
