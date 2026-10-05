"""Violation-event API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.schemas import BoundingBox, ViolationEventResponse, ViolationEventSummary, ViolationListResponse
from modules.event_repository import EventRepository, ViolationEventRecord

router = APIRouter(prefix="/violations", tags=["violations"])


def get_repo(request: Request) -> EventRepository:
    return request.app.state.repository


def _record_to_response(record: ViolationEventRecord) -> ViolationEventResponse:
    return ViolationEventResponse(
        event_id=record.event_id, camera_id=record.camera_id, timestamp=record.timestamp,
        violation_types=record.violation_types, snapshot_url=record.snapshot_url,
        confidence_scores=record.confidence_scores, upload_status=record.upload_status,
        bounding_boxes=[BoundingBox(**box) for box in record.bounding_boxes],
        processing_latency=record.processing_latency, inference_metadata=record.inference_metadata,
        created_at=record.created_at,
    )


def _record_to_summary(record: ViolationEventRecord) -> ViolationEventSummary:
    return ViolationEventSummary(
        event_id=record.event_id, camera_id=record.camera_id, timestamp=record.timestamp,
        violation_types=record.violation_types, snapshot_url=record.snapshot_url,
        upload_status=record.upload_status, bounding_boxes=[BoundingBox(**box) for box in record.bounding_boxes],
        processing_latency=record.processing_latency,
    )


@router.get("", response_model=ViolationListResponse)
async def list_violations(
    repo: Annotated[EventRepository, Depends(get_repo)],
    camera_id: str | None = Query(default=None), start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None), violation_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0),
) -> ViolationListResponse:
    records = await repo.query_violations(camera_id, start_time, end_time, violation_type, limit, offset)
    return ViolationListResponse(items=[_record_to_summary(record) for record in records], total=len(records), limit=limit, offset=offset)


@router.get("/{event_id}", response_model=ViolationEventResponse)
async def get_violation(event_id: str, repo: Annotated[EventRepository, Depends(get_repo)]) -> ViolationEventResponse:
    record = await repo.get_violation_by_id(event_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Violation '{event_id}' not found")
    return _record_to_response(record)
