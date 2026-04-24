"""
Campus Eye — Snapshot Utility
Saves annotated frames to disk with timestamped filenames.
"""
import logging
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)


def save_snapshot(frame: np.ndarray, event_type: str) -> str:
    """
    Save a JPEG snapshot of the given frame.
    Returns the relative path string (relative to project root).
    """
    settings = get_settings()
    snap_dir = Path(settings.snapshot_dir)
    snap_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{event_type}_{ts}.jpg"
    path = snap_dir / filename

    encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85]
    success, buf = cv2.imencode(".jpg", frame, encode_params)
    if success:
        path.write_bytes(buf.tobytes())
        logger.debug(f"Snapshot saved: {path}")
    else:
        logger.warning("cv2.imencode failed — snapshot not saved.")
        return ""

    return str(path)
