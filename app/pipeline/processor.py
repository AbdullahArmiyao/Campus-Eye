"""
Campus Eye — Frame Processor
Main async loop: pull frames → detect → annotate → dispatch alerts.
Runs as a background asyncio task started at app startup.
"""
import asyncio
import json
import logging
import time
from datetime import datetime

import cv2
import numpy as np

from app.config import get_settings, get_yaml_config
from app.database import AsyncSessionLocal
from app.models import Event, Setting, SystemMode
from app.pipeline.behavior_analyzer import BehaviorAnalyzer, DetectedEvent
from app.pipeline.clip_recorder import ClipRecorder
from app.pipeline.face_recognition import get_face_recognizer
from app.pipeline.head_tracker import HeadTracker
from app.pipeline.object_detector import get_object_detector
from app.pipeline.schedule_enforcer import ScheduleEnforcer
from app.pipeline.video_capture import VideoCapture
from app.utils.snapshot import save_snapshot

logger = logging.getLogger(__name__)

# Colours for annotation overlays
COLOURS = {
    "person":         (0,   200, 0),
    "unknown_face":   (0,   0,   255),
    "invigilator":    (255, 165, 0),
    "foreign_object": (0,   0,   200),
    "alert":          (0,   0,   255),
}


class FrameProcessor:
    """
    Async frame-processing loop.
    Designed to run as a long-lived asyncio Task.
    """

    def __init__(self):
        settings = get_settings()
        self._settings = settings
        self._yaml = get_yaml_config()

        self._capture = VideoCapture()
        self._detector = get_object_detector()
        self._recognizer = get_face_recognizer()
        self._head_tracker = HeadTracker()
        self._analyzer = BehaviorAnalyzer()
        self._schedule = ScheduleEnforcer()
        self._clip_recorder = ClipRecorder()

        self.latest_frame: np.ndarray | None = None
        self._running = False
        # Run detection at process_fps, stream at a higher rate (handled by WebSocket router)
        proc_fps = self._yaml.get("processing", {}).get("process_fps", 10)
        self._process_interval = 1.0 / max(proc_fps, 1)

        # Embedding cache
        self._embedding_cache: list[dict] = []
        self._cache_refresh_interval = 30
        self._last_cache_refresh = 0.0

        # Mode cache (avoid DB hit every frame)
        self._cached_mode: str = self._yaml.get("mode", {}).get("current", "normal")
        self._mode_refresh_interval = 5.0   # seconds
        self._last_mode_refresh = 0.0

        # Exam-mode detection confidence
        det_cfg = self._yaml.get("detection", {})
        self._exam_conf: float = det_cfg.get("exam_confidence", 0.25)

        # Per-event-type cooldown
        self._cooldown_seconds: int = 60
        self._last_alert_time: dict[str, float] = {}
        self._last_mode: str | None = None

    # ── Public ────────────────────────────────────────────────────────────────

    async def run(self):
        """Main processing loop — called as an asyncio Task."""
        self._running = True
        self._capture.start()
        self._head_tracker.load()
        logger.info("FrameProcessor: pipeline online.")

        while self._running:
            loop_start = time.monotonic()

            frame = self._capture.get_frame()
            if frame is None:
                await asyncio.sleep(0.1)
                continue

            try:
                await self._process_frame(frame)
            except Exception as e:
                logger.exception(f"FrameProcessor error: {e}")

            elapsed = time.monotonic() - loop_start
            await asyncio.sleep(max(0.0, self._process_interval - elapsed))

    def stop(self):
        self._running = False
        self._capture.stop()

    def set_source(self, url: str):
        """Switch the live video source (RTSP URL, file path, or webcam index)."""
        self._capture.set_source(url)

    @property
    def current_source(self) -> str:
        return self._capture.current_source

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _get_mode_cached(self) -> str:
        """Return cached mode string, refreshing from DB every 5s."""
        now = time.monotonic()
        if now - self._last_mode_refresh < self._mode_refresh_interval:
            return self._cached_mode

        self._last_mode_refresh = now

        # Schedule enforcement: if a schedule says we should be in exam, override
        should_enforce, scheduled_mode = self._schedule.should_override()
        if should_enforce:
            # Write back to DB so API reflects schedule
            async with AsyncSessionLocal() as db:
                row = await db.get(Setting, "system_mode")
                if row is None or row.value != scheduled_mode:
                    if row is None:
                        from app.models import Setting as SettingModel
                        row = SettingModel(key="system_mode", value=scheduled_mode)
                        db.add(row)
                    else:
                        row.value = scheduled_mode
                    await db.commit()
                    logger.info(f"[SCHEDULE] Mode auto-set to {scheduled_mode.upper()}")
            self._cached_mode = scheduled_mode
            return self._cached_mode

        # Read from DB
        try:
            async with AsyncSessionLocal() as db:
                row = await db.get(Setting, "system_mode")
                if row:
                    self._cached_mode = row.value
        except Exception as e:
            logger.warning(f"Mode refresh failed: {e} — using cached '{self._cached_mode}'")

        return self._cached_mode

    async def _refresh_embedding_cache(self):
        """Reload face embeddings from DB into memory."""
        from sqlalchemy import select
        from app.models import FaceEmbedding, User
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(FaceEmbedding, User)
                .join(User, FaceEmbedding.user_id == User.id)
            )
            rows = result.all()
        self._embedding_cache = [
            {
                "embedding_id": emb.id,
                "user_id": user.id,
                "name": user.name,
                "role": user.role.value if hasattr(user.role, "value") else user.role,
                "embedding": emb.embedding,
            }
            for emb, user in rows
        ]
        logger.debug(f"Embedding cache refreshed: {len(self._embedding_cache)} faces.")

    async def _process_frame(self, frame: np.ndarray):
        now = time.monotonic()

        # Refresh embedding cache periodically
        if now - self._last_cache_refresh > self._cache_refresh_interval:
            await self._refresh_embedding_cache()
            self._last_cache_refresh = now

        mode_str = await self._get_mode_cached()
        try:
            mode = SystemMode(mode_str)
        except ValueError:
            mode = SystemMode.normal
        annotated = frame.copy()

        # Feed raw frame into clip recorder buffer
        self._clip_recorder.push_frame(frame)

        # ── Object detection ─────────────────────────────────────────────────────
        # Run YOLO once and derive both all_detections and persons from it.
        # In exam mode we only need persons (exam objects are fetched separately below).
        if mode == SystemMode.normal:
            all_detections = self._detector.detect(frame)
            persons = [d for d in all_detections if d.class_name == "person"]
            threat_detections = self._detector.detect_normal_threats(frame)
        else:
            # Exam mode: only track persons for crowd/invigilator context
            persons = self._detector.detect_persons(frame)
            all_detections = persons   # unused in exam path
            threat_detections = []

        # ── Face recognition ───────────────────────────────────────────────
        raw_faces = await asyncio.get_running_loop().run_in_executor(
            None, self._recognizer.detect_faces, frame
        )

        recognized: list[dict] = []
        unknown_faces: list[dict] = []
        invigilator_bboxes: list[tuple] = []

        for face in raw_faces:
            emb = face["embedding"]
            match = self._recognizer.match_embedding(emb, self._embedding_cache)

            x1, y1, x2, y2 = face["bbox"]
            if match:
                match.bbox = (x1, y1, x2, y2)
                recognized.append({
                    "name": match.name,
                    "role": match.role,
                    "user_id": match.user_id,
                    "bbox": match.bbox,
                    "confidence": match.confidence,
                })
                if match.role == "invigilator":
                    invigilator_bboxes.append(match.bbox)
                color = COLOURS["invigilator"] if match.role == "invigilator" else COLOURS["person"]
                self._draw_box(annotated, match.bbox, f"{match.name} ({match.role})", color)
            else:
                unknown_faces.append({"bbox": (x1, y1, x2, y2), "det_score": face["det_score"]})
                self._draw_box(annotated, (x1, y1, x2, y2), "Unknown", COLOURS["unknown_face"])

        # ── Head tracking ──────────────────────────────────────────────────
        head_events = await asyncio.get_running_loop().run_in_executor(
            None, self._head_tracker.process_frame, frame
        )

        # ── Behavioral analysis ────────────────────────────────────────────
        if mode == SystemMode.normal:
            behavior_events = self._analyzer.analyze_normal(
                frame, persons, all_detections, unknown_faces, head_events,
                threat_detections=threat_detections,
            )
        else:
            # Use lower exam confidence for better phone/book sensitivity
            exam_objects = self._detector.detect_exam_objects(frame, conf=self._exam_conf)
            drink_detections = self._detector.detect_drink_in_exam(frame, conf=self._exam_conf)
            for obj in exam_objects:
                self._draw_box(annotated, obj.bbox, obj.class_name, COLOURS["foreign_object"])
            for d in drink_detections:
                self._draw_box(annotated, d.bbox, d.class_name, COLOURS["foreign_object"])
            behavior_events = self._analyzer.analyze_exam(
                frame, persons, exam_objects, raw_faces, head_events, invigilator_bboxes,
                drink_detections=drink_detections,
            )

        # ── Log mode on change ─────────────────────────────────────────────
        if mode.value != self._last_mode:
            logger.info(f"[MODE] Now operating in {mode.value.upper()} mode")
            self._last_mode = mode.value

        # ── Persist + dispatch alerts (with per-type cooldown) ────────────
        now_t = time.monotonic()
        for ev in behavior_events:
            last = self._last_alert_time.get(ev.event_type, 0.0)
            if now_t - last < self._cooldown_seconds:
                logger.debug(f"[COOLDOWN] Suppressed {ev.event_type} ({now_t - last:.0f}s ago)")
                continue
            self._last_alert_time[ev.event_type] = now_t
            snapshot_path = save_snapshot(annotated, ev.event_type)
            clip_path = self._clip_recorder.trigger(ev.event_type)
            await self._persist_event(ev, mode, snapshot_path, clip_path)

        # ── Mode badge overlay ─────────────────────────────────────────────
        self._draw_mode_badge(annotated, mode)
        self.latest_frame = annotated

    async def _persist_event(self, ev: DetectedEvent, mode: SystemMode, snapshot_path: str, clip_path: str | None = None):
        """Save event to DB and push alert via Celery + WebSocket."""
        try:
            from app.models import EventType
            EventType(ev.event_type)   # validate
        except ValueError:
            logger.warning(f"Unknown event type: {ev.event_type}")
            return

        # Normalise snapshot path to a web URL: always /media/<relative-within-media>
        from pathlib import Path as _Path
        def _to_url(path: str | None) -> str | None:
            if not path:
                return None
            p = _Path(path).as_posix()   # forward slashes on all platforms
            # Strip any leading 'media/' prefix (relative paths) or absolute prefix
            if p.startswith("media/"):
                return "/" + p
            # If the path already starts with /media/, return as-is
            if p.startswith("/media/"):
                return p
            # Fallback: just prepend /media/
            return f"/media/{p}"

        async with AsyncSessionLocal() as db:
            event = Event(
                camera_id="cam_01",
                event_type=ev.event_type,       # plain string — String column
                mode=mode.value,                # plain string — String column
                snapshot_path=snapshot_path,
                clip_path=clip_path,
                description=ev.description,
                meta=ev.meta,
            )
            db.add(event)
            await db.commit()
            await db.refresh(event)
            event_id = event.id

        logger.info(f"Event persisted: {ev.event_type} (id={event_id})")

        # Push to Celery (fire-and-forget)
        try:
            from app.alerts.tasks import dispatch_alert
            dispatch_alert.delay(event_id)
        except Exception as e:
            logger.warning(f"Celery dispatch failed: {e}")

        # Push via WebSocket
        try:
            from app.routers.stream import alert_manager
            await alert_manager.broadcast({
                "event_id": event_id,
                "event_type": ev.event_type,
                "mode": mode.value,
                "camera_id": "cam_01",
                "description": ev.description,
                "snapshot_url": _to_url(snapshot_path),
                "clip_url": _to_url(clip_path),
                "timestamp": datetime.utcnow().isoformat(),
            })
        except Exception as e:
            logger.warning(f"WebSocket broadcast failed: {e}")

    # ── Drawing helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _draw_box(img: np.ndarray, bbox: tuple, label: str, color: tuple):
        x1, y1, x2, y2 = bbox
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(img, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(img, label, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    @staticmethod
    def _draw_mode_badge(img: np.ndarray, mode: SystemMode):
        text = f"MODE: {mode.value.upper()}"
        color = (0, 180, 255) if mode == SystemMode.normal else (0, 0, 220)
        cv2.rectangle(img, (10, 10), (220, 40), color, -1)
        cv2.putText(img, text, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
