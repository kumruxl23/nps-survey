"""Service layer for NPS survey cycle management.

Delegates persistence to app.db.nps_cycle_repo and adds validation,
status transitions, and reminder mode configuration.
"""

import uuid

from app.db import nps_cycle_repo
from app.db.models import SurveyCycle
from app.services import nps_org_config_service

_VALID_REMINDER_MODES = ("daily", "alternate_day", "weekly", "manual")


def create_cycle(org_id: str, start_date: str, end_date: str, cycle_name: str = "") -> SurveyCycle:
    """Create a new survey cycle for an org.

    Generates a UUID for cycle_id, copies asana_project_gid and
    asana_form_url from OrgConfig, sets status='active' and
    reminder_mode='manual'.

    Raises ValueError if end_date <= start_date or org not found / inactive.
    """
    if end_date <= start_date:
        raise ValueError("end_date must be after start_date")

    org = nps_org_config_service.get_org(org_id)
    if org is None:
        raise ValueError(f"Org with id '{org_id}' not found")
    if not org.is_active:
        raise ValueError(f"Org with id '{org_id}' is not active")

    cycle = SurveyCycle(
        org_id=org_id,
        cycle_id=str(uuid.uuid4()),
        start_date=start_date,
        end_date=end_date,
        status="active",
        reminder_mode="manual",
        asana_project_gid=org.asana_project_gid,
        asana_form_url=org.asana_form_url,
        cycle_name=cycle_name,
    )
    nps_cycle_repo.put_cycle(cycle)
    return nps_cycle_repo.get_cycle(org_id, cycle.cycle_id)


def close_cycle(org_id: str, cycle_id: str) -> None:
    """Close a survey cycle by setting status='closed'.

    Raises ValueError if cycle not found.
    """
    cycle = nps_cycle_repo.get_cycle(org_id, cycle_id)
    if cycle is None:
        raise ValueError(f"Cycle '{cycle_id}' not found for org '{org_id}'")

    nps_cycle_repo.update_cycle(org_id, cycle_id, status="closed")


def get_active_cycle(org_id: str) -> SurveyCycle | None:
    """Return the active cycle for an org, or None if no active cycle exists."""
    cycles = nps_cycle_repo.list_cycles(org_id)
    for cycle in cycles:
        if cycle.status == "active":
            return cycle
    return None


def list_cycles(org_id: str) -> list[SurveyCycle]:
    """Return all cycles for an org."""
    return nps_cycle_repo.list_cycles(org_id)


def is_cycle_active(cycle: SurveyCycle) -> bool:
    """Check whether a cycle is active."""
    return cycle.status == "active"


def update_reminder_mode(org_id: str, cycle_id: str, mode: str) -> None:
    """Update the reminder mode for a cycle.

    Validates mode is one of: daily, alternate_day, weekly, manual.
    Raises ValueError if mode is invalid or cycle not found.
    """
    if mode not in _VALID_REMINDER_MODES:
        raise ValueError(
            f"Invalid reminder mode '{mode}'. "
            f"Must be one of: {', '.join(_VALID_REMINDER_MODES)}"
        )

    cycle = nps_cycle_repo.get_cycle(org_id, cycle_id)
    if cycle is None:
        raise ValueError(f"Cycle '{cycle_id}' not found for org '{org_id}'")

    nps_cycle_repo.update_cycle(org_id, cycle_id, reminder_mode=mode)
