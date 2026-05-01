"""
Violation_Recorder module.

Uploads a violation snapshot to Yandex Object Storage (S3-compatible via boto3)
and constructs a ViolationEvent carrying all three extended research fields
(bounding_boxes, processing_latency_ms, raw_api_response) from the
AnalysisResult produced by Vision_Analyzer.

Upload retry policy: max 3 attempts, 2-second sleep between retries.
On total failure the event is returned with upload_status="pending_retry"
so no violation data is silently discarded.
(Requirements 3.1 – 3.6)
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import settings
from modules.vision_analyzer import AnalysisResult, BoundingBox

logger = logging.getLogger(__name__)

_MAX_UPLOAD_ATTEMPTS = 3
_RETRY_SLEEP_SECONDS = 2


# --------------------------------------------------------------------------- #
# Data class
# --------------------------------------------------------------------------- #

@dataclass
class ViolationEvent:
    """
    Represents a single PPE violation event.
    Carries all core metadata plus the three extended research fields.
    """
    camera_id: str
    timestamp: datetime                   # UTC
    violation_types: list[str]
    confidence_scores: dict[str, float]
    bounding_boxes: list[BoundingBox]     # extended field 1
    processing_latency_ms: int            # extended field 2
    raw_api_response: dict                # extended field 3
    snapshot_url: str | None = None       # filled after successful upload
    upload_status: str = "success"        # success | pending_retry | failed


# --------------------------------------------------------------------------- #
# Main class
# --------------------------------------------------------------------------- #

class ViolationRecorder:
    """
    Uploads violation snapshots to Yandex Object Storage and builds
    ViolationEvent objects for downstream persistence.

    Usage:
        recorder = ViolationRecorder()
        event = await recorder.record(frame_bytes, analysis_result, "cam_01")
    """

    def __init__(self) -> None:
        self._s3 = boto3.client(
            "s3",
            endpoint_url=settings.yos_endpoint_url,
            aws_access_key_id=settings.yos_access_key_id,
            aws_secret_access_key=settings.yos_secret_access_key,
            region_name="ru-central1",  # Yandex Cloud region
        )
        self._bucket = settings.yos_bucket_name

    # ---------------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------------- #

    async def record(
        self,
        frame: bytes,
        result: AnalysisResult,
        camera_id: str,
    ) -> ViolationEvent:
        """
        Upload the frame snapshot and return a fully populated ViolationEvent.

        The three extended fields are copied directly from AnalysisResult so
        they are never lost even if the upload fails.
        """
        now_utc = datetime.now(timezone.utc)

        event = ViolationEvent(
            camera_id=camera_id,
            timestamp=now_utc,
            violation_types=result.violation_types,
            confidence_scores=result.confidence_scores,
            bounding_boxes=result.bounding_boxes,
            processing_latency_ms=result.processing_latency_ms,
            raw_api_response=result.raw_api_response,
        )

        storage_key = _build_storage_key(camera_id, now_utc)
        snapshot_url = await self._upload_with_retry(frame, storage_key, camera_id)

        if snapshot_url is not None:
            event.snapshot_url = snapshot_url
            event.upload_status = "success"
        else:
            event.upload_status = "pending_retry"

        return event

    # ---------------------------------------------------------------------- #
    # Private helpers
    # ---------------------------------------------------------------------- #

    async def _upload_with_retry(
        self,
        frame: bytes,
        storage_key: str,
        camera_id: str,
    ) -> str | None:
        """
        Attempt to upload frame up to _MAX_UPLOAD_ATTEMPTS times.
        Returns the public URL on success, None after all attempts fail.
        """
        for attempt in range(1, _MAX_UPLOAD_ATTEMPTS + 1):
            try:
                # boto3 S3 calls are synchronous; run in executor to avoid
                # blocking the event loop.
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._do_upload,
                    frame,
                    storage_key,
                )
                url = f"{settings.yos_endpoint_url}/{self._bucket}/{storage_key}"
                logger.info(
                    "snapshot_upload_success",
                    extra={
                        "camera_id": camera_id,
                        "storage_key": storage_key,
                        "attempt": attempt,
                    },
                )
                return url

            except (BotoCoreError, ClientError, Exception) as exc:  # noqa: BLE001
                logger.warning(
                    "snapshot_upload_failed",
                    extra={
                        "camera_id": camera_id,
                        "storage_key": storage_key,
                        "attempt": attempt,
                        "max_attempts": _MAX_UPLOAD_ATTEMPTS,
                        "error": str(exc),
                    },
                )
                if attempt < _MAX_UPLOAD_ATTEMPTS:
                    await asyncio.sleep(_RETRY_SLEEP_SECONDS)

        logger.error(
            "snapshot_upload_all_attempts_failed",
            extra={
                "camera_id": camera_id,
                "storage_key": storage_key,
                "upload_status": "pending_retry",
            },
        )
        return None

    def _do_upload(self, frame: bytes, storage_key: str) -> None:
        """Synchronous S3 put_object call (executed in thread pool)."""
        self._s3.put_object(
            Bucket=self._bucket,
            Key=storage_key,
            Body=io.BytesIO(frame),
            ContentType="image/jpeg",
        )


# --------------------------------------------------------------------------- #
# Pure helper — exposed for property testing (Task 2.5)
# --------------------------------------------------------------------------- #

def _build_storage_key(camera_id: str, ts: datetime) -> str:
    """
    Build the S3 object key for a violation snapshot.

    Format: violations/{camera_id}/{YYYY-MM-DD}/{unix_timestamp_ms}.jpg
    (Requirements 3.3)
    """
    date_str = ts.strftime("%Y-%m-%d")
    ts_ms = int(ts.timestamp() * 1000)
    return f"violations/{camera_id}/{date_str}/{ts_ms}.jpg"
