from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from family_newsletter.app.config import Settings
from family_newsletter.app.newsletter.delivery import deliver_newsletter


logger = logging.getLogger(__name__)


def create_scheduler() -> BackgroundScheduler:
    return BackgroundScheduler()


def _parse_send_time(send_time: str) -> tuple[int, int]:
    hour_str, _, minute_str = send_time.partition(":")
    return int(hour_str), int(minute_str or 0)


def _daily_job(settings: Settings, dry_run: bool) -> None:
    try:
        result = deliver_newsletter(settings, dry_run=dry_run)
        logger.info("Daily newsletter run complete: %s", result)
    except Exception:  # noqa: BLE001 - keep the scheduler alive across failures
        logger.exception("Daily newsletter run failed")


def schedule_daily_send(
    scheduler: BackgroundScheduler | BlockingScheduler,
    settings: Settings,
    *,
    dry_run: bool = False,
) -> None:
    """Register the daily regenerate-and-send job at the configured local time."""
    hour, minute = _parse_send_time(settings.newsletter_send_time)
    trigger = CronTrigger(
        hour=hour,
        minute=minute,
        timezone=settings.newsletter_timezone,
    )
    scheduler.add_job(
        _daily_job,
        trigger=trigger,
        args=[settings, dry_run],
        id="daily_newsletter",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info(
        "Scheduled daily newsletter at %02d:%02d %s (dry_run=%s)",
        hour,
        minute,
        settings.newsletter_timezone,
        dry_run,
    )


def run_blocking(settings: Settings, *, dry_run: bool = False) -> None:
    """Run a foreground scheduler that fires the daily job forever."""
    scheduler = BlockingScheduler()
    schedule_daily_send(scheduler, settings, dry_run=dry_run)
    logger.info("Scheduler started; press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
