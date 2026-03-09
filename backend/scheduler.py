import logging
from apscheduler.schedulers.background import BackgroundScheduler
from backend.config import get_config
from backend.indexer import run_index

logger = logging.getLogger(__name__)

_scheduler = None


def start_scheduler():
    global _scheduler
    config = get_config()
    hour = config.get("schedule_hour", 2)
    minute = config.get("schedule_minute", 0)

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        run_index,
        "cron",
        hour=hour,
        minute=minute,
        id="nightly_index",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduled nightly indexing at %02d:%02d", hour, minute)

    next_run = _scheduler.get_job("nightly_index").next_run_time
    if next_run:
        logger.info("Next scheduled index: %s", next_run.strftime("%Y-%m-%d %H:%M:%S"))


def stop_scheduler():
    global _scheduler
    if _scheduler:
        logger.info("Stopping scheduler")
        _scheduler.shutdown(wait=False)
        _scheduler = None
