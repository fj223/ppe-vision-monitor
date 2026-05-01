"""
Pydantic request/response schemas for the PPE Compliance Monitoring API.

ViolationEventResponse strictly includes the three extended research fields:
  - bounding_boxes       : for frontend canvas overlay rendering
  - processing_latency   : for performance evaluation dashboard
  - raw_api_response     : for data replay and offline experiments
(Requirements 4.3, 4.8, 5.1–5.5)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Shared sub-models
# --------------------------------------------------------------------------- #

class BoundingBox(BaseModel):
    """
    Pixel coordinates of a single detected object.
    Used by the frontend to draw overlay rectangles on snapshot images.
    """
    label: str
    confidence: float
    x_min: int
    y_min: int
    x_max: int
    y_max: int


# --------------------------------------------------------------------------- #
# Violation responses
# --------------------------------------------------------------------------- #

class ViolationEventResponse(BaseModel):
    """
    Full violation event — returned by GET /violations/{event_id}.
    Includes all three extended research fields so the React dashboard
    can render bounding boxes and display latency metrics.
    """
    event_id: str
    camera_id: str
    timestamp: datetime
    violation_types: list[str]
    snapshot_url: str | None
    confidence_scores: dict[str, float]
    upload_status: str

    # Extended research fields (Requirements 4.3 / 4.8)
    bounding_boxes: list[BoundingBox]
    processing_latency: int = Field(
        description="Yandex Vision API round-trip time in milliseconds"
    )
    raw_api_response: dict[str, Any] = Field(
        description="Complete untruncated Yandex Vision API JSON response"
    )

    created_at: datetime

    model_config = {"from_attributes": True}


class ViolationEventSummary(BaseModel):
    """
    Lightweight summary — used in paginated list responses.
    Includes bounding_boxes and processing_latency so the list view can
    render thumbnails with overlays and latency badges without a second request.
    Omits raw_api_response to keep list payloads compact.
    """
    event_id: str
    camera_id: str
    timestamp: datetime
    violation_types: list[str]
    snapshot_url: str | None
    upload_status: str
    bounding_boxes: list[BoundingBox]
    processing_latency: int

    model_config = {"from_attributes": True}


class ViolationListResponse(BaseModel):
    """Paginated list of violation events."""
    items: list[ViolationEventSummary]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Camera responses
# --------------------------------------------------------------------------- #

class CameraStatusResponse(BaseModel):
    """Current status of a single camera."""
    camera_id: str
    status: str  # online | offline | retrying


class CameraListResponse(BaseModel):
    cameras: list[CameraStatusResponse]


# --------------------------------------------------------------------------- #
# Stats responses
# --------------------------------------------------------------------------- #

class ViolationStatsResponse(BaseModel):
    """Aggregated statistics for a time window."""
    total_violations: int
    by_type: dict[str, int]
    avg_processing_latency_ms: float
    cameras_with_violations: list[str]
    start_time: datetime
    end_time: datetime


# --------------------------------------------------------------------------- #
# Query parameter models
# --------------------------------------------------------------------------- #

class ViolationQueryParams(BaseModel):
    """
    Query parameters for GET /violations.
    All fields are optional; unset fields are ignored by the repository.
    """
    camera_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    violation_type: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


# --------------------------------------------------------------------------- #
# Error response
# --------------------------------------------------------------------------- #

class ErrorResponse(BaseModel):
    detail: str
