"""End-to-end investigation + follow-up draft over HTTP (spec Modules H/I)."""
from tests.conftest import auth_headers, register_org


def _case(client, h, received=None):
    cust = client.post("/api/v1/customers", json={"name": "C"}, headers=h).json()
    sup = client.post("/api/v1/suppliers", json={"name": "IndiGo"}, headers=h).json()
    trip = client.post("/api/v1/trips", json={"reference": "T1", "customer_id": cust["id"]},
                       headers=h).json()
    booking = client.post(f"/api/v1/trips/{trip['id']}/bookings", json={
        "supplier_id": sup["id"], "booking_reference": "6E-1", "service_type": "FLIGHT",
        "original_amount": "10000.00"}, headers=h).json()
    case = client.post("/api/v1/refund-cases", json={"booking_id": booking["id"]}, headers=h).json()
    if received:
        client.post(f"/api/v1/refund-cases/{case['id']}/supplier-refund", json={
            "amount": received, "evidence_ref": "bank:x", "external_ref": "R1"}, headers=h)
    return case


def test_investigation_flags_shortfall(client):
    h = auth_headers(register_org(client)["access_token"])
    case = _case(client, h, received="6000.00")  # expected 10000
    r = client.post(f"/api/v1/refund-cases/{case['id']}/investigate", headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    codes = {f["code"] for f in body["findings"]}
    assert "SUPPLIER_SHORTFALL" in codes
    assert body["recommended_actions"]
    assert body["engine"] == "deterministic"


def test_followup_draft_created_and_approvable(client):
    h = auth_headers(register_org(client)["access_token"])
    case = _case(client, h, received="6000.00")
    draft = client.post(f"/api/v1/refund-cases/{case['id']}/followup-draft", headers=h)
    assert draft.status_code == 201
    body = draft.json()
    assert body["status"] == "DRAFT" and "4000" in body["body"]
    # Approve it (does not actually send).
    cid = body["id"]
    appr = client.post(f"/api/v1/communications/{cid}/status", json={"status": "APPROVED"}, headers=h)
    assert appr.status_code == 200 and appr.json()["status"] == "APPROVED"


def test_investigation_tenant_isolated(client):
    ha = auth_headers(register_org(client)["access_token"])
    hb = auth_headers(register_org(client, org="Other", email="o@o.test")["access_token"])
    case = _case(client, ha, received="6000.00")
    client.post(f"/api/v1/refund-cases/{case['id']}/investigate", headers=ha)
    # B cannot investigate or view A's case.
    assert client.post(f"/api/v1/refund-cases/{case['id']}/investigate", headers=hb).status_code == 404
    assert client.get(f"/api/v1/refund-cases/{case['id']}/investigations", headers=hb).json() == []
