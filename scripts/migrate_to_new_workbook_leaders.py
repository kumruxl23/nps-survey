"""Migrate nominations + responses to a workbook's new leader assignments.

Use case: an org's H1 2026 sheet was updated with new POC -> stakeholder
mappings. The DB holds the OLD leader names on both Nominations and
NpsResponses. Run this to re-tag both tables to the workbook's POC.

What it does (per org+cycle):

  1. Build the workbook's truth: { (base_email, leader) for every Yes-row }.
  2. For each existing Nomination:
       - If the (base_email, leader) is in the workbook -> KEEP as-is.
       - Else if the base_email appears under ANY leader in the workbook
         AND the nomination has responded=True -> RE-TAG: rewrite the
         row with the workbook's new leader (and re-encode the sort-key
         if there are multiple leaders for the same email).
       - Else if responded=True and base_email is NOT in workbook ->
         KEEP as off-list responder (rule 3) under their existing leader.
       - Else (responded=False, not in workbook) -> DROP.
  3. For each NpsResponse, if its respondent's base_email is in the
     workbook, set response.leader to the workbook's POC for that email.
     If the workbook lists multiple leaders for that email AND the
     response.leader already matches one of them, leave it. Otherwise
     pick the first.
  4. Add Nominations for any (base_email, leader) in the workbook that
     don't have an existing row.

Usage on EC2:

    /usr/bin/python3.11 scripts/migrate_to_new_workbook_leaders.py \\
        --workbook /tmp/cpt_na.xlsx --org whs_cpt_na --cycle h1-2026 --dry-run

Drop --dry-run to apply.

Safety:
  - --dry-run prints the plan, writes nothing.
  - Aborts if the workbook parses 0 yes-rows.
  - Pattern 2 (leader self-noms, name == leader) ARE dropped here since
    they're never legitimate.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

from app.db import nps_nomination_repo, nps_response_repo  # noqa: E402
from app.db.models import Nomination  # noqa: E402
from app.services.nomination_keys import base_email, encode_for_leader  # noqa: E402
from scripts.import_h1_2026_stakeholders import (  # noqa: E402
    ORG_CONFIGS,
    _norm_leader_name,
    _parse_h1_2026,
    _parse_stakeholder_list,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate")


def _norm_name(s: str) -> str:
    return " ".join((s or "").lower().split())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--org", required=True, choices=sorted(ORG_CONFIGS.keys()))
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.workbook.is_file():
        sys.exit(f"Workbook not found: {args.workbook}")

    cfg = ORG_CONFIGS[args.org]
    yes_rows = _parse_h1_2026(args.workbook, cfg)
    if not yes_rows:
        sys.exit(f"Workbook returned 0 yes-rows for '{args.org}' — refusing to mutate.")
    sh_map = _parse_stakeholder_list(args.workbook, cfg)

    # workbook truth: list of {email, leader, name, responded}
    workbook_targets: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    email_to_leaders: dict[str, list[str]] = {}  # email -> [leaders]
    name_to_email: dict[str, str] = {}
    for row in yes_rows:
        alias = row["stakeholder_alias"]
        if not alias:
            continue
        sh = sh_map.get(alias) or {}
        email = (sh.get("email") or f"{alias}@amazon.com").strip().lower()
        leader = _norm_leader_name(row["poc"] or sh.get("leader") or "")
        if not leader:
            continue
        pair = (email, leader)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        workbook_targets.append({
            "email": email,
            "leader": leader,
            "name": row["stakeholder"],
            "responded_flag": (row.get("responded") == "yes"),
        })
        email_to_leaders.setdefault(email, []).append(leader)
        if row["stakeholder"]:
            name_to_email.setdefault(_norm_name(row["stakeholder"]), email)

    workbook_pairs = {(t["email"], t["leader"]) for t in workbook_targets}
    logger.info("[%s] workbook targets: %d, unique emails: %d",
                args.org, len(workbook_pairs), len(email_to_leaders))

    existing_noms = nps_nomination_repo.list_nominations(args.org, args.cycle)
    existing_resps = nps_response_repo.list_responses(args.org, args.cycle)
    logger.info("[%s] DB: %d nominations, %d responses",
                args.org, len(existing_noms), len(existing_resps))

    # --- plan nomination changes -----------------------------------------

    plan_keep: list[Nomination] = []          # already correct
    plan_retag: list[tuple[Nomination, str]] = []  # (old, new_leader)
    plan_offlist_keep: list[Nomination] = []  # responded=True, not in WB
    plan_drop: list[Nomination] = []          # responded=False, not in WB
    plan_self_drop: list[Nomination] = []     # name == leader
    plan_add: list[dict] = []                 # new (email, leader) from WB

    for n in existing_noms:
        be = base_email(n.email).strip().lower()
        cur_leader = _norm_leader_name((n.leader or "").strip())
        nom_name = _norm_name(n.name)

        # Self-nom: name == leader, never legitimate -> drop
        if nom_name and nom_name == _norm_name(cur_leader):
            plan_self_drop.append(n)
            continue

        if (be, cur_leader) in workbook_pairs:
            plan_keep.append(n)
            continue

        # Email IS in workbook but under a DIFFERENT leader -> retag if responded
        if be in email_to_leaders:
            wb_leaders = email_to_leaders[be]
            if n.responded:
                # Pick the first WB leader for this email — if WB has them
                # under multiple leaders, the OTHER leader's nomination will
                # be added in plan_add.
                plan_retag.append((n, wb_leaders[0]))
            else:
                # responded=False under wrong leader -> drop, the right
                # nomination(s) will be added below
                plan_drop.append(n)
            continue

        # Email not in workbook at all
        if n.responded:
            plan_offlist_keep.append(n)
        else:
            plan_drop.append(n)

    # ADDs: any workbook pair not already covered by KEEP or RETAG
    covered_pairs: set[tuple[str, str]] = {
        (base_email(n.email).strip().lower(),
         _norm_leader_name((n.leader or "").strip()))
        for n in plan_keep
    }
    covered_pairs.update(
        (base_email(n.email).strip().lower(), new_leader)
        for n, new_leader in plan_retag
    )
    for t in workbook_targets:
        if (t["email"], t["leader"]) not in covered_pairs:
            plan_add.append(t)

    logger.info("[%s] NOMINATION plan: keep=%d retag=%d offlist-keep=%d "
                "drop=%d self-drop=%d add=%d",
                args.org, len(plan_keep), len(plan_retag), len(plan_offlist_keep),
                len(plan_drop), len(plan_self_drop), len(plan_add))

    for n, new_leader in plan_retag:
        logger.info("  RETAG: email=%s name='%s' leader='%s' -> '%s'",
                    n.email, n.name, n.leader, new_leader)
    for n in plan_drop:
        logger.info("  DROP (orphan, not in WB): email=%s name='%s' leader='%s' responded=%s",
                    n.email, n.name, n.leader, n.responded)
    for n in plan_self_drop:
        logger.info("  DROP (self-nom): email=%s name='%s' leader='%s'",
                    n.email, n.name, n.leader)
    for n in plan_offlist_keep:
        logger.info("  KEEP (off-list responder, email not in WB): "
                    "email=%s name='%s' leader='%s'", n.email, n.name, n.leader)
    for t in plan_add:
        logger.info("  ADD: email=%s leader='%s' name='%s' responded=%s",
                    t["email"], t["leader"], t["name"], t["responded_flag"])

    # --- plan response retags ---------------------------------------------

    resp_retag_count = 0
    resp_retag_plans: list[tuple[object, str]] = []
    for r in existing_resps:
        # Try to map this response back to a workbook entry by name.
        rname = _norm_name(r.respondent_name)
        be = name_to_email.get(rname) if rname else None
        if not be:
            # Can't map - leave the leader as-is.
            continue
        wb_leaders = email_to_leaders.get(be, [])
        cur = _norm_leader_name((r.leader or "").strip())
        if cur in [_norm_leader_name(l) for l in wb_leaders]:
            continue  # already correct
        if not wb_leaders:
            continue
        new_leader = wb_leaders[0]
        resp_retag_plans.append((r, new_leader))
        resp_retag_count += 1

    logger.info("[%s] RESPONSE plan: retag=%d (others left as-is)",
                args.org, resp_retag_count)
    for r, new_leader in resp_retag_plans[:30]:
        logger.info("  RETAG response: respondent='%s' leader='%s' -> '%s'",
                    r.respondent_name, r.leader, new_leader)
    if resp_retag_count > 30:
        logger.info("  ... and %d more", resp_retag_count - 30)

    if args.dry_run:
        logger.info("DRY RUN — no changes made.")
        return

    # --- apply ------------------------------------------------------------

    # Drop self-noms and orphans first (free up keys)
    for n in plan_drop + plan_self_drop:
        nps_nomination_repo.delete_nomination(args.org, args.cycle, n.email)

    # Re-tag: delete old row, write new with possibly-new sort-key.
    # Build the running "taken_keys" set from rows we're keeping +
    # off-list keeps so encode_for_leader can pick a unique key.
    taken_keys: set[str] = set()
    for n in plan_keep + plan_offlist_keep:
        if n.email:
            taken_keys.add(n.email.strip().lower())

    for old, new_leader in plan_retag:
        nps_nomination_repo.delete_nomination(args.org, args.cycle, old.email)
        be = base_email(old.email).strip().lower()
        # Free up the old key if it was the plain email
        taken_keys.discard(old.email.strip().lower())
        new_key = encode_for_leader(be, new_leader, taken_keys)
        new_nom = Nomination(
            org_id=old.org_id,
            cycle_id=old.cycle_id,
            email=new_key,
            name=old.name,
            leader=new_leader,
            slack_user_id=old.slack_user_id,
            responded=old.responded,
            responded_at=old.responded_at,
            created_at=old.created_at,
        )
        nps_nomination_repo.put_nomination(new_nom)

    # Add new workbook rows
    for t in plan_add:
        new_key = encode_for_leader(t["email"], t["leader"], taken_keys)
        nom = Nomination(
            org_id=args.org,
            cycle_id=args.cycle,
            email=new_key,
            name=t["name"],
            leader=t["leader"],
            responded=t["responded_flag"],
            responded_at=(datetime.now(timezone.utc).isoformat()
                          if t["responded_flag"] else ""),
        )
        nps_nomination_repo.put_nomination(nom)

    # Re-tag responses
    from app.db.nps_response_repo import _build_composite_key, _get_table  # noqa: E402
    table = _get_table()
    pk = _build_composite_key(args.org, args.cycle)
    for r, new_leader in resp_retag_plans:
        table.update_item(
            Key={"org_id_cycle_id": pk, "response_id": r.response_id},
            UpdateExpression="SET #ld = :ld",
            ExpressionAttributeNames={"#ld": "leader"},
            ExpressionAttributeValues={":ld": new_leader},
        )

    logger.info("[%s] Done. nominations: kept=%d retagged=%d offlist-kept=%d "
                "dropped=%d self-dropped=%d added=%d | responses retagged=%d",
                args.org,
                len(plan_keep), len(plan_retag), len(plan_offlist_keep),
                len(plan_drop), len(plan_self_drop), len(plan_add),
                resp_retag_count)


if __name__ == "__main__":
    main()
