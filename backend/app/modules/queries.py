"""Read use-cases shared by every module (list with filters, get one, list a parent's children).

Services depend only on the Protocols below; each module's ``sql_repositories.py`` provides
the SQLAlchemy implementation and ``app/api/deps.py`` wires them together. A new read-only
resource needs a repository and a query model - no new service class (Open/Closed).
"""

from __future__ import annotations

from typing import Protocol

from app.db.repository import Page
from app.domain.errors import NotFoundError


class Searchable[M, Q](Protocol):
    def get(self, entity_id: str) -> M | None: ...

    def search(self, query: Q) -> Page[M]: ...


class ChildSearchable[M, Q](Protocol):
    def search_for(self, parent_id: str, query: Q) -> Page[M]: ...


class ParentChecker(Protocol):
    def exists(self, entity_id: str) -> bool: ...


class QueryService[M, Q]:
    """List (filtered, paginated) and fetch one entity; a missing record is a ``NotFoundError``."""

    def __init__(self, repository: Searchable[M, Q], *, entity: str) -> None:
        self._repository = repository
        self._entity = entity

    def list(self, query: Q) -> Page[M]:
        return self._repository.search(query)

    def get(self, entity_id: str) -> M:
        found = self._repository.get(entity_id)
        if found is None:
            raise NotFoundError(self._entity, entity_id)
        return found


class ChildQueryService[M, Q]:
    """List the children of one parent (e.g. an employee's skills); unknown parent -> 404."""

    def __init__(
        self, parents: ParentChecker, children: ChildSearchable[M, Q], *, parent_entity: str
    ) -> None:
        self._parents = parents
        self._children = children
        self._parent_entity = parent_entity

    def list(self, parent_id: str, query: Q) -> Page[M]:
        if not self._parents.exists(parent_id):
            raise NotFoundError(self._parent_entity, parent_id)
        return self._children.search_for(parent_id, query)
