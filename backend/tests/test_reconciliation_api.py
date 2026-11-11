"""End-to-end reconciliation: open a case, record a supplier refund, then import
bank records and confirm matches + discrepancies are detected and persisted."""
from tests.conftest import auth_headers, register_org


def _case_with_ledger(client, h):
    cust = client.post("/api/v1/customers", json={"name": "C"}, headers=h).json()
    sup = client.post("/api/v1/suppliers", json={"name": "IndiGo"}, headers=h).json()
    trip = client.post("/api/v1/trips", json={"reference": "T1", "customer_id": cust["id"]},
                       headers=h).json()
    booking = client.post(f"/api/v1/trips/{trip['id']}/bookings", json={
        "supplier_id": sup["id"], "booking_reference": "6E-1", "service_type": "FLIGHT",
        "original_amount": "10000.00"}, headers=h).json()
    case = client.post("/api/v1/refund-cases", json={"booking_id": booking["id"]}, headers=h).json()
    # Record one supplier refund (ledger entry) with a known external ref.
    client.post(f"/api/v1/refund-cases/{case['id']}/supplier-refund", json={
        "amount": "10000.00", "evidence_ref": "bank:x", "external_ref": "BANK-REF-1"}, headers=h)
    return case


def test_import_matches_ledger_and_flags_mystery_credit(client):
    h = auth_headers(register_org(client)["access_token"])
    _case_with_ledger(client, h)
    r = client.post("/api/v1/reconciliation/import", json={
        "source": "BANK", "filename": "hdfc.csv",
        "rows": [
            {"external_ref": "BANK-REF-1", "amount": "10000.00"},   # matches ledger
            {"external_ref": "MYSTERY-9", "amount": "2500.00"},     # unmatched credit
        ],
    }, headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["record_count"] == 2
    assert body["matched_count"] == 1
    kinds = {d["kind"] for d in body["discrepancies"]}
    assert "UNMATCHED_BANK_CREDIT" in kinds
    # The matched record carries the strategy + full confidence.
    matched = [rec for rec in body["records"] if rec["matched"]][0]
    assert matched["match_strategy"] == "EXACT_REF"
    assert matched["match_confidence"] == "1.00"


def test_amount_mismatch_detected(client):
    h = auth_headers(register_org(client)["access_token"])
    _case_with_ledger(client, h)
    r = client.post("/api/v1/reconciliation/import", json={
        "rows": [{"external_ref": "BANK-REF-1", "amount": "9000.00"}],  # ledger says 10000
    }, headers=h)
    body = r.json()
    mism = [d for d in body["discrepancies"] if d["kind"] == "AMOUNT_MISMATCH"]
    assert len(mism) == 1
    assert mism[0]["difference"] == "-1000.00"


def test_csv_text_import(client):
    h = auth_headers(register_org(client)["access_token"])
    _case_with_ledger(client, h)
    csv_text = "reference,amount,date\nBANK-REF-1,10000.00,2026-03-01\n"
    r = client.post("/api/v1/reconciliation/import", json={"csv_text": csv_text}, headers=h)
    assert r.status_code == 201
    assert r.json()["matched_count"] == 1


def test_discrepancies_listed_and_resolvable(client):
    h = auth_headers(register_org(client)["access_token"])
    _case_with_ledger(client, h)
    client.post("/api/v1/reconciliation/import", json={
        "rows": [{"external_ref": "MYSTERY", "amount": "5000.00"}]}, headers=h)
    discs = client.get("/api/v1/reconciliation/discrepancies?status=OPEN", headers=h).json()
    assert len(discs) >= 1
    did = discs[0]["id"]
    res = client.post(f"/api/v1/reconciliation/discrepancies/{did}/resolve",
                      json={"status": "RESOLVED"}, headers=h)
    assert res.status_code == 200 and res.json()["status"] == "RESOLVED"


def test_reconciliation_is_tenant_isolated(client):
    ha = auth_headers(register_org(client, org="Org A", email="a@a.test")["access_token"])
    hb = auth_headers(register_org(client, org="Org B", email="b@b.test")["access_token"])
    _case_with_ledger(client, ha)
    batch = client.post("/api/v1/reconciliation/import", json={
        "rows": [{"external_ref": "BANK-REF-1", "amount": "10000.00"}]}, headers=ha).json()
    # Tenant B cannot see A's batch.
    assert client.get(f"/api/v1/reconciliation/batches/{batch['id']}", headers=hb).status_code == 404
    assert client.get("/api/v1/reconciliation/batches", headers=hb).json() == []
