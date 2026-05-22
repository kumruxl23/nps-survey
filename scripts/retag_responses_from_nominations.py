"""Retag NpsResponses to match the leader on their matching Nomination row.

After a workbook-leader migration, NpsResponses can be left holding the
OLD leader name even though the corresponding Nomination row has been
re-tagged to the new POC. The dashboard groups by `response.leader`, so
the dashboard ends up showing responses under leaders who no longer
nominated those people.

This script walks every response, finds the Nomination row that best
represents its respondent, and copies that nomination's leader onto the
response. Matching priority:

  1. Exact: response.respondent_name == nomination.name (norm)
     AND response.leader == nomination.leader -> already correct, skip
  2. Same name, different leader: respondent_name matches nomination.name
     and the response's current leader is one of the leaders that have
     nominations for that respondent -> already correct, skip
  3. Same name, no current-leader match -> retag to the FIRST nomination's
     leader for that respondent
  4. Fuzzy name match (token overlap, handles 'Ganesh Kumar' vs
     'Ganesh Kumar Subramanian') -> retag to the matched nom's leader
  5. No match -> leave as-is (off-list response we can't place)

Usage on EC2:

    /usr/bin/python3.11 scripts/retag_responses_from_nominations.py \\
        --org whs_cpt_na --cycle h1-2026 --dry-run

Drop --dry-run to apply.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

from app.db import nps_nomination_repo, nps_response_repo  # noqa: E402
from app.db.nps_response_repo import _build_composite_key, _get_table  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("retag_resp")


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True)
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    noms = nps_nomination_repo.list_nominations(args.org, args.cycle)
    resps = nps_response_repo.list_responses(args.org, args.cycle)
    logger.info("[%s] %d nominations, %d responses",
                args.org, len(noms), len(resps))

    # Index nominations by normalized name -> [leaders]
    name_to_leaders: dict[str, list[str]] = {}
    for n in noms:
        if not n.name:
            continue
        key = _norm_name(n.name)
        name_to_leaders.setdefault(key, [])
        if n.leader and n.leader not in name_to_leaders[key]:
            name_to_leaders[key].append(n.leader)

    plan: list[tuple[object, str]] = []
    skipped_correct = 0
    skipped_no_match = 0

    for r in resps:
        rname = _norm_name(r.respondent_name)
        if not rname:
            skipped_no_match += 1
            continue

        # Exact name match first
        leaders = name_to_leaders.get(rname)
        if leaders is None:
            # Fuzzy fallback
            for nom_name, lds in name_to_leaders.items():
                if _names_likely_same(rname, nom_name):
                    leaders = lds
                    break

        if not leaders:
            skipped_no_match += 1
            continue

        cur = (r.leader or "").strip()
        if cur in leaders:
            skipped_correct += 1
            continue

        # Pick the first leader (deterministic). If the response
        # respondent has multiple leaders, the one already on the
        # response would have hit the "already correct" branch; here
        # we just pick the first as canonical.
        plan.append((r, leaders[0]))

    logger.info("[%s] retag plan: %d responses (already-correct: %d, no-name-match: %d)",
                args.org, len(plan), skipped_correct, skipped_no_match)
    for r, new_leader in plan:
        logger.info("  RETAG resp_id=%s respondent='%s' leader='%s' -> '%s'",
                    r.response_id, r.respondent_name, r.leader, new_leader)

    if args.dry_run:
        logger.info("DRY RUN — no changes made.")
        return

    table = _get_table()
    pk = _build_composite_key(args.org, args.cycle)
    for r, new_leader in plan:
        table.update_item(
            Key={"org_id_cycle_id": pk, "response_id": r.response_id},
            UpdateExpression="SET #ld = :ld",
            ExpressionAttributeNames={"#ld": "leader"},
            ExpressionAttributeValues={":ld": new_leader},
        )

    logger.info("[%s] Done. retagged=%d", args.org, len(plan))


if __name__ == "__main__":
    main()
