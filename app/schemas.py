"""
Campus Eye — Pydantic Schemas (Request / Response)
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models import EventType, SystemMode, UserRole


# ── User / Face ───────────────────────────────────────────────────────────────

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: UserRole
    student_id: str | None = None
    photo_path: str | None = None
    created_at: datetime


class FaceRegisterResponse(BaseModel):
    message: str
    user_id: int
    embedding_id: int


# ── Events ────────────────────────────────────────────────────────────────────

class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: str
    event_type: EventType
    mode: SystemMode
    snapshot_path: str | None = None
    clip_path: str | None = None
    description: str | None = None
    meta: dict[str, Any] | None = None
    acknowledged: bool
    created_at: datetime


class EventListResponse(BaseModel):
    total: int
    items: list[EventOut]


class AcknowledgeResponse(BaseModel):
    message: str
    event_id: int


# ── Settings ──────────────────────────────────────────────────────────────────

class ModeResponse(BaseModel):
    mode: SystemMode


class ModeUpdateRequest(BaseModel):
    mode: SystemMode


class ScheduleEntry(BaseModel):
    day: str
    start: str
    end: str
    mode: SystemMode


class ScheduleResponse(BaseModel):
    schedule: list[ScheduleEntry]


# ── Alerts (WebSocket push payload) ──────────────────────────────────────────

class AlertPayload(BaseModel):
    event_id: int
    event_type: str
    mode: str
    camera_id: str
    description: str | None = None
    snapshot_url: str | None = None
    clip_url: str | None = None      # added: matches processor broadcast payload
    timestamp: str
