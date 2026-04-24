# Campus Eye — Technical Reference

Deep technical documentation covering every module, class, function, model, and data flow in the system.

---

## Table of Contents

1. [System Data Flow](#1-system-data-flow)
2. [AI Models — Detail](#2-ai-models--detail)
3. [Pipeline Modules](#3-pipeline-modules)
4. [FastAPI Application](#4-fastapi-application)
5. [Database Layer](#5-database-layer)
6. [Alert System](#6-alert-system)
7. [Frontend](#7-frontend)
8. [Configuration](#8-configuration)

---

## 1. System Data Flow

```
Camera / File / Webcam
        │
        ▼
VideoCapture (Thread)
  – OpenCV VideoCapture
  – stores latest frame in memory
        │
        ▼  (every 1/FPS seconds)
FrameProcessor.run() [asyncio Task]
        │
        ├──► ObjectDetector.detect_persons()     ← YOLOv8n + ByteTrack
        │        returns: list[Detection]
        │
        ├──► FaceRecognizer.detect_faces()       ← InsightFace buffalo_l
        │        returns: list[{bbox, embedding, det_score}]
        │        then: match_embedding() → cosine similarity vs DB cache
        │
        ├──► HeadTracker.process_frame()         ← MediaPipe FaceMesh
        │        returns: list[HeadEvent]
        │
        ├──► BehaviorAnalyzer.analyze_normal/exam()
        │        combines all above → list[DetectedEvent]
        │
        ├──► save_snapshot()  → media/snapshots/*.jpg
        │
        ├──► DB: INSERT INTO events
        │
        ├──► Celery: dispatch_alert.delay(event_id)  → email + Discord
        │
        └──► WebSocket broadcast → dashboard
```

---

## 2. AI Models — Detail

### 2.1 YOLOv8n (Object Detection + Tracking)

**File:** `app/pipeline/object_detector.py`  
**Weight file:** `models/yolov8n.pt` (~6 MB)  
**Provider:** Ultralytics (AGPL-3.0)

YOLOv8 (You Only Look Once, version 8) is a single-stage object detection model. The `n` (nano) variant is used for speed on CPU.

**How it works:**
- Divides the frame into a grid; for each cell predicts bounding boxes, objectness, and class probabilities simultaneously
- Uses a CSP (Cross-Stage Partial) backbone + PANet neck
- Produces detections in one forward pass (~30ms on CPU for 640×640)

**ByteTrack (built-in):**
- Ultralytics has ByteTrack integrated via `.track(persist=True)`
- Assigns a stable integer `track_id` to each person across frames
- Required for loitering detection (need to know *the same* person dwelled)

**COCO class IDs used:**

| ID | Class | Used for |
|----|-------|---------|
| 0 | person | All modes — tracking |
| 63 | laptop | Exam mode |
| 67 | cell phone | Exam mode — mobile cheating |
| 73/84 | book | Exam mode — unauthorised papers |
| 74 | clock | Exam mode — proxy for watch |

**Key methods:**
- `detect(frame, track, classes)` — raw detections from YOLO
- `detect_persons(frame)` — filters class 0 only
- `detect_exam_objects(frame)` — filters exam-banned objects

---

### 2.2 YOLOv8n-pose (Skeleton Keypoints)

**File:** `app/pipeline/object_detector.py` → `ObjectDetector._pose_model`  
**Weight file:** `models/yolov8n-pose.pt`

Extends YOLOv8 with a keypoint head. Detects 17 COCO body keypoints per person (nose, eyes, shoulders, elbows, wrists, hips, knees, ankles).

**Used for:** `get_pose_keypoints()` — provides wrist positions that feed hand interaction geometry. If two people's wrist bounding regions overlap, a `hand_interaction` event fires.

---

### 2.3 InsightFace buffalo_l (Face Recognition)

**File:** `app/pipeline/face_recognition.py`  
**Model dir:** `models/models/buffalo_l/`  
**Sub-models:**

| File | Purpose |
|------|---------|
| `det_10g.onnx` | RetinaFace face detector — locates face bounding boxes |
| `1k3d68.onnx` | 68-point 3D landmark detector |
| `2d106det.onnx` | 106-point 2D landmark detector |
| `genderage.onnx` | Gender + age estimation |
| `w600k_r50.onnx` | ResNet-50 trained on 600K faces — generates 512-dim embeddings |

**How recognition works:**
1. `detect_faces(frame)` → InsightFace detects all faces + generates `normed_embedding` (L2-normalised 512-dim vector) per face
2. `match_embedding(query, candidates)` → dot product between two L2-normalised vectors equals cosine similarity
3. If `cosine_similarity >= face_recognition_threshold` (default 0.45), it's a match
4. The candidate list is an **in-memory cache** of all enrolled face embeddings, refreshed from PostgreSQL every 30 seconds (avoids a DB query every frame)

**Why cosine similarity?**  
InsightFace normalises all embeddings to unit vectors. For unit vectors, `dot(a,b) = cos(angle)`. The closer to 1.0, the more similar the faces.

**pgvector:**  
Embeddings are stored in PostgreSQL as `vector(512)` columns using the pgvector extension. This would allow approximate-nearest-neighbour search at scale; currently the system does exact cosine matching in Python against the cache.

---

### 2.4 MediaPipe Face Mesh (Head Pose)

**File:** `app/pipeline/head_tracker.py`  
**Provider:** Google (Apache 2.0)

MediaPipe Face Mesh fits a 468-point 3D mesh to each detected face in real time.

**Head yaw estimation:**

```
Nose tip (landmark 1)
Left ear (landmark 234)
Right ear (landmark 454)

ear_midpoint = (left_ear + right_ear) / 2
horizontal_offset = (nose_x - ear_midpoint_x) / face_width
yaw_deg = offset × 90°
```

- Positive yaw → face turning right
- Negative yaw → face turning left
- When `|yaw| > head_swivel_yaw_degrees` (default 25°) for `head_swivel_frames` (default 10) consecutive frames → `HeadEvent` fires

**Why this approach?**  
Full 3D head pose estimation from Face Mesh requires solving a PnP problem with camera intrinsics. This simpler geometric approximation is sufficient for detecting gross head turns (cheating behaviour) without calibration.

**Fallback:** If MediaPipe's `solutions` attribute is unavailable (newer API), `HeadTracker` logs a warning and returns empty events — it does not crash the pipeline.

---

## 3. Pipeline Modules

### 3.1 `video_capture.py` — `VideoCapture`

Thread-safe frame producer that runs in a `daemon=True` background thread.

| Method | Description |
|--------|-------------|
| `start()` | Launches the background capture thread |
| `stop()` | Sets stop event, joins thread, releases OpenCV cap |
| `set_source(url)` | **Hot-swap:** updates `_url`, clears latest frame, releases current cap so the loop re-opens with the new source |
| `get_frame()` | Returns `_latest_frame` (may be `None` during startup/reconnect) |
| `current_source` | Property — returns active URL/index string |
| `_open()` | Opens `cv2.VideoCapture(source)`. Sets 5s timeout for RTSP to avoid 30s hangs |
| `_capture_loop()` | Infinite loop: opens → reads frame → writes to `_latest_frame` → sleeps `1/fps` |

**Source types:**
- Integer string `"0"` → webcam index via `int()` conversion
- `rtsp://` → RTSP network stream, 5s open/read timeout applied
- File path → local video file, loops when `ret=False` (EOF)

---

### 3.2 `object_detector.py` — `ObjectDetector`

Singleton (via `lru_cache`) YOLO wrapper.

| Method | Description |
|--------|-------------|
| `load()` | Loads YOLOv8n + YOLOv8n-pose. Applies PyTorch 2.6 `add_safe_globals()` allowlist to prevent `weights_only` errors |
| `detect(frame, track, classes)` | Core detection. Calls `.track()` for ByteTrack or `.predict()` for stateless detection |
| `detect_persons(frame)` | Shorthand — class 0 only with tracking |
| `detect_exam_objects(frame)` | Stateless detection of phones/books/laptops |
| `get_pose_keypoints(frame)` | Returns 17-keypoint arrays per person |

**`Detection` dataclass:**
```python
class_name: str        # COCO label e.g. "cell phone"
confidence: float      # 0.0–1.0
bbox: tuple            # (x1, y1, x2, y2) pixel coords
track_id: int | None   # ByteTrack ID, None if tracking disabled
```

---

### 3.3 `face_recognition.py` — `FaceRecognizer`

Singleton (via `lru_cache`) InsightFace wrapper. All CPU-heavy methods are called via `asyncio.get_event_loop().run_in_executor(None, ...)` from the processor to avoid blocking the event loop.

| Method | Description |
|--------|-------------|
| `load()` | Initialises InsightFace `FaceAnalysis("buffalo_l")`, tries CUDA first then falls back to CPU |
| `generate_embedding(image)` | Single-image embedding — used at face registration time |
| `detect_faces(frame)` | All faces in a frame with embeddings + scores |
| `match_embedding(query, candidates)` | Linear scan cosine similarity against in-memory cache |
| `cosine_similarity(a, b)` | `dot(a, b)` for pre-normalised vectors |

**`RecognizedFace` dataclass:**
```python
bbox: tuple          # filled by caller
name: str
role: str            # student | invigilator | staff
user_id: int | None
confidence: float    # cosine similarity score
```

---

### 3.4 `head_tracker.py` — `HeadTracker`

| Method | Description |
|--------|-------------|
| `load()` | Initialises `mp.solutions.face_mesh.FaceMesh` with `max_num_faces=10` |
| `process_frame(frame)` | BGR → RGB → FaceMesh → yaw estimation per face → accumulate consecutive frames |
| `_estimate_yaw(landmarks, w, h)` | Geometric yaw from nose/ear landmark positions |

**`HeadEvent` dataclass:**
```python
track_id: int
yaw_deg: float          # signed — negative=left, positive=right
direction: str          # "left" | "right" | "center"
consecutive_frames: int # resets to 0 after firing
```

---

### 3.5 `behavior_analyzer.py` — `BehaviorAnalyzer`

Combines all detector outputs into structured `DetectedEvent` objects. Contains no ML models itself — it is pure logic.

**`_OBJECT_LABELS` dict** — maps YOLO class names to human-readable alert text:
```python
"cell phone"  → "Mobile phone"
"book"        → "Unauthorised book/paper"
"clock"       → "Watch or clock"
"laptop"      → "Laptop computer"
```

**Normal mode pipeline (`analyze_normal`):**
1. **Loitering** — calls `LoiteringDetector.update(persons)` → fires if any track has dwelled > threshold
2. **Unknown face** — every unmatched face in `unknown_faces` → alert with detection confidence
3. **Vandalism** — optical flow (`calcOpticalFlowFarneback`) mean magnitude spike → rapid motion = possible fight/vandalism

**Exam mode pipeline (`analyze_exam`):**
1. **Foreign object** — each exam object not near an invigilator → alert with label + confidence
2. **Head swiveling** — each `HeadEvent` from `HeadTracker` → alert with direction and angle
3. **Hand interaction** — pairs of student bounding boxes with IoU > threshold → alert

**`_is_near_invigilator`** — checks if a detection bbox is within `margin=30px` of any invigilator bbox. Prevents false positives for objects the invigilator legitimately holds.

**`_compute_iou`** — standard Intersection over Union for two bounding boxes.

**`DetectedEvent` dataclass:**
```python
event_type: str        # matches EventType enum in models.py
description: str       # human-readable alert message
bbox: tuple | None     # optional location
meta: dict             # extra structured data (confidence, track_id, etc.)
```

---

### 3.6 `loitering_detector.py` — `LoiteringDetector`

Tracks how long each `track_id` has been stationary in the same zone.

- Uses centroid of bounding box per track
- If centroid displacement < `movement_threshold` pixels across frames AND duration > `loitering_seconds` → fires
- Track state is maintained across frames; resets when person moves significantly

---

### 3.7 `processor.py` — `FrameProcessor`

The master orchestration loop. Runs as a long-lived `asyncio.Task` started at app startup.

| Method | Description |
|--------|-------------|
| `run()` | Main `while self._running` loop: pulls frame → calls `_process_frame` → sleeps |
| `stop()` | Sets `_running=False`, calls `VideoCapture.stop()` |
| `set_source(url)` | Delegates to `VideoCapture.set_source()` |
| `current_source` | Property exposing `VideoCapture.current_source` |
| `_get_mode()` | Reads `system_mode` setting from DB (with YAML default fallback) |
| `_refresh_embedding_cache()` | Queries all `FaceEmbedding` + `User` rows into memory every 30s |
| `_process_frame(frame)` | Full single-frame pipeline: detect → recognise → analyse → annotate → persist |
| `_persist_event(ev, mode, snapshot)` | INSERTs event to DB, dispatches Celery task, broadcasts via WebSocket |
| `_draw_box(img, bbox, label, color)` | OpenCV rectangle + label overlay |
| `_draw_mode_badge(img, mode)` | Top-left mode indicator on the annotated frame |

**Embedding cache:** A Python list of dicts `[{user_id, name, role, embedding}]` held in RAM. Refreshed from DB every 30 seconds. This means new face registrations take up to 30s to become active.

---

## 4. FastAPI Application

### 4.1 `main.py` — App Factory

```python
@asynccontextmanager
async def lifespan(app):
    # startup: load models, start processor task
    yield
    # shutdown: stop processor
```

- Mounts `StaticFiles` on `/` for the frontend HTML/JS/CSS
- Mounts `StaticFiles` on `/media` for snapshot images
- Includes all routers with `/api` prefix (except WebSocket routes)
- Stores `processor` on `app.state.processor` so all routes can access it

### 4.2 `config.py` — Settings

`Settings` (Pydantic `BaseSettings`) reads from `.env`:

| Field | Description |
|-------|-------------|
| `database_url` | PostgreSQL connection string |
| `redis_url` | Redis connection string |
| `camera_url` | Default video source (`0`, RTSP, or file path) |
| `face_recognition_threshold` | Cosine similarity cutoff (default 0.45) |
| `model_dir` | Path to downloaded model weights |
| `process_fps` | Target pipeline frame rate |

`get_yaml_config()` — loads `config.yaml` once via `lru_cache`.

### 4.3 Routers

**`stream.py`:**
- `GET /api/stream/snapshot` — returns latest frame as JPEG (polling fallback)
- `GET/POST /api/stream/source` — query or switch the video source at runtime
- `POST /api/stream/upload` — async file upload → switches processor source
- `GET /api/stream/uploads` — lists files in `media/uploads/`
- `POST /api/stream/use-upload` — re-activates a previously uploaded file
- `WS /ws/stream` — pushes base64 JPEG frames every 100ms
- `WS /ws/alerts` — `AlertConnectionManager` broadcasts to all connected clients

**`faces.py`:**
- `GET /api/faces/` — list all users with face counts
- `POST /api/faces/register` — saves photo, generates InsightFace embedding, stores in DB
- `DELETE /api/faces/{id}` — removes user + all embeddings

**`events.py`:**
- `GET /api/events/` — paginated, filterable by type/mode/acknowledged
- `POST /api/events/{id}/acknowledge` — marks event acknowledged
- `GET /api/events/{id}` — single event detail

**`settings.py`:**
- `GET/POST /api/settings/mode` — read/write `system_mode` in DB settings table
- `GET /api/settings/schedule` — reads exam schedule from `config.yaml`

---

## 5. Database Layer

### 5.1 `database.py`

```python
engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
```

All DB access uses `async with AsyncSessionLocal() as db:` — each route/task gets its own short-lived session.

### 5.2 `models.py` — ORM Tables

**`User`** — enrolled person:
```
id, name, student_id, role (student|invigilator|staff), photo_path, created_at
```

**`FaceEmbedding`** — one or more embeddings per user:
```
id, user_id (FK), embedding (vector(512)), created_at
```
`vector(512)` is the pgvector type enabling approximate nearest-neighbour search.

**`Event`** — every detected incident:
```
id, camera_id, event_type (enum), mode (normal|exam),
snapshot_path, description, meta (JSON), acknowledged, created_at
```

**`Setting`** — key-value store:
```
key (PK), value
```
Used for `system_mode` persistence across restarts.

### 5.3 `migrations/`

Alembic migration `001` creates:
1. `pgvector` extension (`CREATE EXTENSION IF NOT EXISTS vector`)
2. All four tables above
3. Indexes on `events.event_type`, `events.created_at`

---

## 6. Alert System

### 6.1 `alerts/celery_app.py`

```python
celery_app = Celery("campus_eye", broker=REDIS_URL, backend=REDIS_URL)
```

Celery uses Redis as both the task broker and result backend.

### 6.2 `alerts/tasks.py` — `dispatch_alert`

Called with `dispatch_alert.delay(event_id)` (fire-and-forget from the processor).

1. Loads the `Event` from DB by ID
2. **Email** — sends via SMTP (Gmail app password recommended) with event details + snapshot link
3. **Discord** — POSTs to the configured webhook URL with a formatted embed

Both are optional — if `SMTP_USER` or `DISCORD_WEBHOOK_URL` is empty, that delivery is skipped.

### 6.3 Real-time WebSocket Alerts

Independently of Celery, `alert_manager.broadcast()` pushes alert JSON directly to all connected dashboard clients via the `/ws/alerts` WebSocket — no Celery needed for the live dashboard feed.

---

## 7. Frontend

### 7.1 `index.html` — Single-page Dashboard

Five panels rendered via CSS `display:none` / `display:block`:
- **Live** — video feed + source control + recent alerts
- **Alerts** — full alert history
- **Events** — filterable paginated event log table
- **Faces** — face registry CRUD
- **Settings** — mode toggle + schedule table

### 7.2 `app.js` — Dashboard Logic

**WebSocket management:**
- `connectStreamWebSocket()` — maintains `/ws/stream` connection, updates `<img id="live-feed">` src
- `connectAlertWebSocket()` — maintains `/ws/alerts`, calls `handleIncomingAlert()` on each message
- Both auto-reconnect on close with exponential backoff

**Source management:**
- `updateSourceStatus()` — polls `/api/stream/source` every 5s, shows green dot when frames are live
- `uploadVideo()` — XHR with progress events → auto-triggered on `<input onchange>`
- `setRtspSource()` — POSTs URL to `/api/stream/source`
- `loadUploads()` / `useUpload(filename)` — manages previously uploaded files

**Alert flow:**
- `handleIncomingAlert(alert)` — updates badge count, prepends to recent/all lists, shows toast
- `buildAlertItem(alert)` — builds DOM element with snapshot thumbnail + acknowledge button
- `acknowledgeEvent(id)` — POSTs to acknowledge endpoint, updates UI

**Face registry:**
- `registerFace(e)` — FormData POST with photo + metadata
- `deleteFace(id)` — DELETE request + removes card from DOM
- `previewPhoto(input)` — FileReader preview in the drop zone

### 7.3 `style.css`

CSS custom properties (variables) for the full design system:
- `--bg-primary`, `--bg-card` — dark background hierarchy
- `--accent-green`, `--accent-red`, `--accent-blue`, `--accent-amber` — semantic alert colours
- `.ws-dot.connected` — animated green pulse for live status indicators
- `.alert-item.new` — slide-in animation for incoming alerts
- `.mode-badge.exam` — red badge for exam mode

---

## 8. Configuration (`config.yaml`)

```yaml
detection:
  yolo_confidence: 0.45         # Min YOLO score to count a detection
  head_swivel_yaw_degrees: 25.0 # Angle threshold for head turn alert
  head_swivel_frames: 10        # Consecutive frames before firing
  motion_vandalism_threshold: 0.15
  proximity_overlap_iou: 0.05   # IoU to detect hand-to-hand interaction

normal_mode:
  detect_loitering: true
  detect_unknown_faces: true
  detect_vandalism: true
  loitering_seconds: 30         # Seconds before loitering fires

exam_mode:
  detect_phones: true
  detect_foreign_papers: true
  detect_head_swiveling: true
  detect_hand_interaction: true

processing:
  fps: 10                        # Pipeline processing rate
  frame_width: 640
  frame_height: 480
  reconnect_delay_seconds: 5

alerts:
  cooldown_seconds: 60           # Minimum seconds between same-type alerts
```

---

## Model Interaction Diagram

```
                    ┌─────────────┐
                    │  Raw Frame  │
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │  YOLOv8n   │ │ InsightFace │ │  MediaPipe  │
    │  + Tracker  │ │  buffalo_l  │ │  FaceMesh   │
    └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
           │               │               │
    list[Detection]  list[{bbox,     list[HeadEvent]
    (persons, objs)   embedding}]   (yaw, direction)
           │               │               │
           └───────────────┼───────────────┘
                           ▼
                  ┌─────────────────┐
                  │ BehaviorAnalyzer│
                  │ .analyze_*()    │
                  └────────┬────────┘
                           │
                  list[DetectedEvent]
                  {type, description, meta}
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         PostgreSQL     Celery       WebSocket
         INSERT         .delay()     broadcast
         Event          email+discord dashboard
```
