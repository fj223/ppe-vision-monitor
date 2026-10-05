"""Pydantic schemas for local YOLOv8 monitoring results."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    label: str
    confidence: float
    x_min: int
    y_min: int
    x_max: int
    y_max: int


class ViolationEventResponse(BaseModel):
    event_id: str
    camera_id: str
    timestamp: datetime
    violation_types: list[str]
    snapshot_url: str | None
    confidence_scores: dict[str, float]
    upload_status: str
    bounding_boxes: list[BoundingBox]
    processing_latency: int = Field(description="Local YOLOv8 inference latency in milliseconds")
    inference_metadata: dict[str, Any] = Field(description="Model and inference settings recorded for this event")
    created_at: datetime
    model_config = {"from_attributes": True}


class ViolationEventSummary(BaseModel):
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
    items: list[ViolationEventSummary]
    total: int
    limit: int
    offset: int


class CameraStatusResponse(BaseModel):
    camera_id: str
    status: str


class CameraListResponse(BaseModel):
    cameras: list[CameraStatusResponse]


class ViolationStatsResponse(BaseModel):
    total_violations: int
    by_type: dict[str, int]
    avg_processing_latency_ms: float
    cameras_with_violations: list[str]
    start_time: datetime
    end_time: datetime


class ViolationQueryParams(BaseModel):
    camera_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    violation_type: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class ErrorResponse(BaseModel):
    detail: str
