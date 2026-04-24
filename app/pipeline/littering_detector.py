"""
Campus Eye — Littering Detector
Tracks unattended objects (bags, bottles, etc.) that appear near a previous
person location and remain stationary without a nearby person for a configurable
number of seconds. Approximates littering / abandoned object scenarios.
"""
import logging
import time
from dataclasses import dataclass, field

import numpy as np

from app.config import get_yaml_config

logger = logging.getLogger(__name__)

# COCO class IDs to watch for as potential litter / abandoned objects
LITTER_CLASSES = {
    24: "backpack",
    25: "umbrella",
    26: "handbag",
    28: "suitcase",
    39: "bottle",
    40: "wine glass",
    41: "cup",
    67: "cell phone",
}


@dataclass
class LitterEvent:
    track_key: str       # "{class_name}_{cx}_{cy}" stable key
    class_name: str
    bbox: tuple[int, int, int, int]
    seconds_unattended: float


class LitteringDetector:
    """
    Tracks objects that appear without a nearby person for N seconds.
    Uses a centroid-based 'sticky' track: if an object centroid stays within
    `_move_tolerance` pixels, it is considered the same object.
    """

    def __init__(self):
        cfg = get_yaml_config().get("detection", {})
        self._threshold: float = cfg.get("littering_threshold_seconds", 20.0)
        self._move_tol: int = 40   # pixels — if centroid moves < this, same object
        # track_key → {first_seen, centroid, bbox, class_name}
        self._tracks: dict[str, dict] = {}

    def update(
        self,
        objects: list,            # list[Detection] with class_name & bbox
        persons: list,            # list[Detection] — persons in frame
    ) -> list[LitterEvent]:
        """
        Call once per frame. Returns LitterEvents for newly-threshold-crossed tracks.
        """
        now = time.monotonic()
        events: list[LitterEvent] = []

        # Collect person centroids
        person_centroids = [
            self._centroid(p.bbox) for p in persons
        ]

        # Filter to litter-candidate objects
        candidates = [o for o in objects if o.class_name in LITTER_CLASSES.values()]

        # Match candidates to existing tracks (nearest centroid)
        matched_keys: set[str] = set()
        for obj in candidates:
            cx, cy = self._centroid(obj.bbox)
            matched_key = self._find_track(cx, cy)

            if matched_key:
                track = self._tracks[matched_key]
                track["centroid"] = (cx, cy)
                track["bbox"] = obj.bbox
            else:
                matched_key = f"{obj.class_name}_{cx}_{cy}"
                self._tracks[matched_key] = {
                    "first_seen": now,
                    "centroid": (cx, cy),
                    "bbox": obj.bbox,
                    "class_name": obj.class_name,
                }
            matched_keys.add(matched_key)

        # Remove tracks for objects no longer visible
        stale = [k for k in self._tracks if k not in matched_keys]
        for k in stale:
            del self._tracks[k]

        # Fire events for tracks with no nearby person exceeding threshold
        for key, track in self._tracks.items():
            cx, cy = track["centroid"]
            near_person = any(
                abs(px - cx) < 120 and abs(py - cy) < 120
                for px, py in person_centroids
            )
            if near_person:
                # Reset clock while a person is nearby
                track["first_seen"] = now
                continue

            unattended = now - track["first_seen"]
            if unattended >= self._threshold:
                events.append(LitterEvent(
                    track_key=key,
                    class_name=track["class_name"],
                    bbox=track["bbox"],
                    seconds_unattended=round(unattended, 1),
                ))
                # Reset so we don't spam
                track["first_seen"] = now

        return events

    def _find_track(self, cx: int, cy: int) -> str | None:
        for key, track in self._tracks.items():
            tx, ty = track["centroid"]
            if abs(tx - cx) <= self._move_tol and abs(ty - cy) <= self._move_tol:
                return key
        return None

    @staticmethod
    def _centroid(bbox: tuple) -> tuple[int, int]:
        x1, y1, x2, y2 = bbox
        return (x1 + x2) // 2, (y1 + y2) // 2
