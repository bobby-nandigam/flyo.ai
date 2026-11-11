"""End-to-end refund flow over HTTP, persisting to the ledger.

Register -> customer -> supplier -> trip -> booking -> open refund case
(engine computes expected) -> post supplier refund -> settlement -> transition.
Also checks duplicate-transaction rejection and the supplier/customer separation.
"""
from tests.conftest import auth_headers, register_org


def _setup_booking(client, headers, amount="10000.00"):
    cust = client.post("/api/v1/customers", json={"name": "Priya"}, headers=headers).json()
    sup = client.post("/api/v1/suppliers", json={"name": "IndiGo", "supplier_type": "AIRLINE"},
                      headers=headers).json()
    trip = client.post("/api/v1/trips", json={
        "reference": "TRIP-001", "customer_id": cust["id"], "currency": "INR",
    }, headers=headers).json()
    booking = client.post(f"/api/v1/trips/{trip['id']}/bookings", json={
        "supplier_id": sup["id"], "booking_reference": "6E-ABC123", "service_type": "FLIGHT",
        "original_amount": amount, "currency": "INR",
    }, headers=headers).json()
    return trip, booking


def test_open_case_computes_expected_refund(client):
    h = auth_headers(register_org(client)["access_token"])
    _, booking = _setup_booking(client, h, amount="10000.00")
    r = client.post("/api/v1/refund-cases", json={
        "booking_id": booking["id"],
        "deductions": [
            {"kind": "CANCELLATION_DEDUCTION", "label": "Cancellation penalty",
             "amount": "2000.00", "evidence_ref": "doc:cancel-1"},
            {"kind": "REFUNDABLE_TAX", "label": "Refundable GST",
             "amount": "300.00", "evidence_ref": "doc:cancel-1"},
        ],
    }, headers=h)
    assert r.status_code == 201, r.text
    case = r.json()
    # 10000 - 2000 + 300 = 8300
    assert case["expected_supplier_refund"] == "8300.00"
    assert case["status"] == "REFUND_EXPECTED"
    assert case["supplier_breakdown"]["total"] == "8300.00"


def test_full_settlement_cycle(client):
    h = auth_headers(register_org(client)["access_token"])
    _, booking = _setup_booking(client, h)
    case = client.post("/api/v1/refund-cases", json={
        "booking_id": booking["id"],
        "deductions": [{"kind": "CANCELLATION_DEDUCTION", "label": "Penalty",
                        "amount": "2000.00", "evidence_ref": "doc:1"}],
    }, headers=h).json()
    case_id = case["id"]
    assert case["expected_supplier_refund"] == "8000.00"

    # Partial supplier refund received.
    r1 = client.post(f"/api/v1/refund-cases/{case_id}/supplier-refund", json={
        "amount": "5000.00", "evidence_ref": "bank:stmt-1", "external_ref": "BANK-TXN-1",
    }, headers=h)
    assert r1.status_code == 201

    s1 = client.get(f"/api/v1/refund-cases/{case_id}/settlement?side=supplier", headers=h).json()
    assert s1["received"] == "5000.00"
    assert s1["outstanding"] == "3000.00"
    assert s1["is_settled"] is False

    # Remaining supplier refund.
    client.post(f"/api/v1/refund-cases/{case_id}/supplier-refund", json={
        "amount": "3000.00", "evidence_ref": "bank:stmt-2", "external_ref": "BANK-TXN-2",
    }, headers=h)
    s2 = client.get(f"/api/v1/refund-cases/{case_id}/settlement?side=supplier", headers=h).json()
    assert s2["received"] == "8000.00" and s2["is_settled"] is True


def test_duplicate_external_ref_rejected(client):
    h = auth_headers(register_org(client)["access_token"])
    _, booking = _setup_booking(client, h)
    case = client.post("/api/v1/refund-cases", json={"booking_id": booking["id"]},
                       headers=h).json()
    payload = {"amount": "1000.00", "evidence_ref": "bank:x", "external_ref": "DUP-1"}
    r1 = client.post(f"/api/v1/refund-cases/{case['id']}/supplier-refund", json=payload, headers=h)
    assert r1.status_code == 201
    r2 = client.post(f"/api/v1/refund-cases/{case['id']}/supplier-refund", json=payload, headers=h)
    assert r2.status_code == 409  # invariant #1: no double count


def test_supplier_and_customer_refunds_tracked_separately(client):
    h = auth_headers(register_org(client)["access_token"])
    _, booking = _setup_booking(client, h)
    case = client.post("/api/v1/refund-cases", json={"booking_id": booking["id"]},
                       headers=h).json()
    cid = case["id"]
    # Supplier pays agency 8000; agency later pays customer 7800.
    client.post(f"/api/v1/refund-cases/{cid}/supplier-refund", json={
        "amount": "8000.00", "evidence_ref": "bank:s", "external_ref": "S1"}, headers=h)
    client.post(f"/api/v1/refund-cases/{cid}/customer-refund", json={
        "amount": "7800.00", "evidence_ref": "upi:c", "external_ref": "C1"}, headers=h)

    sup = client.get(f"/api/v1/refund-cases/{cid}/settlement?side=supplier", headers=h).json()
    cust = client.get(f"/api/v1/refund-cases/{cid}/settlement?side=customer", headers=h).json()
    assert sup["received"] == "8000.00"
    assert cust["received"] == "7800.00"
    # The two figures are independent, not the same number.
    assert sup["received"] != cust["received"]

    ledger = client.get(f"/api/v1/refund-cases/{cid}/ledger", headers=h).json()
    accounts = {e["account"] for e in ledger}
    assert accounts == {"SUPPLIER", "CUSTOMER"}


def test_illegal_status_transition_rejected(client):
    h = auth_headers(register_org(client)["access_token"])
    _, booking = _setup_booking(client, h)
    case = client.post("/api/v1/refund-cases", json={"booking_id": booking["id"]},
                       headers=h).json()
    # REFUND_EXPECTED -> CUSTOMER_REFUNDED is not a legal jump.
    r = client.post(f"/api/v1/refund-cases/{case['id']}/transition", json={
        "new_status": "CUSTOMER_REFUNDED"}, headers=h)
    assert r.status_code == 409


def test_legal_status_transition_accepted(client):
    h = auth_headers(register_org(client)["access_token"])
    _, booking = _setup_booking(client, h)
    case = client.post("/api/v1/refund-cases", json={"booking_id": booking["id"]},
                       headers=h).json()
    r = client.post(f"/api/v1/refund-cases/{case['id']}/transition", json={
        "new_status": "REFUND_REQUESTED"}, headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "REFUND_REQUESTED"
