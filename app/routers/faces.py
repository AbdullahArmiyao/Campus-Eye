"""
Campus Eye — Face Registration & Management Router
POST /api/faces/register            – upload single photo
POST /api/faces/register-clip       – upload short video clip (multi-angle embeddings)
POST /api/faces/register-webcam     – capture from browser webcam (base64 frames)
GET  /api/faces/                    – list all registered faces
DELETE /api/faces/{id}              – remove a face
"""
import base64
import json
import logging
import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import FaceEmbedding, User, UserRole
from app.pipeline.face_recognition import get_face_recognizer
from app.schemas import FaceRegisterResponse, UserOut

logger = logging.getLogger(__name__)
router = APIRouter()

PHOTO_DIR = Path("media/photos")
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

# Maximum frames to sample from a registration clip
_CLIP_MAX_FRAMES = 60
# Minimum distinct embeddings required to accept a clip registration
_CLIP_MIN_EMBEDDINGS = 3


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_thumbnail(frame: np.ndarray, stem: str) -> Path:
    """Save a single frame as the user's profile thumbnail."""
    thumb_path = PHOTO_DIR / f"{stem}.jpg"
    cv2.imwrite(str(thumb_path), frame)
    return thumb_path


def _extract_embeddings_from_clip(video_path: str) -> tuple[list[np.ndarray], np.ndarray | None]:
    """
    Open a video file, sample up to _CLIP_MAX_FRAMES evenly spaced frames,
    run face detection on each, and return all valid embeddings plus the
    best thumbnail frame (highest detection score).
    """
    recognizer = get_face_recognizer()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return [], None

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        return [], None

    step = max(1, total // _CLIP_MAX_FRAMES)
    embeddings: list[np.ndarray] = []
    best_frame: np.ndarray | None = None
    best_score: float = 0.0

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % step == 0:
            faces = recognizer._app.get(frame) if recognizer._app else []
            for face in faces:
                if face.det_score > 0.5:
                    emb = face.normed_embedding.astype(np.float32)
                    embeddings.append(emb)
                    if face.det_score > best_score:
                        best_score = float(face.det_score)
                        best_frame = frame.copy()
        frame_idx += 1

    cap.release()
    return embeddings, best_frame


async def _persist_user_and_embeddings(
    db: AsyncSession,
    name: str,
    role: str,
    student_id: str | None,
    photo_path: str,
    embeddings: list[np.ndarray],
) -> tuple[User, list[FaceEmbedding]]:
    """Create User + multiple FaceEmbedding rows in one transaction."""
    user = User(name=name, role=role, student_id=student_id, photo_path=photo_path)
    db.add(user)
    await db.flush()

    face_embs: list[FaceEmbedding] = []
    for emb in embeddings:
        fe = FaceEmbedding(user_id=user.id, embedding=emb.tolist())
        db.add(fe)
        face_embs.append(fe)

    await db.commit()
    await db.refresh(user)
    return user, face_embs


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=FaceRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_face(
    name: str = Form(..., description="Full name of the person"),
    role: UserRole = Form(UserRole.student),
    student_id: str | None = Form(None),
    photo: UploadFile = File(..., description="Clear frontal face photo (JPEG/PNG)"),
    db: AsyncSession = Depends(get_db),
):
    """Register a new face from a single photo."""
    ext = Path(photo.filename).suffix.lower() if photo.filename else ".jpg"
    if ext not in {".jpg", ".jpeg", ".png"}:
        raise HTTPException(400, "Only JPEG/PNG photos are accepted.")

    stem = f"{name.replace(' ', '_')}_{student_id or 'x'}"
    photo_path = PHOTO_DIR / f"{stem}{ext}"
    with photo_path.open("wb") as f:
        shutil.copyfileobj(photo.file, f)

    recognizer = get_face_recognizer()
    embedding = recognizer.generate_embedding_from_file(str(photo_path))
    if embedding is None:
        photo_path.unlink(missing_ok=True)
        raise HTTPException(422, "No face detected in the uploaded photo. Please use a clear frontal image.")

    user, face_embs = await _persist_user_and_embeddings(
        db, name, role.value, student_id, str(photo_path), [embedding]
    )
    logger.info(f"Registered face (photo): {name} (id={user.id}, role={role})")
    return FaceRegisterResponse(
        message=f"Face registered successfully for {name} (1 embedding from photo).",
        user_id=user.id,
        embedding_id=face_embs[0].id,
    )


@router.post("/register-clip", response_model=FaceRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_face_from_clip(
    name: str = Form(...),
    role: UserRole = Form(UserRole.student),
    student_id: str | None = Form(None),
    clip: UploadFile = File(..., description="Short video clip of person turning head left to right"),
    db: AsyncSession = Depends(get_db),
):
    """
    Register a face from a short video clip.
    Extracts up to 60 frames, generates an embedding per frame where a face
    is detected, then stores all unique embeddings for robust multi-angle
    recognition. A thumbnail is saved from the best-quality frame.
    """
    allowed = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".wmv"}
    ext = Path(clip.filename).suffix.lower() if clip.filename else ".mp4"
    if ext not in allowed:
        raise HTTPException(400, f"Unsupported video format. Accepted: {', '.join(sorted(allowed))}")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        shutil.copyfileobj(clip.file, tmp)
        tmp_path = tmp.name

    try:
        embeddings, best_frame = _extract_embeddings_from_clip(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if len(embeddings) < _CLIP_MIN_EMBEDDINGS:
        raise HTTPException(
            422,
            f"Only {len(embeddings)} face frame(s) detected in the clip "
            f"(minimum {_CLIP_MIN_EMBEDDINGS} required). "
            "Ensure your face is clearly visible and well-lit throughout the clip."
        )

    stem = f"{name.replace(' ', '_')}_{student_id or 'x'}"
    photo_path = _save_thumbnail(best_frame, stem) if best_frame is not None else PHOTO_DIR / f"{stem}.jpg"

    user, face_embs = await _persist_user_and_embeddings(
        db, name, role.value, student_id, str(photo_path), embeddings
    )
    logger.info(f"Registered face (clip): {name} (id={user.id}, {len(embeddings)} embeddings)")
    return FaceRegisterResponse(
        message=f"Face registered for {name} with {len(embeddings)} multi-angle embeddings from clip.",
        user_id=user.id,
        embedding_id=face_embs[0].id,
    )


@router.post("/register-webcam", response_model=FaceRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_face_from_webcam(
    name: str = Form(...),
    role: UserRole = Form(UserRole.student),
    student_id: str | None = Form(None),
    frames: str = Form(..., description="JSON array of base64-encoded JPEG frames from webcam"),
    db: AsyncSession = Depends(get_db),
):
    """
    Register from one or more webcam-captured frames (sent as base64 JPEGs).
    The frontend captures frames while the user turns their head, then sends
    them all in a single request.
    """
    try:
        frame_list: list[str] = json.loads(frames)
    except Exception:
        raise HTTPException(400, "frames must be a JSON array of base64-encoded JPEG strings.")

    if not frame_list:
        raise HTTPException(400, "No frames provided.")

    recognizer = get_face_recognizer()
    embeddings: list[np.ndarray] = []
    best_frame: np.ndarray | None = None
    best_score: float = 0.0

    for b64 in frame_list:
        try:
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            img_bytes = base64.b64decode(b64)
            arr = np.frombuffer(img_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue
        except Exception:
            continue

        faces = recognizer._app.get(frame) if recognizer._app else []
        for face in faces:
            if face.det_score > 0.5:
                emb = face.normed_embedding.astype(np.float32)
                embeddings.append(emb)
                if face.det_score > best_score:
                    best_score = float(face.det_score)
                    best_frame = frame.copy()

    if not embeddings:
        raise HTTPException(
            422,
            "No face detected in any of the captured frames. "
            "Ensure you are well-lit and facing the camera."
        )

    stem = f"{name.replace(' ', '_')}_{student_id or 'x'}"
    photo_path = _save_thumbnail(best_frame, stem) if best_frame is not None else PHOTO_DIR / f"{stem}.jpg"

    user, face_embs = await _persist_user_and_embeddings(
        db, name, role.value, student_id, str(photo_path), embeddings
    )
    logger.info(f"Registered face (webcam): {name} (id={user.id}, {len(embeddings)} embeddings from {len(frame_list)} frames)")
    return FaceRegisterResponse(
        message=f"Face registered for {name} with {len(embeddings)} embeddings from webcam.",
        user_id=user.id,
        embedding_id=face_embs[0].id,
    )


@router.get("/", response_model=list[UserOut])
async def list_faces(db: AsyncSession = Depends(get_db)):
    """Return all registered persons."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return users


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_face(user_id: int, db: AsyncSession = Depends(get_db)):
    """Remove a registered face (cascades to embeddings)."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, f"User {user_id} not found.")
    if user.photo_path:
        Path(user.photo_path).unlink(missing_ok=True)
    await db.delete(user)
    await db.commit()
    logger.info(f"Deleted face: user_id={user_id}")
