from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog

log = logging.getLogger("geoattend.audit")


def audit(db: Session, *, org_id: int, actor_id: int | None, action: str, entity_type: str,
          entity_id: Any = None, changes: dict | None = None, ip: str | None = None) -> AuditLog:
    entry = AuditLog(organization_id=org_id, actor_user_id=actor_id, action=action, entity_type=entity_type,
                     entity_id=str(entity_id) if entity_id is not None else None, changes=_jsonable(changes), ip_address=ip)
    db.add(entry)
    log.info("audit", extra={"org_id": org_id, "actor_id": actor_id, "action": action, "entity": entity_type, "entity_id": entity_id})
    return entry


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def diff(obj: Any, fields: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Apply `fields` onto obj and return {field: {old, new}} for real changes."""
    changes: dict[str, dict[str, Any]] = {}
    for key, new in fields.items():
        old = getattr(obj, key)
        if old != new:
            changes[key] = {"old": _jsonable(old), "new": _jsonable(new)}
            setattr(obj, key, new)
    return changes
