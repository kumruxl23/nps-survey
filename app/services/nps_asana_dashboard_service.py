"""LIVE dashboard data from Asana's "Ongoing Survey" section.

Unlike nps_dashboard_service (which reads responses previously recorded in
DynamoDB), this service pulls the org's Asana project directly, so the
dashboard reflects what is in Asana RIGHT NOW. Only tasks in the project's
"Ongoing Survey" section are considered (archived per-cycle sections are
ignored), further filtered to the cycle's date window by task created_at.

Nominations remain DynamoDB-sourced — the nomination table is still the
source of truth for who was invited, and the response rate denominator.

Per-task fields used (see infra/tmp_asana_probe.py for the same pattern):
- score: org's custom_field_nps_score_gid -> number_value
- leader: org's custom_field_leader_gid -> display_value
- created_at: cycle-window filter
- completed_at: action-tracker status; a task with no completed_at is
  "incomplete", and "overdue" once the cycle's action_due_date has passed.

Score bands: Promoter 9-10, Passive 7-8, Detractor 0-6.
NPS = promoters/total_scored*100 - detractors/total_scored*100.
"""

import re
from datetime import datetime, timezone

from app.db import nps_cycle_repo, nps_nomination_repo
from app.services import asana_client, nps_org_config_service

# Matched case-insensitively against Asana section names.
ONGOING_SECTION_NAME = "Ongoing Survey"

_OPT_FIELDS = (
    "created_at,completed_at,"
    "custom_fields.gid,custom_fields.number_value,custom_fields.display_value"
)

_UNASSIGNED = "Unassigned"


# ── loading / normalization helpers ──────────────────────────────────


def _load_org(org_id: str):
    org = nps_org_config_service.get_org(org_id)
    if org is None:
        raise ValueError(f"Org '{org_id}' not found")
    return org


def _load_cycle(org_id: str, cycle_id: str):
    cycle = nps_cycle_repo.get_cycle(org_id, cycle_id)
    if cycle is None:
        raise ValueError(f"Cycle '{cycle_id}' not found for org '{org_id}'")
    return cycle


def _find_ongoing_section_gid(project_gid: str) -> str:
    """GID of the project's "Ongoing Survey" section (case-insensitive)."""
    for section in asana_client.list_sections(project_gid):
        if (section.get("name") or "").strip().lower() == ONGOING_SECTION_NAME.lower():
            return section["gid"]
    raise ValueError(
        f"No '{ONGOING_SECTION_NAME}' section found in Asana project {project_gid}"
    )


def _score_from_task(task: dict, score_gid: str) -> int | None:
    for cf in task.get("custom_fields") or []:
        if cf.get("gid") == score_gid:
            value = cf.get("number_value")
            if value is None and cf.get("display_value") not in (None, ""):
                try:
                    value = float(cf["display_value"])
                except ValueError:
                    return None
            return None if value is None else int(value)
    return None


def _leader_from_task(task: dict, leader_gid: str) -> str:
    if not leader_gid:
        return ""
    for cf in task.get("custom_fields") or []:
        if cf.get("gid") == leader_gid:
            return (cf.get("display_value") or "").strip()
    return ""


def _today() -> str:
    """Today's ISO date (UTC). Separate function so tests can freeze it."""
    return datetime.now(timezone.utc).date().isoformat()


def _fetch_cycle_tasks(org_id: str, cycle_id: str) -> list[dict]:
    """Normalized "Ongoing Survey" tasks inside the cycle window.

    Returns [{score, leader, created_at, completed, overdue}]. ``score`` is
    None when the task has no NPS score yet. ``overdue`` is True only when
    the task is incomplete AND the cycle has an action_due_date in the past
    (no due date configured = nothing is overdue).
    """
    org = _load_org(org_id)
    cycle = _load_cycle(org_id, cycle_id)
    if not org.asana_project_gid:
        raise ValueError(f"Org '{org_id}' has no Asana project configured")

    section_gid = _find_ongoing_section_gid(org.asana_project_gid)
    tasks = asana_client.list_tasks_in_section(section_gid, opt_fields=_OPT_FIELDS)

    lo = cycle.start_date or ""
    hi = (cycle.end_date or "") + "~"  # '~' sorts after any date char
    due = (cycle.action_due_date or "").strip()
    due_passed = bool(due) and _today() > due

    out = []
    for task in tasks:
        created = (task.get("created_at") or "")[:10]
        if not (lo <= created <= hi):
            continue
        completed = bool(task.get("completed_at"))
        out.append({
            "score": _score_from_task(task, org.custom_field_nps_score_gid),
            "leader": _leader_from_task(task, org.custom_field_leader_gid),
            "created_at": created,
            "completed": completed,
            "overdue": (not completed) and due_passed,
        })
    return out


def _band(score: int) -> str:
    if score >= 9:
        return "promoter"
    if score >= 7:
        return "passive"
    return "detractor"


def _nps(promoters: int, detractors: int, total_scored: int) -> float:
    if not total_scored:
        return 0.0
    return round(
        promoters / total_scored * 100 - detractors / total_scored * 100, 1
    )


def _group_by_leader(tasks: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for task in tasks:
        groups.setdefault(task["leader"] or _UNASSIGNED, []).append(task)
    return groups


# ── public API ────────────────────────────────────────────────────────


def get_dashboard_summary(org_id: str, cycle_id: str) -> dict:
    """Org+cycle headline numbers, live from Asana.

    ``total_nominated`` comes from the nomination DynamoDB table (source
    of truth); everything else comes from the Asana section. Response
    rate = Asana responses / nominated * 100.
    """
    tasks = _fetch_cycle_tasks(org_id, cycle_id)
    scores = [t["score"] for t in tasks if t["score"] is not None]
    promoters = sum(1 for s in scores if _band(s) == "promoter")
    passives = sum(1 for s in scores if _band(s) == "passive")
    detractors = sum(1 for s in scores if _band(s) == "detractor")

    nominated = len(nps_nomination_repo.list_nominations(org_id, cycle_id))
    responses = len(tasks)

    return {
        "nps_score": _nps(promoters, detractors, len(scores)),
        "response_rate": round(responses / nominated * 100, 1) if nominated else 0.0,
        "total_nominated": nominated,
        "total_responses": responses,
        "promoters_count": promoters,
        "passives_count": passives,
        "detractors_count": detractors,
        "incomplete_tasks": sum(1 for t in tasks if not t["completed"]),
        "overdue_tasks": sum(1 for t in tasks if t["overdue"]),
    }


def get_leader_breakdown(org_id: str, cycle_id: str) -> list[dict]:
    """Per-leader rollup, sorted by leader name.

    ``action_complete`` is True when every one of the leader's tasks is
    completed; ``is_overdue`` when any of their tasks is overdue.
    """
    # Per-leader nomination counts (DynamoDB is the source of truth for who
    # was invited). Grouped by the nomination's leader tag.
    nom_by_leader: dict[str, int] = {}
    for nom in nps_nomination_repo.list_nominations(org_id, cycle_id):
        key = (getattr(nom, "leader", "") or "").strip() or _UNASSIGNED
        nom_by_leader[key] = nom_by_leader.get(key, 0) + 1

    rows = []
    for leader, tasks in sorted(_group_by_leader(_fetch_cycle_tasks(org_id, cycle_id)).items()):
        scores = [t["score"] for t in tasks if t["score"] is not None]
        promoters = sum(1 for s in scores if _band(s) == "promoter")
        passives = sum(1 for s in scores if _band(s) == "passive")
        detractors = sum(1 for s in scores if _band(s) == "detractor")
        completed = sum(1 for t in tasks if t["completed"])
        rows.append({
            "leader_name": leader,
            "nominated": nom_by_leader.get(leader, 0),
            "responses": len(tasks),
            "nps": _nps(promoters, detractors, len(scores)),
            "promoters": promoters,
            "passives": passives,
            "detractors": detractors,
            "actions_completed": completed,
            "action_complete": all(t["completed"] for t in tasks),
            "is_overdue": any(t["overdue"] for t in tasks),
        })
    return rows


def get_nps_distribution(org_id: str, cycle_id: str) -> list[dict]:
    """Per-leader promoter/passive/detractor counts (stacked bar data)."""
    return [
        {
            "leader_name": row["leader_name"],
            "promoters": row["promoters"],
            "passives": row["passives"],
            "detractors": row["detractors"],
        }
        for row in get_leader_breakdown(org_id, cycle_id)
    ]


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_EMAIL_LABELLED_RE = re.compile(
    r"email\s*address\s*:?\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
    re.IGNORECASE,
)


def _email_from_notes(notes: str) -> str:
    """Pull the respondent email out of the task description.

    The survey form writes answers into the task notes, including a line
    like ``Email address: uparibnk@amazon.com``. Prefer the value after the
    "Email address" label; fall back to the first email found.
    """
    if not notes:
        return ""
    m = _EMAIL_LABELLED_RE.search(notes)
    if m:
        return m.group(1).strip()
    m = _EMAIL_RE.search(notes)
    return m.group(0).strip() if m else ""


def _respondent_name(task: dict, org, leader: str) -> str:
    """Stakeholder name for a response task.

    Prefers an explicit respondent-name custom field if the org configures
    one; otherwise parses the task title, which the survey form populates as
    "<Leader>, <Stakeholder>" (strip the leader prefix, else take the part
    after the first comma, else the whole title).
    """
    explicit = _cf_display(task, getattr(org, "custom_field_respondent_name_gid", ""))
    if explicit:
        return explicit
    full = (task.get("name") or "").strip()
    if not full:
        return ""
    if leader and full.lower().startswith(leader.lower()):
        rest = full[len(leader):].lstrip(" ,").strip()
        if rest:
            return rest
    if "," in full:
        return full.split(",", 1)[1].strip()
    return full


def _cf_display(task: dict, gid: str) -> str:
    """A custom field's display_value by GID (empty string when absent)."""
    if not gid:
        return ""
    for cf in task.get("custom_fields") or []:
        if cf.get("gid") == gid:
            return (cf.get("display_value") or "").strip()
    return ""


def get_feedback(org_id: str, cycle_id: str) -> list[dict]:
    """Per-stakeholder feedback rows, live from Asana's Ongoing Survey.

    Includes the real respondent identity (name + email) when the org's
    ``custom_field_respondent_name_gid`` / ``custom_field_respondent_email_gid``
    are configured — the survey form collects Name + Email. Rows without a
    score are still returned (they carry written feedback).

    Returns [{leader, respondent_name, respondent_email, score, category,
    feedback, what_missing, date}], newest first.
    """
    org = _load_org(org_id)
    cycle = _load_cycle(org_id, cycle_id)
    if not org.asana_project_gid:
        raise ValueError(f"Org '{org_id}' has no Asana project configured")

    section_gid = _find_ongoing_section_gid(org.asana_project_gid)
    # Include ``name`` (title = "<Leader>, <Stakeholder>") and ``notes`` (the
    # form answers, incl. an "Email address:" line) — neither is a custom field.
    opt_fields = "name,notes," + _OPT_FIELDS
    tasks = asana_client.list_tasks_in_section(section_gid, opt_fields=opt_fields)

    lo = cycle.start_date or ""
    hi = (cycle.end_date or "") + "~"

    rows = []
    for task in tasks:
        created = (task.get("created_at") or "")[:10]
        if not (lo <= created <= hi):
            continue
        score = _score_from_task(task, org.custom_field_nps_score_gid)
        leader = _leader_from_task(task, org.custom_field_leader_gid)
        rows.append({
            "leader": leader,
            "respondent_name": _respondent_name(task, org, leader),
            "respondent_email": (
                _cf_display(task, org.custom_field_respondent_email_gid)
                or _email_from_notes(task.get("notes"))
            ),
            "score": score,
            "category": _band(score).capitalize() if score is not None else "",
            "feedback": _cf_display(task, org.custom_field_feedback_gid),
            "what_missing": _cf_display(task, org.custom_field_what_missing_gid),
            "date": created,
        })
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def get_action_tracker_status(org_id: str, cycle_id: str) -> list[dict]:
    """Per-leader completed vs incomplete task counts, sorted by leader."""
    rows = []
    for leader, tasks in sorted(_group_by_leader(_fetch_cycle_tasks(org_id, cycle_id)).items()):
        completed = sum(1 for t in tasks if t["completed"])
        rows.append({
            "leader_name": leader,
            "completed": completed,
            "incomplete": len(tasks) - completed,
        })
    return rows
