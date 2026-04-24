# Campus Eye — CCTV Monitoring System MVP

A full-stack campus surveillance platform with real-time face recognition, multi-mode behavioral detection, and a live alerting pipeline.

---

## Overview

The system is composed of five main layers:

1. **Ingestion Layer** — pulls frames from RTSP streams or uploaded video files.
2. **Detection Pipeline** — runs YOLO object detection, face recognition (InsightFace), MediaPipe pose/head tracking, and behavioral analyzers (loitering, malpractice).
3. **Backend API** — FastAPI serving REST endpoints + WebSocket push for the dashboard.
4. **Alert Dispatcher** — Celery workers that send email (SMTP), Discord webhooks, and in-app notifications.
5. **Frontend Dashboard** — Vanilla HTML/JS (no build step) showing live feed, alerts, face registration, mode control.

---

## User Review Required

> [!IMPORTANT]
> **InsightFace vs DeepFace**: The plan uses **InsightFace** (`buffalo_l` model) as the primary face recognition engine. It is significantly faster and more accurate than DeepFace for real-time use, and works well with pgvector cosine similarity. DeepFace is retained as an optional fallback.

> [!IMPORTANT]
> **CPU Fallback**: All detection modules check for CUDA availability at startup and gracefully fall back to CPU. CPU-only mode will be ~5–10× slower but still functional for testing.

> [!WARNING]
> **pgvector Extension**: The PostgreSQL container requires `pgvector` to be compiled in. The Dockerfile for PostgreSQL extends `pgvector/pgvector:pg16` which handles this automatically.

> [!CAUTION]
> **Model Downloads**: First run will auto-download YOLOv8n (~6 MB), YOLOv8n-pose (~7 MB), and InsightFace `buffalo_l` (~300 MB). A script is provided to pre-download them.

---

## Open Questions

> [!IMPORTANT]
> 1. **Camera count**: The MVP hardcodes a single camera stream per session. Do you need multi-camera support in v1?
> 2. **Authentication**: Should the dashboard have login/auth, or is it internal-only for now?
> 3. **Alert recipients**: Are alert recipients configured once globally, or per-camera/per-event?
> 4. **Exam schedule**: Should the scheduler auto-switch modes using a predefined timetable, or is manual toggle sufficient for the MVP?

---

## Proposed Changes

All files will be created inside `/home/ab07/Documents/Studies/Assignment/AI/Campus Eye/`.

---

### Project Root

#### [NEW] `docker-compose.yml`
Orchestrates: PostgreSQL+pgvector, Redis, FastAPI app, Celery worker.

#### [NEW] `Dockerfile`
Multi-stage build for the FastAPI + pipeline container.

#### [NEW] `.env.example`
Template with all required environment variables (DB URL, Redis URL, SMTP, Discord webhook, camera RTSP URL).

#### [NEW] `requirements.txt`
All Python dependencies pinned to compatible versions.

#### [NEW] `config.yaml`
Runtime configuration: camera URLs, detection thresholds, mode schedules, alert targets.

#### [NEW] `setup.sh`
One-shot script: creates virtualenv, installs deps, downloads models, runs DB migrations.

---

### `app/` — FastAPI Application

#### [NEW] `app/main.py`
FastAPI app entry point. Mounts routers, initialises DB, starts background video processor on startup.

#### [NEW] `app/config.py`
Loads `.env` + `config.yaml`, exposes a single `Settings` dataclass.

#### [NEW] `app/database.py`
SQLAlchemy async engine, session factory, `Base` declarative base.

#### [NEW] `app/models.py`
ORM models:
- `User` (id, name, role: student/invigilator/staff, photo_path, created_at)
- `FaceEmbedding` (id, user_id FK, embedding VECTOR(512), created_at)
- `Event` (id, camera_id, event_type, mode, snapshot_path, clip_path, metadata JSONB, created_at, acknowledged)
- `Setting` (key, value) — runtime key-value store for mode, thresholds

#### [NEW] `app/schemas.py`
Pydantic request/response schemas.

---

### `app/routers/` — API Endpoints

#### [NEW] `app/routers/faces.py`
- `POST /api/faces/register` — upload photo + name + role → generate embedding → store
- `GET  /api/faces/` — list registered faces
- `DELETE /api/faces/{id}` — remove face

#### [NEW] `app/routers/events.py`
- `GET  /api/events/` — paginated event log with filters
- `POST /api/events/{id}/acknowledge` — mark event seen

#### [NEW] `app/routers/settings.py`
- `GET  /api/settings/mode` — current mode
- `POST /api/settings/mode` — switch Normal/Exam
- `GET  /api/settings/schedule` — view exam schedule
- `POST /api/settings/schedule` — update schedule

#### [NEW] `app/routers/stream.py`
- `GET  /api/stream/snapshot` — latest JPEG frame
- `WebSocket /ws/stream` — MJPEG-over-WebSocket live feed
- `WebSocket /ws/alerts` — real-time alert push

---

### `app/pipeline/` — Core Detection Pipeline

#### [NEW] `app/pipeline/video_capture.py`
`VideoCapture` class — wraps OpenCV `VideoCapture` for both RTSP and file sources. Emits frames at a configurable FPS. Handles reconnection for RTSP.

#### [NEW] `app/pipeline/face_recognition.py`
`FaceRecognizer` class:
- Loads InsightFace `buffalo_l` model.
- `generate_embedding(image) → np.ndarray` — 512-dim vector.
- `recognize(frame) → List[RecognizedFace]` — runs detection + embedding, queries pgvector with cosine similarity, returns name/role/confidence per face.

#### [NEW] `app/pipeline/object_detector.py`
`ObjectDetector` class:
- Loads `yolov8n.pt` (general) and optionally `yolov8n-pose.pt`.
- `detect_objects(frame, classes) → List[Detection]` — bounding boxes, labels, confidence.
- Relevant classes: person, cell phone, watch, book, laptop, backpack.

#### [NEW] `app/pipeline/head_tracker.py`
`HeadTracker` class (MediaPipe Face Mesh):
- Tracks head pose (yaw/pitch) per person per frame.
- Returns `HeadEvent(person_id, direction, angle, timestamp)`.
- Triggers alert if yaw > threshold for N consecutive frames.

#### [NEW] `app/pipeline/loitering_detector.py`
`LoiteringDetector` class:
- Maintains a dict `{track_id: first_seen_time}` using YOLO ByteTrack.
- Fires alert if a person remains in a zone for longer than `loiter_threshold` seconds.

#### [NEW] `app/pipeline/behavior_analyzer.py`
`BehaviorAnalyzer` — orchestrates per-frame analysis:
- **Normal Mode**: loitering, unknown face, littering (YOLO detects object drop), vandalism (motion magnitude spike).
- **Exam Mode**: foreign object (phone/watch/paper), head swiveling, hand-to-hand interaction (proximity of bounding boxes).
- Invigilators identified by face recognition are skipped in Exam Mode.

#### [NEW] `app/pipeline/processor.py`
`FrameProcessor` — main loop:
1. Pull frame from `VideoCapture`.
2. Run `ObjectDetector` → `FaceRecognizer` → `BehaviorAnalyzer`.
3. Annotate frame (bounding boxes, labels).
4. Push annotated frame to a shared `asyncio.Queue` for WebSocket streaming.
5. Dispatch alerts via Celery tasks.

---

### `app/alerts/` — Alert Dispatcher

#### [NEW] `app/alerts/tasks.py`
Celery task definitions:
- `send_email_alert(event_id)` — SMTP with snapshot attachment.
- `send_discord_alert(event_id)` — Discord webhook with embed + image.
- `send_websocket_alert(event_id)` — pushes JSON to all connected WS clients.

#### [NEW] `app/alerts/email_sender.py`
SMTP helper using Python `smtplib` + `email.mime`.

#### [NEW] `app/alerts/discord_sender.py`
Discord webhook helper using `httpx`.

#### [NEW] `app/alerts/celery_app.py`
Celery app configured with Redis broker + backend.

---

### `app/utils/`

#### [NEW] `app/utils/snapshot.py`
`save_snapshot(frame, event_type) → path` — saves JPEG to `media/snapshots/`.

#### [NEW] `app/utils/logger.py`
Structured logging setup (Python `logging` + JSON formatter for production).

---

### `migrations/` — Alembic

#### [NEW] `migrations/env.py`, `migrations/versions/001_initial.py`
Initial schema migration creating all four tables + enabling pgvector extension.

---

### `frontend/` — Dashboard

#### [NEW] `frontend/index.html`
Single-page dashboard:
- **Live Feed panel** — displays MJPEG stream via WebSocket.
- **Alerts panel** — real-time list of recent events (type, snapshot, time, acknowledge button).
- **Mode Control** — toggle Normal/Exam, display current mode with badge.
- **Face Registration** — form to upload photo + name + role.
- **Event Log** — filterable table of past events.

#### [NEW] `frontend/style.css`
Dark glassmorphism theme with vibrant accent colors.

#### [NEW] `frontend/app.js`
Vanilla JS: WebSocket client, fetch API calls, live feed renderer, alert list, face upload form.

---

### `scripts/`

#### [NEW] `scripts/download_models.py`
Pre-downloads YOLOv8 weights and InsightFace models to avoid first-run delays.

#### [NEW] `scripts/seed_db.py`
Optional: seeds a few test users/faces for demo.

---

## File Tree Summary

```
Campus Eye/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── requirements.txt
├── config.yaml
├── setup.sh
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── routers/
│   │   ├── faces.py
│   │   ├── events.py
│   │   ├── settings.py
│   │   └── stream.py
│   ├── pipeline/
│   │   ├── video_capture.py
│   │   ├── face_recognition.py
│   │   ├── object_detector.py
│   │   ├── head_tracker.py
│   │   ├── loitering_detector.py
│   │   ├── behavior_analyzer.py
│   │   └── processor.py
│   ├── alerts/
│   │   ├── celery_app.py
│   │   ├── tasks.py
│   │   ├── email_sender.py
│   │   └── discord_sender.py
│   └── utils/
│       ├── snapshot.py
│       └── logger.py
├── migrations/
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       └── 001_initial.py
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── scripts/
│   ├── download_models.py
│   └── seed_db.py
└── media/
    └── snapshots/   (auto-created at runtime)
```

---

## Verification Plan

### Automated Tests
- After setup, run `pytest tests/` (smoke tests for API endpoints, face registration, embedding generation).
- `docker compose up --build` should start all services without errors.

### Manual Verification
1. Open `http://localhost:8000` — dashboard loads.
2. Register a face via the form → confirm it appears in the face list.
3. Upload a short video file → confirm frames are processed and displayed.
4. Trigger a detected event → confirm alert appears in the dashboard alert panel.
5. Toggle mode → confirm mode badge changes.
6. Check Discord / email for alert delivery (if credentials configured).
