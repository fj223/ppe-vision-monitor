# Implementation Plan: PPE Compliance Monitoring System

## Overview

Incremental implementation of the PPE compliance monitoring system across five phases:
environment setup → core backend modules → API layer → React dashboard → property-based tests.
Each task builds on the previous, ending with full integration. All code is Python (backend) + TypeScript/React (frontend).

## Tasks

- [x] 1. Environment & Database Setup
  - [x] 1.1 Create PostgreSQL migration script with extended fields
    - Create `backend/db/migrations/001_initial_schema.sql`
    - Define `violation_events` table with all core fields: `event_id UUID PRIMARY KEY`, `camera_id`, `timestamp`, `violation_types TEXT[]`, `snapshot_url`, `confidence_scores JSONB`, `upload_status`
    - Add three extended fields: `bounding_boxes JSONB NOT NULL DEFAULT '[]'`, `processing_latency INTEGER NOT NULL`, `raw_api_response JSONB NOT NULL DEFAULT '{}'`
    - Add indexes: `idx_violations_camera_id`, `idx_violations_timestamp DESC`, `idx_violations_types` (GIN on `violation_types`)
    - Enable `pgcrypto` extension for `gen_random_uuid()`
    - _Requirements: 4.1, 4.2, 4.3, 4.7_

  - [x] 1.2 Create pydantic-settings configuration module
    - Create `backend/config.py` using `pydantic-settings` `BaseSettings`
    - Define all required fields: `DATABASE_URL`, `YOS_ENDPOINT_URL`, `YOS_ACCESS_KEY_ID`, `YOS_SECRET_ACCESS_KEY`, `YOS_BUCKET_NAME`, `YANDEX_VISION_API_KEY`, `YANDEX_VISION_FOLDER_ID`, `RTSP_STREAMS`, `FRAME_INTERVAL_SECONDS`, `VISION_API_TIMEOUT_SECONDS`, `MAX_RETRY_ATTEMPTS`, `LOG_LEVEL`, `CORS_ORIGINS`
    - All fields must be required (no defaults for secrets); app must raise `ValidationError` with field names on missing vars
    - Load from `.env` file via `model_config = SettingsConfigDict(env_file=".env")`
    - _Requirements: 7.1, 7.3_

  - [x] 1.3 Create Dockerfile and docker-compose.yml
    - Create `backend/Dockerfile` with Python 3.11-slim base, install dependencies from `requirements.txt`, expose port 8000
    - Create `docker-compose.yml` at project root with `backend` service (port 8000, `env_file: .env`, depends on postgres with healthcheck) and `postgres:16-alpine` service with volume mount for migrations at `/docker-entrypoint-initdb.d`
    - Add named volume `pgdata` for PostgreSQL data persistence
    - _Requirements: 7.5_

  - [x] 1.4 Create backend project skeleton and requirements.txt
    - Create `backend/requirements.txt` with: `fastapi`, `uvicorn[standard]`, `asyncpg`, `pydantic-settings`, `boto3`, `opencv-python-headless`, `httpx`, `structlog`, `hypothesis`, `pytest`, `pytest-asyncio`
    - Create empty `backend/main.py`, `backend/modules/__init__.py`, `backend/api/__init__.py`, `backend/api/routes/__init__.py`
    - _Requirements: 7.2_

- [x] 2. Core Backend Modules
  - [x] 2.1 Implement Vision_Analyzer module
    - Create `backend/modules/vision_analyzer.py`
    - Define `BoundingBox` dataclass and `AnalysisResult` dataclass with all fields: `is_violation`, `violation_types`, `detected_ppe`, `confidence_scores`, `bounding_boxes: list[BoundingBox]`, `processing_latency_ms: int`, `raw_api_response: dict`
    - Implement `VisionAnalyzer.analyze(frame: bytes, camera_id: str) -> AnalysisResult | None`
    - Measure `processing_latency_ms` using `time.monotonic()` before and after the API POST call
    - Store complete untruncated API response in `raw_api_response`
    - Extract `bounding_boxes` from `raw_api_response`
    - Mark `is_violation=True` when any required PPE category (helmet, vest) is missing
    - Return `None` on any API error (network, 4xx/5xx, malformed JSON) — log error, do not raise
    - Enforce 5-second timeout; log and skip frame on timeout
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x]* 2.2 Write property test for Vision_Analyzer — Property 1: violation detection completeness
    - Create `backend/tests/test_vision_analyzer_properties.py`
    - **Property 1: 违规判断的完备性**
    - Use `@given(st.lists(st.sampled_from(["helmet", "vest"]), min_size=1))` to generate missing PPE combinations
    - Assert `is_violation=True` and `violation_types` contains all missing categories
    - `@settings(max_examples=100)`
    - **Validates: Requirements 2.4**

  - [x]* 2.3 Write property test for Vision_Analyzer — Property 2: API failure produces no false positives
    - Add to `backend/tests/test_vision_analyzer_properties.py`
    - **Property 2: API 失败不产生误报**
    - Use `@given(st.one_of(st.integers(400, 599), st.text()))` to generate error HTTP codes and malformed bodies
    - Mock `httpx.AsyncClient.post` to raise or return error; assert `analyze()` returns `None` and no exception propagates
    - `@settings(max_examples=100)`
    - **Validates: Requirements 2.5**

  - [x] 2.4 Implement Violation_Recorder module
    - Create `backend/modules/violation_recorder.py`
    - Define `ViolationEvent` dataclass with all fields including `bounding_boxes`, `processing_latency_ms`, `raw_api_response`, `snapshot_url: str | None`
    - Implement `ViolationRecorder.record(frame: bytes, result: AnalysisResult, camera_id: str) -> ViolationEvent`
    - Use `boto3` with `endpoint_url=YOS_ENDPOINT_URL` (S3-compatible)
    - Storage key format: `violations/{camera_id}/{YYYY-MM-DD}/{timestamp}.jpg` using UTC timestamp
    - Implement retry loop: max 3 attempts, 2-second sleep between retries using `asyncio.sleep`
    - On all 3 failures: set `upload_status="pending_retry"`, log error, return event without `snapshot_url` (do not discard)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x]* 2.5 Write property test for Violation_Recorder — Property 3: storage path format correctness
    - Create `backend/tests/test_violation_recorder_properties.py`
    - **Property 3: 存储路径格式正确性**
    - Use `@given(st.from_regex(r'[a-zA-Z0-9_]+', fullmatch=True), st.datetimes(timezones=st.just(timezone.utc)))` to generate camera_ids and timestamps
    - Assert generated key matches regex `^violations/[a-zA-Z0-9_]+/\d{4}-\d{2}-\d{2}/\d+\.jpg$`
    - `@settings(max_examples=100)`
    - **Validates: Requirements 3.3, 3.4**

  - [x]* 2.6 Write property test for Violation_Recorder — Property 7: upload retry count upper bound
    - Add to `backend/tests/test_violation_recorder_properties.py`
    - **Property 7: 上传重试次数上限**
    - Use `@given(st.integers(min_value=1, max_value=3))` to generate failure counts
    - Mock `boto3` client to fail N times then succeed; assert retry count equals N and total attempts ≤ 3
    - For N=3 failures: assert `upload_status="pending_retry"` and event is returned (not discarded)
    - `@settings(max_examples=100)`
    - **Validates: Requirements 3.5, 3.6**

  - [x] 2.7 Implement Event_Repository module
    - Create `backend/modules/event_repository.py`
    - Implement `EventRepository` with `asyncpg` connection pool
    - Implement `insert_violation(event: ViolationEvent) -> str`: parameterized INSERT with all fields including `bounding_boxes` (JSON-serialized), `processing_latency`, `raw_api_response` (JSON-serialized); return generated `event_id`
    - Implement `query_violations(camera_id, start_time, end_time, violation_type, limit, offset) -> list[ViolationEventRecord]` with dynamic WHERE clause
    - Implement `get_violation_by_id(event_id) -> ViolationEventRecord | None` returning all fields including extended fields
    - Implement `get_stats(start_time, end_time) -> ViolationStats`
    - All queries must use `$1, $2, ...` parameterized placeholders (no string interpolation)
    - On DB write failure: log error, raise exception (do not silently discard)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.8_

  - [x]* 2.8 Write property test for Event_Repository — Property 4: violation event record completeness (round-trip)
    - Create `backend/tests/test_event_repository_properties.py`
    - **Property 4: 违规事件记录完整性**
    - Use `@given(st.builds(ViolationEvent, ...))` with hypothesis strategies to generate random `ViolationEvent` objects with arbitrary `bounding_boxes`, `processing_latency_ms`, `raw_api_response`
    - Mock `asyncpg` pool; assert that values passed to INSERT match values returned by `get_violation_by_id` (round-trip equality)
    - `@settings(max_examples=100)`
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.8**

  - [x]* 2.9 Write property test for Event_Repository — Property 5: query filter result consistency
    - Add to `backend/tests/test_event_repository_properties.py`
    - **Property 5: 查询过滤结果一致性**
    - Use `@given(st.lists(st.builds(ViolationEvent, ...)), st.one_of(st.none(), st.text()), ...)` to generate event sets and filter combinations
    - Assert every returned record satisfies all specified filter conditions; no out-of-filter records returned
    - `@settings(max_examples=100)`
    - **Validates: Requirements 4.6, 5.2**

  - [x] 2.10 Implement Video_Processor module
    - Create `backend/modules/video_processor.py`
    - Implement `VideoProcessor` managing a dict of `camera_id -> asyncio.Task`
    - Implement `start(camera_id, rtsp_url)`: create asyncio Task running frame extraction loop
    - Frame loop: `cv2.VideoCapture(rtsp_url)`, read frame every `FRAME_INTERVAL_SECONDS` (2s), pass bytes to `VisionAnalyzer.analyze()`
    - On connection failure: log error, `await asyncio.sleep(10)`, retry; after 5 consecutive failures log critical alert and stop task
    - Implement `stop(camera_id)`: cancel and await the task
    - Implement `get_camera_status(camera_id) -> CameraStatus` returning `online | offline | retrying`
    - Wire: if `AnalysisResult.is_violation`, call `ViolationRecorder.record()` then `EventRepository.insert_violation()`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [ ] 3. Checkpoint — Core modules complete
  - Ensure all non-optional tests pass. Verify `Vision_Analyzer`, `Violation_Recorder`, `Event_Repository`, and `Video_Processor` are importable and unit-testable in isolation. Ask the user if questions arise.

- [x] 4. API Layer
  - [x] 4.1 Create Pydantic request/response schemas
    - Create `backend/api/schemas.py`
    - Define `BoundingBox(BaseModel)` with `label: str`, `confidence: float`, `x_min: int`, `y_min: int`, `x_max: int`, `y_max: int`
    - Define `ViolationEventResponse(BaseModel)` with all fields including `bounding_boxes: list[BoundingBox]`, `processing_latency: int`, `raw_api_response: dict`
    - Define `CameraStatusResponse`, `ViolationStatsResponse`, `ViolationListResponse` (with pagination metadata)
    - Define query parameter models for `/violations` endpoint filters
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 4.2 Implement violations API routes
    - Create `backend/api/routes/violations.py`
    - Implement `GET /api/v1/violations` with query params `camera_id`, `start_time`, `end_time`, `violation_type`, `limit` (default 50), `offset` (default 0); call `EventRepository.query_violations()`
    - Implement `GET /api/v1/violations/{event_id}` returning full `ViolationEventResponse` including extended fields; return 404 if not found
    - _Requirements: 5.2, 5.3_

  - [x] 4.3 Implement cameras and stats API routes
    - Create `backend/api/routes/cameras.py`: `GET /api/v1/cameras` returning list of `CameraStatusResponse` from `VideoProcessor.get_camera_status()`
    - Create `backend/api/routes/stats.py`: `GET /api/v1/stats` with `start_time`/`end_time` query params; call `EventRepository.get_stats()`
    - _Requirements: 5.4, 5.5_

  - [x] 4.4 Create FastAPI application entry point with CORS and error handling
    - Create `backend/main.py`
    - Instantiate `FastAPI()` app, include all routers with prefix `/api/v1`
    - Add `CORSMiddleware` with `allow_origins` from `settings.CORS_ORIGINS`
    - Add global exception handler for unhandled exceptions: log full traceback, return HTTP 500 with generic message (no internal details)
    - On startup: initialize `asyncpg` pool, start `VideoProcessor` tasks for all RTSP streams from config
    - On shutdown: stop all `VideoProcessor` tasks, close DB pool
    - _Requirements: 5.1, 5.6, 5.7, 5.8, 7.1, 7.4_

  - [x]* 4.5 Write property test for API layer — Property 6: API parameter validation coverage
    - Create `backend/tests/test_api_properties.py`
    - **Property 6: API 参数验证覆盖性**
    - Use `@given(st.fixed_dictionaries({...}))` to generate invalid query params (wrong types, out-of-range values, missing required fields) for each endpoint
    - Use FastAPI `TestClient`; assert response status is 422 and body contains structured error description
    - `@settings(max_examples=100)`
    - **Validates: Requirements 5.6**

  - [x]* 4.6 Write unit tests for API error handling
    - Add to `backend/tests/test_api_properties.py`
    - Mock `EventRepository` to raise unhandled exception; assert API returns HTTP 500 with no internal details in response body
    - Test 404 response for unknown `event_id`
    - _Requirements: 5.7_

- [ ] 5. Checkpoint — API layer complete
  - Run `pytest backend/tests/ --tb=short` (excluding optional tests if desired). Verify all four API endpoints respond correctly via FastAPI `TestClient`. Ask the user if questions arise.

- [x] 6. React Dashboard
  - [x] 6.1 Initialize React project with Tailwind CSS
    - Scaffold frontend with `create-react-app` or Vite + TypeScript template in `frontend/` directory
    - Install and configure Tailwind CSS
    - Create base layout component with navigation header and main content area
    - Configure API base URL via environment variable `REACT_APP_API_URL` / `VITE_API_URL`
    - _Requirements: 6.1_

  - [x] 6.2 Implement API client and shared TypeScript types
    - Create `frontend/src/api/client.ts` with typed fetch wrappers for all four endpoints
    - Define TypeScript interfaces matching backend Pydantic schemas: `BoundingBox`, `ViolationEvent`, `CameraStatus`, `ViolationStats`
    - Implement error handling: on API failure return typed error state (do not throw)
    - _Requirements: 6.7_

  - [x] 6.3 Implement violation alert list with 5-second polling
    - Create `frontend/src/components/ViolationList.tsx`
    - Use `useEffect` + `setInterval` (5000ms) to poll `GET /api/v1/violations`
    - Display each violation with: camera ID, timestamp, violation types, snapshot thumbnail
    - Show newest violations at top of list
    - Display friendly error message (not blank page) when API call fails
    - _Requirements: 6.2, 6.3, 6.7_

  - [x] 6.4 Implement bounding box overlay on snapshot images
    - Create `frontend/src/components/SnapshotViewer.tsx`
    - Accept `snapshot_url` and `bounding_boxes: BoundingBox[]` as props
    - Render snapshot `<img>` with a `<canvas>` or `<svg>` overlay positioned absolutely on top
    - Draw each bounding box as a colored rectangle with `label` text using canvas `strokeRect` / SVG `<rect>`
    - Handle image load event to size canvas to match rendered image dimensions
    - _Requirements: 6.3, 4.3, 4.8_

  - [x] 6.5 Implement processing latency performance metrics display
    - Create `frontend/src/components/LatencyBadge.tsx`
    - Accept `processing_latency: number` (milliseconds) as prop
    - Display latency value with color coding: green (<1000ms), yellow (1000–3000ms), red (>3000ms)
    - Integrate into `ViolationList` item and violation detail view
    - _Requirements: 6.3, 4.3_

  - [x] 6.6 Implement historical query with camera and time range filters
    - Create `frontend/src/components/HistoryFilter.tsx` with controlled inputs for `camera_id` (select), `start_time` (datetime-local), `end_time` (datetime-local)
    - On filter change, call `GET /api/v1/violations` with filter params and update results list
    - _Requirements: 6.4_

  - [x] 6.7 Implement camera online status display
    - Create `frontend/src/components/CameraStatusPanel.tsx`
    - Poll `GET /api/v1/cameras` every 5 seconds
    - Display each camera as a card with status indicator: green dot (online), red dot (offline), yellow dot (retrying)
    - _Requirements: 6.5_

  - [x] 6.8 Implement daily statistics chart
    - Create `frontend/src/components/StatsChart.tsx`
    - Call `GET /api/v1/stats` with today's date range on mount
    - Display total violation count for the day and a bar/pie chart of violations by type using a lightweight chart library (e.g., `recharts`)
    - _Requirements: 6.6_

  - [x] 6.9 Wire all dashboard components into main App layout
    - Update `frontend/src/App.tsx` to compose `CameraStatusPanel`, `ViolationList`, `HistoryFilter`, `StatsChart`
    - Ensure shared state (selected camera filter) flows correctly between `HistoryFilter` and `ViolationList`
    - _Requirements: 6.1, 6.2, 6.4, 6.5, 6.6_

- [ ] 7. Checkpoint — Dashboard complete
  - Verify React app compiles without errors. Confirm bounding box overlay renders correctly with sample data. Ask the user if questions arise.

- [x] 8. Property-Based Tests (Hypothesis)
  - [x]* 8.1 Finalize Property 1 test — violation detection completeness
    - Ensure `backend/tests/test_vision_analyzer_properties.py` test for Property 1 is complete and passing
    - **Property 1: 违规判断的完备性** — `@given` missing PPE lists, assert `is_violation=True` and `violation_types` completeness
    - `@settings(max_examples=100)`
    - **Validates: Requirements 2.4**

  - [x]* 8.2 Finalize Property 2 test — API failure produces no false positives
    - Ensure Property 2 test in `test_vision_analyzer_properties.py` covers HTTP errors, network exceptions, and malformed JSON bodies
    - **Property 2: API 失败不产生误报**
    - `@settings(max_examples=100)`
    - **Validates: Requirements 2.5**

  - [x]* 8.3 Finalize Property 3 test — storage path format correctness
    - Ensure `backend/tests/test_violation_recorder_properties.py` Property 3 test covers all valid `camera_id` character sets and UTC timestamp edge cases
    - **Property 3: 存储路径格式正确性**
    - `@settings(max_examples=100)`
    - **Validates: Requirements 3.3, 3.4**

  - [x]* 8.4 Finalize Property 4 test — violation event record completeness (round-trip)
    - Ensure `backend/tests/test_event_repository_properties.py` Property 4 test generates diverse `ViolationEvent` objects including edge cases (empty `bounding_boxes`, zero `processing_latency`, nested `raw_api_response`)
    - **Property 4: 违规事件记录完整性**
    - `@settings(max_examples=100)`
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.8**

  - [x]* 8.5 Finalize Property 5 test — query filter result consistency
    - Ensure `backend/tests/test_event_repository_properties.py` Property 5 test covers all filter parameter combinations including None values
    - **Property 5: 查询过滤结果一致性**
    - `@settings(max_examples=100)`
    - **Validates: Requirements 4.6, 5.2**

  - [x]* 8.6 Finalize Property 6 test — API parameter validation coverage
    - Ensure `backend/tests/test_api_properties.py` Property 6 test covers all four endpoints with diverse invalid input types
    - **Property 6: API 参数验证覆盖性**
    - `@settings(max_examples=100)`
    - **Validates: Requirements 5.6**

  - [x]* 8.7 Finalize Property 7 test — upload retry count upper bound
    - Ensure `backend/tests/test_violation_recorder_properties.py` Property 7 test covers all failure count values (1, 2, 3) and verifies `pending_retry` status on total failure
    - **Property 7: 上传重试次数上限**
    - `@settings(max_examples=100)`
    - **Validates: Requirements 3.5, 3.6**

- [x] 9. Final Checkpoint — All tests pass
  - Run `pytest backend/tests/ --tb=short`. Ensure all non-optional tests pass. Verify Docker Compose starts cleanly with `docker-compose up --build`. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Property tests (tasks 2.2, 2.3, 2.5, 2.6, 2.8, 2.9, 4.5, 4.6, 8.1–8.7) correspond directly to the 7 correctness properties defined in the design document
- Each task references specific requirements for full traceability
- Backend language: Python 3.11+ with asyncio; Frontend: TypeScript + React
- All DB queries use asyncpg parameterized placeholders to prevent SQL injection (Requirement 4.4)
