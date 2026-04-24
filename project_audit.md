# Campus Eye — Project Audit Report

---

## Overall Verdict

The project is **~70% complete relative to its stated scope**. The core pipeline
(video capture → detection → persistence → dashboard) works end-to-end.
Several features are wired in config but never implemented, one critical model
integration is broken, and several runtime bugs remain.

---

## 🔴 Critical Bugs (things actively broken right now)

### 1. Snapshot URL double `/media/` prefix
**Where:** `processor.py` line 266 + `snapshot.py` line 39

`save_snapshot()` returns `"media/snapshots/file.jpg"` (full relative path).
`_persist_event` then builds:
```python
snapshot_url = f"/media/{snapshot_path}"
# → "/media/media/snapshots/file.jpg"   ← 404
```
The static mount is at `/media` serving the `media/` directory.
The snapshot_url should strip the leading `media/` before prepending `/media/`.

**Fix needed in `processor.py`:**
```python
rel = Path(snapshot_path).relative_to("media") if snapshot_path else None
snapshot_url = f"/media/{rel}" if rel else None
```

---

### 2. `event_type` stored as `EventType` enum in `String` column
**Where:** `processor.py` line 237, `models.py`

`Event(event_type=event_type)` where `event_type` is `EventType.unknown_face`.
In Python 3.11+, `str(EventType.unknown_face)` returns `"EventType.unknown_face"`,
not `"unknown_face"`. This means the DB may store `"EventType.unknown_face"` which
then fails to deserialise back into the `EventType` enum.

**Fix:** Use `.value` explicitly:
```python
event_type=event_type.value,
mode=mode.value,
```

---

### 3. `_get_mode()` hits the database every single frame
**Where:** `processor.py` line 140

At 5 fps, this is 5 DB round-trips per second, every second, permanently.
Mode changes are rare (a human changes them). This should be cached and refreshed
on a longer interval (e.g., every 5s), same pattern as embedding cache.

---

### 4. Snapshot spam (mitigated but not fully solved)
Before the 60-second cooldown was added, every frame with a visible face produced
a `unknown_face` snapshot. The snapshot dir contained 400+ files in one session.
The cooldown now limits alerts to 1 per type per 60s — but does not deduplicate
per-person. If 5 different unknown faces appear simultaneously, only the first fires.
This is acceptable but should be documented.

---

### 5. `Enum(UserRole)` on `users.role` column
**Where:** `models.py` line 60

Same issue as the fixed `event_type`/`mode` columns — `role` uses `Enum(UserRole)`
but the DB column is likely `character varying`. This will crash when you try to
filter users by role. Has not caused an error yet only because the faces router
doesn't filter by role in a query parameter.

---

## 🟡 Features in Config but NOT Implemented

These are in `config.yaml` and appear to be fully planned but have no code:

| Config key | Status |
|---|---|
| `normal_mode.detect_littering` | ❌ No `LitteringDetector` class exists anywhere |
| `exam_mode.detect_talking` | ❌ No talking/audio detector implemented |
| `storage.clip_dir` | ❌ `Event.clip_path` column exists but is never populated |
| Multi-camera | ❌ `config.yaml` has a camera list; only `"cam_01"` is ever hardcoded |

**Impact:** The system cannot perform littering detection or detect talking during
exams, despite the UI and config implying these are active.

---

## 🟡 AI Model Issues

### Head Tracker — MediaPipe disabled
**Where:** `head_tracker.py` line 44

MediaPipe's `mp.solutions` namespace was removed in recent versions.
The `HeadTracker.load()` fails silently with:
```
ERROR app.pipeline.head_tracker Failed to load MediaPipe: module 'mediapipe' has no attribute 'solutions'
```
**Result:** `head_swiveling` events **never fire** in exam mode.
The `detect_head_swiveling: true` config setting is effectively ignored.

**Fix options:**
- Downgrade: `pip install mediapipe==0.10.9`
- Migrate to the new `mp.tasks.vision.FaceLandmarker` API

---

### YOLOv8n-nano — Too small for phone detection
The `n` variant has the lowest accuracy of the YOLOv8 family.
A phone quickly held up to a webcam is a small, low-resolution object.
At confidence 0.25, YOLOv8n may still miss it.

**Recommendation:** Switch to `yolov8s.pt` (small, 22MB vs 6MB):
```python
det_path = self._model_dir / "yolov8s.pt"
self._model = YOLO(str(det_path) if det_path.exists() else "yolov8s.pt")
```
YOLOv8s has ~60% better mAP on the COCO benchmark while still running at
acceptable speed on CPU.

---

### YOLOv8n-pose — Loaded but never used in the main pipeline
**Where:** `object_detector.py` line 125, `behavior_analyzer.py` line 161

`get_pose_keypoints()` is defined and the model is loaded, but the `FrameProcessor`
never calls it. The `_detect_hand_interactions()` method uses **bounding-box IoU**
between person detections instead of actual wrist keypoints. This means:
- Two people standing close together will trigger `hand_interaction` even with no
  physical contact
- The pose model wastes ~50MB of memory and load time

---

## 🟡 Performance Issues

| Issue | Impact |
|---|---|
| Dashboard polls `/api/stream/source` every ~1s | Generates ~60 log lines/minute of noise |
| Dashboard polls `/api/events`, `/api/settings/mode`, `/api/faces` every 5–10s | 4–5 concurrent polling loops per tab |
| `save_snapshot()` is a synchronous blocking disk write in an async context | Blocks the event loop while writing JPEG to disk |
| No frame resize before YOLO inference | Processing 1080p webcam frames is slower than 640×640 |

---

## 🟡 Security / Privacy Issues (relevant for an assignment)

| Issue | Notes |
|---|---|
| **No authentication** | Any device on localhost can view the live feed, delete registered faces, change modes, or upload arbitrary files |
| **No upload validation** | Only MIME type is checked; a malicious file could be uploaded |
| **Snapshots never cleaned up** | `media/snapshots/` grows indefinitely |
| **Passwords in `.env`** | DB password, SMTP password in plaintext `.env` — `.gitignore` covers this but worth noting |

---

## 🟢 What Works Correctly

| Feature | Status |
|---|---|
| Webcam capture + hot-swap source | ✅ Working |
| YOLOv8n person detection + ByteTrack | ✅ Working |
| InsightFace face detection | ✅ Working |
| Face registration + cosine matching | ✅ Working |
| Unknown face alerts (Normal mode) | ✅ Working (60s cooldown) |
| Loitering detection | ✅ Working (requires registered tracks) |
| Optical flow vandalism detection | ✅ Working (fixed frame-size guard) |
| Exam object detection (phones at 0.25 conf) | ✅ Implemented (detection quality depends on model) |
| Alert descriptions — specific text | ✅ Fixed this session |
| WebSocket live feed | ✅ Working |
| WebSocket alert push | ✅ Working |
| Video file upload + hot-swap | ✅ Working |
| Event log + filtering | ✅ Fixed this session (enum cast) |
| Snapshot saving | ✅ Saving correctly (URL path is broken) |
| Mode switching via dashboard | ✅ Working |
| Exam schedule config | ✅ Parseable (auto-switching not wired) |
| Docker PostgreSQL + pgvector | ✅ Running |
| Docker Redis | ✅ Running |
| Face embedding storage | ✅ Working |

---

## 📋 Correlation with Original Prompt

| Requirement | Implemented? | Notes |
|---|---|---|
| Live CCTV feed on dashboard | ✅ Yes | WebSocket MJPEG stream |
| Normal mode security monitoring | ✅ Yes | Loitering, unknown faces, vandalism |
| Exam mode integrity monitoring | ⚠️ Partial | Phones/books work; head-swiveling disabled |
| Face recognition + enrolment | ✅ Yes | InsightFace buffalo_l |
| Real-time alerts with descriptions | ✅ Yes | Fixed this session |
| Dual mode toggle | ✅ Yes | Dashboard + API |
| Video upload support | ✅ Yes | Added this session |
| RTSP IP camera support | ✅ Yes | With 5s timeout guard |
| Email/Discord notifications | ⚠️ Partial | Celery task exists; worker not tested |
| Littering detection | ❌ No | In config, not implemented |
| Talking detection | ❌ No | In config, not implemented |
| Head swiveling detection | ❌ No | MediaPipe API broken |
| Multi-camera support | ❌ No | Only cam_01 ever used |
| Schedule-based auto mode switching | ❌ No | Schedule is readable, not enforced |

---

## 🔧 Priority Fix List

1. **Fix snapshot URL** — strip `media/` before prepending `/media/` (5 min fix)
2. **Use `.value` when persisting enums** — prevent corrupted `event_type` in DB
3. **Cache `_get_mode()`** — stop hitting DB every frame
4. **Upgrade to YOLOv8s** — dramatically better phone detection
5. **Fix MediaPipe** — either downgrade or migrate to new API
6. **Remove unused pose model** — or wire it into hand interaction detection properly
7. **Add schedule enforcement** — read schedule in processor, auto-switch mode
8. **Add `/api/stream/source` polling interval backoff** — reduce log noise

