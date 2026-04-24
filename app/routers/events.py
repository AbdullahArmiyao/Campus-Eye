"""
Campus Eye — Events Router
GET    /api/events/                   – paginated event log
POST   /api/events/{id}/acknowledge   – mark event as seen
DELETE /api/events/                   – clear all events (optional: ?acknowledged_only=true)
DELETE /api/events/{id}               – delete a single event
"""
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Event, EventType, SystemMode
from app.schemas import AcknowledgeResponse, EventListResponse, EventOut

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_model=EventListResponse)
async def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    event_type: EventType | None = Query(None),
    mode: SystemMode | None = Query(None),
    camera_id: str | None = Query(None),
    acknowledged: bool | None = Query(None),
    since: datetime | None = Query(None, description="ISO8601 timestamp — return events after this time"),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated, filterable event log."""
    q = select(Event).order_by(Event.created_at.desc())

    if event_type:
        q = q.where(Event.event_type == event_type.value)
    if mode:
        q = q.where(Event.mode == mode.value)
    if camera_id:
        q = q.where(Event.camera_id == camera_id)
    if acknowledged is not None:
        q = q.where(Event.acknowledged == acknowledged)
    if since:
        q = q.where(Event.created_at >= since)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(q)).scalars().all()

    return EventListResponse(total=total, items=items)


@router.post("/{event_id}/acknowledge", response_model=AcknowledgeResponse)
async def acknowledge_event(event_id: int, db: AsyncSession = Depends(get_db)):
    """Mark an event as acknowledged (seen by operator)."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, f"Event {event_id} not found.")
    event.acknowledged = True
    await db.commit()
    logger.info(f"Event {event_id} acknowledged.")
    return AcknowledgeResponse(message="Event acknowledged.", event_id=event_id)


@router.get("/{event_id}", response_model=EventOut)
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, f"Event {event_id} not found.")
    return event


@router.delete("/", status_code=200)
async def clear_events(
    acknowledged_only: bool = Query(False, description="Only delete already-acknowledged events"),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete events from the database and their associated snapshot/clip files.
    Pass ?acknowledged_only=true to only remove events already marked as seen.
    """
    q = select(Event)
    if acknowledged_only:
        q = q.where(Event.acknowledged == True)  # noqa: E712
    events = (await db.execute(q)).scalars().all()

    deleted = 0
    for ev in events:
        for path_attr in (ev.snapshot_path, ev.clip_path):
            if path_attr:
                Path(path_attr).unlink(missing_ok=True)
        await db.delete(ev)
        deleted += 1

    await db.commit()
    logger.info(f"Cleared {deleted} event(s) (acknowledged_only={acknowledged_only})")
    return {"deleted": deleted, "message": f"{deleted} event(s) cleared."}


@router.delete("/{event_id}", status_code=200)
async def delete_event(event_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a single event and its associated snapshot/clip files."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, f"Event {event_id} not found.")
    for path_attr in (event.snapshot_path, event.clip_path):
        if path_attr:
            Path(path_attr).unlink(missing_ok=True)
    await db.delete(event)
    await db.commit()
    logger.info(f"Deleted event {event_id}.")
    return {"deleted": event_id, "message": f"Event {event_id} deleted."}
