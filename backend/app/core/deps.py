"""FastAPI dependencies for authentication and tenant context."""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token
from app.models.tenant import Role, User

_bearer = HTTPBearer(auto_error=True)


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: Role


def get_current_principal(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Principal:
    try:
        payload = decode_token(creds.credentials, expected_type="access")
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, payload["sub"])
    # Defence in depth: the token's tenant must match the stored user's tenant.
    if user is None or not user.is_active or user.tenant_id != payload.get("tenant_id"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return Principal(user_id=user.id, tenant_id=user.tenant_id, role=Role(user.role))


def require_roles(*roles: Role):
    """Dependency factory: allow only the given roles."""

    def _checker(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {[r.value for r in roles]}",
            )
        return principal

    return _checker
