from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


def schedule_job(
    scheduler: AsyncIOScheduler,
    callback,
    interval_days: int,
    schedule_time: str,
    timezone: str,
) -> datetime:
    """(Re)schedule the recurring pipeline job. Safe to call again later with
    new values — replace_existing swaps out the previous job/trigger."""
    tz = ZoneInfo(timezone)
    hour, minute = (int(p) for p in schedule_time.split(":"))

    now = datetime.now(tz)
    first_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if first_run <= now:
        first_run += timedelta(days=1)

    scheduler.add_job(
        callback,
        trigger=IntervalTrigger(days=interval_days, start_date=first_run),
        id="pipeline_job",
        replace_existing=True,
    )
    logger.info("Scheduled pipeline job: every %s day(s), first run at %s", interval_days, first_run)
    return first_run


def build_scheduler(
    callback,
    interval_days: int,
    schedule_time: str,
    timezone: str,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(timezone))
    schedule_job(scheduler, callback, interval_days, schedule_time, timezone)
    return scheduler
