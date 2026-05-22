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


def _name_tokens(s: str) -> set[str]:
    """Token set for fuzzy name matching (handles 'Alex' vs 'Alexander')."""
    raw = _norm_name(s)
    return {t for t in raw.replace(",", " ").split() if t}


def _names_likely_same(a: str, b: str) -> bool:
    """Loose match: same name if every short-name token is substring of a
    long-name token in the other string, OR they share 2+ tokens.

    Examples:
      'Alex Kraemer' ~ 'Alexander Kraemer'      -> True (alex in alexander, kraemer ==)
      'Ganesh Kumar' ~ 'Ganesh Kumar Subramanian'-> True (2+ shared tokens)
      'Alice Smith' ~ 'Bob Jones'              -> False
    """
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    if _norm_name(a) == _norm_name(b):
        return True
    # 2+ shared tokens (handles middle name / suffix differences)
    if len(ta & tb) >= 2:
        return True
    # Each token in the smaller set is substring of some token in the larger
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return all(any(s in lg or lg in s for lg in large) for s in small)


SYNTH_PREFIX = "asana-task-"
SYNTH_DOMAIN = "@unknown.local"


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
    name_keys_in_wb: list[tuple[str, str]] = []  # (raw_name, email)
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
            name_keys_in_wb.append((row["stakeholder"], email))

    # Set of all leader names that appear in the workbook — used to detect
    # leader self-noms with fuzzy matching.
    workbook_leaders: set[str] = {t["leader"] for t in workbook_targets}

    workbook_pairs = {(t["email"], t["leader"]) for t in workbook_targets}
    logger.info("[%s] workbook targets: %d, unique emails: %d",
                args.org, len(workbook_pairs), len(email_to_leaders))

    existing_noms = nps_nomination_repo.list_nominations(args.org, args.cycle)
    existing_resps = nps_response_repo.list_responses(args.org, args.cycle)
    logger.info("[%s] DB: %d nominations, %d responses",
                args.org, len(existing_noms), len(existing_resps))

    # --- plan nomination changes -----------------------------------------

    plan_keep: list[Nomination] = []          # already correct
    # plan_retag entries are EITHER (old_nom, new_leader) — keep email — OR
    # (old_nom, new_leader, new_base_email) — rewrite email AND leader.
    plan_retag: list[tuple] = []
    plan_offlist_keep: list[Nomination] = []  # responded=True, not in WB
    plan_drop: list[Nomination] = []          # responded=False, not in WB
    plan_self_drop: list[Nomination] = []     # name == leader
    plan_add: list[dict] = []                 # new (email, leader) from WB

    for n in existing_noms:
        be = base_email(n.email).strip().lower()
        cur_leader = _norm_leader_name((n.leader or "").strip())
        nom_name = _norm_name(n.name)

        # Self-nom: name resembles ANY workbook leader (fuzzy match catches
        # 'Alex Kraemer' nom under 'Alexander Kraemer' leader).
        is_self_nom = False
        for wl in {cur_leader, *workbook_leaders}:
            if wl and _names_likely_same(n.name, wl):
                is_self_nom = True
                break
        if is_self_nom:
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

        # Email not in workbook directly. Try to match by NAME — synthetic
        # rows ('asana-task-...@unknown.local') and other off-list rows
        # often share a name with a workbook person who responded under a
        # different leader. If so, retag the synthetic into the workbook
        # person's email + leader. Otherwise it's a true off-list response.
        is_synthetic = (n.email.startswith(SYNTH_PREFIX)
                        and SYNTH_DOMAIN in n.email)
        wb_email_for_name: str | None = None
        for wb_name, wb_email in name_keys_in_wb:
            if _names_likely_same(n.name, wb_name):
                wb_email_for_name = wb_email
                break

        if wb_email_for_name and n.responded:
            # If their CURRENT leader matches one of the workbook leaders
            # for that email, retag to that leader. Otherwise, retag to the
            # first workbook leader.
            wb_leaders = email_to_leaders.get(wb_email_for_name, [])
            target_leader = wb_leaders[0] if wb_leaders else cur_leader
            for wl in wb_leaders:
                if _norm_leader_name(wl) == cur_leader:
                    target_leader = wl
                    break
            # Use a synthetic-marker tuple so the apply step knows to
            # rewrite the email AND the leader.
            plan_retag.append((n, target_leader, wb_email_for_name))  # type: ignore[arg-type]
            continue

        # No name match either - true off-list responder or junk
        if n.responded:
            plan_offlist_keep.append(n)
        elif is_synthetic:
            # Synthetic + not responded + no match — junk row, drop
            plan_drop.append(n)
        else:
            plan_drop.append(n)

    # ADDs: any workbook pair not already covered by KEEP or RETAG
    covered_pairs: set[tuple[str, str]] = {
        (base_email(n.email).strip().lower(),
         _norm_leader_name((n.leader or "").strip()))
        for n in plan_keep
    }

    # Dedup retag entries that resolve to the same (target_email, target_leader).
    # A synthetic row + a real-email row can both fuzzy-match into the same
    # workbook pair — keep the real-email source, drop the synthetic.
    def _retag_target(entry):
        if len(entry) == 2:
            old, new_leader = entry
            new_be = base_email(old.email).strip().lower()
        else:
            old, new_leader, new_be = entry
        return (new_be, _norm_leader_name(new_leader))

    deduped_retag: list[tuple] = []
    by_target: dict[tuple[str, str], tuple] = {}
    for entry in plan_retag:
        target = _retag_target(entry)
        existing_entry = by_target.get(target)
        if existing_entry is None:
            by_target[target] = entry
            continue
        # Pick the real-email source over synthetic; if both real, keep
        # the first one (deterministic).
        cur_old = existing_entry[0]
        new_old = entry[0]
        cur_is_synth = (cur_old.email.startswith(SYNTH_PREFIX)
                        and SYNTH_DOMAIN in cur_old.email)
        new_is_synth = (new_old.email.startswith(SYNTH_PREFIX)
                        and SYNTH_DOMAIN in new_old.email)
        if cur_is_synth and not new_is_synth:
            # Drop the synth, keep the real
            plan_drop.append(cur_old)
            by_target[target] = entry
        else:
            # Keep what we already have, drop the new one
            plan_drop.append(new_old)
    deduped_retag = list(by_target.values())
    if len(deduped_retag) < len(plan_retag):
        logger.info("[%s] retag dedup: %d -> %d (collisions on same target pair)",
                    args.org, len(plan_retag), len(deduped_retag))
    plan_retag = deduped_retag

    for entry in plan_retag:
        covered_pairs.add(_retag_target(entry))
    for t in workbook_targets:
        if (t["email"], t["leader"]) not in covered_pairs:
            plan_add.append(t)

    logger.info("[%s] NOMINATION plan: keep=%d retag=%d offlist-keep=%d "
                "drop=%d self-drop=%d add=%d",
                args.org, len(plan_keep), len(plan_retag), len(plan_offlist_keep),
                len(plan_drop), len(plan_self_drop), len(plan_add))

    for entry in plan_retag:
        if len(entry) == 2:
            n, new_leader = entry
            logger.info("  RETAG: email=%s name='%s' leader='%s' -> '%s'",
                        n.email, n.name, n.leader, new_leader)
        else:
            n, new_leader, new_be = entry
            logger.info("  RETAG (rewrite email): %s -> %s, leader='%s' -> '%s' (name='%s')",
                        n.email, new_be, n.leader, new_leader, n.name)
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
            # Fuzzy fallback for spelling differences ('Ganesh Kumar Subramanian'
            # vs workbook's 'Ganesh Kumar').
            for wb_name, wb_email in name_keys_in_wb:
                if _names_likely_same(r.respondent_name, wb_name):
                    be = wb_email
                    break
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
    #
    # Order matters: do ALL deletes before ANY puts. Otherwise an interleaved
    # apply can delete a row we just wrote — e.g. when synthetic 'jsarreal@'
    # retag claims plain 'jsarreal@amazon.com' and the next retag's delete
    # of the SAME email wipes our just-written row.

    # 1. Collect every key that will be deleted
    keys_to_delete: list[str] = []
    for n in plan_drop + plan_self_drop:
        keys_to_delete.append(n.email)
    for entry in plan_retag:
        old = entry[0]
        keys_to_delete.append(old.email)

    # 2. Build the put list (resolve sort-keys against a taken_keys set
    # that reflects the post-delete state).
    taken_keys: set[str] = set()
    for n in plan_keep + plan_offlist_keep:
        if n.email:
            taken_keys.add(n.email.strip().lower())

    puts: list[Nomination] = []
    for entry in plan_retag:
        if len(entry) == 2:
            old, new_leader = entry
            new_be = base_email(old.email).strip().lower()
        else:
            old, new_leader, new_be = entry
        new_key = encode_for_leader(new_be, new_leader, taken_keys)
        puts.append(Nomination(
            org_id=old.org_id,
            cycle_id=old.cycle_id,
            email=new_key,
            name=old.name,
            leader=new_leader,
            slack_user_id=old.slack_user_id,
            responded=old.responded,
            responded_at=old.responded_at,
            created_at=old.created_at,
        ))

    for t in plan_add:
        new_key = encode_for_leader(t["email"], t["leader"], taken_keys)
        puts.append(Nomination(
            org_id=args.org,
            cycle_id=args.cycle,
            email=new_key,
            name=t["name"],
            leader=t["leader"],
            responded=t["responded_flag"],
            responded_at=(datetime.now(timezone.utc).isoformat()
                          if t["responded_flag"] else ""),
        ))

    # 3. Apply: deletes first, then puts.
    for key in keys_to_delete:
        nps_nomination_repo.delete_nomination(args.org, args.cycle, key)
    for nom in puts:
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
