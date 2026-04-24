"""
Campus Eye — Email Alert Sender (SMTP)
"""
import logging
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


def send_alert_email(
    to: str,
    event_type: str,
    description: str,
    camera_id: str,
    snapshot_path: str | None,
    timestamp: str,
):
    settings = get_settings()

    msg = MIMEMultipart("related")
    msg["Subject"] = f"[Campus Eye Alert] {event_type.replace('_', ' ').title()} — {camera_id}"
    msg["From"] = settings.smtp_user
    msg["To"] = to

    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;background:#111;color:#eee;padding:20px;">
      <h2 style="color:#f55;">&#9888; Campus Eye Security Alert</h2>
      <table style="border-collapse:collapse;width:100%;">
        <tr><td style="padding:8px;color:#aaa;">Event</td>
            <td style="padding:8px;font-weight:bold;color:#ff9;">{event_type.replace('_',' ').title()}</td></tr>
        <tr><td style="padding:8px;color:#aaa;">Camera</td>
            <td style="padding:8px;">{camera_id}</td></tr>
        <tr><td style="padding:8px;color:#aaa;">Time</td>
            <td style="padding:8px;">{timestamp}</td></tr>
        <tr><td style="padding:8px;color:#aaa;">Details</td>
            <td style="padding:8px;">{description}</td></tr>
      </table>
      {"<br><img src='cid:snapshot' style='max-width:640px;border:2px solid #555;border-radius:6px;'/>" if snapshot_path else ""}
      <p style="color:#555;font-size:12px;margin-top:20px;">Campus Eye Monitoring System</p>
    </body></html>
    """
    msg.attach(MIMEText(html_body, "html"))

    if snapshot_path:
        snap = Path(snapshot_path)
        if snap.exists():
            with snap.open("rb") as f:
                img = MIMEImage(f.read(), name=snap.name)
                img.add_header("Content-ID", "<snapshot>")
                img.add_header("Content-Disposition", "inline", filename=snap.name)
                msg.attach(img)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, to, msg.as_string())
        logger.info(f"Email alert sent to {to}.")
