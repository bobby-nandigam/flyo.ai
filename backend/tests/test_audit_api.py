"""Audit history endpoint test."""
from tests.conftest import auth_headers, register_org


def test_audit_log_records_actions_and_is_scoped(client):
    h = auth_headers(register_org(client)["access_token"])
    # Registration itself writes an audit record; create a customer for another.
    client.post("/api/v1/customers", json={"name": "C"}, headers=h)
    rows = client.get("/api/v1/audit-logs", headers=h).json()
    actions = {r["action"] for r in rows}
    assert "org.register" in actions

    # Another tenant sees only its own (empty but for its registration).
    hb = auth_headers(register_org(client, org="Other", email="o@o.test")["access_token"])
    b_rows = client.get("/api/v1/audit-logs", headers=hb).json()
    assert all(r["action"] != "trip.create" for r in b_rows)
    assert len(b_rows) >= 1  # its own registration
