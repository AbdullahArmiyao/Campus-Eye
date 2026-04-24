"""
Campus Eye — SQLAlchemy ORM Models
"""
import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ── Enums ─────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    student = "student"
    invigilator = "invigilator"
    staff = "staff"
    unknown = "unknown"


class SystemMode(str, enum.Enum):
    normal = "normal"
    exam = "exam"


class EventType(str, enum.Enum):
    # Normal mode
    loitering          = "loitering"
    littering          = "littering"
    vandalism          = "vandalism"
    unknown_face       = "unknown_face"
    weapon             = "weapon"             # knife / sharp object on campus
    vehicle_intrusion  = "vehicle_intrusion"  # bicycle / motorcycle in pedestrian zone
    overcrowding       = "overcrowding"       # too many people in one area
    alcohol            = "alcohol"            # bottle / wine glass detected
    # Exam mode
    foreign_object     = "foreign_object"
    head_swiveling     = "head_swiveling"
    talking            = "talking"
    hand_interaction   = "hand_interaction"
    drink_in_exam      = "drink_in_exam"      # food/drink brought into exam hall
    crowd_cheat        = "crowd_cheat"        # cluster of students huddled together


# ── Models ────────────────────────────────────────────────────────────────────

class User(Base):
    """Registered person (student / invigilator / staff)."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=UserRole.student.value)
    photo_path: Mapped[str | None] = mapped_column(String(512))
    student_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    embeddings: Mapped[list["FaceEmbedding"]] = relationship(
        "FaceEmbedding", back_populates="user", cascade="all, delete-orphan"
    )


class FaceEmbedding(Base):
    """512-dimensional face embedding stored in pgvector."""
    __tablename__ = "face_embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="embeddings")


class Event(Base):
    """Detected security/exam event with snapshot."""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    camera_id: Mapped[str] = mapped_column(String(64), nullable=False, default="cam_01")
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_path: Mapped[str | None] = mapped_column(String(512))
    clip_path: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Setting(Base):
    """Key-value runtime settings store."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
