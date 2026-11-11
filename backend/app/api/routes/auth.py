"""Authentication routes: register organisation, login, refresh, me."""
from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, get_current_principal
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.models.tenant import User
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, user.tenant_id, user.role.value
                                         if hasattr(user.role, "value") else str(user.role)),
        refresh_token=create_refresh_token(user.id, user.tenant_id),
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    _, user = auth_service.register_organization(
        db, org_name=req.org_name, email=req.email, password=req.password,
        full_name=req.full_name,
    )
    return _tokens(user)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        user = auth_service.authenticate(db, email=req.email, password=req.password)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid credentials") from exc
    return _tokens(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(req: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        payload = decode_token(req.refresh_token, expected_type="refresh")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid refresh token") from exc
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return _tokens(user)


@router.get("/me", response_model=MeResponse)
def me(principal: Principal = Depends(get_current_principal),
       db: Session = Depends(get_db)) -> MeResponse:
    user = db.get(User, principal.user_id)
    return MeResponse(user_id=principal.user_id, tenant_id=principal.tenant_id,
                      role=principal.role.value, email=user.email if user else "")
