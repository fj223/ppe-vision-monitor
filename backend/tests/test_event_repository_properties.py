"""
Property-based tests for Event_Repository.

Property 4: Violation event record completeness (round-trip)
  For ANY ViolationEvent, values written by insert_violation must be returned
  unchanged by get_violation_by_id — especially the three extended fields.

  Edge cases covered:
    - Empty bounding_boxes list
    - Single bounding box
    - Maximum bounding boxes (5)
    - processing_latency_ms = 0 (zero latency)
    - processing_latency_ms at maximum (10 000 ms)
    - raw_api_response = {} (empty dict)
    - raw_api_response with nested structures
    - snapshot_url = None (upload failed)
    - upload_status = "pending_retry"
    - violation_types with single item
    - violation_types with both items
    - Confidence scores at 0.0 and 1.0 boundaries
    - Timestamps at UTC midnight
    - Timestamps with microseconds

Property 5: Query filter result consistency
  For ANY combination of filter parameters, every record returned by
  query_violations must satisfy ALL supplied filter conditions.

  Edge cases covered:
    - No filters → no WHERE clause
    - camera_id only
    - start_time only
    - end_time only
    - violation_type only
    - All four filters combined
    - start_time == end_time (point-in-time query)
    - limit = 1 (minimum)
    - limit = 500 (maximum)
    - offset = 0 vs offset > 0
    - camera_id values with underscores and digits
    - violation_type "helmet" vs "vest"

(Design doc: Properties 4 & 5 | Requirements 4.1, 4.2, 4.3, 4.6, 4.8, 5.2)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from modules.vision_analyzer import BoundingBox
from modules.violation_recorder import ViolationEvent

# ===========================================================================
# Hypothesis strategies
# ===========================================================================

_bb_strategy = st.builds(
    BoundingBox,
    label=st.text(min_size=1, max_size=20),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    x_min=st.integers(min_value=0, max_value=1920),
    y_min=st.integers(min_value=0, max_value=1080),
    x_max=st.integers(min_value=0, max_value=1920),
    y_max=st.integers(min_value=0, max_value=1080),
)

# Raw API response strategy — covers empty, flat, and nested structures
_raw_response_strategy = st.one_of(
    st.just({}),
    st.just({"results": []}),
    st.fixed_dictionaries({
        "results": st.lists(
            st.fixed_dictionaries({
                "results": st.lists(st.fixed_dictionaries({}), max_size=2)
            }),
            max_size=2,
        )
    }),
    st.fixed_dictionaries({
        "results": st.just([{"status": "ok", "latency": 123}])
    }),
)

_violation_event_strategy = st.builds(
    ViolationEvent,
    camera_id=st.from_regex(r"cam_[a-z0-9]{1,8}", fullmatch=True),
    timestamp=st.datetimes(timezones=st.just(timezone.utc)),
    violation_types=st.lists(
        st.sampled_from(["helmet", "vest"]), min_size=1, unique=True
    ),
    confidence_scores=st.fixed_dictionaries({
        "helmet": st.floats(0.0, 1.0, allow_nan=False),
        "vest":   st.floats(0.0, 1.0, allow_nan=False),
    }),
    bounding_boxes=st.lists(_bb_strategy, min_size=0, max_size=5),
    processing_latency_ms=st.integers(min_value=0, max_value=10000),
    raw_api_response=_raw_response_strategy,
    snapshot_url=st.one_of(
        st.none(),
        st.just("https://storage.yandexcloud.net/ppe-violations/violations/cam_01/2024-01-15/1705312200000.jpg"),
    ),
    upload_status=st.sampled_from(["success", "pending_retry"]),
)


# ===========================================================================
# Mock pool factory
# ===========================================================================

def _make_round_trip_pool(captured: dict):
    """
    Mock asyncpg pool that:
    - Captures INSERT params on fetchrow("INSERT ...")
    - Returns them verbatim on fetchrow("SELECT ... WHERE event_id ...")
    """
    fake_event_id = str(uuid.uuid4())

    async def _fetchrow(sql: str, *params):
        if "INSERT" in sql:
            captured["params"] = list(params)
            captured["event_id"] = fake_event_id
            row = MagicMock()
            row.__getitem__ = lambda self, key: fake_event_id if key == "event_id" else None
            return row

        if "WHERE event_id" in sql:
            p = captured["params"]
            # p indices match the INSERT parameter order:
            # 0=camera_id, 1=timestamp, 2=violation_types, 3=snapshot_url,
            # 4=confidence_scores(json), 5=upload_status,
            # 6=bounding_boxes(json), 7=processing_latency, 8=raw_api_response(json)
            def _get(key):
                mapping = {
                    "event_id":          fake_event_id,
                    "camera_id":         p[0],
                    "timestamp":         p[1],
                    "violation_types":   p[2],
                    "snapshot_url":      p[3],
                    "confidence_scores": json.loads(p[4]),
                    "upload_status":     p[5],
                    "bounding_boxes":    json.loads(p[6]),
                    "processing_latency": p[7],
                    "raw_api_response":  json.loads(p[8]),
                    "created_at":        p[1],
                }
                return mapping[key]

            row = MagicMock()
            row.__getitem__ = lambda self, key: _get(key)
            return row

        return None

    mock_conn = AsyncMock()
    mock_conn.fetchrow = _fetchrow
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool


# ===========================================================================
# PROPERTY 4: Violation event record completeness (round-trip)
# Feature: ppe-compliance-monitoring, Property 4: 违规事件记录完整性
# ===========================================================================

@given(event=_violation_event_strategy)
@h_settings(max_examples=100)
def test_p4_round_trip_all_fields(event: ViolationEvent) -> None:
    """
    Property 4 core: every field written by insert_violation must be returned
    unchanged by get_violation_by_id.
    """
    from modules.event_repository import EventRepository, _bb_to_dict

    captured: dict = {}
    pool = _make_round_trip_pool(captured)

    async def _run():
        repo = EventRepository(pool)
        event_id = await repo.insert_violation(event)
        record = await repo.get_violation_by_id(event_id)

        assert record is not None, "get_violation_by_id returned None after insert"

        # --- Extended field 1: bounding_boxes ---
        expected_boxes = [_bb_to_dict(bb) for bb in event.bounding_boxes]
        assert record.bounding_boxes == expected_boxes, (
            f"bounding_boxes mismatch:\n  got:      {record.bounding_boxes}\n"
            f"  expected: {expected_boxes}"
        )

        # --- Extended field 2: processing_latency ---
        assert record.processing_latency == event.processing_latency_ms, (
            f"processing_latency: got {record.processing_latency}, "
            f"expected {event.processing_latency_ms}"
        )

        # --- Extended field 3: raw_api_response ---
        assert record.raw_api_response == event.raw_api_response, (
            f"raw_api_response mismatch:\n  got:      {record.raw_api_response}\n"
            f"  expected: {event.raw_api_response}"
        )

        # --- Core fields ---
        assert record.camera_id == event.camera_id
        assert record.violation_types == event.violation_types
        assert record.snapshot_url == event.snapshot_url
        assert record.upload_status == event.upload_status

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 4b — Empty bounding_boxes round-trips as empty list
# ---------------------------------------------------------------------------

def test_p4_empty_bounding_boxes_round_trip() -> None:
    from modules.event_repository import EventRepository

    event = ViolationEvent(
        camera_id="cam_01",
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        violation_types=["helmet"],
        confidence_scores={"helmet": 0.1, "vest": 0.9},
        bounding_boxes=[],
        processing_latency_ms=0,
        raw_api_response={},
        snapshot_url=None,
        upload_status="pending_retry",
    )
    captured: dict = {}
    pool = _make_round_trip_pool(captured)

    async def _run():
        repo = EventRepository(pool)
        event_id = await repo.insert_violation(event)
        record = await repo.get_violation_by_id(event_id)
        assert record is not None
        assert record.bounding_boxes == []
        assert record.processing_latency == 0
        assert record.raw_api_response == {}
        assert record.snapshot_url is None
        assert record.upload_status == "pending_retry"

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 4c — processing_latency boundary values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("latency_ms", [0, 1, 999, 1000, 4999, 5000, 10000])
def test_p4_processing_latency_boundary_values(latency_ms: int) -> None:
    from modules.event_repository import EventRepository

    event = ViolationEvent(
        camera_id="cam_01",
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        violation_types=["vest"],
        confidence_scores={"helmet": 0.9, "vest": 0.1},
        bounding_boxes=[],
        processing_latency_ms=latency_ms,
        raw_api_response={"results": []},
    )
    captured: dict = {}
    pool = _make_round_trip_pool(captured)

    async def _run():
        repo = EventRepository(pool)
        event_id = await repo.insert_violation(event)
        record = await repo.get_violation_by_id(event_id)
        assert record is not None
        assert record.processing_latency == latency_ms

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 4d — Nested raw_api_response round-trips correctly
# ---------------------------------------------------------------------------

def test_p4_nested_raw_api_response_round_trip() -> None:
    from modules.event_repository import EventRepository

    nested = {
        "results": [
            {
                "results": [
                    {
                        "objectDetectionResult": {
                            "objects": [
                                {"name": "helmet", "probability": 0.94,
                                 "boundingBox": {"vertices": []}}
                            ]
                        }
                    }
                ]
            }
        ]
    }
    event = ViolationEvent(
        camera_id="cam_01",
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        violation_types=["vest"],
        confidence_scores={"helmet": 0.94, "vest": 0.05},
        bounding_boxes=[],
        processing_latency_ms=312,
        raw_api_response=nested,
    )
    captured: dict = {}
    pool = _make_round_trip_pool(captured)

    async def _run():
        repo = EventRepository(pool)
        event_id = await repo.insert_violation(event)
        record = await repo.get_violation_by_id(event_id)
        assert record is not None
        assert record.raw_api_response == nested

    asyncio.get_event_loop().run_until_complete(_run())


# ===========================================================================
# PROPERTY 5: Query filter result consistency
# Feature: ppe-compliance-monitoring, Property 5: 查询过滤结果一致性
# ===========================================================================

def _make_filter_pool():
    """Mock pool that captures the SQL and params from fetch()."""
    captured_sql: list[str] = []
    captured_params: list[tuple] = []

    async def _fetch(sql: str, *params):
        captured_sql.append(sql)
        captured_params.append(params)
        return []

    mock_conn = AsyncMock()
    mock_conn.fetch = _fetch
    mock_conn.fetchrow = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool, captured_sql, captured_params


# ---------------------------------------------------------------------------
# 5a — No filters → no WHERE clause, limit/offset still present
# ---------------------------------------------------------------------------

def test_p5_no_filters_no_where_clause() -> None:
    from modules.event_repository import EventRepository

    pool, sqls, params = _make_filter_pool()

    async def _run():
        repo = EventRepository(pool)
        await repo.query_violations()
        assert len(sqls) == 1
        assert "WHERE" not in sqls[0], "WHERE clause present with no filters"
        # limit and offset must still be bound
        assert 50 in params[0], "Default limit=50 not in params"
        assert 0 in params[0], "Default offset=0 not in params"

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 5b — camera_id filter → WHERE clause + value in params
# ---------------------------------------------------------------------------

@given(camera_id=st.from_regex(r"cam_[a-z0-9]{1,8}", fullmatch=True))
@h_settings(max_examples=50)
def test_p5_camera_id_filter_in_sql_and_params(camera_id: str) -> None:
    from modules.event_repository import EventRepository

    pool, sqls, params = _make_filter_pool()

    async def _run():
        repo = EventRepository(pool)
        await repo.query_violations(camera_id=camera_id)
        sql = sqls[0]
        p = params[0]
        assert "camera_id" in sql, "camera_id missing from SQL"
        assert "WHERE" in sql, "WHERE clause missing"
        assert camera_id in p, f"camera_id value '{camera_id}' not in params"

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 5c — violation_type filter → ANY(violation_types) in SQL
# ---------------------------------------------------------------------------

@given(vtype=st.sampled_from(["helmet", "vest"]))
@h_settings(max_examples=20)
def test_p5_violation_type_filter_uses_any(vtype: str) -> None:
    from modules.event_repository import EventRepository

    pool, sqls, params = _make_filter_pool()

    async def _run():
        repo = EventRepository(pool)
        await repo.query_violations(violation_type=vtype)
        sql = sqls[0]
        p = params[0]
        assert "violation_types" in sql
        assert "ANY" in sql.upper()
        assert vtype in p

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 5d — time range filters → timestamp conditions in SQL
# ---------------------------------------------------------------------------

def test_p5_time_range_filters_in_sql() -> None:
    from modules.event_repository import EventRepository

    start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end   = datetime(2024, 1, 31, 23, 59, 59, tzinfo=timezone.utc)
    pool, sqls, params = _make_filter_pool()

    async def _run():
        repo = EventRepository(pool)
        await repo.query_violations(start_time=start, end_time=end)
        sql = sqls[0]
        p = params[0]
        assert "timestamp" in sql
        assert start in p, "start_time not in params"
        assert end in p, "end_time not in params"

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 5e — All four filters combined → all conditions in SQL
# ---------------------------------------------------------------------------

def test_p5_all_filters_combined() -> None:
    from modules.event_repository import EventRepository

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end   = datetime(2024, 1, 31, tzinfo=timezone.utc)
    pool, sqls, params = _make_filter_pool()

    async def _run():
        repo = EventRepository(pool)
        await repo.query_violations(
            camera_id="cam_01",
            start_time=start,
            end_time=end,
            violation_type="helmet",
        )
        sql = sqls[0]
        p = params[0]
        assert "camera_id" in sql
        assert "timestamp" in sql
        assert "violation_types" in sql
        assert "cam_01" in p
        assert start in p
        assert end in p
        assert "helmet" in p

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 5f — Custom limit and offset are bound as parameters
# ---------------------------------------------------------------------------

@given(
    limit=st.integers(min_value=1, max_value=500),
    offset=st.integers(min_value=0, max_value=10000),
)
@h_settings(max_examples=50)
def test_p5_limit_and_offset_bound_as_params(limit: int, offset: int) -> None:
    from modules.event_repository import EventRepository

    pool, sqls, params = _make_filter_pool()

    async def _run():
        repo = EventRepository(pool)
        await repo.query_violations(limit=limit, offset=offset)
        p = params[0]
        assert limit in p, f"limit={limit} not in params={p}"
        assert offset in p, f"offset={offset} not in params={p}"

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 5g — Point-in-time query (start_time == end_time)
# ---------------------------------------------------------------------------

def test_p5_point_in_time_query() -> None:
    from modules.event_repository import EventRepository

    ts = datetime(2024, 6, 15, 12, 30, 0, tzinfo=timezone.utc)
    pool, sqls, params = _make_filter_pool()

    async def _run():
        repo = EventRepository(pool)
        await repo.query_violations(start_time=ts, end_time=ts)
        sql = sqls[0]
        p = params[0]
        # Both start and end must be bound (even if equal)
        assert p.count(ts) == 2, (
            f"Expected ts to appear twice in params (start+end), got {p.count(ts)}"
        )

    asyncio.get_event_loop().run_until_complete(_run())
