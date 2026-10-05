"""PostgreSQL persistence for locally inferred PPE-violation events."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from modules.violation_recorder import ViolationEvent
from modules.vision_analyzer import BoundingBox

logger = logging.getLogger(__name__)


@dataclass
class ViolationEventRecord:
    event_id: str
    camera_id: str
    timestamp: datetime
    violation_types: list[str]
    snapshot_url: str | None
    confidence_scores: dict[str, float]
    upload_status: str
    bounding_boxes: list[dict]
    processing_latency: int
    inference_metadata: dict
    created_at: datetime


@dataclass
class ViolationStats:
    total_violations: int
    by_type: dict[str, int]
    avg_processing_latency_ms: float
    cameras_with_violations: list[str]


def _serialize_jsonb(value: Any) -> str:
    return json.dumps(value, default=str)


def _box_to_dict(box: BoundingBox) -> dict:
    return {
        "label": box.label, "confidence": box.confidence,
        "x_min": box.x_min, "y_min": box.y_min, "x_max": box.x_max, "y_max": box.y_max,
    }


class EventRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def insert_violation(self, event: ViolationEvent) -> str:
        sql = """
            INSERT INTO violation_events (
                camera_id, timestamp, violation_types, snapshot_url, confidence_scores,
                upload_status, bounding_boxes, processing_latency, inference_metadata
            ) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8, $9::jsonb)
            RETURNING event_id::text
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                sql, event.camera_id, event.timestamp, event.violation_types, event.snapshot_url,
                _serialize_jsonb(event.confidence_scores), event.upload_status,
                _serialize_jsonb([_box_to_dict(box) for box in event.bounding_boxes]),
                event.processing_latency_ms, _serialize_jsonb(event.inference_metadata),
            )
        return row["event_id"]

    async def query_violations(
        self, camera_id: str | None = None, start_time: datetime | None = None,
        end_time: datetime | None = None, violation_type: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> list[ViolationEventRecord]:
        conditions: list[str] = []
        parameters: list[Any] = []
        index = 1
        for condition, value in (
            ("camera_id", camera_id), ("timestamp >=", start_time), ("timestamp <=", end_time),
        ):
            if value is not None:
                conditions.append(f"{condition} ${index}")
                parameters.append(value)
                index += 1
        if violation_type is not None:
            conditions.append(f"${index} = ANY(violation_types)")
            parameters.append(violation_type)
            index += 1
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        parameters.extend((limit, offset))
        sql = f"""
            SELECT event_id::text, camera_id, timestamp, violation_types, snapshot_url,
                   confidence_scores, upload_status, bounding_boxes, processing_latency,
                   inference_metadata, created_at
            FROM violation_events {where}
            ORDER BY timestamp DESC LIMIT ${index} OFFSET ${index + 1}
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *parameters)
        return [_row_to_record(row) for row in rows]

    async def get_violation_by_id(self, event_id: str) -> ViolationEventRecord | None:
        sql = """
            SELECT event_id::text, camera_id, timestamp, violation_types, snapshot_url,
                   confidence_scores, upload_status, bounding_boxes, processing_latency,
                   inference_metadata, created_at
            FROM violation_events WHERE event_id = $1::uuid
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, event_id)
        return _row_to_record(row) if row else None

    async def get_stats(self, start_time: datetime, end_time: datetime) -> ViolationStats:
        summary_sql = """
            SELECT COUNT(*) AS total_violations, AVG(processing_latency) AS avg_latency,
                   ARRAY_AGG(DISTINCT camera_id) AS cameras
            FROM violation_events WHERE timestamp BETWEEN $1 AND $2
        """
        type_sql = """
            SELECT unnest(violation_types) AS vtype, COUNT(*) AS cnt
            FROM violation_events WHERE timestamp BETWEEN $1 AND $2 GROUP BY vtype
        """
        async with self._pool.acquire() as conn:
            summary = await conn.fetchrow(summary_sql, start_time, end_time)
            types = await conn.fetch(type_sql, start_time, end_time)
        return ViolationStats(
            total_violations=summary["total_violations"] or 0,
            by_type={row["vtype"]: row["cnt"] for row in types},
            avg_processing_latency_ms=float(summary["avg_latency"] or 0),
            cameras_with_violations=[camera for camera in (summary["cameras"] or []) if camera],
        )


def _parse_jsonb(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value) if isinstance(value, str) else value


def _row_to_record(row: asyncpg.Record) -> ViolationEventRecord:
    return ViolationEventRecord(
        event_id=row["event_id"], camera_id=row["camera_id"], timestamp=row["timestamp"],
        violation_types=list(row["violation_types"] or []), snapshot_url=row["snapshot_url"],
        confidence_scores=dict(_parse_jsonb(row["confidence_scores"]) or {}),
        upload_status=row["upload_status"], bounding_boxes=list(_parse_jsonb(row["bounding_boxes"]) or []),
        processing_latency=row["processing_latency"],
        inference_metadata=dict(_parse_jsonb(row["inference_metadata"]) or {}), created_at=row["created_at"],
    )
