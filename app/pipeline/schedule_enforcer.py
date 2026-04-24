"""
Campus Eye — Schedule Enforcer
Reads the exam schedule from config.yaml and determines whether the system
should automatically be in 'exam' or 'normal' mode based on the current time.
"""
import logging
from datetime import datetime

from app.config import get_yaml_config

logger = logging.getLogger(__name__)


class ScheduleEnforcer:
    """
    Checks the current time against the schedule defined in config.yaml.
    Returns the scheduled mode for the current moment.
    Used by the FrameProcessor to auto-switch modes.
    """

    def __init__(self):
        self._schedule: list[dict] = get_yaml_config().get("mode", {}).get("schedule", [])
        self._last_scheduled_mode: str | None = None
        if self._schedule:
            logger.info(f"Schedule enforcer loaded {len(self._schedule)} time window(s).")
        else:
            logger.info("No exam schedule configured — schedule enforcement disabled.")

    def get_scheduled_mode(self) -> str | None:
        """
        Returns 'exam' or 'normal' if the current time falls in a scheduled window,
        or None if no schedule is configured (manual mode stays in effect).
        """
        if not self._schedule:
            return None

        now = datetime.now()
        day_name = now.strftime("%A")          # e.g. "Monday"
        current_hm = now.strftime("%H:%M")    # e.g. "09:30"

        for entry in self._schedule:
            if entry.get("day") == day_name:
                start = entry.get("start", "00:00")
                end   = entry.get("end",   "23:59")
                if start <= current_hm <= end:
                    return entry.get("mode", "exam")

        return "normal"

    def should_override(self) -> tuple[bool, str]:
        """
        Returns (should_override: bool, target_mode: str).

        should_override is True ONLY when the current time falls inside a
        scheduled EXAM window — never when we're between windows.
        Outside exam hours, manual mode switches are always respected.
        """
        if not self._schedule:
            return False, "normal"

        now = datetime.now()
        day_name = now.strftime("%A")
        current_hm = now.strftime("%H:%M")

        for entry in self._schedule:
            if entry.get("day") == day_name:
                start = entry.get("start", "00:00")
                end   = entry.get("end",   "23:59")
                if start <= current_hm <= end:
                    scheduled = entry.get("mode", "exam")
                    logger.info(f"[SCHEDULE] In exam window ({day_name} {start}–{end}), enforcing {scheduled.upper()}")
                    return True, scheduled

        # Outside all exam windows — do NOT override manual mode choice
        return False, "normal"

