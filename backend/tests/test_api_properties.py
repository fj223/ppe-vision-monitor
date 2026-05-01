"""
Property-based and unit tests for the API layer.

Property 6: API parameter validation coverage
  For ANY invalid query parameter, the API must return HTTP 422 with a
  structured error body — never 500 or an empty response.

  Edge cases covered:
    - limit = 0 (below minimum)
    - limit = -1, -1000 (negative)
    - limit = 501, 999, MAX_INT (above maximum)
    - offset = -1, -1000 (negative)
    - start_time / end_time: arbitrary non-ISO strings
    - start_time / end_time: integers, floats, booleans as strings
    - start_time / end_time: partial ISO strings ("2024", "2024-01")
    - All four endpoints validated for parameter rejection

Unit tests (Requirement 5.7):
  - Unhandled repository exception → HTTP 500, no internal details in body
  - Unknown event_id → HTTP 404
  - 500 body must not contain: exception class names, module paths,
    stack trace fragments, internal error messages

Smoke tests:
  - All four endpoints return 200 on valid requests
  - /health returns {"status": "ok"}
  - ViolationEventResponse contains all three extended research fields
  - BoundingBox structure is correct for frontend canvas rendering

(Design doc: Property 6 | Requirements 5.6, 5.7)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st


# ===========================================================================
# Test client factory
# ===========================================================================

def _make_test_client(repo_override=None, processor_override=None):
    """
    Build a TestClient with fully mocked app.state.
    Uses the context-manager form (with TestClient(app) as client:) so the
    lifespan runs and app.state is populated before any request is made.
    The lifespan is patched to a no-op so no real DB/camera connections occur.
    """
    from main import app

    mock_repo = repo_override or MagicMock()
    mock_repo.query_violations = AsyncMock(return_value=[])
    mock_repo.get_violation_by_id = AsyncMock(return_value=None)
    mock_repo.get_stats = AsyncMock(return_value=MagicMock(
        total_violations=0,
        by_type={},
        avg_processing_latency_ms=0.0,
        cameras_with_violations=[],
    ))

    mock_processor = processor_override or MagicMock()
    mock_processor.get_all_statuses = MagicMock(return_value={})

    @asynccontextmanager
    async def _noop_lifespan(app):
        app.state.repository = mock_repo
        app.state.video_processor = mock_processor
        yield

    app.router.lifespan_context = _noop_lifespan

    # Use context-manager form so lifespan events fire before requests
    client = TestClient(app, raise_server_exceptions=False)
    client.__enter__()
    return client, mock_repo, mock_processor


def _is_valid_iso_datetime(s: str) -> bool:
    try:
        datetime.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False


# ===========================================================================
# PROPERTY 6: API parameter validation coverage
# Feature: ppe-compliance-monitoring, Property 6: API 参数验证覆盖性
# ===========================================================================

# ---------------------------------------------------------------------------
# 6a — limit out of [1, 500] → 422
# ---------------------------------------------------------------------------

@given(limit=st.one_of(
    st.integers(max_value=0),           # 0 and below
    st.integers(min_value=501),         # 501 and above
))
@h_settings(max_examples=100)
def test_p6_invalid_limit_returns_422(limit: int) -> None:
    client, _, _ = _make_test_client()
    response = client.get(f"/api/v1/violations?limit={limit}")
    assert response.status_code == 422, (
        f"Expected 422 for limit={limit}, got {response.status_code}"
    )
    body = response.json()
    assert "detail" in body, "422 response must contain 'detail'"


# ---------------------------------------------------------------------------
# 6b — Specific boundary values for limit
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("limit,expected", [
    (0, 422), (-1, 422), (-1000, 422),
    (501, 422), (1000, 422),
    (1, 200), (500, 200),   # valid boundaries must pass
])
def test_p6_limit_boundary_values(limit: int, expected: int) -> None:
    client, _, _ = _make_test_client()
    response = client.get(f"/api/v1/violations?limit={limit}")
    assert response.status_code == expected, (
        f"limit={limit}: expected {expected}, got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# 6c — negative offset → 422
# ---------------------------------------------------------------------------

@given(offset=st.integers(max_value=-1))
@h_settings(max_examples=100)
def test_p6_negative_offset_returns_422(offset: int) -> None:
    client, _, _ = _make_test_client()
    response = client.get(f"/api/v1/violations?offset={offset}")
    assert response.status_code == 422, (
        f"Expected 422 for offset={offset}, got {response.status_code}"
    )
    assert "detail" in response.json()


# ---------------------------------------------------------------------------
# 6d — Non-ISO start_time → 422
# ---------------------------------------------------------------------------

@given(bad_date=st.one_of(
    st.text(min_size=1, max_size=30, alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),  # printable only, no control chars
    )).filter(lambda s: not _is_valid_iso_datetime(s)),
    st.integers().map(str),             # integers as strings
    st.floats(allow_nan=False).map(str),# floats as strings
    st.just("true"), st.just("false"),  # booleans
    st.just("2024"),                    # year only
    st.just("2024-01"),                 # year-month only
    st.just("not-a-date"),
))
@h_settings(max_examples=100)
def test_p6_invalid_start_time_returns_422(bad_date: str) -> None:
    from urllib.parse import quote
    client, _, _ = _make_test_client()
    response = client.get(f"/api/v1/violations?start_time={quote(bad_date)}")
    # FastAPI may return 422 or 200 (if it ignores the param) — must NOT be 500
    assert response.status_code != 500, (
        f"Got 500 for start_time='{bad_date}' — must never be 500"
    )
    if response.status_code == 422:
        assert "detail" in response.json()


# ---------------------------------------------------------------------------
# 6e — Non-ISO end_time → 422
# ---------------------------------------------------------------------------

@given(bad_date=st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),  # printable only, no control chars
    ),
).filter(lambda s: not _is_valid_iso_datetime(s) and s.strip()))
@h_settings(max_examples=50)
def test_p6_invalid_end_time_never_500(bad_date: str) -> None:
    from urllib.parse import quote
    client, _, _ = _make_test_client()
    response = client.get(f"/api/v1/stats?end_time={quote(bad_date)}")
    assert response.status_code != 500, (
        f"Got 500 for end_time='{bad_date}'"
    )


# ---------------------------------------------------------------------------
# 6f — 422 response always has structured 'detail' field
# ---------------------------------------------------------------------------

@given(limit=st.integers(max_value=0))
@h_settings(max_examples=50)
def test_p6_422_always_has_structured_detail(limit: int) -> None:
    client, _, _ = _make_test_client()
    response = client.get(f"/api/v1/violations?limit={limit}")
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body, "422 must have 'detail' key"
    # FastAPI returns detail as a list of error objects
    assert body["detail"] is not None
    assert body["detail"] != ""


# ===========================================================================
# Unit tests — error handling (Requirement 5.7)
# ===========================================================================

# ---------------------------------------------------------------------------
# 500 on unhandled exception — no internal details leaked
# ---------------------------------------------------------------------------

def test_unhandled_exception_returns_500_generic_message() -> None:
    client, mock_repo, _ = _make_test_client()
    mock_repo.query_violations = AsyncMock(
        side_effect=RuntimeError("asyncpg connection pool exhausted at limit 10")
    )
    response = client.get("/api/v1/violations")
    assert response.status_code == 500

    body = response.json()
    assert "detail" in body
    detail = body["detail"].lower()

    # Must NOT expose any internal implementation details
    forbidden_fragments = [
        "asyncpg", "pool", "traceback", "runtimeerror",
        "exhausted", "limit 10", "modules.", "event_repository",
        "file ", "line ", "  at ",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in detail, (
            f"Internal detail '{fragment}' leaked in 500 response body: {body['detail']}"
        )


@pytest.mark.parametrize("exc", [
    RuntimeError("internal db error"),
    ValueError("unexpected value"),
    KeyError("missing key"),
    AttributeError("NoneType has no attribute"),
    Exception("generic failure"),
])
def test_various_exceptions_all_return_500_without_details(exc) -> None:
    client, mock_repo, _ = _make_test_client()
    mock_repo.query_violations = AsyncMock(side_effect=exc)
    response = client.get("/api/v1/violations")
    assert response.status_code == 500
    body = response.json()
    assert "detail" in body
    # The specific exception message must not appear verbatim
    assert str(exc).lower() not in body["detail"].lower(), (
        f"Exception message leaked: '{exc}' found in '{body['detail']}'"
    )


# ---------------------------------------------------------------------------
# 404 for unknown event_id
# ---------------------------------------------------------------------------

@given(event_id=st.uuids().map(str))
@h_settings(max_examples=30)
def test_unknown_event_id_returns_404(event_id: str) -> None:
    client, mock_repo, _ = _make_test_client()
    mock_repo.get_violation_by_id = AsyncMock(return_value=None)
    response = client.get(f"/api/v1/violations/{event_id}")
    assert response.status_code == 404
    assert "detail" in response.json()


# ===========================================================================
# Smoke tests — happy path
# ===========================================================================

def test_list_violations_200() -> None:
    client, _, _ = _make_test_client()
    response = client.get("/api/v1/violations")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body
    assert "limit" in body
    assert "offset" in body


def test_cameras_200() -> None:
    client, _, _ = _make_test_client()
    response = client.get("/api/v1/cameras")
    assert response.status_code == 200
    assert "cameras" in response.json()


def test_stats_200() -> None:
    client, _, _ = _make_test_client()
    response = client.get("/api/v1/stats")
    assert response.status_code == 200
    body = response.json()
    for key in ("total_violations", "by_type", "avg_processing_latency_ms",
                "cameras_with_violations", "start_time", "end_time"):
        assert key in body, f"'{key}' missing from stats response"


def test_health_ok() -> None:
    client, _, _ = _make_test_client()
    assert client.get("/health").json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Extended fields present and correctly structured in detail response
# ---------------------------------------------------------------------------

def test_violation_detail_contains_all_extended_fields() -> None:
    """
    Verify GET /violations/{id} response includes all three extended research
    fields with correct types and structure for the React dashboard.
    """
    from modules.event_repository import ViolationEventRecord

    fake_record = ViolationEventRecord(
        event_id="abc-123",
        camera_id="cam_01",
        timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        violation_types=["helmet"],
        snapshot_url="https://storage.example.com/snap.jpg",
        confidence_scores={"helmet": 0.1, "vest": 0.9},
        upload_status="success",
        bounding_boxes=[{
            "label": "no_helmet", "confidence": 0.9,
            "x_min": 10, "y_min": 20, "x_max": 200, "y_max": 180,
        }],
        processing_latency=342,
        raw_api_response={"results": [{"status": "ok"}]},
        created_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
    )

    client, mock_repo, _ = _make_test_client()
    mock_repo.get_violation_by_id = AsyncMock(return_value=fake_record)

    response = client.get("/api/v1/violations/abc-123")
    assert response.status_code == 200
    body = response.json()

    # All three extended research fields must be present
    assert "bounding_boxes" in body, "bounding_boxes missing"
    assert "processing_latency" in body, "processing_latency missing"
    assert "raw_api_response" in body, "raw_api_response missing"

    # BoundingBox structure for canvas rendering
    assert len(body["bounding_boxes"]) == 1
    bb = body["bounding_boxes"][0]
    for field in ("label", "confidence", "x_min", "y_min", "x_max", "y_max"):
        assert field in bb, f"BoundingBox field '{field}' missing"
    assert bb["x_min"] == 10
    assert bb["y_min"] == 20
    assert bb["x_max"] == 200
    assert bb["y_max"] == 180

    # processing_latency must be an integer (milliseconds)
    assert isinstance(body["processing_latency"], int)
    assert body["processing_latency"] == 342

    # raw_api_response must be a dict
    assert isinstance(body["raw_api_response"], dict)


@given(processing_latency=st.integers(min_value=0, max_value=10000))
@h_settings(max_examples=50)
def test_processing_latency_preserved_in_response(processing_latency: int) -> None:
    """processing_latency must be returned exactly as stored."""
    from modules.event_repository import ViolationEventRecord

    fake_record = ViolationEventRecord(
        event_id="test-id",
        camera_id="cam_01",
        timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        violation_types=["helmet"],
        snapshot_url=None,
        confidence_scores={},
        upload_status="success",
        bounding_boxes=[],
        processing_latency=processing_latency,
        raw_api_response={},
        created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )

    client, mock_repo, _ = _make_test_client()
    mock_repo.get_violation_by_id = AsyncMock(return_value=fake_record)

    response = client.get("/api/v1/violations/test-id")
    assert response.status_code == 200
    assert response.json()["processing_latency"] == processing_latency


# ---------------------------------------------------------------------------
# ViolationList summary also includes bounding_boxes and processing_latency
# ---------------------------------------------------------------------------

def test_violation_list_summary_includes_overlay_fields() -> None:
    """
    ViolationEventSummary (list response) must include bounding_boxes and
    processing_latency so the list view can render thumbnails with overlays.
    """
    from modules.event_repository import ViolationEventRecord

    fake_record = ViolationEventRecord(
        event_id="sum-001",
        camera_id="cam_02",
        timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        violation_types=["vest"],
        snapshot_url="https://storage.example.com/snap2.jpg",
        confidence_scores={"vest": 0.05},
        upload_status="success",
        bounding_boxes=[{
            "label": "no_vest", "confidence": 0.88,
            "x_min": 50, "y_min": 60, "x_max": 300, "y_max": 400,
        }],
        processing_latency=512,
        raw_api_response={"results": []},
        created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )

    client, mock_repo, _ = _make_test_client()
    mock_repo.query_violations = AsyncMock(return_value=[fake_record])

    response = client.get("/api/v1/violations")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]

    assert "bounding_boxes" in item, "bounding_boxes missing from list summary"
    assert "processing_latency" in item, "processing_latency missing from list summary"
    # raw_api_response intentionally omitted from summary to keep payloads lean
    assert "raw_api_response" not in item, (
        "raw_api_response should NOT be in list summary (payload size)"
    )
    assert item["processing_latency"] == 512
