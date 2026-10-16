from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SENTINEL_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///data/sentinel.db"
    data_dir: Path = Path("data")
    secret: str = ""
    origin: str = "http://127.0.0.1:3000"
    model: str = "yolo11n.pt"
    device: str = "cpu"
    max_upload_mb: int = Field(default=100, ge=1, le=2048)
    max_duration_seconds: int = Field(default=600, ge=1, le=3600)
    retention_days: int = Field(default=7, ge=1, le=365)
    queue: Literal["database", "celery"] = "database"
    redis_url: str = "redis://localhost:6379/0"
    rtsp_hosts: str = ""
    rtsp_allowed_ips: str = ""
    allow_loopback_camera_fixture: bool = False
    storage: Literal["local", "s3"] = "local"
    s3_endpoint: str | None = None
    s3_bucket: str = "sentinel"
    s3_region: str = "us-east-1"
    lease_seconds: int = Field(default=120, ge=30, le=3600)
    retention_interval: int = Field(default=3600, ge=60)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
