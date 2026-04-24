"""
Campus Eye — Clip Recorder
Maintains a circular buffer of recent frames and saves a video clip
(before + after the triggering event) when requested.
"""
import logging
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.config import get_settings, get_yaml_config

logger = logging.getLogger(__name__)


class ClipRecorder:
    """
    Circular frame buffer + on-demand clip writer.
    Thread-safe reads from the main processing loop;
    writes are performed synchronously (acceptable at low fps).
    """

    def __init__(self):
        settings = get_settings()
        cfg = get_yaml_config()
        det_cfg = cfg.get("detection", {})
        clip_cfg = cfg.get("clip_recording", {})

        self._enabled: bool = clip_cfg.get("enabled", True)
        self._before_s: int = det_cfg.get("clip_seconds_before", 5)
        self._after_s: int  = det_cfg.get("clip_seconds_after", 5)
        self._fps: int = clip_cfg.get("fps", 10)
        self._codec: str = clip_cfg.get("codec", "mp4v")

        # Circular buffer: stores (timestamp, frame) for the last `_before_s` seconds
        max_frames = self._before_s * self._fps + 10
        self._buffer: deque[tuple[float, np.ndarray]] = deque(maxlen=max_frames)

        self._clip_dir = Path(settings.clip_dir if hasattr(settings, "clip_dir") else "media/clips")
        self._clip_dir.mkdir(parents=True, exist_ok=True)

        # Pending clip: frames to write after the trigger
        self._pending: dict | None = None   # {path, writer, frames_remaining}

    def push_frame(self, frame: np.ndarray):
        """Add a frame to the circular buffer and write pending clip if active."""
        if not self._enabled:
            return
        self._buffer.append((time.monotonic(), frame.copy()))

        if self._pending:
            self._write_pending_frame(frame)

    def trigger(self, event_type: str) -> str | None:
        """
        Called when an event fires. Saves the buffered pre-event frames
        and begins recording post-event frames.
        Returns the clip file path (relative), or None if disabled.
        """
        if not self._enabled or not self._buffer:
            return None

        # If a clip is already in progress, finalize it before starting a new one
        # to avoid VideoWriter handle leaks.
        if self._pending:
            self._pending["writer"].release()
            logger.info(f"Previous clip finalized early (new event): {self._pending['path']}")
            self._pending = None

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{event_type}_{ts}.mp4"
        clip_path = self._clip_dir / filename

        # Get frame dimensions from buffer
        _, sample_frame = self._buffer[-1]
        h, w = sample_frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*self._codec)
        writer = cv2.VideoWriter(str(clip_path), fourcc, self._fps, (w, h))

        if not writer.isOpened():
            logger.warning(f"Could not open VideoWriter for clip: {clip_path}")
            return None

        # Write buffered pre-event frames
        now = time.monotonic()
        for ts_buf, frm in self._buffer:
            if now - ts_buf <= self._before_s:
                writer.write(frm)

        self._pending = {
            "path": clip_path,
            "writer": writer,
            "frames_remaining": self._after_s * self._fps,
        }

        logger.info(f"Clip recording started: {clip_path}")
        return str(clip_path)

    def _write_pending_frame(self, frame: np.ndarray):
        if self._pending is None:
            return
        self._pending["writer"].write(frame)
        self._pending["frames_remaining"] -= 1
        if self._pending["frames_remaining"] <= 0:
            self._pending["writer"].release()
            logger.info(f"Clip saved: {self._pending['path']}")
            self._pending = None
