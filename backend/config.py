"""Application configuration for the local YOLOv8 deployment."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    database_url: str = "postgresql+asyncpg://ppe_user:ppe_pass@postgres:5432/ppe_monitoring"
    model_path: str = "models/best.pt"
    model_confidence: float = 0.5
    model_device: str | None = None
    snapshot_dir: str = "snapshots"
    rtsp_streams: str = ""
    frame_interval_seconds: int = 2
    max_retry_attempts: int = 5
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    def get_rtsp_streams(self) -> dict[str, str]:
        """Parse RTSP_STREAMS as comma-separated camera_id=URL pairs."""
        result: dict[str, str] = {}
        for pair in self.rtsp_streams.split(","):
            if "=" in pair:
                camera_id, url = pair.split("=", 1)
                result[camera_id.strip()] = url.strip()
        return result

    def get_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def snapshot_path(self) -> Path:
        path = Path(self.snapshot_dir)
        return path if path.is_absolute() else Path(__file__).resolve().parent / path


settings = Settings()
