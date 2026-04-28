"""
Campus Eye — Configuration
Merges .env environment variables with config.yaml runtime settings.
"""
import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),   # avoids clash with model_dir field
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://campus_eye:campus_eye_secret@localhost:5432/campus_eye"
    postgres_user: str = "campus_eye"
    postgres_password: str = "campus_eye_secret"
    postgres_db: str = "campus_eye"

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── SMTP ──────────────────────────────────────────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""

    # ── Discord ───────────────────────────────────────────────────────────────
    discord_webhook_url: str = ""

    # ── Camera ───────────────────────────────────────────────────────────────
    camera_url: str = "0"          # "0" = webcam fallback for local testing

    # ── App ───────────────────────────────────────────────────────────────────
    secret_key: str = "changeme"
    debug: bool = False
    app_host: str = "0.0.0.0"
    app_port: int = 9000

    # ── Detection ─────────────────────────────────────────────────────────────
    process_fps: int = 10
    stream_fps: int = 30
    face_recognition_threshold: float = 0.50
    loitering_threshold_seconds: int = 30

    # ── Derived paths (not from env) ──────────────────────────────────────────
    base_dir: Path = Path(__file__).parent.parent
    media_dir: Path = Path("media")
    snapshot_dir: Path = Path("media/snapshots")
    clip_dir: Path = Path("media/clips")
    model_dir: Path = Path("models")
    config_yaml_path: Path = Path("config.yaml")

    def ensure_dirs(self):
        for d in (self.snapshot_dir, self.clip_dir, self.model_dir):
            d.mkdir(parents=True, exist_ok=True)


def _load_yaml() -> dict:
    path = Path("config.yaml")
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


# Expose raw YAML config for pipeline-specific settings
@lru_cache(maxsize=1)
def get_yaml_config() -> dict:
    return _load_yaml()
