"""
Vision Analyzer module.

Uses a local YOLOv8 model (best.pt) to analyse JPEG frames for PPE compliance.
Returns AnalysisResult on success, never raises to the caller.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import cv2
import numpy as np
from ultralytics import YOLO

logger = logging.getLogger(__name__)

# PPE categories that MUST be present for a frame to be compliant.
REQUIRED_PPE: frozenset[str] = frozenset({"helmet", "vest"})


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #

@dataclass
class BoundingBox:
    """Pixel coordinates of a detected object region."""
    label: str
    confidence: float
    x_min: int
    y_min: int
    x_max: int
    y_max: int


@dataclass
class AnalysisResult:
    """Structured result of a single frame analysis."""
    is_violation: bool
    violation_types: list[str]
    detected_ppe: list[str]
    confidence_scores: dict[str, float]
    bounding_boxes: list[BoundingBox]
    processing_latency_ms: int
    raw_api_response: dict


# --------------------------------------------------------------------------- #
# Main class
# --------------------------------------------------------------------------- #

class VisionAnalyzer:
    """
    Wraps a local YOLOv8 model for PPE compliance analysis.

    Usage:
        analyzer = VisionAnalyzer()
        result = await analyzer.analyze(frame_bytes, camera_id="cam_01")
    """

    def __init__(self) -> None:
        # 获取当前文件 (vision_analyzer.py) 所在的绝对路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # 向上一级获取 backend 根目录，并拼接 best.pt
        model_path = os.path.join(os.path.dirname(current_dir), "best.pt")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"致命错误：未找到模型文件 {model_path}")
        self.model = YOLO(model_path)

    async def analyze(self, frame: bytes, camera_id: str) -> AnalysisResult | None:
        """
        Analyse a single JPEG frame for PPE compliance using YOLOv8.

        Returns AnalysisResult on success.
        Returns None on any error — never raises.
        """
        try:
            img = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                logger.warning("vision_decode_failed", extra={"camera_id": camera_id})
                return None

            t0 = time.monotonic()
            results = self.model(img, conf=0.5)[0]
            processing_latency_ms = int((time.monotonic() - t0) * 1000)

            bounding_boxes: list[BoundingBox] = []
            confidence_scores: dict[str, float] = {}

            for box in results.boxes:
                x_min, y_min, x_max, y_max = map(int, box.xyxy[0].cpu().tolist())
                conf = float(box.conf[0].cpu().item())
                cls_id = int(box.cls[0].cpu().item())
                label = self.model.names[cls_id]

                bounding_boxes.append(BoundingBox(
                    label=label,
                    confidence=conf,
                    x_min=x_min,
                    y_min=y_min,
                    x_max=x_max,
                    y_max=y_max,
                ))

                # Keep highest confidence per label
                if conf > confidence_scores.get(label, 0.0):
                    confidence_scores[label] = float(conf)

            detected_ppe = [
                label for label in confidence_scores
                if label in REQUIRED_PPE
            ]
            violation_types = sorted(REQUIRED_PPE - set(detected_ppe))
            is_violation = len(violation_types) > 0

            logger.info(
                "vision_analysis_complete",
                extra={
                    "camera_id": camera_id,
                    "is_violation": is_violation,
                    "violation_types": violation_types,
                    "detected_ppe": detected_ppe,
                    "processing_latency_ms": processing_latency_ms,
                    "bounding_boxes_count": len(bounding_boxes),
                },
            )

            logger.debug("confidence_scores_debug: %s", confidence_scores)

            return AnalysisResult(
                is_violation=is_violation,
                violation_types=violation_types,
                detected_ppe=detected_ppe,
                confidence_scores=confidence_scores,
                bounding_boxes=bounding_boxes,
                processing_latency_ms=processing_latency_ms,
                raw_api_response={
                    "detections": len(bounding_boxes),
                    "latency_ms": processing_latency_ms,
                },
            )

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "vision_analysis_error",
                extra={"camera_id": camera_id, "error": str(exc)},
            )
            return None
