"""Tenant-scoping helpers — the enforcement point for invariant #7.

Every read/write of a tenant-owned table goes through these helpers, which inject
``tenant_id`` into the query. A handler that forgets to scope would have to bypass
this module deliberately; routine code cannot leak across tenants by omission.
"""
from __future__ import annotations

from typing import Type, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

T = TypeVar("T")


def scoped_query(db: Session, model: Type[T], tenant_id: str):
    """A SELECT already filtered to ``tenant_id``."""
    return select(model).where(model.tenant_id == tenant_id)  # type: ignore[attr-defined]


def scoped_list(db: Session, model: Type[T], tenant_id: str) -> list[T]:
    return list(db.scalars(scoped_query(db, model, tenant_id)).all())


def scoped_get(db: Session, model: Type[T], tenant_id: str, entity_id: str) -> T | None:
    stmt = scoped_query(db, model, tenant_id).where(model.id == entity_id)  # type: ignore[attr-defined]
    return db.scalars(stmt).first()
