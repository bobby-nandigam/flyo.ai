"""Invariant #7: one tenant must never access another tenant's data.

This is the invariant the pure domain layer could not cover. Here we exercise it
through the real HTTP stack: two organisations, each with its own data, and every
cross-tenant access path must 404 (not found *for you*), never leak.
"""
from tests.conftest import auth_headers, register_org


def _make_tenant_with_trip(client, org, email):
    tok = register_org(client, org=org, email=email)["access_token"]
    h = auth_headers(tok)
    cust = client.post("/api/v1/customers", json={"name": "Cust"}, headers=h).json()
    trip = client.post("/api/v1/trips", json={
        "reference": f"TRIP-{org[:3]}", "customer_id": cust["id"], "currency": "INR",
    }, headers=h).json()
    return h, trip


def test_tenant_cannot_read_another_tenants_trip(client):
    h_a, trip_a = _make_tenant_with_trip(client, "Alpha Travels", "a@alpha.test")
    h_b, trip_b = _make_tenant_with_trip(client, "Beta Tours", "b@beta.test")

    # B tries to read A's trip by id -> 404, as if it does not exist.
    r = client.get(f"/api/v1/trips/{trip_a['id']}", headers=h_b)
    assert r.status_code == 404

    # A can read its own.
    assert client.get(f"/api/v1/trips/{trip_a['id']}", headers=h_a).status_code == 200


def test_trip_list_is_scoped_to_tenant(client):
    h_a, trip_a = _make_tenant_with_trip(client, "Alpha Travels", "a@alpha.test")
    h_b, trip_b = _make_tenant_with_trip(client, "Beta Tours", "b@beta.test")

    a_ids = {t["id"] for t in client.get("/api/v1/trips", headers=h_a).json()}
    b_ids = {t["id"] for t in client.get("/api/v1/trips", headers=h_b).json()}

    assert trip_a["id"] in a_ids and trip_a["id"] not in b_ids
    assert trip_b["id"] in b_ids and trip_b["id"] not in a_ids
    assert a_ids.isdisjoint(b_ids)


def test_cannot_add_booking_to_another_tenants_trip(client):
    h_a, trip_a = _make_tenant_with_trip(client, "Alpha Travels", "a@alpha.test")
    h_b, _ = _make_tenant_with_trip(client, "Beta Tours", "b@beta.test")

    # B creates its own supplier, then tries to book onto A's trip.
    sup_b = client.post("/api/v1/suppliers", json={"name": "SupB"}, headers=h_b).json()
    r = client.post(f"/api/v1/trips/{trip_a['id']}/bookings", json={
        "supplier_id": sup_b["id"], "booking_reference": "X", "service_type": "FLIGHT",
        "original_amount": "1000.00", "currency": "INR",
    }, headers=h_b)
    assert r.status_code == 404


def test_same_trip_reference_allowed_across_tenants(client):
    # Uniqueness is per-tenant, so both tenants may use TRIP-Alp/TRIP-Bet freely;
    # here we assert each tenant can create a reference the other also holds.
    h_a, _ = _make_tenant_with_trip(client, "Alp", "a@alp.test")
    h_b, _ = _make_tenant_with_trip(client, "Alp", "b@alp2.test")  # same ref base "TRIP-Alp"
    # Both creations above succeeded (register_org/_make_tenant assert 201/200 paths),
    # proving the per-tenant unique constraint did not collide across tenants.
    assert client.get("/api/v1/trips", headers=h_a).json()
    assert client.get("/api/v1/trips", headers=h_b).json()
