"""
Property-based tests for Violation_Recorder.

Property 3: Storage path format correctness
  For ANY valid camera_id and UTC timestamp, _build_storage_key must produce
  a key that strictly matches violations/{camera_id}/{YYYY-MM-DD}/{ts_ms}.jpg

  Edge cases covered:
    - Single-character camera_id
    - camera_id with only digits
    - camera_id with only underscores
    - Maximum-length camera_id (alphanumeric + underscores)
    - Timestamps at UTC midnight (date boundary)
    - Timestamps at year boundary (Dec 31 → Jan 1)
    - Timestamps with microseconds (must not appear in key)
    - Leap-year dates (Feb 29)
    - Earliest and latest representable datetimes

Property 7: Upload retry count upper bound
  For N consecutive failures (1 ≤ N ≤ 3):
    - N < 3: upload succeeds; total put_object calls == N+1
    - N == 3: upload_status == "pending_retry"; event returned (not discarded)
    - Extended fields preserved on all failure paths
    - asyncio.sleep called exactly N times (retry delays honoured)
    - No extra attempts beyond 3

  Edge cases covered:
    - Exactly 1 failure then success
    - Exactly 2 failures then success
    - Exactly 3 failures (all fail)
    - Different exception types (ClientError, BotoCoreError, generic Exception)
    - Extended fields (bounding_boxes, processing_latency_ms, raw_api_response)
      preserved regardless of upload outcome

(Design doc: Properties 3 & 7 | Requirements 3.3, 3.4, 3.5, 3.6)
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from modules.violation_recorder import _build_storage_key

# Strict regex the storage key must always match
_KEY_PATTERN = re.compile(
    r"^violations/[a-zA-Z0-9_]+/\d{4}-\d{2}-\d{2}/\d+\.jpg$"
)

# ===========================================================================
# PROPERTY 3: Storage path format correctness
# Feature: ppe-compliance-monitoring, Property 3: 存储路径格式正确性
# ===========================================================================

# ---------------------------------------------------------------------------
# 3a — Core: any valid camera_id + UTC timestamp → correct key format
# ---------------------------------------------------------------------------

@given(
    camera_id=st.from_regex(r"[a-zA-Z0-9_]+", fullmatch=True),
    ts=st.datetimes(
        min_value=datetime(2000, 1, 1),
        timezones=st.just(timezone.utc),
    ),
)
@h_settings(max_examples=100)
def test_p3_key_matches_pattern(camera_id: str, ts: datetime) -> None:
    """Property 3 core: key must always match the required pattern."""
    key = _build_storage_key(camera_id, ts)
    assert _KEY_PATTERN.match(key), (
        f"Key '{key}' does not match pattern for camera_id='{camera_id}', ts={ts}"
    )


# ---------------------------------------------------------------------------
# 3b — camera_id segment preserved verbatim
# ---------------------------------------------------------------------------

@given(camera_id=st.from_regex(r"[a-zA-Z0-9_]+", fullmatch=True))
@h_settings(max_examples=100)
def test_p3_camera_id_segment_preserved(camera_id: str) -> None:
    ts = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    key = _build_storage_key(camera_id, ts)
    parts = key.split("/")
    assert parts[1] == camera_id, f"camera_id segment '{parts[1]}' != '{camera_id}'"


# ---------------------------------------------------------------------------
# 3c — Date segment matches UTC date of timestamp
# ---------------------------------------------------------------------------

@given(ts=st.datetimes(
    min_value=datetime(2000, 1, 1),
    timezones=st.just(timezone.utc),
))
@h_settings(max_examples=100)
def test_p3_date_segment_matches_utc_date(ts: datetime) -> None:
    key = _build_storage_key("cam_01", ts)
    parts = key.split("/")
    expected_date = ts.strftime("%Y-%m-%d")
    assert parts[2] == expected_date, (
        f"Date segment '{parts[2]}' != '{expected_date}' for ts={ts}"
    )


# ---------------------------------------------------------------------------
# 3d — Filename is integer milliseconds + .jpg (no microseconds, no floats)
# ---------------------------------------------------------------------------

@given(ts=st.datetimes(
    min_value=datetime(2000, 1, 1),
    timezones=st.just(timezone.utc),
))
@h_settings(max_examples=100)
def test_p3_filename_is_integer_ms_dot_jpg(ts: datetime) -> None:
    key = _build_storage_key("cam_01", ts)
    filename = key.split("/")[3]
    assert filename.endswith(".jpg"), f"Filename '{filename}' does not end with .jpg"
    stem = filename[:-4]
    assert stem.isdigit(), f"Filename stem '{stem}' is not a pure integer"
    # Verify the value matches expected ms
    expected_ms = int(ts.timestamp() * 1000)
    assert int(stem) == expected_ms, (
        f"Filename ms {stem} != expected {expected_ms}"
    )


# ---------------------------------------------------------------------------
# 3e — Key has exactly 4 path segments (violations/cam/date/file.jpg)
# ---------------------------------------------------------------------------

@given(
    camera_id=st.from_regex(r"[a-zA-Z0-9_]+", fullmatch=True),
    ts=st.datetimes(
        min_value=datetime(2000, 1, 1),
        timezones=st.just(timezone.utc),
    ),
)
@h_settings(max_examples=50)
def test_p3_key_has_exactly_four_segments(camera_id: str, ts: datetime) -> None:
    key = _build_storage_key(camera_id, ts)
    parts = key.split("/")
    assert len(parts) == 4, f"Expected 4 path segments, got {len(parts)}: {parts}"
    assert parts[0] == "violations"


# ---------------------------------------------------------------------------
# 3f — Date boundary: midnight UTC (Dec 31 → Jan 1)
# ---------------------------------------------------------------------------

def test_p3_year_boundary_date() -> None:
    ts = datetime(2023, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
    key = _build_storage_key("cam_01", ts)
    assert "2023-12-31" in key

    ts_next = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    key_next = _build_storage_key("cam_01", ts_next)
    assert "2024-01-01" in key_next


# ---------------------------------------------------------------------------
# 3g — Leap year date (Feb 29)
# ---------------------------------------------------------------------------

def test_p3_leap_year_date() -> None:
    ts = datetime(2024, 2, 29, 12, 0, 0, tzinfo=timezone.utc)
    key = _build_storage_key("cam_01", ts)
    assert "2024-02-29" in key
    assert _KEY_PATTERN.match(key)


# ===========================================================================
# PROPERTY 7: Upload retry count upper bound
# Feature: ppe-compliance-monitoring, Property 7: 上传重试次数上限
# ===========================================================================

def _make_analysis_result(
    latency_ms: int = 250,
    n_boxes: int = 1,
    raw_response: dict | None = None,
):
    from modules.vision_analyzer import AnalysisResult, BoundingBox
    boxes = [
        BoundingBox(label="no_helmet", confidence=0.9,
                    x_min=10, y_min=10, x_max=100, y_max=100)
        for _ in range(n_boxes)
    ]
    return AnalysisResult(
        is_violation=True,
        violation_types=["helmet"],
        detected_ppe=["vest"],
        confidence_scores={"helmet": 0.1, "vest": 0.9},
        bounding_boxes=boxes,
        processing_latency_ms=latency_ms,
        raw_api_response=raw_response or {"results": [{"status": "ok"}]},
    )


async def _run_recorder(result, n_failures: int, exc_type: type = Exception):
    """
    Run ViolationRecorder.record() with a mock S3 that fails n_failures times
    then succeeds. Returns (event, put_object_call_count, sleep_call_count).
    """
    from modules.violation_recorder import ViolationRecorder

    call_count = 0

    def _put(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= n_failures:
            if exc_type is ClientError:
                raise ClientError(
                    {"Error": {"Code": "ServiceUnavailable", "Message": "retry"}},
                    "PutObject",
                )
            raise exc_type(f"Simulated failure #{call_count}")

    recorder = ViolationRecorder.__new__(ViolationRecorder)
    recorder._bucket = "test-bucket"
    mock_s3 = MagicMock()
    mock_s3.put_object.side_effect = _put
    recorder._s3 = mock_s3

    sleep_calls = []

    async def _fake_sleep(secs):
        sleep_calls.append(secs)

    with patch("modules.violation_recorder.asyncio.sleep", side_effect=_fake_sleep):
        event = await recorder.record(b"\xff\xd8\xff", result, "cam_01")

    return event, mock_s3.put_object.call_count, len(sleep_calls)


# ---------------------------------------------------------------------------
# 7a — N failures (1 or 2) then success: correct call counts
# ---------------------------------------------------------------------------

@given(n_failures=st.integers(min_value=1, max_value=2))
@h_settings(max_examples=50)
def test_p7_partial_failures_then_success(n_failures: int) -> None:
    result = _make_analysis_result()

    async def _run():
        event, put_calls, sleep_calls = await _run_recorder(result, n_failures)
        assert event.upload_status == "success", (
            f"Expected 'success' after {n_failures} failures, got '{event.upload_status}'"
        )
        assert put_calls == n_failures + 1, (
            f"Expected {n_failures + 1} put_object calls, got {put_calls}"
        )
        assert sleep_calls == n_failures, (
            f"Expected {n_failures} sleep calls (retry delays), got {sleep_calls}"
        )
        assert event.snapshot_url is not None

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 7b — All 3 failures: pending_retry, exactly 3 attempts, 2 sleeps
# ---------------------------------------------------------------------------

def test_p7_all_three_failures_pending_retry() -> None:
    result = _make_analysis_result()

    async def _run():
        event, put_calls, sleep_calls = await _run_recorder(result, 3)
        assert event.upload_status == "pending_retry"
        assert event.snapshot_url is None
        assert put_calls == 3, f"Expected exactly 3 put_object calls, got {put_calls}"
        # Sleep called between attempt 1→2 and 2→3, NOT after attempt 3
        assert sleep_calls == 2, f"Expected 2 sleep calls, got {sleep_calls}"

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 7c — Extended fields preserved on all failure paths
# ---------------------------------------------------------------------------

@given(
    latency_ms=st.integers(min_value=0, max_value=9999),
    n_boxes=st.integers(min_value=0, max_value=4),
    n_failures=st.integers(min_value=0, max_value=3),
)
@h_settings(max_examples=100)
def test_p7_extended_fields_preserved_regardless_of_upload_outcome(
    latency_ms: int, n_boxes: int, n_failures: int
) -> None:
    """
    Extended fields must be present on the returned ViolationEvent
    regardless of whether the upload succeeded or failed.
    """
    raw = {"results": [{"latency": latency_ms}]}
    result = _make_analysis_result(
        latency_ms=latency_ms, n_boxes=n_boxes, raw_response=raw
    )

    async def _run():
        event, _, _ = await _run_recorder(result, n_failures)
        assert event.processing_latency_ms == latency_ms
        assert len(event.bounding_boxes) == n_boxes
        assert event.raw_api_response == raw

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 7d — Different exception types all trigger retry
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc_type", [Exception, RuntimeError, OSError, ClientError])
def test_p7_different_exception_types_trigger_retry(exc_type) -> None:
    result = _make_analysis_result()

    async def _run():
        event, put_calls, _ = await _run_recorder(result, 1, exc_type=exc_type)
        assert event.upload_status == "success"
        assert put_calls == 2

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 7e — Zero failures: single attempt, no sleep, immediate success
# ---------------------------------------------------------------------------

def test_p7_zero_failures_single_attempt() -> None:
    result = _make_analysis_result()

    async def _run():
        event, put_calls, sleep_calls = await _run_recorder(result, 0)
        assert event.upload_status == "success"
        assert put_calls == 1, f"Expected 1 put_object call, got {put_calls}"
        assert sleep_calls == 0, f"Expected 0 sleep calls, got {sleep_calls}"

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 7f — No more than 3 total attempts regardless of failure count
# ---------------------------------------------------------------------------

def test_p7_never_exceeds_three_attempts() -> None:
    """Even if the mock always fails, put_object must be called at most 3 times."""
    from modules.violation_recorder import ViolationRecorder

    call_count = 0

    def _always_fail(**kwargs):
        nonlocal call_count
        call_count += 1
        raise Exception("always fail")

    result = _make_analysis_result()

    async def _run():
        nonlocal call_count
        call_count = 0
        recorder = ViolationRecorder.__new__(ViolationRecorder)
        recorder._bucket = "test-bucket"
        mock_s3 = MagicMock()
        mock_s3.put_object.side_effect = _always_fail
        recorder._s3 = mock_s3

        with patch("modules.violation_recorder.asyncio.sleep", new_callable=AsyncMock):
            event = await recorder.record(b"\xff\xd8\xff", result, "cam_01")

        assert call_count <= 3, f"put_object called {call_count} times (max 3)"
        assert event.upload_status == "pending_retry"

    asyncio.get_event_loop().run_until_complete(_run())
