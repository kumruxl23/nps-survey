"""NPS reminder scheduler using APScheduler.

Provides the should_send_reminder logic and a BackgroundScheduler job
that iterates active orgs/cycles and triggers automated reminders.
"""

import logging
import os
from datetime import date, datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db.models import SurveyCycle

logger = logging.getLogger(__name__)


def should_send_reminder(cycle: SurveyCycle, now: datetime = None) -> bool:
    """Determine whether a reminder should be sent for the given cycle.

    Checks that the cycle is active, not in manual mode, has been
    distributed, is not past its end_date, and enough time has elapsed
    since the last reminder (or distribution if no prior reminder).

    Args:
        cycle: The survey cycle to evaluate.
        now: Optional current time for testability. Defaults to UTC now.

    Returns:
        True if a reminder should be sent, False otherwise.
    """
    if cycle.status != "active":
        return False
    if cycle.reminder_mode == "manual":
        return False
    if not cycle.distributed_at:
        return False

    now = now or datetime.now(timezone.utc)

    if now.date() > date.fromisoformat(cycle.end_date):
        return False

    interval_days = {"daily": 1, "alternate_day": 2, "weekly": 7}
    days = interval_days[cycle.reminder_mode]

    if not cycle.last_reminder_at:
        dist_time = datetime.fromisoformat(cycle.distributed_at)
        return (now - dist_time).total_seconds() >= days * 86400

    last = datetime.fromisoformat(cycle.last_reminder_at)
    return (now - last).total_seconds() >= days * 86400


def reminder_check_job():
    """Scheduled job: iterate active orgs and send reminders where due.

    For each active org with an active cycle that is not in manual mode,
    checks should_send_reminder and triggers an automated reminder if True.
    """
    from app.services import nps_cycle_service, nps_distribution_service, nps_org_config_service

    try:
        active_orgs = nps_org_config_service.list_active_orgs()
    except Exception:
        logger.exception("Failed to list active orgs in reminder_check_job")
        return

    for org in active_orgs:
        try:
            cycle = nps_cycle_service.get_active_cycle(org.org_id)
            if not cycle or cycle.reminder_mode == "manual":
                continue
            if should_send_reminder(cycle):
                nps_distribution_service.send_reminder(
                    org.org_id, cycle.cycle_id, trigger_type="automated"
                )
        except Exception:
            logger.exception(
                "Error processing reminders for org '%s'", org.org_id
            )


def _phase_base_url() -> str:
    """Public base URL for links in phase notifications (no request context)."""
    return os.environ.get("NPS_PUBLIC_BASE_URL", "https://nps.whs-cpt.amazon.dev").rstrip("/")


def phase_send_job(now: datetime = None):
    """Scheduled job: dispatch due survey phases across active orgs/cycles.

    Runs alongside reminder_check_job. For each active org's active cycle,
    evaluates every phase in the admin-defined sequence and dispatches those
    whose cadence is due. Per-org and per-phase errors are contained so one
    failure never halts the loop.
    """
    from app.services import nps_cycle_service, nps_org_config_service, nps_phase_service

    now = now or datetime.now(timezone.utc)
    try:
        active_orgs = nps_org_config_service.list_active_orgs()
    except Exception:
        logger.exception("Failed to list active orgs in phase_send_job")
        return

    base_url = _phase_base_url()
    for org in active_orgs:
        try:
            cycle = nps_cycle_service.get_active_cycle(org.org_id)
            if not cycle:
                continue
            phases = nps_phase_service.get_phase_sequence(org.org_id, cycle.cycle_id)
            for phase in phases:
                try:
                    if nps_phase_service.phase_send_due(phase, now):
                        nps_phase_service.dispatch_phase(
                            org.org_id, cycle.cycle_id, phase, base_url,
                            trigger_type="automated",
                        )
                except Exception:
                    logger.exception(
                        "phase dispatch failed org=%s phase=%s",
                        org.org_id, phase.get("name"),
                    )
        except Exception:
            logger.exception("phase_send_job failed for org '%s'", org.org_id)


def init_scheduler(app):
    """Initialize the APScheduler BackgroundScheduler within the Flask app.

    Reads NPS_SCHEDULER_INTERVAL_MINUTES from the environment (default 60).
    The scheduler is not started when TESTING is truthy in the app config.

    Args:
        app: The Flask application instance.
    """
    if app.config.get("TESTING"):
        return None

    interval_minutes = int(os.environ.get("NPS_SCHEDULER_INTERVAL_MINUTES", "60"))

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        reminder_check_job,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="nps_reminder_check",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        phase_send_job,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="nps_phase_send",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "NPS reminder scheduler started with interval=%d minutes",
        interval_minutes,
    )
    return scheduler
