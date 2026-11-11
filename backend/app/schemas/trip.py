from __future__ import annotations

import datetime as _dt
from typing import Optional

from pydantic import BaseModel, Field

from app.models.trip import ServiceType, SupplierType


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: Optional[str] = None
    phone: Optional[str] = None


class CustomerOut(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    supplier_type: SupplierType = SupplierType.OTHER
    contact_email: Optional[str] = None


class SupplierOut(BaseModel):
    id: str
    name: str
    supplier_type: str
    contact_email: Optional[str] = None


class TripCreate(BaseModel):
    reference: str = Field(min_length=1, max_length=64)
    customer_id: str
    currency: str = Field(default="INR", min_length=3, max_length=3)
    booking_date: Optional[_dt.date] = None
    travel_start: Optional[_dt.date] = None
    travel_end: Optional[_dt.date] = None


class TripOut(BaseModel):
    id: str
    reference: str
    customer_id: str
    currency: str
    status: str


class BookingCreate(BaseModel):
    supplier_id: str
    booking_reference: str = Field(min_length=1, max_length=64)
    service_type: ServiceType = ServiceType.OTHER
    original_amount: str = Field(description="Decimal string, e.g. '12500.00'")
    currency: str = Field(default="INR", min_length=3, max_length=3)


class BookingOut(BaseModel):
    id: str
    trip_id: str
    supplier_id: str
    booking_reference: str
    service_type: str
    original_amount: str
    currency: str
