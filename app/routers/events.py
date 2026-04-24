"""
Campus Eye — Events Router
GET  /api/events/              – paginated event log
POST /api/events/{id}/acknowledge – mark event as seen
"""
import logging
from datetime import datetime

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

    # Total count
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Paginate
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
