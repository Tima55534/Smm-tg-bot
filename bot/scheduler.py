from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
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


def schedule_daily_job(
    scheduler: AsyncIOScheduler,
    callback,
    time_str: str,
    timezone: str,
    job_id: str,
) -> None:
    """Run `callback` every day at `time_str` (HH:MM), in `timezone`. Used for
    the publish-time check, which is intentionally daily and independent of
    interval_days — it just sends out whatever has been approved."""
    tz = ZoneInfo(timezone)
    hour, minute = (int(p) for p in time_str.split(":"))
    scheduler.add_job(
        callback,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
        id=job_id,
        replace_existing=True,
    )
    logger.info("Scheduled daily job %r at %s (%s)", job_id, time_str, timezone)


def build_scheduler(
    callback,
    interval_days: int,
    schedule_time: str,
    timezone: str,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(timezone))
    schedule_job(scheduler, callback, interval_days, schedule_time, timezone)
    return scheduler
