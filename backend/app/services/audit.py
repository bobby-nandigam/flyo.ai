"""Audit-log writer (spec §9, §13: every financial change has an audit record)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.refund import AuditLog


def record(
    db: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=json.dumps(detail or {}, default=str),
    )
    db.add(entry)
    return entry
