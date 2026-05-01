"""
Event_Repository module.

Persists violation events to PostgreSQL via asyncpg.
All queries use $N parameterized placeholders — no string interpolation.
JSONB fields (bounding_boxes, confidence_scores, raw_api_response) are
serialized to JSON strings before binding, as asyncpg requires explicit
casting for JSONB parameters.

On write failure the exception is logged and re-raised so the caller can
decide how to handle it — data is never silently discarded.
(Requirements 4.1 – 4.8)
"""

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


# --------------------------------------------------------------------------- #
# Read-side data classes
# --------------------------------------------------------------------------- #

@dataclass
class ViolationEventRecord:
    """Row returned by SELECT queries — mirrors the violation_events table."""
    event_id: str
    camera_id: str
    timestamp: datetime
    violation_types: list[str]
    snapshot_url: str | None
    confidence_scores: dict[str, float]
    upload_status: str
    # Extended research fields
    bounding_boxes: list[dict]   # raw dicts; Pydantic layer converts to BoundingBox
    processing_latency: int
    raw_api_response: dict
    created_at: datetime


@dataclass
class ViolationStats:
    total_violations: int
    by_type: dict[str, int]          # {violation_type: count}
    avg_processing_latency_ms: float
    cameras_with_violations: list[str]


# --------------------------------------------------------------------------- #
# Serialization helpers
# --------------------------------------------------------------------------- #

def _bb_to_dict(bb: BoundingBox) -> dict:
    return {
        "label": bb.label,
        "confidence": bb.confidence,
        "x_min": bb.x_min,
        "y_min": bb.y_min,
        "x_max": bb.x_max,
        "y_max": bb.y_max,
    }


def _serialize_jsonb(value: Any) -> str:
    """Serialize a Python object to a JSON string for asyncpg JSONB binding."""
    return json.dumps(value, default=str)


# --------------------------------------------------------------------------- #
# Main class
# --------------------------------------------------------------------------- #

class EventRepository:
    """
    Async repository for violation_events table.

    Requires an asyncpg connection pool injected at construction time so the
    pool lifecycle is managed by the FastAPI app (startup/shutdown events).

    Usage:
        repo = EventRepository(pool)
        event_id = await repo.insert_violation(event)
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ---------------------------------------------------------------------- #
    # Write
    # ---------------------------------------------------------------------- #

    async def insert_violation(self, event: ViolationEvent) -> str:
        """
        Insert a ViolationEvent row and return the generated event_id (UUID).
        Raises on DB error — never silently discards data.
        """
        bounding_boxes_json = _serialize_jsonb(
            [_bb_to_dict(bb) for bb in event.bounding_boxes]
        )
        confidence_scores_json = _serialize_jsonb(event.confidence_scores)
        raw_api_response_json = _serialize_jsonb(event.raw_api_response)

        sql = """
            INSERT INTO violation_events (
                camera_id,
                timestamp,
                violation_types,
                snapshot_url,
                confidence_scores,
                upload_status,
                bounding_boxes,
                processing_latency,
                raw_api_response
            ) VALUES (
                $1, $2, $3, $4,
                $5::jsonb,
                $6,
                $7::jsonb,
                $8,
                $9::jsonb
            )
            RETURNING event_id::text
        """
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    sql,
                    event.camera_id,
                    event.timestamp,
                    event.violation_types,
                    event.snapshot_url,
                    confidence_scores_json,
                    event.upload_status,
                    bounding_boxes_json,
                    event.processing_latency_ms,
                    raw_api_response_json,
                )
            event_id: str = row["event_id"]
            logger.info(
                "violation_inserted",
                extra={"event_id": event_id, "camera_id": event.camera_id},
            )
            return event_id
        except Exception as exc:
            logger.error(
                "violation_insert_failed",
                extra={"camera_id": event.camera_id, "error": str(exc)},
            )
            raise

    # ---------------------------------------------------------------------- #
    # Read — list with filters
    # ---------------------------------------------------------------------- #

    async def query_violations(
        self,
        camera_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        violation_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ViolationEventRecord]:
        """
        Return violation events matching all supplied filters.
        All filter parameters are optional; unset parameters are ignored.
        """
        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        if camera_id is not None:
            conditions.append(f"camera_id = ${idx}")
            params.append(camera_id)
            idx += 1

        if start_time is not None:
            conditions.append(f"timestamp >= ${idx}")
            params.append(start_time)
            idx += 1

        if end_time is not None:
            conditions.append(f"timestamp <= ${idx}")
            params.append(end_time)
            idx += 1

        if violation_type is not None:
            conditions.append(f"${idx} = ANY(violation_types)")
            params.append(violation_type)
            idx += 1

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        params.extend([limit, offset])
        sql = f"""
            SELECT
                event_id::text, camera_id, timestamp, violation_types,
                snapshot_url, confidence_scores, upload_status,
                bounding_boxes, processing_latency, raw_api_response, created_at
            FROM violation_events
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [_row_to_record(r) for r in rows]

    # ---------------------------------------------------------------------- #
    # Read — single record
    # ---------------------------------------------------------------------- #

    async def get_violation_by_id(self, event_id: str) -> ViolationEventRecord | None:
        """
        Return a single violation event by its UUID, including all extended
        fields (bounding_boxes, processing_latency, raw_api_response).
        Returns None if not found.
        """
        sql = """
            SELECT
                event_id::text, camera_id, timestamp, violation_types,
                snapshot_url, confidence_scores, upload_status,
                bounding_boxes, processing_latency, raw_api_response, created_at
            FROM violation_events
            WHERE event_id = $1::uuid
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, event_id)

        return _row_to_record(row) if row else None

    # ---------------------------------------------------------------------- #
    # Read — stats
    # ---------------------------------------------------------------------- #

    async def get_stats(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> ViolationStats:
        """Return aggregated statistics for the given time window."""
        sql = """
            SELECT
                COUNT(*)                        AS total_violations,
                AVG(processing_latency)         AS avg_latency,
                ARRAY_AGG(DISTINCT camera_id)   AS cameras
            FROM violation_events
            WHERE timestamp BETWEEN $1 AND $2
        """
        type_sql = """
            SELECT unnest(violation_types) AS vtype, COUNT(*) AS cnt
            FROM violation_events
            WHERE timestamp BETWEEN $1 AND $2
            GROUP BY vtype
        """
        async with self._pool.acquire() as conn:
            summary = await conn.fetchrow(sql, start_time, end_time)
            type_rows = await conn.fetch(type_sql, start_time, end_time)

        by_type = {r["vtype"]: r["cnt"] for r in type_rows}
        cameras = [c for c in (summary["cameras"] or []) if c is not None]

        return ViolationStats(
            total_violations=summary["total_violations"] or 0,
            by_type=by_type,
            avg_processing_latency_ms=float(summary["avg_latency"] or 0.0),
            cameras_with_violations=cameras,
        )


# --------------------------------------------------------------------------- #
# Row mapper
# --------------------------------------------------------------------------- #

def _parse_jsonb(value) -> Any:
    """
    Safely parse a JSONB column value from asyncpg.

    asyncpg returns JSONB columns as plain Python objects (dict/list) when a
    JSON codec is registered on the connection pool. Without an explicit codec
    it returns them as raw JSON strings. This helper handles both cases so the
    code works regardless of whether a codec was registered.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value          # already decoded by asyncpg codec
    if isinstance(value, str):
        return json.loads(value)   # raw JSON string — decode manually
    return value


def _row_to_record(row: asyncpg.Record) -> ViolationEventRecord:
    """Convert an asyncpg Record to a ViolationEventRecord dataclass."""
    bounding_boxes = _parse_jsonb(row["bounding_boxes"]) or []
    confidence_scores = _parse_jsonb(row["confidence_scores"]) or {}
    raw_api_response = _parse_jsonb(row["raw_api_response"]) or {}

    return ViolationEventRecord(
        event_id=row["event_id"],
        camera_id=row["camera_id"],
        timestamp=row["timestamp"],
        violation_types=list(row["violation_types"] or []),
        snapshot_url=row["snapshot_url"],
        confidence_scores=dict(confidence_scores),
        upload_status=row["upload_status"],
        bounding_boxes=list(bounding_boxes),
        processing_latency=row["processing_latency"],
        raw_api_response=dict(raw_api_response),
        created_at=row["created_at"],
    )
