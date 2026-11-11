"""Tests for Phase 7 hardening: request id, security headers, metrics."""
from tests.conftest import register_org


def test_request_id_and_security_headers(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_client_request_id_is_echoed(client):
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers.get("X-Request-ID") == "abc-123"


def test_metrics_endpoint_prometheus_format(client):
    client.get("/health")  # generate at least one sample
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "flyo_requests_total" in body
    assert "flyo_request_duration_seconds_count" in body
