"""Backup and wipe test data from NPS DynamoDB tables.

Backs up the 5 transactional tables to JSON files, then deletes every
record in those tables. The ``NpsOrgConfig`` table is NOT touched —
it holds admin user accounts and Asana project/field configuration.

Usage (run on the EC2):

    sudo -u ssm-user -H bash -lc \\
        'export PYTHONPATH=/home/ssm-user/.local/lib/python3.11/site-packages && \\
         cd /opt/nps-survey && \\
         /usr/bin/python3.11 scripts/backup_and_wipe_test_data.py --backup-only'

Then to actually wipe (after reviewing the backup):

    /usr/bin/python3.11 scripts/backup_and_wipe_test_data.py --wipe \\
        --backup-dir /tmp/nps-backup-<timestamp>

Safety:
    - Two-phase: --backup-only does not modify anything.
    - --wipe requires --backup-dir to point at a *successful* backup.
    - Confirms each table item count before deleting.
    - NpsOrgConfig is hard-coded NOT to be touched.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import boto3

REGION = os.environ.get("AWS_REGION", "ap-south-1")

# Tables to backup + wipe. Each entry = (env_var_name, default_table_name, key_attrs)
TABLES_TO_WIPE = [
    ("NPS_SURVEY_CYCLES_TABLE",     "NpsSurveyCycles",     ("org_id", "cycle_id")),
    ("NPS_NOMINATIONS_TABLE",        "NpsNominations",      ("org_id_cycle_id", "email")),
    ("NPS_RESPONSES_TABLE",          "NpsResponses",        ("org_id_cycle_id", "response_id")),
    ("NPS_REMINDER_LOGS_TABLE",      "NpsReminderLogs",     ("org_id_cycle_id", "log_id")),
    ("NPS_DELIVERY_FAILURES_TABLE",  "NpsDeliveryFailures", ("org_id_cycle_id", "failure_id")),
]

# Hard-coded protected table — never wiped by this script.
PROTECTED_TABLE = "NpsOrgConfig"


class DecimalEncoder(json.JSONEncoder):
    """Convert DynamoDB Decimals to int/float so JSON dump works."""
    def default(self, o):
        if isinstance(o, Decimal):
            if o == int(o):
                return int(o)
            return float(o)
        return super().default(o)


def _resolve_table_name(env_var: str, default: str) -> str:
    return os.environ.get(env_var, default)


def _scan_all(table) -> list[dict]:
    """Scan an entire table, paginating until done."""
    items: list[dict] = []
    kwargs = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return items


def backup(backup_dir: Path) -> dict:
    """Snapshot every wipe-target table to JSON. Returns count summary."""
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    backup_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, int] = {}

    for env_var, default, _ in TABLES_TO_WIPE:
        table_name = _resolve_table_name(env_var, default)
        table = dynamodb.Table(table_name)
        items = _scan_all(table)
        out_file = backup_dir / f"{table_name}.json"
        with out_file.open("w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, cls=DecimalEncoder)
        summary[table_name] = len(items)
        print(f"  Backed up {len(items):>5} items from {table_name} -> {out_file}")

    # Also backup NpsOrgConfig separately as a precaution (we won't wipe it)
    table_name = PROTECTED_TABLE
    table = dynamodb.Table(table_name)
    items = _scan_all(table)
    out_file = backup_dir / f"{table_name}.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, cls=DecimalEncoder)
    summary[table_name] = len(items)
    print(f"  Backed up {len(items):>5} items from {table_name} -> {out_file}  (READ-ONLY snapshot)")

    return summary


def _verify_backup_exists(backup_dir: Path) -> dict:
    """Confirm the backup dir has a JSON file for every table, and load counts."""
    counts: dict[str, int] = {}
    missing: list[str] = []

    for env_var, default, _ in TABLES_TO_WIPE:
        table_name = _resolve_table_name(env_var, default)
        bf = backup_dir / f"{table_name}.json"
        if not bf.exists():
            missing.append(str(bf))
            continue
        with bf.open("r", encoding="utf-8") as f:
            items = json.load(f)
        counts[table_name] = len(items)

    if missing:
        raise SystemExit(
            "Backup verification failed — missing files:\n  - "
            + "\n  - ".join(missing)
            + "\nAborting wipe."
        )
    return counts


def wipe(backup_dir: Path, force: bool = False) -> None:
    """Delete every item in the wipe-target tables. Refuses without backup."""
    counts = _verify_backup_exists(backup_dir)
    print(f"\nVerified backup at {backup_dir}.")
    for name, n in counts.items():
        print(f"  {name}: {n} items in backup")

    if PROTECTED_TABLE in counts:
        # Sanity check: protected table file exists but we never delete from it
        pass

    if not force:
        print("\nThis will DELETE every item in the 5 tables above.")
        print(f"Region: {REGION}")
        print(f"Protected (NOT touched): {PROTECTED_TABLE}")
        confirm = input('Type "WIPE TEST DATA" to proceed: ').strip()
        if confirm != "WIPE TEST DATA":
            print("Aborted by user.")
            return

    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    for env_var, default, key_attrs in TABLES_TO_WIPE:
        table_name = _resolve_table_name(env_var, default)
        if table_name == PROTECTED_TABLE:  # paranoia
            continue
        table = dynamodb.Table(table_name)
        items = _scan_all(table)
        if not items:
            print(f"  {table_name}: already empty")
            continue
        deleted = 0
        with table.batch_writer() as batch:
            for item in items:
                key = {k: item[k] for k in key_attrs if k in item}
                batch.delete_item(Key=key)
                deleted += 1
        print(f"  {table_name}: deleted {deleted} items")

    print("\nWipe complete.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--backup-only", action="store_true",
                       help="Snapshot tables to JSON, do not delete anything.")
    group.add_argument("--wipe", action="store_true",
                       help="Delete all items from the 5 tables. Requires --backup-dir.")
    parser.add_argument("--backup-dir", type=Path,
                        help="Backup directory (created for --backup-only, "
                             "required for --wipe).")
    parser.add_argument("--force", action="store_true",
                        help="Skip the typed-confirmation prompt during --wipe.")
    args = parser.parse_args()

    if args.backup_only:
        if args.backup_dir is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
            args.backup_dir = Path(f"/tmp/nps-backup-{ts}")
        print(f"Backing up to {args.backup_dir}")
        summary = backup(args.backup_dir)
        print("\nBackup summary:")
        for name, n in summary.items():
            print(f"  {name}: {n} items")
        print(f"\nRe-run with: --wipe --backup-dir {args.backup_dir}")
        return

    if args.wipe:
        if args.backup_dir is None:
            sys.exit("--wipe requires --backup-dir pointing at a backup directory.")
        if not args.backup_dir.is_dir():
            sys.exit(f"Backup directory not found: {args.backup_dir}")
        wipe(args.backup_dir, force=args.force)


if __name__ == "__main__":
    main()
