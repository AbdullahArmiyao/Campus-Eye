"""
Campus Eye — Celery Application
Broker: Redis
Backend: Redis (for task result storage)
"""
from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "campus_eye",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.alerts.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.alerts.tasks.send_email_alert":   {"queue": "alerts"},
        "app.alerts.tasks.send_discord_alert": {"queue": "alerts"},
    },
)
