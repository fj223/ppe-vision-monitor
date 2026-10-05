"""Local YOLOv8 inference for PPE compliance monitoring."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from config import settings

logger = logging.getLogger(__name__)
REQUIRED_PPE: frozenset[str] = frozenset({"helmet", "vest"})


@dataclass
class BoundingBox:
    label: str
    confidence: float
    x_min: int
    y_min: int
    x_max: int
    y_max: int


@dataclass
class AnalysisResult:
    is_violation: bool
    violation_types: list[str]
    detected_ppe: list[str]
    confidence_scores: dict[str, float]
    bounding_boxes: list[BoundingBox]
    processing_latency_ms: int
    inference_metadata: dict


class VisionAnalyzer:
    """Load a fine-tuned YOLOv8 model once and analyse JPEG frames locally."""

    def __init__(self) -> None:
        model_path = Path(settings.model_path)
        if not model_path.is_absolute():
            model_path = Path(__file__).resolve().parents[1] / model_path
        if not model_path.is_file():
            raise FileNotFoundError(
                f"YOLOv8 weights were not found at '{model_path}'. "
                "Run backend/training/train.py and copy best.pt to backend/models/."
            )
        self.model_path = model_path
        from ultralytics import YOLO

        self.model = YOLO(model_path)

    async def analyze(self, frame: bytes, camera_id: str) -> AnalysisResult | None:
        """Return PPE detections for a JPEG frame, or ``None`` if inference fails."""
        try:
            image = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                logger.warning("vision_decode_failed", extra={"camera_id": camera_id})
                return None

            options: dict[str, object] = {"conf": settings.model_confidence}
            if settings.model_device:
                options["device"] = settings.model_device
            started = time.monotonic()
            result = self.model(image, **options)[0]
            latency_ms = int((time.monotonic() - started) * 1000)

            boxes: list[BoundingBox] = []
            confidence_scores: dict[str, float] = {}
            for box in result.boxes:
                x_min, y_min, x_max, y_max = map(int, box.xyxy[0].cpu().tolist())
                confidence = float(box.conf[0].cpu().item())
                class_id = int(box.cls[0].cpu().item())
                label = str(self.model.names[class_id])
                boxes.append(BoundingBox(label, confidence, x_min, y_min, x_max, y_max))
                confidence_scores[label] = max(confidence, confidence_scores.get(label, 0.0))

            detected_ppe = sorted(set(confidence_scores) & REQUIRED_PPE)
            violation_types = sorted(REQUIRED_PPE - set(detected_ppe))
            return AnalysisResult(
                is_violation=bool(violation_types),
                violation_types=violation_types,
                detected_ppe=detected_ppe,
                confidence_scores=confidence_scores,
                bounding_boxes=boxes,
                processing_latency_ms=latency_ms,
                inference_metadata={
                    "engine": "ultralytics-yolov8",
                    "model_path": str(self.model_path),
                    "confidence_threshold": settings.model_confidence,
                    "detections": len(boxes),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("yolov8_inference_failed", extra={"camera_id": camera_id, "error": str(exc)})
            return None
