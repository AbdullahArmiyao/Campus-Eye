"""
Campus Eye — Discord Webhook Alert Sender
Sends rich embeds with event details and optionally uploads snapshot.
"""
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Colour codes per event type
EMBED_COLOURS = {
    "loitering":       0xF5A623,
    "littering":       0x7ED321,
    "vandalism":       0xD0021B,
    "unknown_face":    0x9013FE,
    "foreign_object":  0xFF0000,
    "head_swiveling":  0xFF6900,
    "talking":         0xFF9500,
    "hand_interaction":0xE8001D,
}


def send_discord_webhook(
    webhook_url: str,
    event_type: str,
    description: str,
    camera_id: str,
    mode: str,
    snapshot_path: str | None,
    timestamp: str,
):
    colour = EMBED_COLOURS.get(event_type, 0xAAAAAA)

    embed = {
        "title": f"⚠ {event_type.replace('_', ' ').title()}",
        "description": description,
        "color": colour,
        "fields": [
            {"name": "Camera",    "value": camera_id, "inline": True},
            {"name": "Mode",      "value": mode.upper(), "inline": True},
            {"name": "Timestamp", "value": timestamp, "inline": False},
        ],
        "footer": {"text": "Campus Eye Monitoring System"},
    }

    payload: dict = {"embeds": [embed]}

    snap = Path(snapshot_path) if snapshot_path else None
    if snap and snap.exists():
        # Send as multipart with file attachment
        with snap.open("rb") as f:
            files = {"file": (snap.name, f, "image/jpeg")}
            embed["image"] = {"url": f"attachment://{snap.name}"}
            payload["embeds"] = [embed]
            resp = httpx.post(
                webhook_url,
                data={"payload_json": __import__("json").dumps(payload)},
                files=files,
                timeout=10,
            )
    else:
        resp = httpx.post(webhook_url, json=payload, timeout=10)

    resp.raise_for_status()
    logger.info(f"Discord alert sent (event_type={event_type}).")
