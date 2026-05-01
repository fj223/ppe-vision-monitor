"""
Cameras API route.

GET /api/v1/cameras — list all registered cameras with their current status.
(Requirement 5.4)
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from api.schemas import CameraListResponse, CameraStatusResponse

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("", response_model=CameraListResponse)
async def list_cameras(request: Request) -> CameraListResponse:
    """
    Return the current status of all registered cameras.
    Status values: online | offline | retrying
    """
    processor = request.app.state.video_processor
    statuses = processor.get_all_statuses()
    return CameraListResponse(
        cameras=[
            CameraStatusResponse(camera_id=cam_id, status=status.value)
            for cam_id, status in statuses.items()
        ]
    )
