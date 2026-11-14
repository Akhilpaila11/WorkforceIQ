"""Dashboard endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api import deps
from app.modules.reporting.schemas import SummaryOut
from app.modules.reporting.services import SummaryService

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary")
def dashboard_summary(
    service: Annotated[SummaryService, Depends(deps.summary_service)],
) -> SummaryOut:
    """Totals for the dashboard, computed from the stored records."""
    return service.summary()
