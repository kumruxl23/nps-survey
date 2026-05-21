"""Refresh feedback_text on existing NpsResponse rows from Asana.

The original backfill (scripts/backfill_from_asana.py) always wrote
feedback_text="" because we hadn't wired up the Feedback custom-field GID.
This script does NOT create or delete anything; it only updates the
feedback_text on existing responses by matching them to Asana tasks via
(score, leader, recorded_at) — the only signals we have, since responses
are anonymized.

Usage on the EC2:

    /usr/bin/python3.11 scripts/refresh_response_feedback.py --org whs_cpt_in --cycle h1-2026 --dry-run

Drop --dry-run to actually update.

Caveat: a single response can be matched ambiguously if two tasks have
the exact same (score, leader, day). In that case we update the first
match. Logged when it happens.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from decimal import Decimal

import boto3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

from app.db import nps_org_config_repo, nps_response_repo  # noqa: E402
from app.services import asana_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("refresh_feedback")

ACTIVE_SECTION_NAME = "H1 2026"


def _custom_field_value(task: dict, gid: str):
    if not gid:
        return None
    for cf in task.get("custom_fields", []) or []:
        if cf.get("gid") != gid:
            continue
        if cf.get("type") == "number":
            return cf.get("number_value")
        if cf.get("type") == "enum":
            ev = cf.get("enum_value") or {}
            return ev.get("name") if ev else None
        if cf.get("type") == "text":
            return cf.get("text_value")
        for k in ("display_value", "text_value", "number_value"):
            if cf.get(k) is not None:
                return cf.get(k)
    return None


def _parse_score(raw):
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        try:
            return int(str(raw).strip().split()[0])
        except (ValueError, IndexError):
            return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True)
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    org = nps_org_config_repo.get_org(args.org)
    if not org:
        sys.exit(f"Org {args.org!r} not found")

    nps_gid = org.custom_field_nps_score_gid
    leader_gid = getattr(org, "custom_field_leader_gid", "")
    feedback_gid = getattr(org, "custom_field_feedback_gid", "")

    if not feedback_gid or "placeholder" in str(feedback_gid).lower() or "tbd" in str(feedback_gid).lower():
        sys.exit(f"[{args.org}] custom_field_feedback_gid not set ({feedback_gid!r}). "
                 f"Run backfill_from_asana.py --fix-gids first.")

    # Find the H1 2026 section + list its tasks
    sections = asana_client.list_sections(org.asana_project_gid)
    target = next((s for s in sections if (s.get("name") or "").strip().lower() == ACTIVE_SECTION_NAME.lower()), None)
    if not target:
        sys.exit(f"[{args.org}] no '{ACTIVE_SECTION_NAME}' section in Asana project")
    tasks = asana_client.list_tasks_in_section(target["gid"])
    logger.info("[%s] %d tasks in section '%s'", args.org, len(tasks), target.get("name"))

    # Build a lookup of (score, leader, day) -> [(feedback_text, respondent_name), ...]
    asana_lookup: dict[tuple[int, str, str], list[tuple[str, str]]] = defaultdict(list)
    for task in tasks:
        score = _parse_score(_custom_field_value(task, nps_gid))
        if score is None:
            continue
        leader_raw = _custom_field_value(task, leader_gid) if leader_gid else None
        leader = (leader_raw or "").strip() if isinstance(leader_raw, str) else ""
        feedback_raw = _custom_field_value(task, feedback_gid)
        feedback_text = ""
        if feedback_raw is not None:
            feedback_text = str(feedback_raw).strip()
        # Pull the respondent name from "<Leader>, <Stakeholder>" task title
        full_name = (task.get("name") or "").strip()
        respondent_name = ""
        if "," in full_name:
            respondent_name = full_name.split(",", 1)[1].strip()
        else:
            respondent_name = full_name
        # Index every task — even ones with empty feedback — so we can fill in
        # the respondent name on responses that previously had no match.
        day = (task.get("completed_at") or task.get("created_at") or "")[:10]
        asana_lookup[(score, leader, day)].append((feedback_text, respondent_name))

    feedback_count = sum(1 for v in asana_lookup.values() for f, _ in v if f)
    logger.info("[%s] %d Asana tasks have non-empty feedback", args.org, feedback_count)

    # Walk existing responses, update feedback_text where empty + a match exists
    responses = nps_response_repo.list_responses(args.org, args.cycle)
    logger.info("[%s] %d responses currently in DynamoDB", args.org, len(responses))

    updated = 0
    skipped_no_match = 0
    skipped_already_set = 0
    ambiguous = 0

    # Use a copy of the lookup so we can pop matches as we use them
    remaining = {k: list(v) for k, v in asana_lookup.items()}

    for r in responses:
        # Skip rows that already have BOTH feedback and respondent_name set.
        # If only one is missing we still try to fill the other.
        had_feedback = bool((r.feedback_text or "").strip())
        had_name = bool((getattr(r, "respondent_name", "") or "").strip())
        if had_feedback and had_name:
            skipped_already_set += 1
            continue
        day = (r.recorded_at or "")[:10]
        key = (int(r.nps_score), r.leader or "", day)
        choices = remaining.get(key, [])
        if not choices:
            skipped_no_match += 1
            continue
        if len(choices) > 1:
            ambiguous += 1
        feedback_text, respondent_name = choices.pop(0)

        # Build the SET expression conditionally so we don't clobber data
        # the user already manually filled in.
        set_parts = []
        expr_vals = {}
        if not had_feedback and feedback_text:
            set_parts.append("feedback_text = :f")
            expr_vals[":f"] = feedback_text
        if not had_name and respondent_name:
            set_parts.append("respondent_name = :n")
            expr_vals[":n"] = respondent_name

        if not set_parts:
            # Nothing to update for this response.
            skipped_no_match += 1
            continue

        if args.dry_run:
            logger.debug("[%s] DRY RUN response_id=%s would set %s",
                         args.org, r.response_id, set_parts)
        else:
            ddb = boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"])
            table = ddb.Table(os.environ.get("NPS_RESPONSES_TABLE", "NpsResponses"))
            table.update_item(
                Key={
                    "org_id_cycle_id": f"{r.org_id}#{r.cycle_id}",
                    "response_id": r.response_id,
                },
                UpdateExpression="SET " + ", ".join(set_parts),
                ExpressionAttributeValues=expr_vals,
            )
        updated += 1

    logger.info("[%s] updated=%d skipped_already_set=%d skipped_no_match=%d ambiguous=%d",
                args.org, updated, skipped_already_set, skipped_no_match, ambiguous)
    if args.dry_run:
        logger.info("(DRY RUN — nothing was written)")


if __name__ == "__main__":
    main()
