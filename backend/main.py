"""
FastAPI application entry point.

Lifecycle:
  startup  — create asyncpg pool, instantiate modules, start camera tasks
  shutdown — stop camera tasks, close DB pool

Middleware:
  - CORSMiddleware (origins from CORS_ORIGINS env var)
  - Global exception handler: logs full traceback, returns HTTP 500
    with a generic message — never exposes internal details to clients.

(Requirements 5.1, 5.6, 5.7, 5.8, 7.1, 7.4)
"""

from __future__ import annotations

import base64
import logging
import traceback
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import cameras, stats, violations
from config import settings
from modules.event_repository import EventRepository
from modules.video_processor import VideoProcessor
from modules.violation_recorder import ViolationRecorder
from modules.vision_analyzer import VisionAnalyzer

# --------------------------------------------------------------------------- #
# Logging setup
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Lifespan — startup / shutdown
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- Startup ----
    logger.info("app_startup_begin")

    # Database pool
    # Strip the SQLAlchemy-style prefix if present; asyncpg uses plain DSN.
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool: asyncpg.Pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
    logger.info("db_pool_created")

    # Module instances
    analyzer = VisionAnalyzer()
    recorder = ViolationRecorder()
    repository = EventRepository(pool)
    processor = VideoProcessor(analyzer, recorder, repository)

    # Attach to app state so routes can access them via request.app.state
    app.state.pool = pool
    app.state.analyzer = analyzer
    app.state.repository = repository
    app.state.video_processor = processor

    # Start one asyncio Task per configured RTSP stream
    rtsp_streams = settings.get_rtsp_streams()
    for camera_id, rtsp_url in rtsp_streams.items():
        await processor.start(camera_id, rtsp_url)
        logger.info("camera_started", extra={"camera_id": camera_id})

    logger.info("app_startup_complete", extra={"cameras": list(rtsp_streams.keys())})

    yield  # application runs here

    # ---- Shutdown ----
    logger.info("app_shutdown_begin")
    await processor.stop_all()
    await pool.close()
    logger.info("app_shutdown_complete")


# --------------------------------------------------------------------------- #
# App instance
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="PPE Compliance Monitoring API",
    description=(
        "Real-time PPE compliance detection system. "
        "Provides violation events with bounding boxes, "
        "processing latency metrics, and raw Vision API responses."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# --------------------------------------------------------------------------- #
# CORS middleware (Requirement 5.8)
# --------------------------------------------------------------------------- #

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Global exception handler (Requirement 5.7)
# --------------------------------------------------------------------------- #

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all for unhandled exceptions.
    Logs the full traceback server-side; returns a generic 500 to the client
    so internal implementation details are never exposed.
    """
    logger.error(
        "unhandled_exception",
        extra={
            "path": request.url.path,
            "method": request.method,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        },
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


# --------------------------------------------------------------------------- #
# Routers
# --------------------------------------------------------------------------- #

app.include_router(violations.router, prefix="/api/v1")
app.include_router(cameras.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")


# --------------------------------------------------------------------------- #
# Health check
# --------------------------------------------------------------------------- #

@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Manual upload analysis (not persisted to DB)
# --------------------------------------------------------------------------- #

@app.post("/api/analyze-upload", tags=["analysis"])
async def analyze_upload(file: UploadFile = File(...)) -> JSONResponse:
    """
    Accept a single image upload, run PPE detection, and return results
    with bounding boxes and a Base64-encoded copy of the original image.
    Results are NOT stored in the database to avoid polluting statistics.
    """
    frame_bytes = await file.read()

    analyzer: VisionAnalyzer = app.state.analyzer
    result = await analyzer.analyze(frame_bytes, camera_id="manual_upload")

    if result is None:
        return JSONResponse(
            status_code=422,
            content={"detail": "图片解析失败，请确认上传的是有效的图片文件。"},
        )

    image_base64 = base64.b64encode(frame_bytes).decode("utf-8")

    return JSONResponse(content={
        "is_violation": result.is_violation,
        "violation_types": result.violation_types,
        "detected_ppe": result.detected_ppe,
        "bounding_boxes": [
            {
                "label": bb.label,
                "confidence": bb.confidence,
                "x_min": bb.x_min,
                "y_min": bb.y_min,
                "x_max": bb.x_max,
                "y_max": bb.y_max,
            }
            for bb in result.bounding_boxes
        ],
        "image_base64": image_base64,
    })
