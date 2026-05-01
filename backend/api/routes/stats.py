"""
Stats API route.

GET /api/v1/stats — aggregated violation statistics for a time window.
(Requirement 5.5)
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from typing import Annotated

from api.schemas import ViolationStatsResponse
from modules.event_repository import EventRepository

router = APIRouter(prefix="/stats", tags=["stats"])


def get_repo(request: Request) -> EventRepository:
    return request.app.state.repository


@router.get("", response_model=ViolationStatsResponse)
async def get_stats(
    repo: Annotated[EventRepository, Depends(get_repo)],
    start_time: datetime = Query(
        default=None,
        description="Start of the time window (ISO 8601). Defaults to start of today (UTC).",
    ),
    end_time: datetime = Query(
        default=None,
        description="End of the time window (ISO 8601). Defaults to now (UTC).",
    ),
) -> ViolationStatsResponse:
    """
    Return aggregated violation statistics for the given time window.
    Defaults to today (UTC) when start_time / end_time are omitted.
    """
    now = datetime.now(timezone.utc)
    if end_time is None:
        end_time = now
    if start_time is None:
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)

    stats = await repo.get_stats(start_time, end_time)
    return ViolationStatsResponse(
        total_violations=stats.total_violations,
        by_type=stats.by_type,
        avg_processing_latency_ms=stats.avg_processing_latency_ms,
        cameras_with_violations=stats.cameras_with_violations,
        start_time=start_time,
        end_time=end_time,
    )
