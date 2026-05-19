"""Wipe Nominations + Responses for one org + one cycle.

Targeted complement to ``backup_and_wipe_test_data.py``. Use this when you
need to re-do the data for a specific org+cycle without touching others
(e.g. to re-import the targeted-list nominations for whs_cpt_in / H1 2026
without disturbing whs_cpt_na or fec).

What it does (always for the same single (org_id, cycle_id) pair):
  - Lists every Nomination for that org+cycle, deletes them all.
  - Lists every NpsResponse for that org+cycle, deletes them all.
  - Does NOT touch NpsSurveyCycles (the cycle row stays).
  - Does NOT touch NpsOrgConfig.
  - Does NOT touch any other org or any other cycle.

Usage:

    /usr/bin/python3.11 scripts/wipe_org_cycle_data.py \\
        --org whs_cpt_in --cycle h1-2026-backfill --dry-run

Drop --dry-run to actually delete. Will prompt for typed confirmation.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import boto3

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("wipe_org_cycle")

REGION = os.environ.get("AWS_REGION", "ap-south-1")

NOMINATIONS_TABLE = os.environ.get("NPS_NOMINATIONS_TABLE", "NpsNominations")
RESPONSES_TABLE = os.environ.get("NPS_RESPONSES_TABLE", "NpsResponses")


def _scan_partition(table_name: str, partition_key_value: str) -> list[dict]:
    """Scan a table for items whose 'org_id_cycle_id' matches the partition key."""
    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(table_name)
    items: list[dict] = []
    kwargs = {
        "FilterExpression": "org_id_cycle_id = :pk",
        "ExpressionAttributeValues": {":pk": partition_key_value},
    }
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return items


def _delete_items(table_name: str, key_attrs: tuple[str, ...], items: list[dict]) -> int:
    if not items:
        return 0
    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(table_name)
    deleted = 0
    with table.batch_writer() as batch:
        for item in items:
            key = {k: item[k] for k in key_attrs if k in item}
            batch.delete_item(Key=key)
            deleted += 1
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True, help="org_id (e.g. whs_cpt_in)")
    parser.add_argument("--cycle", required=True, help="cycle_id (e.g. h1-2026-backfill)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read-only — count items, do not delete.")
    parser.add_argument("--force", action="store_true",
                        help="Skip the typed-confirmation prompt.")
    parser.add_argument("--include-cycle-row", action="store_true",
                        help="Also delete the SurveyCycle row itself (use when "
                             "renaming/retiring a cycle entirely).")
    args = parser.parse_args()

    pk = f"{args.org}#{args.cycle}"
    logger.info("Targeting partition: %s", pk)

    nominations = _scan_partition(NOMINATIONS_TABLE, pk)
    responses = _scan_partition(RESPONSES_TABLE, pk)
    logger.info("Found %d nominations + %d responses to delete",
                len(nominations), len(responses))

    cycle_row = None
    if args.include_cycle_row:
        ddb = boto3.resource("dynamodb", region_name=REGION)
        cycle_table = ddb.Table(os.environ.get("NPS_SURVEY_CYCLES_TABLE", "NpsSurveyCycles"))
        resp = cycle_table.get_item(Key={"org_id": args.org, "cycle_id": args.cycle})
        cycle_row = resp.get("Item")
        logger.info("Cycle row %s/%s present: %s", args.org, args.cycle, bool(cycle_row))

    if args.dry_run:
        logger.info("DRY RUN — nothing deleted.")
        return

    if not nominations and not responses and not cycle_row:
        logger.info("Nothing to delete. Done.")
        return

    if not args.force:
        extra = " + cycle row" if cycle_row else ""
        confirm = input(
            f'\nThis will DELETE {len(nominations)} nominations + {len(responses)} responses'
            f'{extra} for org={args.org} cycle={args.cycle}.\n'
            f'Type "WIPE {args.org} {args.cycle}" to proceed: '
        ).strip()
        if confirm != f"WIPE {args.org} {args.cycle}":
            logger.info("Aborted by user.")
            return

    n_deleted = _delete_items(NOMINATIONS_TABLE, ("org_id_cycle_id", "email"), nominations)
    r_deleted = _delete_items(RESPONSES_TABLE, ("org_id_cycle_id", "response_id"), responses)
    logger.info("Deleted %d nominations + %d responses", n_deleted, r_deleted)

    if args.include_cycle_row and cycle_row:
        ddb = boto3.resource("dynamodb", region_name=REGION)
        cycle_table = ddb.Table(os.environ.get("NPS_SURVEY_CYCLES_TABLE", "NpsSurveyCycles"))
        cycle_table.delete_item(Key={"org_id": args.org, "cycle_id": args.cycle})
        logger.info("Deleted SurveyCycle row %s/%s", args.org, args.cycle)


if __name__ == "__main__":
    main()
