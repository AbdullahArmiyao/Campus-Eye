"""
Campus Eye — Behavior Analyzer
Orchestrates per-frame behavioral analysis for both Normal and Exam modes.
Returns a list of DetectedEvent objects to be persisted and dispatched.
"""
import logging
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from app.config import get_yaml_config
from app.pipeline.loitering_detector import LoiteringDetector
from app.pipeline.littering_detector import LitteringDetector
from app.pipeline.talking_detector import TalkingDetector
from app.pipeline.object_detector import (
    Detection,
    WEAPON_CLASSES,
    VEHICLE_CLASSES,
    ALCOHOL_CLASSES,
    DRINK_CLASSES,
)

logger = logging.getLogger(__name__)

# Maps YOLO COCO class names → human-readable alert labels shown in alerts / DB.
# Covers every item in EXAM_OBJECTS | PAPER_CLASSES from object_detector.py.
_OBJECT_LABELS: dict[str, str] = {
    # Prohibited electronics
    "cell phone":   "Mobile phone / smartphone",
    "phone":        "Mobile phone / smartphone",
    "laptop":       "Laptop computer",
    "remote":       "Handheld electronic device (calculator / remote / pager)",
    "clock":        "Wristwatch / smartwatch",
    # Unauthorised reading materials
    "book":         "Unauthorised book / printed notes / paper",
    # Sharp / dangerous objects
    "scissors":     "Scissors / sharp object",
    "knife":        "Knife / bladed weapon",
    # Bags — flagged as potential concealment
    "backpack":     "Backpack (potential concealment risk)",
    "handbag":      "Handbag (potential concealment risk)",
    "suitcase":     "Suitcase / large bag",
    # Vehicles
    "bicycle":      "Bicycle in pedestrian zone",
    "motorcycle":   "Motorcycle in pedestrian zone",
    "car":          "Vehicle in pedestrian zone",
    # Alcohol / food
    "bottle":       "Bottle (possible alcohol or prohibited drink)",
    "wine glass":   "Wine glass / alcohol",
    "cup":          "Cup / drink in exam hall",
}


@dataclass
class DetectedEvent:
    event_type: str          # matches models.EventType values
    description: str
    bbox: tuple[int, int, int, int] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class BehaviorAnalyzer:
    """
    Combines outputs from detectors into structured DetectedEvents.
    Call analyze() once per frame with all detection outputs.
    """

    def __init__(self):
        self._cfg = get_yaml_config()
        self._norm_cfg = self._cfg.get("normal_mode", {})
        self._exam_cfg = self._cfg.get("exam_mode", {})
        det_cfg = self._cfg.get("detection", {})
        self._motion_threshold: float = det_cfg.get("motion_vandalism_threshold", 0.15)
        self._proximity_iou: float = det_cfg.get("proximity_overlap_iou", 0.05)

        self._loitering = LoiteringDetector()
        self._littering = LitteringDetector()
        self._talking   = TalkingDetector()
        self._prev_gray: np.ndarray | None = None

    # ── Public ────────────────────────────────────────────────────────────────

    def analyze_normal(
        self,
        frame: np.ndarray,
        persons: list[Detection],
        all_detections: list[Detection],
        unknown_faces: list[dict],
        head_events: list,
        threat_detections: list[Detection] | None = None,
    ) -> list[DetectedEvent]:
        """Run normal-mode analysis pipeline."""
        events: list[DetectedEvent] = []

        if self._norm_cfg.get("detect_loitering", True):
            for ev in self._loitering.update(persons):
                events.append(DetectedEvent(
                    event_type="loitering",
                    description=f"Person has been loitering for {ev.duration_seconds}s in the same area (track #{ev.track_id}).",
                    bbox=ev.bbox,
                    meta={"track_id": ev.track_id, "duration": ev.duration_seconds},
                ))

        if self._norm_cfg.get("detect_littering", True):
            for ev in self._littering.update(all_detections, persons):
                events.append(DetectedEvent(
                    event_type="littering",
                    description=f"Unattended {ev.class_name} detected for {ev.seconds_unattended}s with no person nearby — possible littering or abandoned item.",
                    bbox=ev.bbox,
                    meta={"object": ev.class_name, "seconds": ev.seconds_unattended},
                ))

        if self._norm_cfg.get("detect_unknown_faces", True):
            for uf in unknown_faces:
                score = uf.get("det_score", 0)
                events.append(DetectedEvent(
                    event_type="unknown_face",
                    description=f"Unrecognised person detected (face confidence {score:.0%}). Not in the registered face database.",
                    bbox=uf.get("bbox"),
                    meta={"det_score": score},
                ))

        if self._norm_cfg.get("detect_vandalism", True):
            if self._detect_vandalism(frame):
                events.append(DetectedEvent(
                    event_type="vandalism",
                    description="High-motion event detected — possible vandalism, fighting, or rapid movement in frame.",
                ))

        # ── New normal-mode detections ─────────────────────────────────────
        if threat_detections:
            if self._norm_cfg.get("detect_weapons", True):
                for d in threat_detections:
                    if d.class_name in WEAPON_CLASSES:
                        label = _OBJECT_LABELS.get(d.class_name, d.class_name)
                        logger.warning(f"[WEAPON] {label} detected ({d.confidence:.0%})")
                        events.append(DetectedEvent(
                            event_type="weapon",
                            description=f"⚠ {label} detected on campus (confidence {d.confidence:.0%}). Immediate security review required.",
                            bbox=d.bbox,
                            meta={"object": d.class_name, "confidence": d.confidence},
                        ))

            if self._norm_cfg.get("detect_vehicle_intrusion", True):
                for d in threat_detections:
                    if d.class_name in VEHICLE_CLASSES:
                        label = _OBJECT_LABELS.get(d.class_name, d.class_name)
                        logger.info(f"[VEHICLE] {label} ({d.confidence:.0%})")
                        events.append(DetectedEvent(
                            event_type="vehicle_intrusion",
                            description=f"{label} detected in a pedestrian zone (confidence {d.confidence:.0%}).",
                            bbox=d.bbox,
                            meta={"object": d.class_name, "confidence": d.confidence},
                        ))

            if self._norm_cfg.get("detect_alcohol", True):
                for d in threat_detections:
                    if d.class_name in ALCOHOL_CLASSES:
                        label = _OBJECT_LABELS.get(d.class_name, d.class_name)
                        logger.info(f"[ALCOHOL] {label} ({d.confidence:.0%})")
                        events.append(DetectedEvent(
                            event_type="alcohol",
                            description=f"{label} detected on campus premises (confidence {d.confidence:.0%}). Possible alcohol policy violation.",
                            bbox=d.bbox,
                            meta={"object": d.class_name, "confidence": d.confidence},
                        ))

        if self._norm_cfg.get("detect_overcrowding", True):
            threshold = self._norm_cfg.get("overcrowding_threshold", 10)
            if len(persons) >= threshold:
                logger.info(f"[OVERCROWDING] {len(persons)} persons detected (threshold={threshold})")
                events.append(DetectedEvent(
                    event_type="overcrowding",
                    description=f"{len(persons)} people detected in frame — exceeds the overcrowding threshold of {threshold}.",
                    meta={"count": len(persons), "threshold": threshold},
                ))

        return events

    def analyze_exam(
        self,
        frame: np.ndarray,
        persons: list[Detection],
        exam_objects: list[Detection],
        raw_faces: list[dict],
        head_events: list,
        invigilator_bboxes: list[tuple],
        drink_detections: list[Detection] | None = None,
    ) -> list[DetectedEvent]:
        """Run exam-mode analysis pipeline (skips invigilators)."""
        events: list[DetectedEvent] = []

        if self._exam_cfg.get("detect_phones", True) or self._exam_cfg.get("detect_foreign_papers", True):
            for obj in exam_objects:
                if not self._is_near_invigilator(obj.bbox, invigilator_bboxes):
                    label = _OBJECT_LABELS.get(obj.class_name, obj.class_name)
                    events.append(DetectedEvent(
                        event_type="foreign_object",
                        description=f"⚠ {label} detected during exam (confidence {obj.confidence:.0%}). Possible academic dishonesty.",
                        bbox=obj.bbox,
                        meta={"object": obj.class_name, "label": label, "confidence": obj.confidence},
                    ))

        if self._exam_cfg.get("detect_head_swiveling", True):
            for he in head_events:
                direction = "left" if he.yaw_deg < 0 else "right"
                events.append(DetectedEvent(
                    event_type="head_swiveling",
                    description=f"Student repeatedly turning head {direction} ({abs(he.yaw_deg):.0f}°) — possible attempt to view another student's work.",
                    meta={"yaw": he.yaw_deg, "direction": direction, "frames": he.consecutive_frames},
                ))

        if self._exam_cfg.get("detect_talking", True):
            student_faces = [
                f for f in raw_faces
                if not self._is_near_invigilator(tuple(int(x) for x in f["bbox"]), invigilator_bboxes)
            ]
            for ev in self._talking.update(student_faces):
                events.append(DetectedEvent(
                    event_type="talking",
                    description=f"Two students detected within {ev.distance_px:.0f}px of each other for {ev.consecutive_frames} frames — possible verbal communication during exam.",
                    meta={"distance_px": ev.distance_px, "face_a": ev.face_a_idx, "face_b": ev.face_b_idx},
                ))

        if self._exam_cfg.get("detect_hand_interaction", True):
            for ev in self._detect_hand_interactions(persons, invigilator_bboxes):
                events.append(ev)

        # ── New exam-mode detections ───────────────────────────────────────
        if self._exam_cfg.get("detect_drink", True) and drink_detections:
            for d in drink_detections:
                if not self._is_near_invigilator(d.bbox, invigilator_bboxes):
                    label = _OBJECT_LABELS.get(d.class_name, d.class_name)
                    logger.info(f"[DRINK] {label} in exam hall ({d.confidence:.0%})")
                    events.append(DetectedEvent(
                        event_type="drink_in_exam",
                        description=f"{label} detected in exam hall (confidence {d.confidence:.0%}). Food and drink are not permitted during exams.",
                        bbox=d.bbox,
                        meta={"object": d.class_name, "confidence": d.confidence},
                    ))

        if self._exam_cfg.get("detect_crowd_cheat", True):
            threshold = self._exam_cfg.get("crowd_cheat_threshold", 3)
            students = [p for p in persons if not self._is_near_invigilator(p.bbox, invigilator_bboxes)]
            clusters = self._find_person_clusters(students, iou_threshold=0.01)
            for cluster in clusters:
                if len(cluster) >= threshold:
                    logger.info(f"[CROWD_CHEAT] Cluster of {len(cluster)} students huddled together")
                    events.append(DetectedEvent(
                        event_type="crowd_cheat",
                        description=f"Cluster of {len(cluster)} students detected in close proximity during exam — possible coordinated cheating.",
                        meta={"cluster_size": len(cluster)},
                    ))

        return events


    # ── Internal helpers ──────────────────────────────────────────────────────

    def _detect_vandalism(self, frame: np.ndarray) -> bool:
        """Optical flow magnitude spike → possible vandalism."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self._prev_gray is None or self._prev_gray.shape != gray.shape:
            # First frame, or source changed resolution — reset baseline
            self._prev_gray = gray
            return False
        flow = cv2.calcOpticalFlowFarneback(
            self._prev_gray, gray, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )
        mag = np.mean(np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2))
        self._prev_gray = gray
        return float(mag) > self._motion_threshold * 50


    def _detect_hand_interactions(
        self,
        persons: list[Detection],
        invigilator_bboxes: list[tuple],
    ) -> list[DetectedEvent]:
        """Flag pairs of students whose bounding boxes overlap (hand-to-hand passing)."""
        events = []
        students = [p for p in persons if not self._is_near_invigilator(p.bbox, invigilator_bboxes)]
        for i in range(len(students)):
            for j in range(i + 1, len(students)):
                iou = self._compute_iou(students[i].bbox, students[j].bbox)
                if iou > self._proximity_iou:
                    events.append(DetectedEvent(
                        event_type="hand_interaction",
                        description=f"Possible hand-to-hand interaction between tracks "
                                    f"#{students[i].track_id} and #{students[j].track_id}.",
                        meta={"iou": round(iou, 3)},
                    ))
        return events

    @staticmethod
    def _compute_iou(a: tuple, b: tuple) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        return inter / (area_a + area_b - inter + 1e-6)

    @staticmethod
    def _is_near_invigilator(bbox: tuple, inv_bboxes: list[tuple], margin: int = 30) -> bool:
        """Check if a bbox is close to any invigilator bbox."""
        x1, y1, x2, y2 = bbox
        for ix1, iy1, ix2, iy2 in inv_bboxes:
            if (x1 < ix2 + margin and x2 > ix1 - margin and
                    y1 < iy2 + margin and y2 > iy1 - margin):
                return True
        return False

    @staticmethod
    def _find_person_clusters(
        persons: list[Detection],
        iou_threshold: float = 0.01,
    ) -> list[list[Detection]]:
        """
        Group persons into clusters where any two members are within
        iou_threshold of each other (proximity, not overlap).
        Uses a simple greedy union-find approach.
        """
        if not persons:
            return []
        n = len(persons)
        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i: int, j: int):
            parent[find(i)] = find(j)

        for i in range(n):
            for j in range(i + 1, n):
                ax1, ay1, ax2, ay2 = persons[i].bbox
                bx1, by1, bx2, by2 = persons[j].bbox
                ix1, iy1 = max(ax1, bx1), max(ay1, by1)
                ix2, iy2 = min(ax2, bx2), min(ay2, by2)
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
                area_b = max(1, (bx2 - bx1) * (by2 - by1))
                iou = inter / (area_a + area_b - inter + 1e-6)
                if iou > iou_threshold:
                    union(i, j)

        from collections import defaultdict
        groups: dict[int, list[Detection]] = defaultdict(list)
        for i, p in enumerate(persons):
            groups[find(i)].append(p)
        return [g for g in groups.values() if len(g) > 1]
