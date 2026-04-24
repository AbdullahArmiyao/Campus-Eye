"""
Campus Eye — Video Capture
Wraps OpenCV VideoCapture for both RTSP streams and video files.
Emits frames at a configurable FPS with auto-reconnect for RTSP.
"""
import logging
import time
from threading import Event, Thread
from typing import Optional

import cv2
import numpy as np

from app.config import get_settings, get_yaml_config

logger = logging.getLogger(__name__)


class VideoCapture:
    """
    Thread-safe video frame source.

    Usage:
        cap = VideoCapture("rtsp://...")
        cap.start()
        frame = cap.get_frame()   # latest frame or None
        cap.stop()
    """

    def __init__(self, url: str | None = None):
        settings = get_settings()
        yaml_cfg = get_yaml_config()
        proc_cfg = yaml_cfg.get("processing", {})

        self._url: str = url or settings.camera_url
        self._target_fps: int = proc_cfg.get("fps", settings.process_fps)
        self._reconnect_delay: int = proc_cfg.get("reconnect_delay_seconds", 5)
        self._width: int = proc_cfg.get("frame_width", 640)
        self._height: int = proc_cfg.get("frame_height", 480)

        self._cap: cv2.VideoCapture | None = None
        self._latest_frame: np.ndarray | None = None
        self._running = False
        self._stop_event = Event()
        self._thread: Thread | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        """Start the background capture thread."""
        self._running = True
        self._stop_event.clear()
        self._thread = Thread(target=self._capture_loop, daemon=True, name="VideoCapture")
        self._thread.start()
        logger.info(f"VideoCapture started: {self._url}")

    def stop(self):
        """Stop capture and release the VideoCapture object."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._cap and self._cap.isOpened():
            self._cap.release()
        logger.info("VideoCapture stopped.")

    def set_source(self, url: str):
        """Hot-swap the video source while the capture thread keeps running."""
        logger.info(f"Switching video source to: {url}")
        self._url = url
        self._latest_frame = None   # clear stale frame immediately
        # Force the capture loop to re-open by releasing current handle
        if self._cap and self._cap.isOpened():
            self._cap.release()
            self._cap = None

    def get_frame(self) -> np.ndarray | None:
        """Return the most recent frame (may be None if not yet captured)."""
        return self._latest_frame

    @property
    def current_source(self) -> str:
        return self._url

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Internal ──────────────────────────────────────────────────────────────

    def _open(self) -> bool:
        """Open (or re-open) the video source."""
        if self._cap and self._cap.isOpened():
            self._cap.release()

        # Determine if URL is an integer (webcam index)
        source: int | str = self._url
        try:
            source = int(self._url)
        except (ValueError, TypeError):
            pass

        self._cap = cv2.VideoCapture(source)

        # Short connection timeout so RTSP failures don't hang for 30s
        if isinstance(source, str) and (source.startswith("rtsp") or source.startswith("rtmp")):
            self._cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            self._cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)

        if not self._cap.isOpened():
            logger.warning(f"Failed to open video source: {self._url}")
            return False

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        logger.info(f"Video source opened: {self._url}")
        return True

    def _capture_loop(self):
        """Background thread: read frames, throttle to target FPS."""
        interval = 1.0 / max(self._target_fps, 1)

        while not self._stop_event.is_set():
            if not self._cap or not self._cap.isOpened():
                if not self._open():
                    logger.warning(f"Retrying in {self._reconnect_delay}s...")
                    self._stop_event.wait(self._reconnect_delay)
                    continue

            ret, frame = self._cap.read()
            if not ret:
                logger.warning("Frame read failed — attempting reconnect...")
                self._stop_event.wait(self._reconnect_delay)
                self._open()
                continue

            self._latest_frame = frame
            self._stop_event.wait(interval)

        if self._cap:
            self._cap.release()
