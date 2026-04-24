"""
Campus Eye — Loitering Detector
Tracks persons (by YOLO ByteTrack ID) and fires an alert if they
remain in the frame zone for longer than the configured threshold.
"""
import logging
import time
from dataclasses import dataclass

from app.config import get_settings, get_yaml_config
from app.pipeline.object_detector import Detection

logger = logging.getLogger(__name__)


@dataclass
class LoiteringEvent:
    track_id: int
    duration_seconds: float
    bbox: tuple[int, int, int, int]


class LoiteringDetector:
    """
    Maintains first-seen timestamps per track_id.
    Triggers LoiteringEvent when duration exceeds threshold.
    Cleans up stale track IDs not seen for >2× threshold.
    """

    def __init__(self):
        cfg = get_yaml_config().get("detection", {})
        settings = get_settings()
        self._threshold: float = cfg.get(
            "loitering_threshold_seconds",
            settings.loitering_threshold_seconds,
        )
        self._first_seen: dict[int, float] = {}
        self._last_seen: dict[int, float] = {}
        self._alerted: set[int] = set()

    def update(self, persons: list[Detection]) -> list[LoiteringEvent]:
        """
        Call each frame with the list of detected persons.
        Returns LoiteringEvent for each person that has been loitering
        (only fires once per track_id until they leave the frame).
        """
        now = time.monotonic()
        current_ids = {d.track_id for d in persons if d.track_id is not None}

        # Register new arrivals
        for det in persons:
            tid = det.track_id
            if tid is None:
                continue
            if tid not in self._first_seen:
                self._first_seen[tid] = now
            self._last_seen[tid] = now

        # Expire stale track IDs (not seen for > 2× threshold)
        expired = [
            tid for tid, last in self._last_seen.items()
            if now - last > self._threshold * 2
        ]
        for tid in expired:
            self._first_seen.pop(tid, None)
            self._last_seen.pop(tid, None)
            self._alerted.discard(tid)

        # Check for loitering
        events: list[LoiteringEvent] = []
        det_by_id = {d.track_id: d for d in persons if d.track_id is not None}

        for tid, first in self._first_seen.items():
            duration = now - first
            if duration >= self._threshold and tid not in self._alerted:
                det = det_by_id.get(tid)
                bbox = det.bbox if det else (0, 0, 0, 0)
                events.append(LoiteringEvent(
                    track_id=tid,
                    duration_seconds=round(duration, 1),
                    bbox=bbox,
                ))
                self._alerted.add(tid)
                logger.info(f"Loitering: track_id={tid} for {duration:.1f}s")

        return events
