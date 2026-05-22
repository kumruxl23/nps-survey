"""Prune nominations not on the targeted-list workbook.

⚠️ DEPRECATED as of the multi-leader rules (May 2026). New product rule:
   off-list responders are legitimate nominations (rule 3) and should NOT
   be pruned. Don't run this script unless you specifically want to drop
   nominations whose ``(base_email, leader)`` pair isn't in the workbook.

Usage on the EC2 (when you really want to run it):

    /usr/bin/python3.11 scripts/prune_extra_nominations.py \\
        --workbook /tmp/stakeholders.xlsx \\
        --org whs_cpt_in --cycle h1-2026 --dry-run

Drop --dry-run to actually delete.

Safety:
  - Refuses to run if the targeted-list parse returns 0 rows.
  - Only ever deletes from NpsNominations. Never touches NpsResponses.
  - Compares by ``(base_email, leader)`` so multi-leader rows count
    distinctly.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

from app.db import nps_nomination_repo  # noqa: E402
from app.services.nomination_keys import base_email  # noqa: E402

# Reuse the import script's parsing so we get exactly the same "yes" set.
from scripts.import_h1_2026_stakeholders import (  # noqa: E402
    ORG_CONFIGS,
    _parse_h1_2026,
    _parse_stakeholder_list,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("prune")


def workbook_pairs(workbook_path: Path, org_id: str) -> set[tuple[str, str]]:
    """Return the set of ``(email, leader)`` pairs on the workbook's targeted list.

    Multi-leader: if a stakeholder appears under 2 leaders, we get 2 pairs.
    """
    cfg = ORG_CONFIGS[org_id]
    yes_rows = _parse_h1_2026(workbook_path, cfg)
    sh_map = _parse_stakeholder_list(workbook_path, cfg)
    out: set[tuple[str, str]] = set()
    for row in yes_rows:
        alias = row["stakeholder_alias"]
        if not alias:
            continue
        sh = sh_map.get(alias)
        email = (sh or {}).get("email") if sh else ""
        if not email:
            email = f"{alias}@amazon.com"
        leader = (sh or {}).get("leader") if sh else ""
        if not leader:
            leader = row["poc"]
        out.add((email.strip().lower(), (leader or "").strip()))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True,
                        help="Path to the team's stakeholder workbook (.xlsx).")
    parser.add_argument("--org", required=True, choices=sorted(ORG_CONFIGS.keys()),
                        help="org_id to reconcile.")
    parser.add_argument("--cycle", required=True, help="cycle_id (e.g. h1-2026)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read-only — print what would be deleted, do nothing.")
    args = parser.parse_args()

    if not args.workbook.is_file():
        sys.exit(f"Workbook not found: {args.workbook}")

    targeted_pairs = workbook_pairs(args.workbook, args.org)
    if not targeted_pairs:
        sys.exit(f"Workbook returned 0 targeted (email, leader) pairs — refusing "
                 f"to delete anything. Check workbook path / sheet structure for "
                 f"org='{args.org}'.")

    logger.info("[%s] %d targeted (email, leader) pairs parsed from workbook.",
                args.org, len(targeted_pairs))

    nominations = nps_nomination_repo.list_nominations(args.org, args.cycle)
    logger.info("[%s] %d nominations currently in DynamoDB for cycle '%s'.",
                args.org, len(nominations), args.cycle)

    extras = []
    for n in nominations:
        pair = (base_email(n.email).strip().lower(), (n.leader or "").strip())
        if pair not in targeted_pairs:
            extras.append(n)

    logger.info("[%s] %d nominations are NOT on the targeted list and will be pruned.",
                args.org, len(extras))

    if not extras:
        logger.info("Nothing to do.")
        return

    for n in extras:
        logger.info("  candidate: email=%s leader=%r name=%r responded=%s",
                    n.email, n.leader, n.name, n.responded)

    if args.dry_run:
        logger.info("DRY RUN — nothing deleted.")
        return

    confirm = input(
        f'\nDelete {len(extras)} nominations from {args.org}/{args.cycle}? '
        f'(NpsResponses are untouched.)\nType "PRUNE {args.org} {args.cycle}" to proceed: '
    ).strip()
    if confirm != f"PRUNE {args.org} {args.cycle}":
        logger.info("Aborted by user.")
        return

    for n in extras:
        nps_nomination_repo.delete_nomination(args.org, args.cycle, n.email)
    logger.info("[%s] Deleted %d nominations.", args.org, len(extras))


if __name__ == "__main__":
    main()
