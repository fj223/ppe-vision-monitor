"""
Property-based tests for Vision_Analyzer.

Property 1: Violation detection completeness
  For ANY detection result missing at least one required PPE category,
  _parse_response + the compliance logic must:
    - set is_violation = True
    - include EVERY missing category in violation_types
    - NOT include any present category in violation_types

  Edge cases covered:
    - Only helmet missing
    - Only vest missing
    - Both missing (all required PPE absent)
    - Extra non-PPE labels present (person, hardhat, etc.) — must not affect result
    - Detected objects with probability exactly at the 0.5 threshold boundary
    - Detected objects with probability 0.0 (must count as missing)
    - Duplicate labels in response (highest probability wins)
    - Empty objects list (all PPE missing)

Property 2: API failure produces no false positives
  For ANY error condition, analyze() must return None and never raise.

  Error conditions covered:
    - HTTP 4xx (400, 401, 403, 404, 422, 429)
    - HTTP 5xx (500, 502, 503, 504)
    - All codes in range 400–599 (hypothesis-generated)
    - Network-level RequestError (connection refused, DNS failure, etc.)
    - TimeoutException (connect timeout, read timeout, pool timeout)
    - Response body that is valid text but not JSON
    - Response body that is empty string
    - Response body that is partial/truncated JSON
    - Response body that is a JSON array instead of object
    - Response body that is a JSON number/boolean/null

(Design doc: Properties 1 & 2 | Requirements 2.4, 2.5, 2.6)
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from hypothesis import assume, given, settings as h_settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

REQUIRED_PPE = frozenset({"helmet", "vest"})
ALL_PPE = sorted(REQUIRED_PPE)


def _make_raw_response(
    detected: list[tuple[str, float]],   # [(label, probability), ...]
) -> dict:
    """
    Build a Yandex Vision batchAnalyze response from (label, probability) pairs.
    Each object gets a valid 4-vertex bounding box.
    """
    objects = [
        {
            "name": label,
            "probability": prob,
            "boundingBox": {
                "vertices": [
                    {"x": "10", "y": "20"},
                    {"x": "110", "y": "20"},
                    {"x": "110", "y": "120"},
                    {"x": "10", "y": "120"},
                ]
            },
        }
        for label, prob in detected
    ]
    return {
        "results": [
            {"results": [{"objectDetectionResult": {"objects": objects}}]}
        ]
    }


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _mock_http_client(response: MagicMock):
    """Context manager patch that makes httpx.AsyncClient return `response`."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=response)
    return patch("httpx.AsyncClient", return_value=mock_client)


def _mock_http_client_raising(exc):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=exc)
    return patch("httpx.AsyncClient", return_value=mock_client)


def _ok_response(raw: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = raw
    resp.text = json.dumps(raw)
    return resp


def _error_response(status_code: int) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = f"HTTP {status_code} error"
    return resp


# ===========================================================================
# PROPERTY 1: Violation detection completeness
# Feature: ppe-compliance-monitoring, Property 1: 违规判断的完备性
# ===========================================================================

# ---------------------------------------------------------------------------
# 1a — Core: any non-empty subset of required PPE missing → violation
# ---------------------------------------------------------------------------

@given(
    missing=st.lists(
        st.sampled_from(ALL_PPE),
        min_size=1,
        max_size=len(ALL_PPE),
        unique=True,
    )
)
@h_settings(max_examples=100)
def test_p1_missing_ppe_is_violation(missing: list[str]) -> None:
    """
    Property 1 core: any missing required PPE → is_violation=True,
    violation_types contains exactly the missing categories.
    """
    from modules.vision_analyzer import _parse_response, REQUIRED_PPE as REQ

    present = sorted(REQUIRED_PPE - set(missing))
    detected = [(label, 0.95) for label in present]
    raw = _make_raw_response(detected)

    _, scores = _parse_response(raw)
    detected_ppe = [l for l, p in scores.items() if l in REQ and p >= 0.5]
    missing_ppe = sorted(REQ - set(detected_ppe))
    is_violation = len(missing_ppe) > 0

    assert is_violation is True
    for m in missing:
        assert m in missing_ppe, f"'{m}' not in violation_types={missing_ppe}"
    for p in present:
        assert p not in missing_ppe, f"present PPE '{p}' wrongly in violation_types"


# ---------------------------------------------------------------------------
# 1b — All PPE present → no violation
# ---------------------------------------------------------------------------

def test_p1_all_ppe_present_no_violation() -> None:
    from modules.vision_analyzer import _parse_response, REQUIRED_PPE as REQ

    detected = [(label, 0.95) for label in REQUIRED_PPE]
    raw = _make_raw_response(detected)
    _, scores = _parse_response(raw)
    detected_ppe = [l for l, p in scores.items() if l in REQ and p >= 0.5]
    missing_ppe = sorted(REQ - set(detected_ppe))

    assert missing_ppe == [], f"Expected no violations, got {missing_ppe}"


# ---------------------------------------------------------------------------
# 1c — Probability exactly at threshold boundary (0.5)
# ---------------------------------------------------------------------------

@given(
    label=st.sampled_from(ALL_PPE),
    prob=st.floats(min_value=0.5, max_value=1.0, allow_nan=False),
)
@h_settings(max_examples=100)
def test_p1_probability_at_or_above_threshold_counts_as_detected(
    label: str, prob: float
) -> None:
    """prob >= 0.5 must count as detected (not missing)."""
    from modules.vision_analyzer import _parse_response, REQUIRED_PPE as REQ

    other = sorted(REQUIRED_PPE - {label})
    detected = [(label, prob)] + [(l, 0.95) for l in other]
    raw = _make_raw_response(detected)
    _, scores = _parse_response(raw)
    detected_ppe = [l for l, p in scores.items() if l in REQ and p >= 0.5]
    missing_ppe = sorted(REQ - set(detected_ppe))

    assert label not in missing_ppe, (
        f"label='{label}' with prob={prob} should be detected, not missing"
    )


@given(
    label=st.sampled_from(ALL_PPE),
    prob=st.floats(min_value=0.0, max_value=0.4999, allow_nan=False),
)
@h_settings(max_examples=100)
def test_p1_probability_below_threshold_counts_as_missing(
    label: str, prob: float
) -> None:
    """prob < 0.5 must count as missing."""
    from modules.vision_analyzer import _parse_response, REQUIRED_PPE as REQ

    other = sorted(REQUIRED_PPE - {label})
    detected = [(label, prob)] + [(l, 0.95) for l in other]
    raw = _make_raw_response(detected)
    _, scores = _parse_response(raw)
    detected_ppe = [l for l, p in scores.items() if l in REQ and p >= 0.5]
    missing_ppe = sorted(REQ - set(detected_ppe))

    assert label in missing_ppe, (
        f"label='{label}' with prob={prob} should be missing"
    )


# ---------------------------------------------------------------------------
# 1d — Extra non-PPE labels must not affect compliance result
# ---------------------------------------------------------------------------

@given(
    extra_labels=st.lists(
        st.text(min_size=1, max_size=15).filter(
            lambda s: s not in REQUIRED_PPE
        ),
        min_size=1,
        max_size=5,
        unique=True,
    ),
    missing=st.lists(
        st.sampled_from(ALL_PPE), min_size=1, max_size=2, unique=True
    ),
)
@h_settings(max_examples=100)
def test_p1_extra_labels_do_not_affect_violation_result(
    extra_labels: list[str], missing: list[str]
) -> None:
    """Non-PPE labels (person, hardhat, etc.) must not change is_violation."""
    from modules.vision_analyzer import _parse_response, REQUIRED_PPE as REQ

    present = sorted(REQUIRED_PPE - set(missing))
    detected = (
        [(l, 0.95) for l in present]
        + [(l, 0.95) for l in extra_labels]
    )
    raw = _make_raw_response(detected)
    _, scores = _parse_response(raw)
    detected_ppe = [l for l, p in scores.items() if l in REQ and p >= 0.5]
    missing_ppe = sorted(REQ - set(detected_ppe))

    assert set(missing_ppe) == set(missing), (
        f"Extra labels changed violation result: expected {sorted(missing)}, "
        f"got {missing_ppe}"
    )


# ---------------------------------------------------------------------------
# 1e — Duplicate labels: highest probability wins
# ---------------------------------------------------------------------------

@given(
    label=st.sampled_from(ALL_PPE),
    low_prob=st.floats(min_value=0.0, max_value=0.49, allow_nan=False),
    high_prob=st.floats(min_value=0.5, max_value=1.0, allow_nan=False),
)
@h_settings(max_examples=100)
def test_p1_duplicate_label_highest_prob_wins(
    label: str, low_prob: float, high_prob: float
) -> None:
    """When a label appears twice, the higher probability must be used."""
    from modules.vision_analyzer import _parse_response, REQUIRED_PPE as REQ

    other = sorted(REQUIRED_PPE - {label})
    # First occurrence: low prob (would be missing), second: high prob (detected)
    detected = [(label, low_prob), (label, high_prob)] + [(l, 0.95) for l in other]
    raw = _make_raw_response(detected)
    _, scores = _parse_response(raw)
    detected_ppe = [l for l, p in scores.items() if l in REQ and p >= 0.5]
    missing_ppe = sorted(REQ - set(detected_ppe))

    assert label not in missing_ppe, (
        f"Duplicate label '{label}': high_prob={high_prob} should win over "
        f"low_prob={low_prob}, but label is in missing_ppe={missing_ppe}"
    )


# ---------------------------------------------------------------------------
# 1f — Empty objects list → all PPE missing
# ---------------------------------------------------------------------------

def test_p1_empty_objects_all_ppe_missing() -> None:
    from modules.vision_analyzer import _parse_response, REQUIRED_PPE as REQ

    raw = _make_raw_response([])
    _, scores = _parse_response(raw)
    detected_ppe = [l for l, p in scores.items() if l in REQ and p >= 0.5]
    missing_ppe = sorted(REQ - set(detected_ppe))

    assert set(missing_ppe) == REQUIRED_PPE, (
        f"Empty detection should mark all PPE missing, got {missing_ppe}"
    )


# ---------------------------------------------------------------------------
# 1g — Malformed bounding box vertices must not crash _parse_response
# ---------------------------------------------------------------------------

@given(
    vertex_count=st.integers(min_value=0, max_value=3),  # < 4 → no box extracted
)
@h_settings(max_examples=50)
def test_p1_malformed_vertices_do_not_crash(vertex_count: int) -> None:
    from modules.vision_analyzer import _parse_response

    vertices = [{"x": "10", "y": "10"}] * vertex_count
    raw = {
        "results": [{"results": [{"objectDetectionResult": {"objects": [
            {"name": "helmet", "probability": 0.9, "boundingBox": {"vertices": vertices}}
        ]}}]}]
    }
    # Must not raise
    boxes, scores = _parse_response(raw)
    assert isinstance(boxes, list)
    assert isinstance(scores, dict)


# ===========================================================================
# PROPERTY 2: API failure produces no false positives
# Feature: ppe-compliance-monitoring, Property 2: API 失败不产生误报
# ===========================================================================

# ---------------------------------------------------------------------------
# 2a — Any HTTP 4xx/5xx → None, no raise
# ---------------------------------------------------------------------------

@given(status_code=st.integers(min_value=400, max_value=599))
@h_settings(max_examples=100)
def test_p2_any_http_error_returns_none(status_code: int) -> None:
    from modules.vision_analyzer import VisionAnalyzer

    async def _run():
        analyzer = VisionAnalyzer()
        with _mock_http_client(_error_response(status_code)):
            result = await analyzer.analyze(b"\xff\xd8\xff", "cam_test")
        assert result is None, f"Expected None for HTTP {status_code}, got {result}"

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 2b — Specific important HTTP error codes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422, 429, 500, 502, 503, 504])
def test_p2_specific_http_errors_return_none(status_code: int) -> None:
    from modules.vision_analyzer import VisionAnalyzer

    async def _run():
        analyzer = VisionAnalyzer()
        with _mock_http_client(_error_response(status_code)):
            result = await analyzer.analyze(b"\xff\xd8\xff", "cam_test")
        assert result is None

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 2c — Malformed JSON body (any text that is not valid JSON)
# ---------------------------------------------------------------------------

@given(body=st.one_of(
    st.text(min_size=0, max_size=200),                    # arbitrary text
    st.just(""),                                           # empty string
    st.just("{incomplete"),                                # truncated JSON
    st.just("[1, 2, 3]"),                                  # JSON array not object
    st.just("null"),                                       # JSON null
    st.just("true"),                                       # JSON boolean
    st.just("42"),                                         # JSON number
))
@h_settings(max_examples=100)
def test_p2_malformed_or_unexpected_json_returns_none(body: str) -> None:
    from modules.vision_analyzer import VisionAnalyzer

    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.text = body
    # Make .json() raise for anything that isn't a valid dict
    try:
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            resp.json.side_effect = ValueError("not a dict")
        else:
            resp.json.return_value = parsed
    except (json.JSONDecodeError, ValueError):
        resp.json.side_effect = json.JSONDecodeError("bad json", body, 0)

    async def _run():
        analyzer = VisionAnalyzer()
        with _mock_http_client(resp):
            result = await analyzer.analyze(b"\xff\xd8\xff", "cam_test")
        # If parsed is a valid dict, result may be a valid AnalysisResult — that's OK.
        # If not a dict, result must be None.
        try:
            parsed_val = json.loads(body)
            if not isinstance(parsed_val, dict):
                assert result is None, f"Expected None for non-dict JSON body, got {result}"
        except (json.JSONDecodeError, ValueError):
            assert result is None, f"Expected None for invalid JSON body, got {result}"

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 2d — Network-level exceptions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [
    httpx.RequestError("connection refused"),
    httpx.ConnectError("DNS resolution failed"),
    httpx.RemoteProtocolError("server disconnected"),
    httpx.ReadError("connection reset by peer"),
])
def test_p2_network_exceptions_return_none(exc) -> None:
    from modules.vision_analyzer import VisionAnalyzer

    async def _run():
        analyzer = VisionAnalyzer()
        with _mock_http_client_raising(exc):
            result = await analyzer.analyze(b"\xff\xd8\xff", "cam_test")
        assert result is None, f"Expected None for {type(exc).__name__}, got {result}"

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 2e — Timeout exceptions (all httpx timeout subtypes)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [
    httpx.TimeoutException("generic timeout"),
    httpx.ConnectTimeout("connect timeout"),
    httpx.ReadTimeout("read timeout"),
    httpx.WriteTimeout("write timeout"),
    httpx.PoolTimeout("pool timeout"),
])
def test_p2_timeout_exceptions_return_none(exc) -> None:
    from modules.vision_analyzer import VisionAnalyzer

    async def _run():
        analyzer = VisionAnalyzer()
        with _mock_http_client_raising(exc):
            result = await analyzer.analyze(b"\xff\xd8\xff", "cam_test")
        assert result is None, f"Expected None for {type(exc).__name__}, got {result}"

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 2f — analyze() never raises regardless of error type
# ---------------------------------------------------------------------------

@given(
    status_code=st.integers(min_value=400, max_value=599),
)
@h_settings(max_examples=50)
def test_p2_analyze_never_raises(status_code: int) -> None:
    from modules.vision_analyzer import VisionAnalyzer

    async def _run():
        analyzer = VisionAnalyzer()
        with _mock_http_client(_error_response(status_code)):
            try:
                result = await analyzer.analyze(b"\xff\xd8\xff", "cam_test")
            except Exception as exc:
                pytest.fail(
                    f"analyze() raised {type(exc).__name__} for HTTP {status_code}: {exc}"
                )

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 2g — Frame bytes edge cases: empty bytes, single byte, large frame
# ---------------------------------------------------------------------------

@given(frame=st.one_of(
    st.just(b""),
    st.just(b"\x00"),
    st.binary(min_size=1, max_size=100),
))
@h_settings(max_examples=50)
def test_p2_any_frame_bytes_with_api_error_returns_none(frame: bytes) -> None:
    """analyze() must return None for any frame bytes when the API errors."""
    from modules.vision_analyzer import VisionAnalyzer

    async def _run():
        analyzer = VisionAnalyzer()
        with _mock_http_client(_error_response(500)):
            result = await analyzer.analyze(frame, "cam_test")
        assert result is None

    asyncio.get_event_loop().run_until_complete(_run())
