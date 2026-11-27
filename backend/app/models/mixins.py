from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.core.db import UTCDateTime
from app.core.timeutils import utcnow


def str_enum(enum_cls: type[StrEnum], length: int = 32) -> Enum:
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
        name=enum_cls.__name__.lower(),
    )


class IdMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class OrgScopedMixin:
    """Every business record belongs to exactly one organization (tenant)."""

    @declared_attr
    def organization_id(cls) -> Mapped[int]:  # noqa: N805
        return mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
