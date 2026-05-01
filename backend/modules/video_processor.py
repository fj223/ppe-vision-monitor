"""
Video_Processor module.

Manages one asyncio Task per RTSP camera stream.
Each task:
  1. Opens the stream with OpenCV (cv2.VideoCapture).
  2. Reads one frame every FRAME_INTERVAL_SECONDS (default 2 s).
  3. Passes the JPEG-encoded frame to Vision_Analyzer.
  4. If a violation is detected, calls Violation_Recorder then Event_Repository.
  5. On connection failure: waits 10 s and retries; after 5 consecutive failures
     logs a critical alert and stops the task.

Camera status is tracked per camera_id and exposed via get_camera_status().
(Requirements 1.1 – 1.6)
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum

import cv2
import numpy as np

from config import settings
from modules.event_repository import EventRepository
from modules.violation_recorder import ViolationRecorder
from modules.vision_analyzer import VisionAnalyzer

logger = logging.getLogger(__name__)

_RECONNECT_SLEEP = 10       # seconds between RTSP reconnect attempts
_MAX_FAILURES = 5           # consecutive failures before giving up


class CameraStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    RETRYING = "retrying"


class VideoProcessor:
    """
    Manages per-camera asyncio Tasks for continuous frame extraction.

    Usage (called from FastAPI lifespan):
        processor = VideoProcessor(analyzer, recorder, repo)
        await processor.start("cam_01", "rtsp://...")
        ...
        await processor.stop("cam_01")
    """

    def __init__(
        self,
        analyzer: VisionAnalyzer,
        recorder: ViolationRecorder,
        repository: EventRepository,
    ) -> None:
        self._analyzer = analyzer
        self._recorder = recorder
        self._repository = repository
        self._tasks: dict[str, asyncio.Task] = {}
        self._statuses: dict[str, CameraStatus] = {}

    # ---------------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------------- #

    async def start(self, camera_id: str, rtsp_url: str) -> None:
        """Start the frame-extraction loop for a camera (idempotent)."""
        if camera_id in self._tasks and not self._tasks[camera_id].done():
            logger.info("camera_already_running", extra={"camera_id": camera_id})
            return

        self._statuses[camera_id] = CameraStatus.OFFLINE
        task = asyncio.create_task(
            self._run_camera(camera_id, rtsp_url),
            name=f"video_processor_{camera_id}",
        )
        self._tasks[camera_id] = task
        logger.info("camera_task_started", extra={"camera_id": camera_id})

    async def stop(self, camera_id: str) -> None:
        """Cancel and await the task for a camera."""
        task = self._tasks.get(camera_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._statuses[camera_id] = CameraStatus.OFFLINE
        logger.info("camera_task_stopped", extra={"camera_id": camera_id})

    async def stop_all(self) -> None:
        """Stop all running camera tasks (called on app shutdown)."""
        for camera_id in list(self._tasks.keys()):
            await self.stop(camera_id)

    def get_camera_status(self, camera_id: str) -> CameraStatus:
        return self._statuses.get(camera_id, CameraStatus.OFFLINE)

    def get_all_statuses(self) -> dict[str, CameraStatus]:
        return dict(self._statuses)

    # ---------------------------------------------------------------------- #
    # Private — main loop
    # ---------------------------------------------------------------------- #

    async def _run_camera(self, camera_id: str, rtsp_url: str) -> None:
        """
        Main loop for a single camera.
        Runs until cancelled or max consecutive failures reached.
        """
        consecutive_failures = 0

        while True:
            cap = await asyncio.get_event_loop().run_in_executor(
                None, cv2.VideoCapture, rtsp_url
            )

            if not cap.isOpened():
                consecutive_failures += 1
                self._statuses[camera_id] = CameraStatus.RETRYING
                logger.warning(
                    "rtsp_connection_failed",
                    extra={
                        "camera_id": camera_id,
                        "consecutive_failures": consecutive_failures,
                        "max_failures": _MAX_FAILURES,
                    },
                )

                if consecutive_failures >= _MAX_FAILURES:
                    logger.critical(
                        "rtsp_max_failures_reached",
                        extra={
                            "camera_id": camera_id,
                            "action": "stopping_task_awaiting_manual_intervention",
                        },
                    )
                    self._statuses[camera_id] = CameraStatus.OFFLINE
                    return

                await asyncio.sleep(_RECONNECT_SLEEP)
                continue

            # Connection established
            consecutive_failures = 0
            self._statuses[camera_id] = CameraStatus.ONLINE
            logger.info("rtsp_connected", extra={"camera_id": camera_id})

            try:
                await self._frame_loop(camera_id, cap)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "frame_loop_error",
                    extra={"camera_id": camera_id, "error": str(exc)},
                )
            finally:
                await asyncio.get_event_loop().run_in_executor(None, cap.release)
                self._statuses[camera_id] = CameraStatus.RETRYING

    async def _frame_loop(
        self,
        camera_id: str,
        cap: cv2.VideoCapture,
    ) -> None:
        """
        Read frames at FRAME_INTERVAL_SECONDS intervals until the stream
        drops or the task is cancelled.
        """
        interval = settings.frame_interval_seconds

        while True:
            ret, frame_bgr = await asyncio.get_event_loop().run_in_executor(
                None, cap.read
            )

            if not ret or frame_bgr is None:
                logger.warning(
                    "frame_read_failed",
                    extra={"camera_id": camera_id},
                )
                return  # triggers reconnect in outer loop

            # Encode BGR frame to JPEG bytes
            success, buffer = cv2.imencode(".jpg", frame_bgr)
            if not success:
                logger.warning(
                    "frame_encode_failed",
                    extra={"camera_id": camera_id},
                )
                await asyncio.sleep(interval)
                continue

            frame_bytes = buffer.tobytes()

            # Analyse frame
            result = await self._analyzer.analyze(frame_bytes, camera_id)

            if result is None:
                # API error — skip frame, no violation recorded
                await asyncio.sleep(interval)
                continue

            if result.is_violation:
                await self._handle_violation(camera_id, frame_bytes, result)

            await asyncio.sleep(interval)

    async def _handle_violation(
        self,
        camera_id: str,
        frame_bytes: bytes,
        result,
    ) -> None:
        """Upload snapshot and persist the violation event."""
        try:
            event = await self._recorder.record(frame_bytes, result, camera_id)
            event_id = await self._repository.insert_violation(event)
            logger.info(
                "violation_recorded",
                extra={
                    "camera_id": camera_id,
                    "event_id": event_id,
                    "violation_types": result.violation_types,
                    "processing_latency_ms": result.processing_latency_ms,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "violation_handling_error",
                extra={"camera_id": camera_id, "error": str(exc)},
            )
