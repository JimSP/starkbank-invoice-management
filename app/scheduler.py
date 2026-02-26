import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import config
from app.invoices import issue_batch

logger = logging.getLogger(__name__)


def _job() -> None:
    logger.info("Scheduler tick — issuing invoice batch …")
    try:
        issue_batch()
    except Exception as exc:  # noqa: BLE001
        logger.error("Invoice batch failed: %s", exc)


def start_scheduler() -> BackgroundScheduler:
    end_time  = datetime.now(tz=timezone.utc) + timedelta(hours=config.INVOICE_DURATION_HOURS)
    scheduler = BackgroundScheduler(timezone="UTC")

    scheduler.add_job(
        func=_job,
        id="invoice_batch_initial",
        name="First invoice batch (immediate)",
        max_instances=1,
    )
    scheduler.add_job(
        func=_job,
        trigger=IntervalTrigger(hours=config.INVOICE_INTERVAL_HOURS, timezone="UTC"),
        id="invoice_batch",
        name=f"Invoice batch every {config.INVOICE_INTERVAL_HOURS}h",
        end_date=end_time,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — batches every %dh until %s UTC.",
        config.INVOICE_INTERVAL_HOURS,
        end_time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    return scheduler
