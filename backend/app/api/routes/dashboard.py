"""Dashboard metrics route (spec Module J)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, get_current_principal
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(p: Principal = Depends(get_current_principal),
            db: Session = Depends(get_db)) -> dict:
    return dashboard_service.summary(db, p.tenant_id)
