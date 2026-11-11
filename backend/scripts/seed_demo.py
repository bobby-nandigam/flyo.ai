"""Seed a synthetic Indian travel demo dataset (spec §11).

Everything here is FICTIONAL and clearly labelled as a simulation. It touches no
real airline/hotel systems and initiates no real payments. It drives the same
service layer the API uses, so the seeded data is indistinguishable from data a
real user would enter.

Run (from backend/, venv active):
    python -m scripts.seed_demo

Then log in as  demo-owner@flyo.test / demopassword1  to explore the data.
"""
from __future__ import annotations

import uuid

from app.core.database import Base, get_engine, get_sessionmaker
import app.models  # noqa: F401
from app.domain.refund_status import RefundStatus
from app.models.trip import ServiceType, SupplierType
from app.services import (
    auth_service,
    document_service,
    investigation_service,
    reconciliation_service,
    refund_service,
    trip_service,
)

OWNER_EMAIL = "demo-owner@flyo.test"
OWNER_PASSWORD = "demopassword1"

# Deterministic IDs so every stateless serverless instance seeds identical
# identifiers — a token issued by one instance then validates on all of them.
_NS = uuid.UUID("f1a7e000-0000-4000-8000-000000000000")


def _did(name: str) -> str:
    return uuid.uuid5(_NS, name).hex


def _ensure_schema() -> None:
    Base.metadata.create_all(bind=get_engine())


def seed_if_empty() -> bool:
    """Seed only when there is no tenant yet (safe on serverless cold starts)."""
    from sqlalchemy import select
    from app.models.tenant import Tenant

    _ensure_schema()
    db = get_sessionmaker()()
    try:
        if db.scalar(select(Tenant).limit(1)) is not None:
            return False
    finally:
        db.close()
    seed()
    return True


def seed() -> None:
    _ensure_schema()
    db = get_sessionmaker()()
    try:
        tenant, owner = auth_service.register_organization(
            db, org_name="Himalaya Travels (DEMO)", email=OWNER_EMAIL,
            password=OWNER_PASSWORD, full_name="Demo Owner",
            tenant_id=_did("tenant"), user_id=_did("user"),
        )
        t, u = tenant.id, owner.id

        # --- suppliers (fictional) ---
        indigo = trip_service.create_supplier(db, t, name="IndiGo (SIMULATED)",
                                               supplier_type=SupplierType.AIRLINE)
        airindia = trip_service.create_supplier(db, t, name="Air India (SIMULATED)",
                                                 supplier_type=SupplierType.AIRLINE)
        taj = trip_service.create_supplier(db, t, name="Taj Hotels (SIMULATED)",
                                            supplier_type=SupplierType.HOTEL)

        cust = trip_service.create_customer(db, t, name="Priya Sharma",
                                            email="priya@example.test", phone="+91-98xxxxxx01")

        # ================= Scenario 1: IndiGo cancellation, clean refund ===========
        trip1 = trip_service.create_trip(db, t, u, reference="HT-2026-0001",
                                         customer_id=cust.id)
        b1 = trip_service.add_booking(db, t, u, trip_id=trip1.id, supplier_id=indigo.id,
                                      booking_reference="6E-PNR-AAA111",
                                      service_type=ServiceType.FLIGHT,
                                      original_amount="12500.00")
        case1 = refund_service.open_refund_case(
            db, t, u, booking_id=b1.id, case_id=_did("case1"),
            deductions=[
                {"kind": "CANCELLATION_DEDUCTION", "label": "IndiGo cancellation fee",
                 "amount": "3000.00", "evidence_ref": "doc:indigo-cancel-AAA111"},
                {"kind": "REFUNDABLE_TAX", "label": "Refundable GST",
                 "amount": "250.00", "evidence_ref": "doc:indigo-cancel-AAA111"},
            ],
        )
        # Supplier refunds in two UPI/bank installments (spec: multiple installments).
        refund_service.post_supplier_refund(db, t, u, case_id=case1.id, amount="5000.00",
                                             evidence_ref="bank:HDFC-2026-03-01",
                                             external_ref="BANK-IDG-1")
        refund_service.post_supplier_refund(db, t, u, case_id=case1.id, amount="4750.00",
                                             evidence_ref="bank:HDFC-2026-03-04",
                                             external_ref="BANK-IDG-2")
        # Agency refunds customer in full.
        refund_service.post_customer_refund(db, t, u, case_id=case1.id, amount="9500.00",
                                            evidence_ref="upi:cust-priya-1",
                                            external_ref="UPI-CUST-1")

        # ================= Scenario 2: Hotel partial refund, still outstanding =====
        trip2 = trip_service.create_trip(db, t, u, reference="HT-2026-0002",
                                         customer_id=cust.id)
        b2 = trip_service.add_booking(db, t, u, trip_id=trip2.id, supplier_id=taj.id,
                                      booking_reference="TAJ-RES-77421",
                                      service_type=ServiceType.HOTEL,
                                      original_amount="22000.00")
        case2 = refund_service.open_refund_case(
            db, t, u, booking_id=b2.id, case_id=_did("case2"),
            deductions=[
                {"kind": "CANCELLATION_DEDUCTION", "label": "One night retention",
                 "amount": "8000.00", "evidence_ref": "doc:taj-cancel-77421"},
                {"kind": "NON_REFUNDABLE", "label": "Non-refundable booking fee",
                 "amount": "1000.00", "evidence_ref": "doc:taj-policy-v2"},
            ],
        )
        # Only part received -> outstanding balance the dashboard should surface.
        refund_service.post_supplier_refund(db, t, u, case_id=case2.id, amount="7000.00",
                                            evidence_ref="bank:HDFC-2026-03-06",
                                            external_ref="BANK-TAJ-1")

        # ================= Scenario 3: Air India refund NOT received ===============
        trip3 = trip_service.create_trip(db, t, u, reference="HT-2026-0003",
                                         customer_id=cust.id)
        b3 = trip_service.add_booking(db, t, u, trip_id=trip3.id, supplier_id=airindia.id,
                                      booking_reference="AI-PNR-ZZZ999",
                                      service_type=ServiceType.FLIGHT,
                                      original_amount="18000.00")
        case3 = refund_service.open_refund_case(
            db, t, u, booking_id=b3.id, case_id=_did("case3"),
            deductions=[
                {"kind": "CANCELLATION_DEDUCTION", "label": "Air India cancellation fee",
                 "amount": "4000.00", "evidence_ref": "doc:ai-cancel-ZZZ999"},
            ],
        )
        # No supplier refund posted -> full expected amount is outstanding/overdue.
        refund_service.transition_status(db, t, u, case_id=case3.id,
                                         new_status=RefundStatus.REFUND_REQUESTED)

        # ================= Scenario 4: Reconcile an imported bank statement ========
        # Mirrors the recorded supplier ledger refunds, with one shortfall and one
        # unexplained credit, so the discrepancy queue has realistic items.
        reconciliation_service.import_and_reconcile(
            db, t, u, source="BANK", filename="hdfc-mar-2026.csv",
            rows=[
                {"external_ref": "BANK-IDG-1", "amount": "5000.00", "value_date": "2026-03-01"},
                {"external_ref": "BANK-IDG-2", "amount": "4750.00", "value_date": "2026-03-04"},
                {"external_ref": "BANK-TAJ-1", "amount": "6500.00", "value_date": "2026-03-06"},  # short by 500
                {"external_ref": "UPI-MYSTERY-7", "amount": "3200.00", "value_date": "2026-03-07"},  # unexplained
            ],
        )

        # ================= Scenario 5: Document intelligence + policy =============
        document_service.ingest_text_document(
            db, t, u, trip_id=trip1.id, doc_type="CANCELLATION",
            filename="indigo-cancel-AAA111.txt",
            content_text=(
                "IndiGo - Cancellation Confirmation\n"
                "PNR: 6E-PNR-AAA111\n"
                "Original fare: INR 12,500.00\n"
                "Cancellation charge: Rs. 3,000.00\n"
                "Refund amount payable: Rs. 9,500.00\n"
                "Cancellation date: 2026-03-01\n"
            ),
        )
        document_service.create_policy(
            db, t, u, version="indigo-domestic-v3", currency="INR",
            tiers=[
                {"min_days_before": 15, "basis": "FIXED", "fixed_amount": "2000", "label": ">=15 days"},
                {"min_days_before": 2, "basis": "GREATER_OF", "fixed_amount": "3000",
                 "percent": "25", "label": "2-14 days"},
                {"min_days_before": 0, "basis": "PERCENT", "percent": "100", "label": "<2 days / no-show"},
            ],
            non_refundable_fixed="250", non_refundable_label="Convenience fee",
        )

        # ================= Scenario 6: Investigate the outstanding cases ===========
        for cid in (case2.id, case3.id):
            investigation_service.run_investigation(db, t, u, case_id=cid)
        investigation_service.draft_supplier_followup(db, t, u, case_id=case3.id)

        print("Seed complete.")
        print(f"  Tenant:   {tenant.name}  ({tenant.id})")
        print(f"  Login:    {OWNER_EMAIL} / {OWNER_PASSWORD}")
        print(f"  Scenario 1 (IndiGo, settled):      case {case1.id}")
        print(f"  Scenario 2 (Taj, partial/outstanding): case {case2.id}")
        print(f"  Scenario 3 (Air India, not received):  case {case3.id}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
