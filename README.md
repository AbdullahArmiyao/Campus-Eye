# 🎓 Campus Eye — Intelligent CCTV Monitoring System

> Real-time AI-powered campus surveillance with dual-mode behavioural analysis, face recognition, and an instant-alert dashboard.

---

## Overview

**Campus Eye** analyses live video (webcam / RTSP / uploaded file) to detect suspicious behaviour across two modes:

| Mode | Detections |
|------|-----------|
| **Normal** | Loitering · Unknown faces · Vandalism/fighting |
| **Exam** | Mobile phones · Unauthorised books · Head swiveling · Hand-to-hand passing |

Everything runs on-premises — no data leaves your network.

---

## AI Models Used

| Model | Purpose |
|-------|---------|
| **YOLOv8n** (Ultralytics) | Person + object detection with ByteTrack multi-object tracking |
| **YOLOv8n-pose** (Ultralytics) | Skeleton keypoints for pose-based interaction detection |
| **InsightFace buffalo_l** | Face detection + 512-dim embedding generation for recognition |
| **MediaPipe Face Mesh** | 468-point facial landmarks → head yaw angle estimation |

---

## Quick Start

```bash
# 1. Setup
bash setup.sh

# 2. Configure
cp .env.example .env
# Set CAMERA_URL=0 (webcam) or path to video file

# 3. Start DB + Redis
docker compose up -d db redis

# 4. Migrate DB
source venv/bin/activate && alembic upgrade head

# 5. Run
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 6. Open
# http://localhost:8000
```

---

## Project Structure

```
app/
  main.py              FastAPI app + lifespan hooks
  config.py            Settings (Pydantic) + YAML loader
  database.py          Async SQLAlchemy session
  models.py            ORM: User, FaceEmbedding, Event, Setting
  schemas.py           Pydantic request/response schemas
  alerts/              Celery tasks — email + Discord delivery
  pipeline/
    video_capture.py   Thread-safe OpenCV capture (hot-swappable source)
    object_detector.py YOLOv8 wrapper (detection + tracking)
    face_recognition.py InsightFace embedding + cosine matching
    head_tracker.py    MediaPipe yaw estimation
    behavior_analyzer.py Orchestrates all detectors → events
    loitering_detector.py Dwell-time analysis per track
    processor.py       Master async processing loop
  routers/             FastAPI route handlers
  utils/snapshot.py    Annotated frame saving
frontend/
  index.html           Single-page dashboard
  app.js               WebSocket + fetch logic
  style.css            Dark-mode design system
migrations/            Alembic SQL migrations
config.yaml            Detection thresholds + schedule
docker-compose.yml     PostgreSQL (pgvector) + Redis
```

---

## REST API

| Method | Endpoint | Description |
|--------|---------|-------------|
| GET | `/api/stream/snapshot` | Latest annotated JPEG |
| POST | `/api/stream/upload` | Upload video file |
| GET/POST | `/api/stream/source` | Query / set source |
| GET | `/api/faces/` | List registered faces |
| POST | `/api/faces/register` | Register new face |
| DELETE | `/api/faces/{id}` | Remove face |
| GET | `/api/events/` | Paginated event log |
| POST | `/api/events/{id}/acknowledge` | Acknowledge alert |
| GET/POST | `/api/settings/mode` | Get / set mode |
| WS | `/ws/stream` | Live video frames |
| WS | `/ws/alerts` | Real-time alert push |

---

## Uninstall

```bash
bash uninstall.sh           # venv + models + containers
bash uninstall.sh --all     # + media/snapshots
bash uninstall.sh --dry-run # preview only
```
