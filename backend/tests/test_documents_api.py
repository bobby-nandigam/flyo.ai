"""End-to-end document intelligence + policy tests (spec Modules B/C)."""
from tests.conftest import auth_headers, register_org

DOC = """IndiGo Cancellation Confirmation
PNR: 6E-ABC123
Original fare: INR 12,500.00
Refund amount payable: Rs. 9,500.00
Cancellation date: 2026-03-01
"""


def _headers(client):
    return auth_headers(register_org(client)["access_token"])


def test_ingest_extracts_fields(client):
    h = _headers(client)
    client.post("/api/v1/suppliers", json={"name": "IndiGo"}, headers=h)
    r = client.post("/api/v1/documents", json={"content_text": DOC, "doc_type": "CANCELLATION"},
                    headers=h)
    assert r.status_code == 201, r.text
    ex = r.json()["extraction"]["extracted"]
    assert ex["amounts"][0]["value"] == "9500.00"
    assert ex["supplier"]["value"] == "IndiGo"


def test_verify_extraction_marks_verified(client):
    h = _headers(client)
    doc = client.post("/api/v1/documents", json={"content_text": DOC}, headers=h).json()
    r = client.post(f"/api/v1/documents/{doc['id']}/verify",
                    json={"amount": "9500.00", "booking_ref": "6E-ABC123"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "VERIFIED"
    assert body["extraction"]["verified"] is True
    assert body["extraction"]["verified_amount"] == "9500.00"


def test_policy_create_and_quote(client):
    h = _headers(client)
    cust = client.post("/api/v1/customers", json={"name": "C"}, headers=h).json()
    sup = client.post("/api/v1/suppliers", json={"name": "IndiGo"}, headers=h).json()
    trip = client.post("/api/v1/trips", json={"reference": "T1", "customer_id": cust["id"]},
                       headers=h).json()
    booking = client.post(f"/api/v1/trips/{trip['id']}/bookings", json={
        "supplier_id": sup["id"], "booking_reference": "6E-1", "service_type": "FLIGHT",
        "original_amount": "20000.00"}, headers=h).json()

    pol = client.post("/api/v1/policies", json={
        "version": "indigo-v1", "currency": "INR",
        "tiers": [
            {"min_days_before": 15, "basis": "FIXED", "fixed_amount": "2000"},
            {"min_days_before": 2, "basis": "GREATER_OF", "fixed_amount": "3000", "percent": "25"},
        ],
        "non_refundable_fixed": "250",
    }, headers=h)
    assert pol.status_code == 201

    q = client.post("/api/v1/policies/quote", json={
        "booking_id": booking["id"], "policy_version": "indigo-v1", "days_before_travel": 10,
    }, headers=h)
    assert q.status_code == 200
    # 20000 - max(3000, 25% of 20000=5000)=5000 - 250 = 14750
    assert q.json()["expected_supplier_refund"] == "14750.00"


def test_documents_tenant_isolated(client):
    ha = _headers(client)
    hb = auth_headers(register_org(client, org="Other", email="o@o.test")["access_token"])
    doc = client.post("/api/v1/documents", json={"content_text": DOC}, headers=ha).json()
    assert client.get(f"/api/v1/documents/{doc['id']}", headers=hb).status_code == 404
