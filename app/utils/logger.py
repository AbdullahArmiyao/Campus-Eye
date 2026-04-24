"""
Campus Eye — Logging Setup
Structured logging: human-readable in dev, JSON in production.
"""
import logging
import sys

from app.config import get_settings


def setup_logging():
    settings = get_settings()
    level = logging.DEBUG if settings.debug else logging.INFO

    fmt = (
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        if settings.debug
        else "%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Silence noisy third-party loggers
    for noisy in ("ultralytics", "insightface", "mediapipe", "httpx", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("campus_eye").setLevel(level)
    logging.info("Logging configured.")
