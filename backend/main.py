"""FastAPI entry point for the local YOLOv8 PPE monitor."""

from __future__ import annotations

import base64
import logging
import traceback
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import cameras, stats, violations
from config import settings
from modules.event_repository import EventRepository
from modules.video_processor import VideoProcessor
from modules.violation_recorder import ViolationRecorder
from modules.vision_analyzer import VisionAnalyzer

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool: asyncpg.Pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
    analyzer = VisionAnalyzer()
    repository = EventRepository(pool)
    processor = VideoProcessor(analyzer, ViolationRecorder(), repository)
    app.state.pool = pool
    app.state.analyzer = analyzer
    app.state.repository = repository
    app.state.video_processor = processor
    for camera_id, rtsp_url in settings.get_rtsp_streams().items():
        await processor.start(camera_id, rtsp_url)
    yield
    await processor.stop_all()
    await pool.close()


settings.snapshot_path.mkdir(parents=True, exist_ok=True)
app = FastAPI(
    title="PPE Compliance Monitoring API",
    description="Local YOLOv8 PPE detection with RTSP monitoring and stored evidence frames.",
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
app.mount("/snapshots", StaticFiles(directory=str(settings.snapshot_path)), name="snapshots")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_exception",
        extra={"path": request.url.path, "method": request.method, "error": str(exc), "traceback": traceback.format_exc()},
    )
    return JSONResponse(status_code=500, content={"detail": "An internal server error occurred."})


app.include_router(violations.router, prefix="/api/v1")
app.include_router(cameras.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "inference_engine": "local-yolov8"}


@app.post("/api/analyze-upload", tags=["analysis"])
async def analyze_upload(file: UploadFile = File(...)) -> JSONResponse:
    frame = await file.read()
    result = await app.state.analyzer.analyze(frame, camera_id="manual_upload")
    if result is None:
        return JSONResponse(status_code=422, content={"detail": "The uploaded image could not be analysed."})
    return JSONResponse(content={
        "is_violation": result.is_violation,
        "violation_types": result.violation_types,
        "detected_ppe": result.detected_ppe,
        "inference_metadata": result.inference_metadata,
        "bounding_boxes": [bb.__dict__ for bb in result.bounding_boxes],
        "image_base64": base64.b64encode(frame).decode("utf-8"),
    })
