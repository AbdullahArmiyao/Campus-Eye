"""
Campus Eye — Talking Detector
Flags pairs of students whose face centres are within a configurable pixel
distance for a configurable number of consecutive frames.
Used in exam mode to detect students who may be communicating verbally.
"""
import logging
from collections import defaultdict
from dataclasses import dataclass

from app.config import get_yaml_config

logger = logging.getLogger(__name__)


@dataclass
class TalkingEvent:
    face_a_idx: int
    face_b_idx: int
    distance_px: float
    consecutive_frames: int


class TalkingDetector:
    """
    Tracks pairs of faces by index.
    Fires a TalkingEvent when two faces stay within `proximity_px` pixels
    for at least `frame_threshold` consecutive frames.
    """

    def __init__(self):
        cfg = get_yaml_config().get("detection", {})
        self._proximity_px: int = cfg.get("talking_proximity_px", 120)
        self._frame_threshold: int = cfg.get("talking_frames", 15)
        # (i, j) → consecutive close frames
        self._close_counts: dict[tuple, int] = defaultdict(int)

    def update(self, faces: list[dict]) -> list[TalkingEvent]:
        """
        faces: list of dicts with 'bbox' key — from FaceRecognizer.detect_faces().
        Returns TalkingEvents for pairs that have been close long enough.
        """
        events: list[TalkingEvent] = []
        if len(faces) < 2:
            self._close_counts.clear()
            return events

        # Compute face centroids
        centroids = []
        for f in faces:
            x1, y1, x2, y2 = f["bbox"]
            centroids.append(((x1 + x2) // 2, (y1 + y2) // 2))

        # Pairwise distance check
        active_pairs: set[tuple] = set()
        for i in range(len(centroids)):
            for j in range(i + 1, len(centroids)):
                ax, ay = centroids[i]
                bx, by = centroids[j]
                dist = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
                pair = (i, j)
                if dist <= self._proximity_px:
                    self._close_counts[pair] += 1
                    active_pairs.add(pair)
                    if self._close_counts[pair] >= self._frame_threshold:
                        events.append(TalkingEvent(
                            face_a_idx=i,
                            face_b_idx=j,
                            distance_px=round(dist, 1),
                            consecutive_frames=self._close_counts[pair],
                        ))
                        self._close_counts[pair] = 0  # reset after firing
                else:
                    self._close_counts[pair] = 0

        # Prune stale pairs
        stale = [p for p in self._close_counts if p not in active_pairs]
        for p in stale:
            del self._close_counts[p]

        return events
