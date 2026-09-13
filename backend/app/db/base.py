"""Declarative base and SQLAlchemy type helpers.

All ORM models inherit from :class:`Base`. Enum columns are stored as
controlled string values via :func:`enum_column`, which keeps the database
representation stable and round-trips back to the Pydantic enums.
"""

from typing import TypeVar

from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase

ENUM_T = TypeVar("ENUM_T")


class Base(DeclarativeBase):
    pass


def enum_column(enum_cls, nullable: bool = False) -> SAEnum:
    """Configure a non-native enum column storing ``member.value`` strings."""
    return SAEnum(
        enum_cls,
        values_callable=lambda enum: [member.value for member in enum],
        native_enum=False,
        validate_strings=True,
        nullable=nullable,
        length=max(len(member.value) for member in enum_cls) + 2,
    )