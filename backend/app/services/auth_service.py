"""Organization registration and authentication use-cases."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.tenant import Role, Tenant, User
from app.services import audit


class AuthError(Exception):
    pass


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "org"
    return base[:60]


def register_organization(
    db: Session, *, org_name: str, email: str, password: str, full_name: str = "",
    tenant_id: str | None = None, user_id: str | None = None,
) -> tuple[Tenant, User]:
    """Create a new tenant and its first OWNER user atomically.

    ``tenant_id``/``user_id`` may be supplied to create records with stable,
    deterministic identifiers (used by the demo seed so a token issued by one
    stateless instance validates on every other instance).
    """
    email = email.strip().lower()
    slug = _slugify(org_name)
    # Ensure slug uniqueness by suffixing if needed.
    n = 0
    candidate = slug
    while db.scalar(select(Tenant).where(Tenant.slug == candidate)) is not None:
        n += 1
        candidate = f"{slug}-{n}"

    tenant = Tenant(name=org_name, slug=candidate)
    if tenant_id:
        tenant.id = tenant_id
    db.add(tenant)
    db.flush()  # assign tenant.id

    user = User(
        tenant_id=tenant.id,
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
        role=Role.OWNER,
    )
    if user_id:
        user.id = user_id
    db.add(user)
    db.flush()
    audit.record(
        db, tenant_id=tenant.id, user_id=user.id, action="org.register",
        entity_type="tenant", entity_id=tenant.id, detail={"email": email},
    )
    db.commit()
    return tenant, user


def authenticate(db: Session, *, email: str, password: str) -> User:
    # Email is unique per tenant, so the same address may exist in several tenants.
    # Match on the (email, password) pair across candidates to resolve the user.
    email = email.strip().lower()
    candidates = db.scalars(select(User).where(User.email == email)).all()
    for user in candidates:
        if user.is_active and verify_password(password, user.password_hash):
            return user
    raise AuthError("Invalid credentials")
