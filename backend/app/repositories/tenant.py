"""Tenant-scoped data access. Every lookup is filtered by the caller's organization so a foreign
id behaves exactly like a missing one (404, never 403, to avoid leaking existence)."""
from __future__ import annotations

from typing import Generic, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class TenantRepository(Generic[T]):
    def __init__(self, model: type[T], db: Session, org_id: int, label: str | None = None):
        self.model, self.db, self.org_id = model, db, org_id
        self.label = label or model.__name__

    def query(self) -> Select:
        return select(self.model).where(self.model.organization_id == self.org_id)  # type: ignore[attr-defined]

    def get(self, obj_id: int) -> T | None:
        obj = self.db.get(self.model, obj_id)
        return obj if obj is not None and obj.organization_id == self.org_id else None  # type: ignore[attr-defined]

    def get_or_404(self, obj_id: int) -> T:
        obj = self.get(obj_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{self.label} not found")
        return obj

    def list(self, stmt: Select | None = None, *, order_by=None, offset: int = 0, limit: int | None = None) -> list[T]:
        stmt = stmt if stmt is not None else self.query()
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        if offset:
            stmt = stmt.offset(offset)
        if limit:
            stmt = stmt.limit(limit)
        return list(self.db.scalars(stmt).unique().all())

    def count(self, stmt: Select | None = None) -> int:
        stmt = stmt if stmt is not None else self.query()
        return self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    def ids_belong(self, ids: set[int]) -> bool:
        if not ids:
            return True
        n = self.db.scalar(select(func.count()).select_from(self.model).where(self.model.id.in_(ids), self.model.organization_id == self.org_id))  # type: ignore[attr-defined]
        return n == len(ids)
