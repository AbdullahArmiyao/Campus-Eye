"""
Campus Eye — Celery Alert Tasks
Each task loads the event from DB and dispatches via the configured channels.
"""
import asyncio
import logging

from app.alerts.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Helper to run an async coroutine from a sync Celery task.
    
    Celery workers run tasks in threads that have no running event loop,
    so asyncio.run() is always safe here. The deprecated get_event_loop()
    pattern is avoided to maintain Python 3.10+ compatibility.
    """
    return asyncio.run(coro)


async def _load_event(event_id: int):
    from app.database import AsyncSessionLocal
    from app.models import Event
    async with AsyncSessionLocal() as db:
        event = await db.get(Event, event_id)
        return event


@celery_app.task(name="app.alerts.tasks.dispatch_alert", bind=True, max_retries=3)
def dispatch_alert(self, event_id: int):
    """Fan out to email + Discord alert tasks."""
    logger.info(f"Dispatching alerts for event_id={event_id}")
    send_email_alert.delay(event_id)
    send_discord_alert.delay(event_id)


@celery_app.task(name="app.alerts.tasks.send_email_alert", bind=True, max_retries=3)
def send_email_alert(self, event_id: int):
    """Send SMTP email alert with snapshot attachment."""
    from app.config import get_settings
    settings = get_settings()
    if not settings.smtp_user or not settings.alert_email_to:
        logger.info("Email alerts not configured — skipping.")
        return

    event = _run_async(_load_event(event_id))
    if not event:
        logger.warning(f"Event {event_id} not found — skipping email.")
        return

    try:
        from app.alerts.email_sender import send_alert_email
        send_alert_email(
            to=settings.alert_email_to,
            event_type=event.event_type,   # plain string column — no .value needed
            description=event.description or "",
            camera_id=event.camera_id,
            snapshot_path=event.snapshot_path,
            timestamp=event.created_at.isoformat(),
        )
        logger.info(f"Email alert sent for event {event_id}.")
    except Exception as exc:
        logger.error(f"Email alert failed: {exc}")
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="app.alerts.tasks.send_discord_alert", bind=True, max_retries=3)
def send_discord_alert(self, event_id: int):
    """Send Discord webhook alert with embed."""
    from app.config import get_settings
    settings = get_settings()
    if not settings.discord_webhook_url:
        logger.info("Discord webhook not configured — skipping.")
        return

    event = _run_async(_load_event(event_id))
    if not event:
        logger.warning(f"Event {event_id} not found — skipping Discord.")
        return

    try:
        from app.alerts.discord_sender import send_discord_webhook
        send_discord_webhook(
            webhook_url=settings.discord_webhook_url,
            event_type=event.event_type,   # plain string column — no .value needed
            description=event.description or "",
            camera_id=event.camera_id,
            mode=event.mode,               # plain string column — no .value needed
            snapshot_path=event.snapshot_path,
            timestamp=event.created_at.isoformat(),
        )
        logger.info(f"Discord alert sent for event {event_id}.")
    except Exception as exc:
        logger.error(f"Discord alert failed: {exc}")
        raise self.retry(exc=exc, countdown=30)
