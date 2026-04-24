"""
Campus Eye — Head Tracker (MediaPipe)
Detects head pose (yaw angle) per person using MediaPipe Face Mesh.
Fires a head-swiveling event when yaw exceeds threshold for N frames.
"""
import logging
from collections import defaultdict
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.config import get_yaml_config

logger = logging.getLogger(__name__)


@dataclass
class HeadEvent:
    track_id: int
    yaw_deg: float
    direction: str          # "left" | "right" | "center"
    consecutive_frames: int


class HeadTracker:
    """
    Tracks head yaw angle for each detected person.
    Uses MediaPipe Face Mesh to estimate 3-D head pose.
    """

    def __init__(self):
        self._face_mesh = None
        cfg = get_yaml_config().get("detection", {})
        self._yaw_threshold: float = cfg.get("head_swivel_yaw_degrees", 25.0)
        self._frame_threshold: int = cfg.get("head_swivel_frames", 10)
        # track_id → consecutive frames outside threshold
        self._swivel_counts: dict[int, int] = defaultdict(int)

    def load(self):
        """Initialise MediaPipe Face Mesh. Disables gracefully if unavailable."""
        self._face_mesh = None
        try:
            self._load_solutions()
            logger.info("MediaPipe FaceMesh loaded successfully.")
        except Exception as e:
            logger.warning(
                f"MediaPipe head tracking unavailable ({e}). "
                "To enable, run: pip install 'mediapipe<=0.10.9' --break-system-packages"
            )

    def _load_solutions(self):
        """Standard API: mp.solutions.face_mesh."""
        import mediapipe as mp
        # AttributeError raised on versions that removed solutions
        solutions = mp.solutions
        self._face_mesh = solutions.face_mesh.FaceMesh(
            max_num_faces=10,
            refine_landmarks=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def process_frame(self, frame: np.ndarray) -> list[HeadEvent]:
        """
        Process a BGR frame and return HeadEvents for persons exceeding
        the swivel angle threshold for enough consecutive frames.
        """
        if self._face_mesh is None:
            return []

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._face_mesh.process(rgb)
        events: list[HeadEvent] = []

        if not results.multi_face_landmarks:
            return events

        h, w = frame.shape[:2]

        for idx, landmarks in enumerate(results.multi_face_landmarks):
            yaw = self._estimate_yaw(landmarks, w, h)
            direction = "center"
            if yaw > self._yaw_threshold:
                direction = "right"
            elif yaw < -self._yaw_threshold:
                direction = "left"

            if direction != "center":
                self._swivel_counts[idx] += 1
            else:
                self._swivel_counts[idx] = 0

            if self._swivel_counts[idx] >= self._frame_threshold:
                events.append(HeadEvent(
                    track_id=idx,
                    yaw_deg=round(yaw, 1),
                    direction=direction,
                    consecutive_frames=self._swivel_counts[idx],
                ))
                self._swivel_counts[idx] = 0   # reset after firing

        return events

    @staticmethod
    def _estimate_yaw(landmarks, img_w: int, img_h: int) -> float:
        """
        Estimate head yaw using the horizontal offset between nose tip
        and the midpoint of the two ear landmarks.
        Returns yaw in degrees (positive = right, negative = left).
        """
        # MediaPipe landmark indices
        NOSE_TIP = 1
        LEFT_EAR = 234
        RIGHT_EAR = 454

        def lm(i):
            p = landmarks.landmark[i]
            return np.array([p.x * img_w, p.y * img_h])

        nose = lm(NOSE_TIP)
        mid_ear = (lm(LEFT_EAR) + lm(RIGHT_EAR)) / 2
        face_width = np.linalg.norm(lm(LEFT_EAR) - lm(RIGHT_EAR)) + 1e-6

        offset = (nose[0] - mid_ear[0]) / face_width
        yaw_deg = offset * 90.0       # rough linear mapping
        return yaw_deg
