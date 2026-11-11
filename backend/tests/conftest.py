"""Test harness: a throwaway SQLite database and helpers.

DATABASE_URL is pointed at a temp SQLite file *before* the app imports settings,
so the same ORM models run on SQLite in CI and PostgreSQL in production. Tables
are created directly (not via the lifespan hook) and truncated between tests for
isolation.
"""
from __future__ import annotations

import os
import tempfile

import pytest

_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET"] = "test-secret-key-at-least-32-bytes-long-000"

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.core.database import (  # noqa: E402
    Base,
    get_engine,
    get_sessionmaker,
    reset_engine_for_tests,
)

reset_engine_for_tests()

import app.models  # noqa: E402,F401  -- register tables
from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    Base.metadata.create_all(bind=get_engine())
    yield


@pytest.fixture(autouse=True)
def _clean_between_tests(_create_schema):
    yield
    db = get_sessionmaker()()
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()
    db.close()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def register_org(client: TestClient, org="Acme Travels", email="owner@acme.test",
                 password="supersecret1") -> dict:
    r = client.post("/api/v1/auth/register", json={
        "org_name": org, "email": email, "password": password, "full_name": "Owner",
    })
    assert r.status_code == 201, r.text
    return r.json()


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
