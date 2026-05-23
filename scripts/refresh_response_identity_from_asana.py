"""Refresh respondent_name AND leader on existing NpsResponses from Asana.

After a workbook migration, response.leader can be stale (still old POC),
and response.respondent_name can be empty (original backfill predated
that field). The refresh_response_feedback.py script matches by
(score, leader, day), which falls apart once leader is stale.

This script matches each Asana task to a DB response by **score + day**
(the only stable signals when leader has drifted), then updates:
  - leader  := workbook POC for that respondent (if respondent maps to
              a nomination), else the leader picked on the form
  - respondent_name := from the Asana task title "<Leader>, <Name>"
  - feedback_text / what_missing_text := same as refresh script

Matching strategy:
  1. Index Asana tasks by (score, day) -> [task triples]
  2. For each response, look up its (score, day) bucket and pop the
     first task. If that bucket is empty, fall back to (score) bucket.
  3. Don't touch responses that already have respondent_name + leader
     consistent with a nomination row (they're already correct).

Usage on EC2:

    /usr/bin/python3.11 scripts/refresh_response_identity_from_asana.py \\
        --org whs_cpt_na --cycle h1-2026 --dry-run

Drop --dry-run to apply.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

from app.db import (  # noqa: E402
    nps_nomination_repo,
    nps_org_config_repo,
    nps_response_repo,
)
from app.db.nps_response_repo import _build_composite_key, _get_table  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("refresh_resp_identity")

ACTIVE_SECTION_NAME = "H1 2026"


def _norm_name(s: str) -> str:
    return " ".join((s or "").lower().split())


def _name_tokens(s: str) -> set[str]:
    raw = _norm_name(s)
    return {t for t in raw.replace(",", " ").split() if t}


def _names_likely_same(a: str, b: str) -> bool:
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    if _norm_name(a) == _norm_name(b):
        return True
    if len(ta & tb) >= 2:
        return True
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return all(any(s in lg or lg in s for lg in large) for s in small)


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

    from app.services import asana_client  # late import

    org = nps_org_config_repo.get_org(args.org)
    if not org:
        sys.exit(f"Org {args.org!r} not found")

    nps_gid = org.custom_field_nps_score_gid
    leader_gid = getattr(org, "custom_field_leader_gid", "")
    feedback_gid = getattr(org, "custom_field_feedback_gid", "")
    what_missing_gid = getattr(org, "custom_field_what_missing_gid", "")

    sections = asana_client.list_sections(org.asana_project_gid)
    target = next((s for s in sections
                   if (s.get("name") or "").strip().lower() == ACTIVE_SECTION_NAME.lower()),
                  None)
    if not target:
        sys.exit(f"[{args.org}] no '{ACTIVE_SECTION_NAME}' section in Asana project")
    tasks = asana_client.list_tasks_in_section(target["gid"])
    logger.info("[%s] %d tasks in section '%s'", args.org, len(tasks), target.get("name"))

    # Build (score, day) -> list of task dicts. Also (score,) bucket.
    by_score_day: dict[tuple[int, str], list[dict]] = defaultdict(list)
    by_score: dict[int, list[dict]] = defaultdict(list)

    for task in tasks:
        score = _parse_score(_custom_field_value(task, nps_gid))
        if score is None:
            continue
        leader_form = _custom_field_value(task, leader_gid) if leader_gid else None
        leader_form = (leader_form or "").strip() if isinstance(leader_form, str) else ""
        feedback_text = ""
        if feedback_gid:
            raw = _custom_field_value(task, feedback_gid)
            if raw is not None:
                feedback_text = (str(raw) if not isinstance(raw, str) else raw).strip()
        what_missing_text = ""
        if what_missing_gid:
            raw = _custom_field_value(task, what_missing_gid)
            if raw is not None:
                what_missing_text = (str(raw) if not isinstance(raw, str) else raw).strip()
        full_name = (task.get("name") or "").strip()
        respondent_name = full_name.split(",", 1)[1].strip() if "," in full_name else full_name
        day = (task.get("completed_at") or task.get("created_at") or "")[:10]

        info = {
            "score": score,
            "leader_form": leader_form,
            "feedback_text": feedback_text,
            "what_missing_text": what_missing_text,
            "respondent_name": respondent_name,
            "day": day,
        }
        by_score_day[(score, day)].append(info)
        by_score[score].append(info)

    logger.info("[%s] indexed %d Asana tasks (by score: %s)",
                args.org, sum(len(v) for v in by_score_day.values()),
                {k: len(v) for k, v in sorted(by_score.items())})

    # Build name -> nomination leader map (for canonical leader pick).
    noms = nps_nomination_repo.list_nominations(args.org, args.cycle)
    name_to_leaders: dict[str, list[str]] = {}
    for n in noms:
        if not n.name:
            continue
        key = _norm_name(n.name)
        name_to_leaders.setdefault(key, [])
        if n.leader and n.leader not in name_to_leaders[key]:
            name_to_leaders[key].append(n.leader)

    def lookup_canonical_leader(respondent_name: str, current_leader: str, form_leader: str) -> str:
        """Pick the right leader for a response.

        Priority:
          1. If the response's CURRENT leader is one of the workbook leaders
             for that respondent, keep it (don't move correctly-tagged rows).
          2. Else if the FORM-picked leader (from Asana) is in the workbook
             list, use it.
          3. Else pick the first workbook leader (deterministic fallback).
          4. If the respondent has NO workbook nomination, keep the
             form-picked leader (legitimate off-list response).
        """
        rn = _norm_name(respondent_name)
        leaders = name_to_leaders.get(rn)
        if leaders is None:
            for nom_name, lds in name_to_leaders.items():
                if _names_likely_same(respondent_name, nom_name):
                    leaders = lds
                    break
        if not leaders:
            return form_leader
        cl = (current_leader or "").strip()
        if cl in leaders:
            return cl
        fl = (form_leader or "").strip()
        if fl in leaders:
            return fl
        return leaders[0]

    # Walk responses, plan updates.
    responses = nps_response_repo.list_responses(args.org, args.cycle)
    logger.info("[%s] %d responses in DynamoDB", args.org, len(responses))

    plan: list[tuple[object, dict]] = []  # (response, fields_to_set)

    # Mutable copies of bucket lists so we can pop tasks we use.
    rem_score_day = {k: list(v) for k, v in by_score_day.items()}
    rem_score = {k: list(v) for k, v in by_score.items()}

    for r in responses:
        score = int(r.nps_score)
        day = (r.recorded_at or "")[:10]

        info = None
        # Try (score, day) first
        bucket = rem_score_day.get((score, day), [])
        if bucket:
            info = bucket.pop(0)
            # Also remove from the loose bucket
            for i, item in enumerate(rem_score.get(score, [])):
                if item is info:
                    rem_score[score].pop(i)
                    break
        else:
            bucket = rem_score.get(score, [])
            if bucket:
                info = bucket.pop(0)
                # Remove from score-day bucket too
                for i, item in enumerate(rem_score_day.get((score, info["day"]), [])):
                    if item is info:
                        rem_score_day[(score, info["day"])].pop(i)
                        break

        if info is None:
            logger.warning("  no Asana task left for response_id=%s score=%d day=%s",
                           r.response_id, score, day)
            continue

        canonical_leader = lookup_canonical_leader(
            info["respondent_name"], r.leader, info["leader_form"],
        )

        sets: dict[str, str] = {}
        if (r.respondent_name or "").strip() != info["respondent_name"] and info["respondent_name"]:
            sets["respondent_name"] = info["respondent_name"]
        if (r.leader or "").strip() != canonical_leader and canonical_leader:
            sets["leader"] = canonical_leader
        if not (r.feedback_text or "").strip() and info["feedback_text"]:
            sets["feedback_text"] = info["feedback_text"]
        if not (getattr(r, "what_missing_text", "") or "").strip() and info["what_missing_text"]:
            sets["what_missing_text"] = info["what_missing_text"]

        if sets:
            plan.append((r, sets))

    logger.info("[%s] plan: %d response updates", args.org, len(plan))
    for r, sets in plan:
        change = {k: f"'{r.__dict__.get(k, '')}' -> '{v}'" for k, v in sets.items()}
        logger.info("  UPDATE response_id=%s score=%d %s",
                    r.response_id, r.nps_score, change)

    if args.dry_run:
        logger.info("DRY RUN — no changes made.")
        return

    table = _get_table()
    pk = _build_composite_key(args.org, args.cycle)
    for r, sets in plan:
        update_parts = []
        names = {}
        values = {}
        for i, (k, v) in enumerate(sets.items()):
            update_parts.append(f"#k{i} = :v{i}")
            names[f"#k{i}"] = k
            values[f":v{i}"] = v
        table.update_item(
            Key={"org_id_cycle_id": pk, "response_id": r.response_id},
            UpdateExpression="SET " + ", ".join(update_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    logger.info("[%s] Done. updated=%d", args.org, len(plan))


if __name__ == "__main__":
    main()
