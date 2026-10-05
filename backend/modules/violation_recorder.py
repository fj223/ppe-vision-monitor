"""Local snapshot persistence for PPE violation events."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from modules.vision_analyzer import AnalysisResult, BoundingBox

logger = logging.getLogger(__name__)
_MAX_UPLOAD_ATTEMPTS = 3
_RETRY_SLEEP_SECONDS = 2


@dataclass
class ViolationEvent:
    camera_id: str
    timestamp: datetime
    violation_types: list[str]
    confidence_scores: dict[str, float]
    bounding_boxes: list[BoundingBox]
    processing_latency_ms: int
    inference_metadata: dict
    snapshot_url: str | None = None
    upload_status: str = "success"


class ViolationRecorder:
    """Save JPEG snapshots locally, without a cloud-storage dependency."""

    def __init__(self) -> None:
        self._snapshot_dir = settings.snapshot_path
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)

    async def record(self, frame: bytes, result: AnalysisResult, camera_id: str) -> ViolationEvent:
        now_utc = datetime.now(timezone.utc)
        event = ViolationEvent(
            camera_id=camera_id,
            timestamp=now_utc,
            violation_types=result.violation_types,
            confidence_scores=result.confidence_scores,
            bounding_boxes=result.bounding_boxes,
            processing_latency_ms=result.processing_latency_ms,
            inference_metadata=result.inference_metadata,
        )
        key = _build_storage_key(camera_id, now_utc)
        event.snapshot_url = await self._upload_with_retry(frame, key, camera_id)
        event.upload_status = "success" if event.snapshot_url else "pending_retry"
        return event

    async def _upload_with_retry(self, frame: bytes, storage_key: str, camera_id: str) -> str | None:
        for attempt in range(1, _MAX_UPLOAD_ATTEMPTS + 1):
            try:
                await asyncio.get_running_loop().run_in_executor(None, self._write_snapshot, frame, storage_key)
                return f"/snapshots/{storage_key}"
            except Exception as exc:  # noqa: BLE001
                logger.warning("snapshot_write_failed", extra={"camera_id": camera_id, "attempt": attempt, "error": str(exc)})
                if attempt < _MAX_UPLOAD_ATTEMPTS:
                    await asyncio.sleep(_RETRY_SLEEP_SECONDS)
        return None

    def _write_snapshot(self, frame: bytes, storage_key: str) -> None:
        target = self._snapshot_dir / Path(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(frame)


def _build_storage_key(camera_id: str, ts: datetime) -> str:
    return f"violations/{camera_id}/{ts:%Y-%m-%d}/{int(ts.timestamp() * 1000)}.jpg"
