"""Database engine, session factory, and FastAPI dependency.

Engine creation is lazy so tests can point ``DATABASE_URL`` at a throwaway SQLite
file before anything connects. Production uses PostgreSQL; the ORM models avoid
Postgres-only types so the same schema runs on SQLite in CI.
"""
from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine
    if _engine is None:
        url = get_settings().database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args, future=True, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


def reset_engine_for_tests() -> None:
    """Drop cached engine/sessionmaker so a test can rebind DATABASE_URL."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
