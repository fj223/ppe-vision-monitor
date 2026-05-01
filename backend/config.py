"""
Application configuration loaded from environment variables / .env file.

All fields are required. Missing secrets cause a ValidationError at startup
with the exact field name(s) printed — the process exits with a non-zero code.
(Requirements 7.1, 7.3)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    database_url: str  # e.g. postgresql+asyncpg://user:pass@postgres:5432/ppe_monitoring

    # ------------------------------------------------------------------ #
    # Yandex Object Storage (S3-compatible)
    # ------------------------------------------------------------------ #
    yos_endpoint_url: str       # e.g. https://storage.yandexcloud.net
    yos_access_key_id: str
    yos_secret_access_key: str
    yos_bucket_name: str        # e.g. ppe-violations

    # ------------------------------------------------------------------ #
    # Yandex Vision API
    # ------------------------------------------------------------------ #
    yandex_vision_api_key: str
    yandex_vision_folder_id: str

    # ------------------------------------------------------------------ #
    # RTSP streams — comma-separated key=value pairs
    # e.g. cam_01=rtsp://192.168.1.10/stream,cam_02=rtsp://192.168.1.11/stream
    # ------------------------------------------------------------------ #
    rtsp_streams: str

    # ------------------------------------------------------------------ #
    # Tuning parameters (have safe defaults so they are optional in .env)
    # ------------------------------------------------------------------ #
    frame_interval_seconds: int = 2
    vision_api_timeout_seconds: int = 5
    max_retry_attempts: int = 5

    # ------------------------------------------------------------------ #
    # Observability
    # ------------------------------------------------------------------ #
    log_level: str = "INFO"

    # ------------------------------------------------------------------ #
    # CORS — comma-separated origins
    # e.g. http://localhost:3000,https://dashboard.example.com
    # ------------------------------------------------------------------ #
    cors_origins: str = "http://localhost:3000"

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def get_rtsp_streams(self) -> dict[str, str]:
        """Parse RTSP_STREAMS into {camera_id: rtsp_url} dict."""
        result: dict[str, str] = {}
        for pair in self.rtsp_streams.split(","):
            pair = pair.strip()
            if "=" in pair:
                cam_id, url = pair.split("=", 1)
                result[cam_id.strip()] = url.strip()
        return result

    def get_cors_origins(self) -> list[str]:
        """Parse CORS_ORIGINS into a list of origin strings."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


# Module-level singleton — imported by all other modules.
# Raises pydantic_settings.ValidationError (with field names) if any
# required variable is absent, which prevents the app from starting.
settings = Settings()
