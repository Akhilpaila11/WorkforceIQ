"""Shared request parameter types: pagination (``?page=1&page_size=50``, max 200), date
windows and well-formed entity IDs (a malformed ID is a 422, an unknown one a 404)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.repository import MAX_PAGE_SIZE, Page
from app.domain.ids import ID_FORMATS, EntityKind

EMPLOYEE_ID = ID_FORMATS[EntityKind.EMPLOYEE].pattern.pattern
ROLE_ID = ID_FORMATS[EntityKind.ROLE].pattern.pattern
SKILL_ID = ID_FORMATS[EntityKind.SKILL].pattern.pattern
PROJECT_ID = ID_FORMATS[EntityKind.PROJECT].pattern.pattern

# Field types for query models (path parameters use ``fastapi.Path(pattern=...)``).
EmployeeId = Annotated[str, Field(pattern=EMPLOYEE_ID, examples=["EMP-000001"])]
RoleId = Annotated[str, Field(pattern=ROLE_ID, examples=["ROL-000001"])]
SkillId = Annotated[str, Field(pattern=SKILL_ID, examples=["SKL-000001"])]
ProjectId = Annotated[str, Field(pattern=PROJECT_ID, examples=["PRJ-2026-000001"])]
SearchText = Annotated[str, Field(min_length=1, max_length=100)]
RUN_ID = ID_FORMATS[EntityKind.ANALYSIS_RUN].pattern.pattern
RECOMMENDATION_ID = ID_FORMATS[EntityKind.RECOMMENDATION].pattern.pattern
RunId = Annotated[str, Field(pattern=RUN_ID, examples=["RUN-2026-000001"])]


class QueryParams(BaseModel):
    """Base for every query-parameter model. Unknown query parameters are rejected (422)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PageQuery(QueryParams):
    page: int = Field(default=1, ge=1, description="1-based page number")
    page_size: int = Field(default=50, ge=1, le=MAX_PAGE_SIZE, description="Rows per page")


class DateWindow(QueryParams):
    """Records that overlap the inclusive window ``date_from``..``date_to``."""

    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class DateWindowQuery(PageQuery, DateWindow):
    """Paginated list filtered by an inclusive date window."""


class PageOut[ItemT](BaseModel):
    items: list[ItemT]
    page: int
    page_size: int
    total: int
    pages: int

    @classmethod
    def of(cls, page: Page[object]) -> Self:
        return cls.model_validate(
            {
                "items": list(page.items),
                "page": page.page,
                "page_size": page.page_size,
                "total": page.total,
                "pages": -(-page.total // page.page_size),
            },
            from_attributes=True,
        )
