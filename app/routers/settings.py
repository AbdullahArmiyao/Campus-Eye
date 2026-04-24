"""
Campus Eye — Settings Router
GET  /api/settings/mode     – current operating mode
POST /api/settings/mode     – switch mode
GET  /api/settings/schedule – exam schedule
POST /api/settings/schedule – update schedule
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_yaml_config
from app.database import get_db
from app.models import Setting, SystemMode
from app.schemas import ModeResponse, ModeUpdateRequest, ScheduleEntry, ScheduleResponse

logger = logging.getLogger(__name__)
router = APIRouter()

MODE_KEY = "system_mode"


async def _get_setting(db: AsyncSession, key: str, default: str = "") -> str:
    row = await db.get(Setting, key)
    return row.value if row else default


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    row = await db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    await db.commit()


@router.get("/mode", response_model=ModeResponse)
async def get_mode(db: AsyncSession = Depends(get_db)):
    """Return the current operating mode (normal/exam)."""
    yaml_cfg = get_yaml_config()
    default_mode = yaml_cfg.get("mode", {}).get("current", "normal")
    mode_str = await _get_setting(db, MODE_KEY, default_mode)
    return ModeResponse(mode=SystemMode(mode_str))


@router.post("/mode", response_model=ModeResponse)
async def set_mode(req: ModeUpdateRequest, db: AsyncSession = Depends(get_db)):
    """Switch the operating mode and persist to DB."""
    await _set_setting(db, MODE_KEY, req.mode.value)
    logger.info(f"Mode switched to: {req.mode.value}")
    return ModeResponse(mode=req.mode)


@router.get("/schedule", response_model=ScheduleResponse)
async def get_schedule(db: AsyncSession = Depends(get_db)):
    """Return exam schedule (stored in DB, seeded from config.yaml)."""
    raw = await _get_setting(db, "exam_schedule", "")
    if raw:
        entries = [ScheduleEntry(**e) for e in json.loads(raw)]
    else:
        yaml_cfg = get_yaml_config()
        entries = [
            ScheduleEntry(**e)
            for e in yaml_cfg.get("mode", {}).get("schedule", [])
        ]
    return ScheduleResponse(schedule=entries)


@router.post("/schedule", response_model=ScheduleResponse)
async def update_schedule(entries: list[ScheduleEntry], db: AsyncSession = Depends(get_db)):
    """Persist an updated exam schedule."""
    raw = json.dumps([e.model_dump() for e in entries])
    await _set_setting(db, "exam_schedule", raw)
    logger.info(f"Exam schedule updated: {len(entries)} entries.")
    return ScheduleResponse(schedule=entries)
