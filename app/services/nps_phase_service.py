"""Admin-defined survey phase timeline + cadence-driven notifications.

Generalizes the single ``program_status`` date set into an ordered list of
admin-defined PHASES per org+cycle. Each phase has a name, an audience, a
cadence, and start/end dates. While a phase is active, the scheduler
(``nps_scheduler.phase_send_job``) dispatches that phase's notification to
its audience on the configured cadence, reusing the existing leader
(``nps_leader_service``) and stakeholder (``nps_distribution_service``)
delivery paths — so ``NPS_DEMO_SAFE`` and per-leader ``notify_alias``
controls are inherited unchanged.

Persistence mirrors ``nps_settings_service``: one JSON blob in a
``__phase_schedule__`` system row of NpsOrgConfig, keyed
``org_id -> cycle_id -> [phase, ...]`` (whole-blob, last-write-wins,
admin-only). No new table / IAM change.
"""

import json
import logging
import os
import uuid
from datetime import date, datetime, timezone

import boto3

logger = logging.getLogger(__name__)

PHASE_SCHEDULE_KEY = "__phase_schedule__"
MAX_BLOB_BYTES = 200_000

VALID_AUDIENCE_TYPES = (
    "leaders",
    "stakeholders",
    "leaders-response-summary",
    "non-responders",
)
VALID_CADENCES = ("once", "daily", "alternate_day", "weekly", "manual")
CADENCE_INTERVAL_DAYS = {"daily": 1, "alternate_day": 2, "weekly": 7}


def _get_table():
    table_name = os.environ.get("NPS_ORG_CONFIG_TABLE", "NpsOrgConfig")
    return boto3.resource("dynamodb").Table(table_name)


# ── validation ────────────────────────────────────────────────────────


def validate_phase(phase: dict) -> None:
    """Raise ValueError (naming the phase) if the phase is invalid."""
    name = (phase.get("name") or "").strip()
    label = name or "(unnamed phase)"
    if not name:
        raise ValueError("Phase name is required")
    if phase.get("audience_type") not in VALID_AUDIENCE_TYPES:
        raise ValueError(f"Phase '{label}': invalid audience_type")
    if phase.get("cadence") not in VALID_CADENCES:
        raise ValueError(f"Phase '{label}': invalid cadence")
    start = (phase.get("start_date") or "").strip()
    end = (phase.get("end_date") or "").strip()
    if not start or not end:
        raise ValueError(f"Phase '{label}': start_date and end_date are required")
    try:
        if date.fromisoformat(end) < date.fromisoformat(start):
            raise ValueError(f"Phase '{label}': end_date is before start_date")
    except ValueError as exc:
        # re-raise our message, or a parse error
        if "end_date is before" in str(exc):
            raise
        raise ValueError(f"Phase '{label}': dates must be ISO YYYY-MM-DD") from exc


def _normalize_phase(phase: dict, order: int) -> dict:
    """Return a clean, persisted phase dict (assigns id + order, keeps state)."""
    return {
        "id": (phase.get("id") or str(uuid.uuid4())),
        "name": (phase.get("name") or "").strip(),
        "audience_type": phase.get("audience_type"),
        "cadence": phase.get("cadence"),
        "start_date": (phase.get("start_date") or "").strip(),
        "end_date": (phase.get("end_date") or "").strip(),
        "order": order,
        "last_sent": (phase.get("last_sent") or "").strip(),
        "sent_once": bool(phase.get("sent_once", False)),
    }


# ── persistence (whole-blob, last-write-wins) ──────────────────────────


def _load_blob() -> dict:
    item = _get_table().get_item(Key={"org_id": PHASE_SCHEDULE_KEY}).get("Item")
    if item and item.get("data"):
        try:
            data = json.loads(item["data"])
            if isinstance(data, dict):
                return data
        except (TypeError, ValueError):
            pass
    return {}


def _save_blob(blob: dict, updated_by: str) -> None:
    raw = json.dumps(blob)
    if len(raw.encode("utf-8")) > MAX_BLOB_BYTES:
        raise ValueError("phase schedule too large")
    _get_table().put_item(Item={
        "org_id": PHASE_SCHEDULE_KEY,
        "org_name": "Phase schedules (system record)",
        "data": raw,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": (updated_by or "").strip().lower(),
        "is_active": True,
    })


def get_phase_sequence(org_id: str, cycle_id: str) -> list[dict]:
    """Ordered phase list for org+cycle ([] when none)."""
    org_id = (org_id or "").strip()
    cycle_id = (cycle_id or "").strip()
    phases = (_load_blob().get(org_id, {}) or {}).get(cycle_id, [])
    return sorted(phases, key=lambda p: p.get("order", 0)) if isinstance(phases, list) else []


def save_phase_sequence(org_id: str, cycle_id: str, phases: list, updated_by: str = "") -> list[dict]:
    """Validate + persist the whole phase sequence for org+cycle."""
    org_id = (org_id or "").strip()
    cycle_id = (cycle_id or "").strip()
    if not org_id or not cycle_id:
        raise ValueError("org_id and cycle_id are required")
    if not isinstance(phases, list):
        raise ValueError("phases must be a list")

    normalized = []
    for i, phase in enumerate(phases):
        if not isinstance(phase, dict):
            raise ValueError("each phase must be an object")
        validate_phase(phase)
        normalized.append(_normalize_phase(phase, i))

    blob = _load_blob()
    blob.setdefault(org_id, {})[cycle_id] = normalized
    _save_blob(blob, updated_by)
    return normalized


def update_phase_send_state(org_id: str, cycle_id: str, phase_id: str,
                            last_sent: str = "", sent_once: bool = None) -> None:
    """Update one phase's send-tracking state (whole-blob re-save)."""
    org_id = (org_id or "").strip()
    cycle_id = (cycle_id or "").strip()
    blob = _load_blob()
    phases = (blob.get(org_id, {}) or {}).get(cycle_id, [])
    changed = False
    for phase in phases:
        if phase.get("id") == phase_id:
            if last_sent:
                phase["last_sent"] = last_sent
            if sent_once is not None:
                phase["sent_once"] = bool(sent_once)
            changed = True
            break
    if changed:
        _save_blob(blob, updated_by="scheduler")


# ── cadence evaluation (pure) ──────────────────────────────────────────


def is_active_phase(phase: dict, today: date) -> bool:
    """True when start_date <= today <= end_date."""
    try:
        start = date.fromisoformat((phase.get("start_date") or "").strip())
        end = date.fromisoformat((phase.get("end_date") or "").strip())
    except ValueError:
        return False
    return start <= today <= end


def phase_send_due(phase: dict, now: datetime = None) -> bool:
    """True when this phase should send at ``now``."""
    now = now or datetime.now(timezone.utc)
    if not is_active_phase(phase, now.date()):
        return False
    cadence = phase.get("cadence")
    if cadence == "manual":
        return False
    if cadence == "once":
        return not phase.get("sent_once", False)
    days = CADENCE_INTERVAL_DAYS.get(cadence)
    if not days:
        return False
    last = (phase.get("last_sent") or "").strip()
    if not last:
        return True
    try:
        elapsed = (now - datetime.fromisoformat(last)).total_seconds()
    except ValueError:
        return True
    return elapsed >= days * 86400


# ── audit ───────────────────────────────────────────────────────────────


def _write_audit(org_id, cycle_id, phase, trigger_type, recipient_count, outcome, error=""):
    """Write a Send_Audit_Record onto the existing NpsReminderLogs table."""
    from app.db import nps_reminder_log_repo
    from app.db.models import ReminderLog

    try:
        nps_reminder_log_repo.put_log(ReminderLog(
            org_id=org_id,
            cycle_id=cycle_id,
            log_id=str(uuid.uuid4()),
            sent_at=datetime.now(timezone.utc).isoformat(),
            trigger_type=trigger_type,
            recipient_count=int(recipient_count or 0),
            channels=[],
            failures=json.dumps({
                "kind": "phase",
                "phase": phase.get("name", ""),
                "audience_type": phase.get("audience_type", ""),
                "outcome": outcome,
                "error": error,
            }),
        ))
    except Exception:  # audit must never break a send
        logger.exception("phase audit write failed org=%s phase=%s", org_id, phase.get("name"))


# ── dispatch ──────────────────────────────────────────────────────────


def dispatch_phase(org_id: str, cycle_id: str, phase: dict, base_url: str,
                   trigger_type: str = "automated") -> dict:
    """Send a phase's notification to its audience; persist state + audit."""
    from app.services import (
        nps_distribution_service,
        nps_leader_service,
        nps_nomination_service,
    )
    from app.services.nomination_keys import base_email

    audience = phase.get("audience_type")
    result = {"phase_id": phase.get("id"), "audience_type": audience,
              "recipient_count": 0, "status": "sent", "error": ""}

    try:
        if audience == "leaders":
            r = nps_leader_service.send_leader_reminders(base_url, org_id)
            result["recipient_count"] = r.get("email_sent", 0) + r.get("slack_sent", 0)
        elif audience == "leaders-response-summary":
            r = nps_leader_service.send_response_summary(base_url, org_id, cycle_id)
            result["recipient_count"] = r.get("email_sent", 0) + r.get("slack_sent", 0)
        elif audience == "stakeholders":
            r = nps_distribution_service.send_reminder(org_id, cycle_id, trigger_type=trigger_type)
            result["recipient_count"] = r.email_sent_count + r.slack_sent_count
        elif audience == "non-responders":
            emails = sorted({
                base_email(n.email).lower()
                for n in nps_nomination_service.get_reminder_list(org_id, cycle_id)
                if base_email(n.email)
            })
            if not emails:
                _write_audit(org_id, cycle_id, phase, trigger_type, 0, "zero_recipient")
                result["status"] = "zero_recipient"
                return result
            r = nps_distribution_service.send_targeted_reminder(
                org_id, cycle_id, emails, trigger_type=trigger_type)
            result["recipient_count"] = r.email_sent_count + r.slack_sent_count
        else:
            raise ValueError(f"unknown audience_type: {audience}")
    except Exception as exc:
        _write_audit(org_id, cycle_id, phase, trigger_type, 0, "failed", str(exc))
        result["status"] = "failed"
        result["error"] = str(exc)
        return result

    # success — advance send state, then audit
    update_phase_send_state(
        org_id, cycle_id, phase.get("id"),
        last_sent=datetime.now(timezone.utc).isoformat(),
        sent_once=True if phase.get("cadence") == "once" else None,
    )
    _write_audit(org_id, cycle_id, phase, trigger_type, result["recipient_count"], "sent")
    return result


def dispatch_phase_by_id(org_id: str, cycle_id: str, phase_id: str, base_url: str,
                         trigger_type: str = "manual") -> dict:
    """Look up a phase by id and dispatch it (used by the manual send route)."""
    for phase in get_phase_sequence(org_id, cycle_id):
        if phase.get("id") == phase_id:
            return dispatch_phase(org_id, cycle_id, phase, base_url, trigger_type)
    raise ValueError(f"Phase '{phase_id}' not found for {org_id}/{cycle_id}")
