"""Reconcile DynamoDB nominations against the workbook source of truth.

Per project rules (May 2026):
  1. WORKBOOK = source of truth. Every "Yes" row in H1 2026 sheet -> nomination.
  2. SHARED stakeholders -> multiple nominations (#leader suffix).
  3. OFF-LIST RESPONDERS -> legitimate nominations under their picked leader
     (kept because they actually answered the survey).

This script converges the live DynamoDB state to those rules in one pass:

  ADD      :  (base_email, leader) is in the workbook but NOT in DB
              -> create a new Nomination with the right key, preserving any
                 already-taken plain-email keys.
  KEEP     :  (base_email, leader) is in DB AND (a) in the workbook,
              OR (b) has responded=True (rule 3 — off-list responder).
  DROP     :  (base_email, leader) is in DB, NOT in the workbook, AND
              responded=False. Likely an orphan from an earlier import or a
              row whose stakeholder was un-flagged in the workbook.

Optional extras done on the way:
  - pattern 2 (leader self-response) deletes still happen here for safety
    (cleanup script may not have been run on every org).
  - pattern 1 (synthetic email rewrite) is NOT done here. Run
    cleanup_offlist_nominations.py first if you have synthetic-email rows.

Usage on the EC2:

    /usr/bin/python3.11 scripts/reconcile_workbook_nominations.py \\
        --workbook /tmp/cpt_in.xlsx --org whs_cpt_in --cycle h1-2026 --dry-run

Drop --dry-run to apply.

Safety:
  - --dry-run prints the planned ADD/DROP list, writes nothing.
  - Aborts if the workbook parses 0 yes-rows.
  - NpsResponses are never touched.
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

from app.db import nps_nomination_repo  # noqa: E402
from app.db.models import Nomination  # noqa: E402
from app.services.nomination_keys import base_email, encode_for_leader  # noqa: E402
from scripts.import_h1_2026_stakeholders import (  # noqa: E402
    ORG_CONFIGS,
    _norm_leader_name,
    _parse_h1_2026,
    _parse_stakeholder_list,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("reconcile")


def _build_workbook_targets(workbook: Path, org: str) -> list[dict]:
    """Return ordered list of {email, leader, name, responded} target rows.

    Order matches the H1 2026 sheet so the FIRST appearance of a base email
    claims the unsuffixed key (matches import_h1_2026_stakeholders.py).
    """
    cfg = ORG_CONFIGS[org]
    yes_rows = _parse_h1_2026(workbook, cfg)
    sh_map = _parse_stakeholder_list(workbook, cfg)

    out: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    for row in yes_rows:
        alias = row["stakeholder_alias"]
        if not alias:
            continue
        sh = sh_map.get(alias) or {}
        email = (sh.get("email") or f"{alias}@amazon.com").strip().lower()
        # Leader comes from the H1 2026 sheet's POC column — that's the
        # source of truth for which leader nominated this stakeholder.
        # Stakeholder List's leader column only carries ONE leader per
        # alias, so using it would collapse shared stakeholders that
        # legitimately appear under multiple POCs.
        leader_raw = row["poc"] or sh.get("leader") or ""
        leader = _norm_leader_name(leader_raw)
        if not leader:
            continue
        pair = (email, leader)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        out.append({
            "email": email,
            "leader": leader,
            "name": row["stakeholder"],
            "responded_flag": (row.get("responded") == "yes"),
        })
    return out


def _pair(nom: Nomination) -> tuple[str, str]:
    """(base_email, normalized_leader) tuple for matching against workbook."""
    return (base_email(nom.email).strip().lower(),
            _norm_leader_name((nom.leader or "").strip()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--org", required=True, choices=sorted(ORG_CONFIGS.keys()))
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-self-noms", action="store_true",
                        help="Also drop leader self-response nominations "
                             "(name == leader). Default: skip (assume "
                             "cleanup_offlist_nominations.py handled them).")
    args = parser.parse_args()

    if not args.workbook.is_file():
        sys.exit(f"Workbook not found: {args.workbook}")

    targets = _build_workbook_targets(args.workbook, args.org)
    if not targets:
        sys.exit(f"Workbook returned 0 yes-rows for org='{args.org}' — refusing "
                 f"to mutate. Check the H1 2026 sheet.")

    target_pairs = {(t["email"], t["leader"]) for t in targets}
    logger.info("[%s] %d target (email, leader) pairs from workbook",
                args.org, len(target_pairs))

    existing = nps_nomination_repo.list_nominations(args.org, args.cycle)
    logger.info("[%s] %d nominations in DynamoDB", args.org, len(existing))

    existing_by_pair: dict[tuple[str, str], Nomination] = {
        _pair(n): n for n in existing
    }

    # Plan ADDs: every workbook target with no matching existing pair
    to_add: list[dict] = [t for t in targets
                          if (t["email"], t["leader"]) not in existing_by_pair]

    # Plan DROPs: every existing pair that's not in workbook AND not responded.
    # Off-list responders (responded=True) stay per rule 3.
    to_drop: list[Nomination] = []
    self_noms: list[Nomination] = []
    for n in existing:
        p = _pair(n)
        if p in target_pairs:
            continue
        # Optional pattern 2 — leader self-response
        nom_name = _norm_leader_name((n.name or "").strip())
        nom_leader = p[1]
        is_self_nom = bool(nom_name) and nom_name == nom_leader
        if is_self_nom:
            self_noms.append(n)
            if args.include_self_noms:
                to_drop.append(n)
            continue
        if not n.responded:
            to_drop.append(n)

    logger.info("[%s] ADD %d, DROP %d (self-noms detected: %d, %s)",
                args.org, len(to_add), len(to_drop), len(self_noms),
                "included" if args.include_self_noms else "skipped")

    for t in to_add:
        logger.info("  ADD: leader='%s' email=%s name='%s' responded=%s",
                    t["leader"], t["email"], t["name"], t["responded_flag"])
    for n in to_drop:
        logger.info("  DROP: email=%s leader='%s' name='%s' responded=%s",
                    n.email, n.leader, n.name, n.responded)
    if self_noms and not args.include_self_noms:
        for n in self_noms:
            logger.info("  KEEP (self-nom, pass --include-self-noms to drop): "
                        "email=%s leader='%s' name='%s'",
                        n.email, n.leader, n.name)

    if args.dry_run:
        logger.info("DRY RUN — no changes made.")
        return

    # Apply DROPs first so the freed-up plain-email keys are available for
    # ADDs that target the same base email.
    for n in to_drop:
        nps_nomination_repo.delete_nomination(args.org, args.cycle, n.email)

    # Refresh taken_keys from current state minus drops, including off-list
    # responder rows we kept.
    kept = [n for n in existing if n not in to_drop]
    taken_keys: set[str] = {n.email.strip().lower() for n in kept if n.email}

    # Apply ADDs in workbook order so the first occurrence of each base email
    # claims the unsuffixed key (matches import_h1_2026_stakeholders order).
    for t in to_add:
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

    logger.info("[%s] Done. added=%d dropped=%d", args.org, len(to_add), len(to_drop))


if __name__ == "__main__":
    main()
