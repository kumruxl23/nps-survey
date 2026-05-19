"""Backfill NPS data from Asana into DynamoDB.

Two-step pipeline:

  Step 1 — fix-gids:
      For each org in NpsOrgConfig, fetches the project's custom field
      settings from Asana and updates the org's *_gid placeholders with
      real GIDs (matched by field name).

  Step 2 — backfill:
      For each org, lists every task in the org's Asana project. For each
      task that has a non-empty NPS Score custom field, creates:
        - a Nomination record (email + name from assignee, marked responded)
        - an NpsResponse record (score + category + leader + feedback)
      All into a single H1-2026 cycle (one cycle per org).

Usage (run on the EC2):

  # Dry run — read-only, prints what WOULD be written
  /usr/bin/python3.11 scripts/backfill_from_asana.py --dry-run

  # Step 1 only (fix GIDs)
  /usr/bin/python3.11 scripts/backfill_from_asana.py --fix-gids

  # Step 2 only (backfill, requires GIDs already fixed)
  /usr/bin/python3.11 scripts/backfill_from_asana.py --backfill

  # Both, end-to-end
  /usr/bin/python3.11 scripts/backfill_from_asana.py --fix-gids --backfill

  # Limit to a single org
  /usr/bin/python3.11 scripts/backfill_from_asana.py --fix-gids --backfill \\
      --org whs_cpt_in

Safety:
  - --dry-run never modifies anything (DynamoDB or Asana). It only reads
    and prints planned changes.
  - This script does NOT write to Asana — pure read-from-Asana,
    write-to-DynamoDB.
  - GID matching is name-based (case-insensitive substring). If field
    names change in Asana, re-run --fix-gids.

Field name mapping (case-insensitive substring):
  Org config field            <- Asana custom field name contains
  --------------------------------------------------------------
  custom_field_nps_score_gid  <- "nps score"
  custom_field_category_gid   <- "category"
  custom_field_org_name_gid   <- "org name"   (or just "org")
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

# Add /opt/nps-survey to the path so `app.*` imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Default region for the running app — set BEFORE importing repos so boto3
# picks it up when they call boto3.resource("dynamodb") without a region.
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

from app.db import (  # noqa: E402
    nps_cycle_repo,
    nps_nomination_repo,
    nps_org_config_repo,
    nps_response_repo,
)
from app.db.models import Nomination, NpsResponse, SurveyCycle  # noqa: E402
from app.services import asana_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backfill")

# ---------------------------------------------------------------------------
# Cycle config — H1 2026, ongoing
# ---------------------------------------------------------------------------

H1_2026_CYCLE_ID = "h1-2026"
H1_2026_START = "2026-01-01"
H1_2026_END = "2026-06-30"
H1_2026_NAME = "H1 2026"
H1_2026_STATUS = "active"  # cycle is in-flight, not archived

# Asana section name to filter to. Anything not in this section (older
# cycles archived under their own section headers) is ignored.
ACTIVE_SECTION_NAME = "H1 2026"

# Custom field name -> org_config_repo field name
GID_NAME_MAP = {
    "custom_field_nps_score_gid": ("nps score", "score"),
    "custom_field_category_gid": ("category",),
    "custom_field_org_name_gid": ("org name", "org"),
    "custom_field_leader_gid": ("leader",),
}


def _match_gid_by_name(field_settings: list[dict], name_hints: tuple[str, ...]) -> str | None:
    """Find a custom-field GID whose name (case-insensitive) contains any of the hints.

    Earlier hints win (more specific match preferred).
    """
    for hint in name_hints:
        hint_lower = hint.lower()
        for setting in field_settings:
            cf = setting.get("custom_field", {})
            cf_name = (cf.get("name") or "").lower()
            if hint_lower in cf_name:
                return cf.get("gid")
    return None


def _is_placeholder_gid(value: str) -> bool:
    if not value:
        return True
    val = value.lower()
    return any(p in val for p in ("placeholder", "tbd", "todo"))


# ---------------------------------------------------------------------------
# Step 1 — fix GIDs
# ---------------------------------------------------------------------------


def fix_gids(org_filter: str | None, dry_run: bool) -> int:
    """Replace placeholder GIDs in NpsOrgConfig with real Asana GIDs.

    Returns the number of orgs updated.
    """
    orgs = nps_org_config_repo.list_all_orgs()
    real_orgs = [o for o in orgs if not o.org_id.startswith("__")]
    if org_filter:
        real_orgs = [o for o in real_orgs if o.org_id == org_filter]

    if not real_orgs:
        logger.warning("No orgs to fix.")
        return 0

    updated = 0
    for org in real_orgs:
        if not org.asana_project_gid or org.asana_project_gid == "admin":
            logger.info("[%s] no asana_project_gid, skipping", org.org_id)
            continue

        logger.info("[%s] fetching custom field settings for project %s",
                    org.org_id, org.asana_project_gid)
        try:
            field_settings = asana_client.get_project_custom_fields(org.asana_project_gid)
        except Exception as exc:
            logger.error("[%s] failed to fetch custom fields: %s", org.org_id, exc)
            continue

        new_gids: dict[str, str] = {}
        for field_name, hints in GID_NAME_MAP.items():
            current = getattr(org, field_name, "")
            if not _is_placeholder_gid(current):
                logger.info("[%s] %s already has real GID '%s', leaving alone",
                            org.org_id, field_name, current)
                continue

            real_gid = _match_gid_by_name(field_settings, hints)
            if not real_gid:
                logger.warning("[%s] no Asana custom field matches %s (hints %s) — leaving '%s'",
                               org.org_id, field_name, hints, current)
                continue

            logger.info("[%s] %s: '%s' -> '%s'", org.org_id, field_name, current, real_gid)
            new_gids[field_name] = real_gid

        if not new_gids:
            logger.info("[%s] no GID changes needed", org.org_id)
            continue

        if dry_run:
            logger.info("[%s] DRY RUN — would update: %s", org.org_id, new_gids)
            updated += 1
            continue

        nps_org_config_repo.update_org(org.org_id, **new_gids)
        logger.info("[%s] updated %d GID(s)", org.org_id, len(new_gids))
        updated += 1

    return updated


# ---------------------------------------------------------------------------
# Step 2 — backfill
# ---------------------------------------------------------------------------


def _categorize(score: int) -> str:
    if score >= 9:
        return "Promoter"
    if score >= 7:
        return "Passive"
    return "Detractor"


def _custom_field_value(task: dict, gid: str) -> object | None:
    """Look up a custom field's value on a task, by gid. None if absent."""
    if not gid:
        return None
    for cf in task.get("custom_fields", []) or []:
        if cf.get("gid") != gid:
            continue
        # Different field types store values under different keys
        if cf.get("type") == "number":
            return cf.get("number_value")
        if cf.get("type") == "enum":
            enum_val = cf.get("enum_value")
            return (enum_val or {}).get("name") if enum_val else None
        if cf.get("type") == "text":
            return cf.get("text_value")
        # Fallback — try common keys
        for key in ("display_value", "text_value", "number_value"):
            if cf.get(key) is not None:
                return cf.get(key)
    return None


def _ensure_h1_cycle(org_id: str, project_gid: str, form_url: str, dry_run: bool) -> str:
    """Create or refresh the H1-2026 cycle for an org. Returns the cycle_id.

    If a cycle already exists, leaves it alone (assume it's already correct).
    """
    existing = nps_cycle_repo.get_cycle(org_id, H1_2026_CYCLE_ID)
    if existing:
        logger.info("[%s] %s cycle already exists", org_id, H1_2026_CYCLE_ID)
        return H1_2026_CYCLE_ID

    cycle = SurveyCycle(
        org_id=org_id,
        cycle_id=H1_2026_CYCLE_ID,
        start_date=H1_2026_START,
        end_date=H1_2026_END,
        status=H1_2026_STATUS,
        reminder_mode="manual",
        asana_project_gid=project_gid,
        asana_form_url=form_url,
        cycle_name=H1_2026_NAME,
    )
    if dry_run:
        logger.info("[%s] DRY RUN — would create cycle %s", org_id, H1_2026_CYCLE_ID)
        return H1_2026_CYCLE_ID

    nps_cycle_repo.put_cycle(cycle)
    logger.info("[%s] created %s cycle", org_id, H1_2026_CYCLE_ID)
    return H1_2026_CYCLE_ID


def backfill_org(org, dry_run: bool) -> dict[str, int]:
    """Pull every task from the org's Asana project into a Nomination/Response.

    Leader is read from the Asana ``Leader`` enum custom field (the value the
    respondent picked on the form), NOT from the task's assignee.

    Per Q3.B (May 2026): every responder gets a Nomination row, even if they
    weren't on the targeted stakeholder list — we use the leader they picked
    on the form for that nomination.
    """
    stats = {"tasks": 0, "skipped_no_score": 0, "responses": 0, "nominations": 0}

    nps_gid = org.custom_field_nps_score_gid
    cat_gid = org.custom_field_category_gid
    leader_gid = getattr(org, "custom_field_leader_gid", "") or ""

    if _is_placeholder_gid(nps_gid):
        logger.error("[%s] custom_field_nps_score_gid is still a placeholder ('%s'). "
                     "Run --fix-gids first.", org.org_id, nps_gid)
        return stats

    if _is_placeholder_gid(leader_gid):
        logger.warning("[%s] custom_field_leader_gid is missing/placeholder. "
                       "Leader values will be empty. Run --fix-gids first.", org.org_id)

    cycle_id = _ensure_h1_cycle(org.org_id, org.asana_project_gid, org.asana_form_url, dry_run)

    # Find the active "H1 2026" section in this Asana project. Older cycles
    # live under their own archived sections — we explicitly skip them.
    try:
        sections = asana_client.list_sections(org.asana_project_gid)
    except Exception as exc:
        logger.error("[%s] failed to list sections: %s", org.org_id, exc)
        return stats

    target = next(
        (s for s in sections
         if (s.get("name") or "").strip().lower() == ACTIVE_SECTION_NAME.lower()),
        None,
    )
    if target is None:
        section_names = [s.get("name") for s in sections]
        logger.error("[%s] no Asana section named '%s' found. Sections: %s",
                     org.org_id, ACTIVE_SECTION_NAME, section_names)
        return stats

    section_gid = target["gid"]
    logger.info("[%s] listing tasks in section '%s' (gid=%s)",
                org.org_id, target.get("name"), section_gid)
    try:
        tasks = asana_client.list_tasks_in_section(section_gid)
    except Exception as exc:
        logger.error("[%s] failed to list tasks in section: %s", org.org_id, exc)
        return stats

    logger.info("[%s] %d tasks fetched from section '%s'",
                org.org_id, len(tasks), target.get("name"))

    for task in tasks:
        stats["tasks"] += 1

        score_raw = _custom_field_value(task, nps_gid)
        if score_raw is None or score_raw == "":
            stats["skipped_no_score"] += 1
            continue

        try:
            score = int(score_raw)
        except (TypeError, ValueError):
            # Some "scores" are enums like "9 - Promoter"; try to parse leading int
            try:
                score = int(str(score_raw).strip().split()[0])
            except (ValueError, IndexError):
                logger.debug("[%s] task %s has non-numeric score '%s', skipping",
                             org.org_id, task.get("gid"), score_raw)
                stats["skipped_no_score"] += 1
                continue

        if not (0 <= score <= 10):
            logger.debug("[%s] task %s has out-of-range score %d, skipping",
                         org.org_id, task.get("gid"), score)
            stats["skipped_no_score"] += 1
            continue

        # Category — prefer Asana's enum, fall back to computed
        category_raw = _custom_field_value(task, cat_gid) if cat_gid else None
        if isinstance(category_raw, str) and category_raw.strip():
            category = category_raw.strip().capitalize()
            if category not in ("Promoter", "Passive", "Detractor"):
                category = _categorize(score)
        else:
            category = _categorize(score)

        # Leader — read from the form's enum field (the value the respondent picked)
        leader_raw = _custom_field_value(task, leader_gid) if leader_gid else None
        leader = (leader_raw or "").strip() if isinstance(leader_raw, str) else ""

        # Respondent identity — used for matching against existing nominations + creating one if missing
        assignee = task.get("assignee") or {}
        email = (assignee.get("email") or "").lower()
        respondent_name = assignee.get("name", "") or ""

        recorded_at = task.get("completed_at") or task.get("created_at") \
            or datetime.now(timezone.utc).isoformat()

        # Per Q3.B: always create a nomination row for the responder — even if they
        # weren't on the targeted list. Email key is required for the table; if no
        # email available, fabricate one from task GID so the row stays unique.
        nomination_email = email or f"asana-task-{task.get('gid', 'unknown')}@unknown.local"
        nomination = Nomination(
            org_id=org.org_id,
            cycle_id=cycle_id,
            email=nomination_email,
            name=respondent_name or nomination_email.split("@")[0],
            leader=leader,
            responded=True,
            responded_at=recorded_at,
        )
        if dry_run:
            logger.debug("[%s] DRY RUN nomination: leader='%s' email='%s'",
                         org.org_id, leader, nomination_email)
        else:
            nps_nomination_repo.put_nomination(nomination)
        stats["nominations"] += 1

        response = NpsResponse(
            org_id=org.org_id,
            cycle_id=cycle_id,
            response_id=str(uuid.uuid4()),
            nps_score=score,
            category=category,
            leader=leader,
            feedback_text="",
            recorded_at=recorded_at,
        )
        if dry_run:
            logger.debug("[%s] DRY RUN response: score=%d cat=%s leader='%s'",
                         org.org_id, score, category, leader)
        else:
            nps_response_repo.put_response(response)
        stats["responses"] += 1

    return stats


def backfill(org_filter: str | None, dry_run: bool) -> None:
    orgs = nps_org_config_repo.list_all_orgs()
    real_orgs = [o for o in orgs if not o.org_id.startswith("__")]
    if org_filter:
        real_orgs = [o for o in real_orgs if o.org_id == org_filter]

    if not real_orgs:
        logger.warning("No orgs to backfill.")
        return

    grand_totals = {"tasks": 0, "skipped_no_score": 0, "responses": 0, "nominations": 0}
    for org in real_orgs:
        logger.info("=" * 60)
        logger.info("Backfilling org: %s", org.org_id)
        stats = backfill_org(org, dry_run)
        for k, v in stats.items():
            grand_totals[k] += v
        logger.info("[%s] stats: %s", org.org_id, stats)

    logger.info("=" * 60)
    logger.info("GRAND TOTAL: %s", grand_totals)
    if dry_run:
        logger.info("(DRY RUN — nothing was written)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix-gids", action="store_true",
                        help="Resolve placeholder GIDs in NpsOrgConfig from Asana.")
    parser.add_argument("--backfill", action="store_true",
                        help="Read tasks from Asana, write Nominations + Responses.")
    parser.add_argument("--org", type=str, default=None,
                        help="Restrict to a single org_id (e.g., whs_cpt_in).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read-only — print planned changes, write nothing.")
    args = parser.parse_args()

    if not args.fix_gids and not args.backfill:
        parser.error("Specify --fix-gids and/or --backfill (or use --dry-run with one).")

    if args.fix_gids:
        logger.info("=== Step 1: fix GIDs (dry_run=%s) ===", args.dry_run)
        n = fix_gids(args.org, args.dry_run)
        logger.info("Fix-GIDs: %d org(s) updated\n", n)

    if args.backfill:
        logger.info("=== Step 2: backfill (dry_run=%s) ===", args.dry_run)
        backfill(args.org, args.dry_run)


if __name__ == "__main__":
    main()
