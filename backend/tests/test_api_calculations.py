"""End-to-end API test for the refund calculation endpoint."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_supplier_refund_endpoint_matches_engine():
    payload = {
        "currency": "INR",
        "scope": "supplier",
        "lines": [
            {"kind": "ORIGINAL", "label": "Base fare", "amount": "10000.00", "evidence_ref": "doc:1"},
            {"kind": "CANCELLATION_DEDUCTION", "label": "Penalty", "amount": "2000.00", "evidence_ref": "pol:1"},
            {"kind": "REFUNDABLE_TAX", "label": "Refundable GST", "amount": "300.00", "evidence_ref": "doc:1"},
        ],
    }
    r = client.post("/api/v1/calculations/refund", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == "8300.00"
    assert body["clamped"] is False
    assert len(body["lines"]) == 3


def test_negative_amount_rejected_by_schema():
    payload = {
        "currency": "INR",
        "scope": "supplier",
        "lines": [{"kind": "ORIGINAL", "label": "x", "amount": "-5.00"}],
    }
    r = client.post("/api/v1/calculations/refund", json=payload)
    assert r.status_code == 422


def test_customer_side_line_rejected_for_supplier_scope():
    payload = {
        "currency": "INR",
        "scope": "supplier",
        "lines": [
            {"kind": "ORIGINAL", "label": "Base", "amount": "100.00"},
            {"kind": "GATEWAY_FEE", "label": "fee", "amount": "10.00"},
        ],
    }
    r = client.post("/api/v1/calculations/refund", json=payload)
    assert r.status_code == 422
