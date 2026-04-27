"""
Campus Eye — Object Detector
YOLOv8s for general objects (people, phones, watches, papers) — preferred over YOLOv8n for accuracy.
YOLOv8n-pose for skeleton keypoints (talking / hand-interaction detection).
"""
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from app.config import get_settings, get_yaml_config

logger = logging.getLogger(__name__)

# COCO class IDs relevant to campus surveillance
COCO_CLASSES = {
    0:  "person",
    1:  "bicycle",
    2:  "car",
    3:  "motorcycle",
    24: "backpack",
    25: "umbrella",
    26: "handbag",
    28: "suitcase",
    39: "bottle",
    40: "wine glass",
    41: "cup",
    43: "knife",
    63: "laptop",
    67: "cell phone",
    73: "book",
    74: "clock",       # proxy for wristwatch / smartwatch
    75: "remote",      # proxy for any handheld electronic device
    76: "scissors",    # misc sharp / foreign object
}

# Items students are PROHIBITED from carrying into an exam hall.
EXAM_OBJECTS = {
    "cell phone",   # smartphones / mobiles
    "laptop",       # personal computers
    "clock",        # wristwatches / smartwatches
    "remote",       # handheld electronic devices
    "scissors",     # sharp objects
}
PAPER_CLASSES  = {"book"}                          # unauthorised books/notes
WEAPON_CLASSES = {"knife", "scissors"}             # sharp/dangerous on campus
VEHICLE_CLASSES = {"bicycle", "motorcycle", "car"}  # vehicles in pedestrian zone
ALCOHOL_CLASSES = {"bottle", "wine glass"}         # alcohol proxy
DRINK_CLASSES   = {"bottle", "wine glass", "cup"}  # food/drink in exam hall


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]   # x1, y1, x2, y2
    track_id: int | None = None


class ObjectDetector:
    """Wraps YOLOv8 for detection + ByteTrack tracking."""

    def __init__(self):
        self._model = None
        self._pose_model = None
        self._cfg = get_yaml_config().get("detection", {})
        self._conf = self._cfg.get("yolo_confidence", 0.45)
        self._model_dir = get_settings().model_dir

    def load(self):
        """Download (if needed) and load YOLOv8 weights.

        PyTorch 2.6+ changed torch.load to weights_only=True by default.
        Ultralytics .pt files embed arbitrary nn.Module subclasses that can't
        be fully pre-allowlisted, so we temporarily patch torch.load to use
        weights_only=False only for the duration of this call.  The checkpoint
        files come from Ultralytics' own CDN and are safe to load this way.
        """
        import torch
        from ultralytics import YOLO

        # ── Patch torch.load for weights_only compatibility ──────────────────
        _real_load = torch.load

        def _load_unsafe(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return _real_load(*args, **kwargs)

        torch.load = _load_unsafe
        try:
            # Prefer yolov8s (better accuracy) over yolov8n (faster)
            for det_name in ("yolov8s.pt", "yolov8n.pt"):
                det_path = self._model_dir / det_name
                if det_path.exists():
                    self._model = YOLO(str(det_path))
                    logger.info(f"✔ {det_name} loaded from {det_path}.")
                    break
            else:
                # Neither exists locally — let Ultralytics download yolov8s
                self._model = YOLO("yolov8s.pt")
                logger.info("✔ YOLOv8s downloaded and loaded.")

            pose_path = self._model_dir / "yolov8n-pose.pt"
            self._pose_model = YOLO(str(pose_path) if pose_path.exists() else "yolov8n-pose.pt")
            logger.info("✔ YOLOv8n-pose model loaded.")
        except Exception as e:
            logger.exception(
                f"⚠ YOLO model failed to load — OBJECT DETECTION DISABLED. "
                f"Phone/foreign-object detection will NOT work. Error: {e}"
            )
            self._model = None
        finally:
            # Always restore the original torch.load
            torch.load = _real_load

    def detect(
        self,
        frame: np.ndarray,
        track: bool = True,
        classes: list[int] | None = None,
    ) -> list[Detection]:
        """
        Run detection (+ optional ByteTrack tracking) on a frame.
        classes: COCO class IDs to filter (None = all).
        """
        if self._model is None:
            return []

        results = self._model.track(
            frame,
            persist=True,
            conf=self._conf,
            classes=classes,
            tracker="bytetrack.yaml",
            verbose=False,
        ) if track else self._model(frame, conf=self._conf, classes=classes, verbose=False)

        detections: list[Detection] = []
        for r in results:
            boxes = r.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                cls_name = self._model.names.get(cls_id, str(cls_id))
                conf = float(box.conf[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                track_id = int(box.id[0]) if box.id is not None else None
                detections.append(Detection(
                    class_name=cls_name,
                    confidence=conf,
                    bbox=(x1, y1, x2, y2),
                    track_id=track_id,
                ))
        return detections

    def detect_persons(self, frame: np.ndarray) -> list[Detection]:
        return [d for d in self.detect(frame, classes=[0]) if d.class_name == "person"]

    def detect_exam_objects(self, frame: np.ndarray, conf: float | None = None) -> list[Detection]:
        """
        Detect objects prohibited in exam mode.
        Includes: phones, laptops, clocks/watches, remote/electronic devices,
        scissors, and unauthorised books/papers.
        Uses a lower confidence threshold than normal mode for better recall.
        """
        effective_conf = conf if conf is not None else self._conf
        if self._model is None:
            return []

        # COCO class IDs corresponding to EXAM_OBJECTS | PAPER_CLASSES
        # 63=laptop, 67=cell phone, 73=book, 74=clock, 75=remote, 76=scissors
        exam_class_ids = [63, 67, 73, 74, 75, 76]

        results = self._model(
            frame,
            conf=effective_conf,
            classes=exam_class_ids,
            verbose=False,
        )
        detections: list[Detection] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                cls_id = int(box.cls[0])
                cls_name = self._model.names.get(cls_id, str(cls_id))
                conf_score = float(box.conf[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                detections.append(Detection(
                    class_name=cls_name,
                    confidence=conf_score,
                    bbox=(x1, y1, x2, y2),
                ))

        exam_hits = [d for d in detections if d.class_name in EXAM_OBJECTS | PAPER_CLASSES]
        if exam_hits:
            logger.info(
                f"[EXAM] Prohibited item(s) detected: "
                f"{[(d.class_name, f'{d.confidence:.0%}') for d in exam_hits]}"
            )
        return exam_hits

    def get_pose_keypoints(self, frame: np.ndarray) -> list[dict]:
        """
        Return pose keypoints per detected person.
        Each item: {track_id, keypoints: np.ndarray shape (17, 3)}
        """
        if self._pose_model is None:
            return []
        results = self._pose_model(frame, verbose=False)
        out = []
        for r in results:
            if r.keypoints is None:
                continue
            for i, kp in enumerate(r.keypoints.data):
                out.append({"track_id": i, "keypoints": kp.cpu().numpy()})
        return out

    def detect_normal_threats(
        self,
        frame: np.ndarray,
        conf: float | None = None,
    ) -> list[Detection]:
        """
        Detect normal-mode threats: weapons (knives/scissors),
        vehicles in pedestrian areas, and alcohol.
        Returns detections tagged with class_name for the analyzer to triage.
        """
        if self._model is None:
            return []
        effective_conf = conf if conf is not None else self._conf
        # 1=bicycle, 2=car, 3=motorcycle, 39=bottle, 40=wine glass, 43=knife, 76=scissors
        threat_ids = [1, 2, 3, 39, 40, 43, 76]
        results = self._model(frame, conf=effective_conf, classes=threat_ids, verbose=False)
        detections: list[Detection] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                cls_id  = int(box.cls[0])
                cls_name = self._model.names.get(cls_id, str(cls_id))
                conf_score = float(box.conf[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                detections.append(Detection(
                    class_name=cls_name,
                    confidence=conf_score,
                    bbox=(x1, y1, x2, y2),
                ))
        return detections

    def detect_drink_in_exam(
        self,
        frame: np.ndarray,
        conf: float | None = None,
    ) -> list[Detection]:
        """Detect food/drink items brought into the exam hall."""
        if self._model is None:
            return []
        effective_conf = conf if conf is not None else self._conf
        # 39=bottle, 40=wine glass, 41=cup
        results = self._model(frame, conf=effective_conf, classes=[39, 40, 41], verbose=False)
        detections: list[Detection] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                cls_id  = int(box.cls[0])
                cls_name = self._model.names.get(cls_id, str(cls_id))
                conf_score = float(box.conf[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                detections.append(Detection(
                    class_name=cls_name,
                    confidence=conf_score,
                    bbox=(x1, y1, x2, y2),
                ))
        return [d for d in detections if d.class_name in DRINK_CLASSES]


def get_object_detector() -> ObjectDetector:
    detector = ObjectDetector()
    detector.load()
    return detector
