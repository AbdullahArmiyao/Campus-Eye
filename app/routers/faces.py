"""
Campus Eye — Face Registration & Management Router
POST /api/faces/register  – upload photo, generate embedding, store
GET  /api/faces/          – list all registered faces
DELETE /api/faces/{id}    – remove a face
"""
import logging
import shutil
from pathlib import Path

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


@router.post("/register", response_model=FaceRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_face(
    name: str = Form(..., description="Full name of the person"),
    role: UserRole = Form(UserRole.student),
    student_id: str | None = Form(None),
    photo: UploadFile = File(..., description="Clear frontal face photo (JPEG/PNG)"),
    db: AsyncSession = Depends(get_db),
):
    """Register a new face: save photo, generate 512-dim embedding, store in DB."""
    # ── Save photo ────────────────────────────────────────────────────────────
    ext = Path(photo.filename).suffix.lower() if photo.filename else ".jpg"
    if ext not in {".jpg", ".jpeg", ".png"}:
        raise HTTPException(400, "Only JPEG/PNG photos are accepted.")

    photo_path = PHOTO_DIR / f"{name.replace(' ', '_')}_{student_id or 'x'}{ext}"
    with photo_path.open("wb") as f:
        shutil.copyfileobj(photo.file, f)

    # ── Generate embedding ────────────────────────────────────────────────────
    recognizer = get_face_recognizer()
    embedding = recognizer.generate_embedding_from_file(str(photo_path))
    if embedding is None:
        photo_path.unlink(missing_ok=True)
        raise HTTPException(422, "No face detected in the uploaded photo. Please use a clear frontal image.")

    # ── Store User + Embedding ────────────────────────────────────────────────
    user = User(
        name=name,
        role=role,
        student_id=student_id,
        photo_path=str(photo_path),
    )
    db.add(user)
    await db.flush()          # get user.id without committing

    face_emb = FaceEmbedding(
        user_id=user.id,
        embedding=embedding.tolist(),
    )
    db.add(face_emb)
    await db.commit()
    await db.refresh(user)
    await db.refresh(face_emb)

    logger.info(f"Registered face: {name} (id={user.id}, role={role})")
    return FaceRegisterResponse(
        message=f"Face registered successfully for {name}.",
        user_id=user.id,
        embedding_id=face_emb.id,
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
    # Remove photo file
    if user.photo_path:
        Path(user.photo_path).unlink(missing_ok=True)
    await db.delete(user)
    await db.commit()
    logger.info(f"Deleted face: user_id={user_id}")
