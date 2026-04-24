"""
Campus Eye — Stream Router
GET       /api/stream/snapshot  – latest JPEG frame (for polling clients)
POST      /api/stream/upload    – upload a video file and use it as the source
GET/POST  /api/stream/source    – query or set the current video source (RTSP/webcam)
WebSocket /ws/stream            – MJPEG-over-WebSocket live feed
WebSocket /ws/alerts            – real-time alert JSON push
"""
import asyncio
import base64
import logging
import shutil
from pathlib import Path
from typing import Any

import cv2
from fastapi import APIRouter, Request, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = Path("media/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}


# ── Connection manager for alert WebSocket ────────────────────────────────────

class AlertConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)
        logger.debug(f"Alert WS connected. Total: {len(self._connections)}")

    def disconnect(self, ws: WebSocket):
        if ws in self._connections:
            self._connections.remove(ws)
        logger.debug(f"Alert WS disconnected. Total: {len(self._connections)}")

    async def broadcast(self, payload: dict[str, Any]):
        dead = []
        for ws in self._connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self._connections:
                self._connections.remove(ws)


alert_manager = AlertConnectionManager()


# ── Snapshot endpoint ─────────────────────────────────────────────────────────

@router.get("/api/stream/snapshot")
async def get_snapshot(request: Request):
    """Return the most recent annotated frame as JPEG."""
    processor = getattr(request.app.state, "processor", None)
    if processor is None or processor.latest_frame is None:
        placeholder = _make_placeholder()
        _, buf = cv2.imencode(".jpg", placeholder)
        return Response(content=buf.tobytes(), media_type="image/jpeg")

    _, buf = cv2.imencode(".jpg", processor.latest_frame)
    return Response(content=buf.tobytes(), media_type="image/jpeg")


# ── Source query / set ────────────────────────────────────────────────────────

@router.get("/api/stream/source")
async def get_source(request: Request):
    """Return info about the current video source."""
    processor = getattr(request.app.state, "processor", None)
    if processor is None:
        return JSONResponse({"source": None, "type": "none", "active": False})

    src = processor.current_source
    source_type = _classify_source(src)
    return JSONResponse({
        "source": src,
        "type": source_type,
        "active": processor.latest_frame is not None,
    })


@router.post("/api/stream/source")
async def set_source(request: Request):
    """Set the video source to an RTSP URL or webcam index (e.g. '0')."""
    body = await request.json()
    url: str = body.get("url", "").strip()
    if not url:
        return JSONResponse({"error": "url is required"}, status_code=400)

    processor = getattr(request.app.state, "processor", None)
    if processor is None:
        return JSONResponse({"error": "Processor not running"}, status_code=503)

    processor.set_source(url)
    return JSONResponse({
        "message": f"Source switched to: {url}",
        "source": url,
        "type": _classify_source(url),
    })


# ── Video upload endpoint ─────────────────────────────────────────────────────

@router.post("/api/stream/upload")
async def upload_video(request: Request, file: UploadFile = File(...)):
    """
    Upload a video file (mp4 / avi / mov / mkv / webm) and immediately
    use it as the processing source.
    """
    suffix = Path(file.filename or "video.mp4").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            {"error": f"Unsupported format '{suffix}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"},
            status_code=415,
        )

    dest = UPLOAD_DIR / file.filename
    # If same filename already exists, avoid collision by incrementing a counter
    original_stem = dest.stem
    counter = 1
    while dest.exists():
        dest = UPLOAD_DIR / f"{original_stem}_{counter}{suffix}"
        counter += 1

    # Stream file to disk asynchronously
    contents = await file.read()
    with dest.open("wb") as out:
        out.write(contents)

    logger.info(f"Video uploaded: {dest} ({dest.stat().st_size // 1024} KB)")

    # Switch processor to the uploaded file
    processor = getattr(request.app.state, "processor", None)
    if processor:
        processor.set_source(str(dest))

    return JSONResponse({
        "message": "Video uploaded and processing started.",
        "filename": dest.name,
        "path": str(dest),
        "size_kb": dest.stat().st_size // 1024,
    })


@router.get("/api/stream/uploads")
async def list_uploads():
    """List all previously uploaded video files."""
    files = [
        {
            "name": f.name,
            "path": str(f),
            "size_kb": f.stat().st_size // 1024,
        }
        for f in sorted(UPLOAD_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
        if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS
    ]
    return JSONResponse({"uploads": files})


@router.post("/api/stream/use-upload")
async def use_upload(request: Request):
    """Switch to a previously uploaded file by filename."""
    body = await request.json()
    filename: str = body.get("filename", "").strip()
    if not filename:
        return JSONResponse({"error": "filename is required"}, status_code=400)

    path = UPLOAD_DIR / filename
    if not path.exists():
        return JSONResponse({"error": f"File not found: {filename}"}, status_code=404)

    processor = getattr(request.app.state, "processor", None)
    if processor:
        processor.set_source(str(path))

    return JSONResponse({"message": f"Switched to: {filename}", "path": str(path)})


# ── Live stream WebSocket ─────────────────────────────────────────────────────

@router.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    """Push annotated JPEG frames as base64 JSON messages at stream_fps."""
    from app.config import get_yaml_config
    stream_fps = get_yaml_config().get("processing", {}).get("stream_fps", 30)
    sleep_interval = 1.0 / max(stream_fps, 1)

    await websocket.accept()
    processor = getattr(websocket.app.state, "processor", None)
    try:
        while True:
            if processor and processor.latest_frame is not None:
                _, buf = cv2.imencode(".jpg", processor.latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                b64 = base64.b64encode(buf.tobytes()).decode()
                await websocket.send_json({"type": "frame", "data": b64})
            await asyncio.sleep(sleep_interval)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"Stream WS error: {e}")


# ── Alert push WebSocket ──────────────────────────────────────────────────────

@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """Push alert JSON payloads to connected dashboard clients."""
    await alert_manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        alert_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"Alert WS error: {e}")
        alert_manager.disconnect(websocket)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_placeholder():
    import numpy as np
    img = np.zeros((480, 640, 3), dtype="uint8")
    cv2.putText(img, "No source — upload a video or set RTSP URL",
                (30, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 80), 1)
    cv2.putText(img, "Use the Source panel below the feed",
                (100, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (60, 60, 60), 1)
    return img


def _classify_source(src: str) -> str:
    if not src:
        return "none"
    try:
        int(src)
        return "webcam"
    except ValueError:
        pass
    if src.startswith("rtsp://") or src.startswith("rtmp://"):
        return "rtsp"
    if any(src.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        return "file"
    return "unknown"
