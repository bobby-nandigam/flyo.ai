"""Auth: registration, login, token types, protected routes."""
from tests.conftest import auth_headers, register_org


def test_register_returns_tokens(client):
    body = register_org(client)
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_me_requires_auth(client):
    # No Authorization header -> 401 Unauthorized.
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_principal(client):
    tok = register_org(client)["access_token"]
    r = client.get("/api/v1/auth/me", headers=auth_headers(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "owner@acme.test"
    assert body["role"] == "OWNER"


def test_login_success_and_failure(client):
    register_org(client, email="a@b.test", password="rightpassword1")
    ok = client.post("/api/v1/auth/login", json={"email": "a@b.test", "password": "rightpassword1"})
    assert ok.status_code == 200
    bad = client.post("/api/v1/auth/login", json={"email": "a@b.test", "password": "wrong"})
    assert bad.status_code == 401


def test_refresh_token_cannot_be_used_as_access(client):
    body = register_org(client)
    # Using the refresh token as a bearer access token must fail.
    r = client.get("/api/v1/auth/me", headers=auth_headers(body["refresh_token"]))
    assert r.status_code == 401


def test_refresh_issues_new_access(client):
    body = register_org(client)
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_weak_password_rejected(client):
    r = client.post("/api/v1/auth/register", json={
        "org_name": "X", "email": "x@y.test", "password": "short", "full_name": "",
    })
    assert r.status_code == 422
