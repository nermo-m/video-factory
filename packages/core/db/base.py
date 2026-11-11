"""Declarative base shared by every table.

Design doc section 9: all tables have id (UUID), created_at and updated_at.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Enum, MetaData, Numeric, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Predictable constraint names, so migrations and error messages can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Money is exact decimal with six places: single model calls cost fractions of a cent.
MONEY = Numeric(12, 6, asdecimal=True)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy reads this class attribute by name
        datetime: DateTime(timezone=True),
        Decimal: MONEY,
    }

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        sort_order=-10,
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), sort_order=900)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), sort_order=901
    )


def enum_type(enum: type[StrEnum]) -> Enum:
    """A text column that maps to a StrEnum by value. Pair it with enum_check()."""
    return Enum(
        enum,
        native_enum=False,
        length=32,
        create_constraint=False,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


def enum_check(column: str, enum: type[StrEnum]) -> CheckConstraint:
    """CHECK constraint that limits a text column to the enum's values."""
    allowed = ", ".join(f"'{member.value}'" for member in enum)
    return CheckConstraint(f"{column} IN ({allowed})", name=f"{column}_valid")


def not_negative(column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} >= 0", name=f"{column}_not_negative")
