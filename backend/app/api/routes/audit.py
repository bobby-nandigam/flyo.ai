"""Audit history route (spec §11: review every financial change)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, get_current_principal
from app.models.refund import AuditLog

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
def list_audit(limit: int = 100, p: Principal = Depends(get_current_principal),
               db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.tenant_id == p.tenant_id)
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 500))
    ).all()
    out = []
    for r in rows:
        try:
            detail = json.loads(r.detail) if r.detail else {}
        except (ValueError, TypeError):
            detail = {}
        out.append({
            "id": r.id, "action": r.action, "entity_type": r.entity_type,
            "entity_id": r.entity_id, "user_id": r.user_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "detail": detail,
        })
    return out
