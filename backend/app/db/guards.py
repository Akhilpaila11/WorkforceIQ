"""Immutable identifiers (BR-VAL-007).

Before every flush, any persistent object whose primary key or ``__immutable__`` column has
changed causes :class:`~app.domain.errors.ImmutableFieldError`. Installed once per session
factory with :func:`install_immutability_guard`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.domain.errors import ImmutableFieldError


def _protected_columns(obj: Base) -> tuple[str, ...]:
    mapper = inspect(type(obj))
    pk_attrs = tuple(mapper.get_property_by_column(c).key for c in mapper.primary_key)
    return pk_attrs + type(obj).__immutable__


def _check_immutable(session: Session, _flush_context: Any, _instances: Any) -> None:
    for obj in session.dirty:
        if not isinstance(obj, Base):
            continue
        state = inspect(obj)
        for key in _protected_columns(obj):
            if state.attrs[key].history.has_changes():
                raise ImmutableFieldError(type(obj).__tablename__, key)


def install_immutability_guard(factory: sessionmaker[Session]) -> sessionmaker[Session]:
    """Register the guard once on the ``Session`` base class (covers every session).

    Registering per ``sessionmaker`` is unreliable: each factory creates a throw-away Session
    subclass, and SQLAlchemy's event registry can confuse a garbage-collected class with a new
    one at the same address, so ``event.contains`` may wrongly report the guard as installed.
    """
    if not event.contains(Session, "before_flush", _check_immutable):
        event.listen(Session, "before_flush", _check_immutable)
    return factory
