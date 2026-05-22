"""Merge synthetic-email nominations into their real-email counterparts.

Backfill creates ``asana-task-{gid}@unknown.local`` rows when an Asana
task has no assignee email. If the same human ALSO has a real-email
nomination (because the workbook covered them), we end up with two rows
representing the same person — one of them with a junk email.

This script merges them:

  Same-leader same-name match (SAFE):
    - Synthetic row's responded=True merges into the real row, marking it
      responded if it wasn't.
    - Synthetic row is deleted.

  Cross-leader same-name match (REPORTED, NOT MERGED):
    - The synthetic row says the person responded under a leader who
      didn't nominate them in the workbook (off-list response). That's
      legitimate per rule 3 — keep the synthetic row as the off-list
      nomination. Just print it for awareness.

Usage on EC2:

    /usr/bin/python3.11 scripts/merge_synthetic_nominations.py \\
        --org whs_cpt_na --cycle h1-2026 --dry-run

Drop --dry-run to apply.

Safety:
  - --dry-run prints the merge plan, writes nothing.
  - Only touches NpsNominations. NpsResponses stay untouched (they are
    keyed by response_id, not email, so no rewrite is needed).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

from app.db import nps_nomination_repo  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("merge_synth")

SYNTHETIC_PREFIX = "asana-task-"
SYNTHETIC_DOMAIN = "@unknown.local"


def _norm_name(name: str) -> str:
    return " ".join((name or "").lower().split())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True)
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    noms = nps_nomination_repo.list_nominations(args.org, args.cycle)
    logger.info("[%s] %d nominations", args.org, len(noms))

    synthetics = [n for n in noms
                  if n.email.startswith(SYNTHETIC_PREFIX) and SYNTHETIC_DOMAIN in n.email]
    real = [n for n in noms if n not in synthetics]

    logger.info("[%s] synthetic rows: %d, real rows: %d",
                args.org, len(synthetics), len(real))

    # Index real rows by (norm_name, leader)
    real_by_pair: dict[tuple[str, str], list] = {}
    for n in real:
        key = (_norm_name(n.name), (n.leader or "").strip())
        real_by_pair.setdefault(key, []).append(n)

    same_leader_merges: list[tuple[object, object]] = []
    cross_leader_skips: list[object] = []
    no_match: list[object] = []

    for syn in synthetics:
        nm = _norm_name(syn.name)
        if not nm:
            no_match.append(syn)
            continue
        same_leader = real_by_pair.get((nm, (syn.leader or "").strip()))
        if same_leader:
            same_leader_merges.append((syn, same_leader[0]))
            continue
        # Look across leaders for a same-name real row
        any_real = [r for r in real if _norm_name(r.name) == nm]
        if any_real:
            cross_leader_skips.append(syn)
        else:
            no_match.append(syn)

    logger.info("[%s] plan: merge=%d cross-leader-keep=%d unmatched=%d",
                args.org, len(same_leader_merges), len(cross_leader_skips), len(no_match))

    for syn, real_n in same_leader_merges:
        logger.info("  MERGE: %s -> %s (name='%s' leader='%s')",
                    syn.email, real_n.email, syn.name, syn.leader)
        if real_n.responded != syn.responded:
            logger.info("        responded: %s -> %s", real_n.responded, True)
    for syn in cross_leader_skips:
        logger.info("  KEEP (cross-leader off-list): email=%s name='%s' leader='%s'",
                    syn.email, syn.name, syn.leader)
    for syn in no_match:
        logger.info("  KEEP (no real-email match): email=%s name='%s' leader='%s'",
                    syn.email, syn.name, syn.leader)

    if args.dry_run:
        logger.info("DRY RUN — no changes made.")
        return

    for syn, real_n in same_leader_merges:
        # Mark the real row as responded if the synthetic was responded
        if syn.responded and not real_n.responded:
            nps_nomination_repo.update_nomination(
                args.org, args.cycle, real_n.email,
                responded=True,
                responded_at=(syn.responded_at or real_n.responded_at or ""),
            )
        nps_nomination_repo.delete_nomination(args.org, args.cycle, syn.email)

    logger.info("[%s] Done. merged=%d", args.org, len(same_leader_merges))


if __name__ == "__main__":
    main()
