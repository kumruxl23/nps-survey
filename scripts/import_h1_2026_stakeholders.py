"""Import H1 2026 targeted-stakeholder nominations from the Sandeep Directs workbook.

Reads the "Sandeep Directs - WHS CPT IN Targeted Stakeholder List for NPS Survey.xlsx"
workbook and writes a Nomination row for every stakeholder marked "Yes" for
the H1 2026 targeted-list inclusion question.

How the workbook is parsed:
- "H1 2026" sheet: PoC, PoC Alias, Stakeholder, Stakeholder Alias, "Should this
  stakeholder be included in H1 2026 survey? (Targeted list)"
- "Stakeholder List" sheet: PoC, PoC Alias, Stakeholder Alias, Email, Responded.
  Used to resolve real email addresses (some are .uk / .pl, not @amazon.com).

Cross-reference: each H1 2026 row marked "Yes" is matched to the Stakeholder List
by Stakeholder Alias to get the email. If no match is found, we fall back to
``<alias>@amazon.com`` and log a warning.

Usage (run on the EC2):

    /usr/bin/python3.11 scripts/import_h1_2026_stakeholders.py \\
        --workbook "Sandeep Directs - WHS CPT IN Targeted Stakeholder List for NPS Survey.xlsx" \\
        --org whs_cpt_in --dry-run

Then drop --dry-run to actually write.

The script writes ONLY to NpsNominations. It does NOT touch responses, cycles,
or org configs.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

from app.db import nps_cycle_repo, nps_nomination_repo  # noqa: E402
from app.db.models import Nomination  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("import_stakeholders")

# Sheet + column conventions
H1_2026_SHEET = "H1 2026"
STAKEHOLDER_LIST_SHEET = "Stakeholder List"

H1_2026_COLS = {
    "poc": "PoC",
    "poc_alias": "PoC Alias",
    "stakeholder": "Stakeholder",
    "stakeholder_alias": "Stakeholder\nAlias",  # has a newline in the header
    "include_in_h1_2026": "Should this stakeholder be included in\nH1 2026 survey?\n(Targeted list)",
    "responded": "Did stakeholder respond to\nH1 NPS 2026?",
}

STAKEHOLDER_LIST_COLS = {
    "poc": "PoC",
    "poc_alias": "PoC Alias",
    "stakeholder_alias": "Stakeholder",  # NB: column 4 is the alias on this sheet, despite the header text
    "email": "Email",
    "responded": "Responded",
}

DEFAULT_CYCLE_ID = "h1-2026-backfill"


def _norm_leader_name(name: str) -> str:
    """Collapse spelling variations (e.g. 'NIdhi Bhagat' -> 'Nidhi Bhagat')."""
    if not name:
        return ""
    cleaned = " ".join(name.split())  # collapse internal whitespace
    # Title-case is wrong for names with all-caps surnames; instead, lowercase
    # the *first* token and re-Title only the case-broken initial char.
    # Simpler heuristic: re-Title the whole thing.
    return cleaned.title()


def _row_to_dict(headers: list[str], row_values: list) -> dict[str, object]:
    return {h: v for h, v in zip(headers, row_values) if h is not None}


def _find_header_row(ws, max_check: int = 10) -> int:
    """Return the 1-indexed row number of the first row with >= 3 non-empty cells."""
    for r in range(1, min(ws.max_row, max_check) + 1):
        nonempty = sum(1 for c in ws[r] if c.value not in (None, ""))
        if nonempty >= 3:
            return r
    raise ValueError("No header row found in first 10 rows")


def _parse_h1_2026(workbook_path: Path) -> list[dict]:
    """Return the list of stakeholder rows marked Yes for H1 2026 inclusion."""
    wb = openpyxl.load_workbook(workbook_path, data_only=True)
    ws = wb[H1_2026_SHEET]
    header_row = _find_header_row(ws)
    headers = [c.value for c in ws[header_row]]

    yes_rows: list[dict] = []
    for r in range(header_row + 1, ws.max_row + 1):
        values = [c.value for c in ws[r]]
        if not any(v not in (None, "") for v in values):
            continue
        row = _row_to_dict(headers, values)
        flag = (row.get(H1_2026_COLS["include_in_h1_2026"]) or "").strip().lower()
        if flag != "yes":
            continue
        yes_rows.append({
            "poc": _norm_leader_name(str(row.get(H1_2026_COLS["poc"]) or "")),
            "poc_alias": (row.get(H1_2026_COLS["poc_alias"]) or "").strip().lower(),
            "stakeholder": (row.get(H1_2026_COLS["stakeholder"]) or "").strip(),
            "stakeholder_alias": (row.get(H1_2026_COLS["stakeholder_alias"]) or "").strip().lower(),
            "responded": (row.get(H1_2026_COLS["responded"]) or "").strip().lower(),
        })

    return yes_rows


def _parse_stakeholder_list(workbook_path: Path) -> dict[str, dict]:
    """Return a map of stakeholder_alias -> {email, poc, ...} from the Stakeholder List sheet."""
    wb = openpyxl.load_workbook(workbook_path, data_only=True)
    if STAKEHOLDER_LIST_SHEET not in wb.sheetnames:
        logger.warning("Workbook has no '%s' sheet; emails will be constructed from aliases.",
                       STAKEHOLDER_LIST_SHEET)
        return {}

    ws = wb[STAKEHOLDER_LIST_SHEET]
    header_row = _find_header_row(ws)
    headers = [c.value for c in ws[header_row]]

    # The header for col 4 in the Stakeholder List sheet is also "Stakeholder",
    # which collides. We resolve by position rather than name when needed.
    by_alias: dict[str, dict] = {}
    for r in range(header_row + 1, ws.max_row + 1):
        values = [c.value for c in ws[r]]
        if not any(v not in (None, "") for v in values):
            continue
        # Position-based read (safer given the duplicate header)
        poc = _norm_leader_name(str(values[0] or ""))
        poc_alias = (values[1] or "").strip().lower() if len(values) > 1 else ""
        # Column 3 contains the stakeholder alias in this sheet
        stakeholder_alias = (values[3] or "").strip().lower() if len(values) > 3 else ""
        email_raw = values[4] if len(values) > 4 else None
        if not stakeholder_alias:
            continue
        email = (str(email_raw) if email_raw else "").strip().lower()
        if not email and stakeholder_alias:
            email = f"{stakeholder_alias}@amazon.com"

        by_alias[stakeholder_alias] = {
            "email": email,
            "poc": poc,
            "poc_alias": poc_alias,
        }

    return by_alias


def _ensure_cycle(org_id: str, cycle_id: str, dry_run: bool) -> None:
    """If the cycle doesn't exist, create a closed H1-2026 cycle."""
    existing = nps_cycle_repo.get_cycle(org_id, cycle_id)
    if existing:
        return
    logger.info("[%s] cycle %s does not exist", org_id, cycle_id)
    if dry_run:
        logger.info("[%s] DRY RUN — would create cycle %s", org_id, cycle_id)
        return
    # Defer to backfill_from_asana to actually create cycles. The import
    # script doesn't own cycle creation.
    logger.warning("[%s] cycle %s missing — run backfill_from_asana --backfill first "
                   "to create the cycle.", org_id, cycle_id)


def import_nominations(
    workbook_path: Path,
    org_id: str,
    cycle_id: str,
    dry_run: bool,
) -> dict[str, int]:
    stats = {
        "yes_rows": 0,
        "matched_in_stakeholder_list": 0,
        "fallback_email_constructed": 0,
        "nominations_written": 0,
    }

    yes_rows = _parse_h1_2026(workbook_path)
    stakeholder_map = _parse_stakeholder_list(workbook_path)
    stats["yes_rows"] = len(yes_rows)
    logger.info("Parsed %d 'Yes' rows from %s", len(yes_rows), H1_2026_SHEET)
    logger.info("Loaded %d entries from %s", len(stakeholder_map), STAKEHOLDER_LIST_SHEET)

    _ensure_cycle(org_id, cycle_id, dry_run)

    seen_emails: set[str] = set()

    for row in yes_rows:
        alias = row["stakeholder_alias"]
        if not alias:
            logger.debug("Skipping row with no stakeholder alias: %s", row)
            continue

        sh = stakeholder_map.get(alias)
        if sh and sh["email"]:
            email = sh["email"]
            stats["matched_in_stakeholder_list"] += 1
        else:
            email = f"{alias}@amazon.com"
            stats["fallback_email_constructed"] += 1
            logger.debug("No stakeholder-list email for alias '%s', constructed '%s'",
                         alias, email)

        if email in seen_emails:
            logger.debug("Duplicate email %s in 'Yes' list, skipping", email)
            continue
        seen_emails.add(email)

        nomination = Nomination(
            org_id=org_id,
            cycle_id=cycle_id,
            email=email,
            name=row["stakeholder"],
            leader=row["poc"],
            responded=(row["responded"] == "yes"),
            responded_at="" if row["responded"] != "yes"
            else datetime.now(timezone.utc).isoformat(),
        )

        if dry_run:
            logger.debug("DRY RUN nomination: leader='%s' email=%s name='%s' responded=%s",
                         nomination.leader, nomination.email, nomination.name, nomination.responded)
        else:
            nps_nomination_repo.put_nomination(nomination)

        stats["nominations_written"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True,
                        help="Path to the Sandeep Directs workbook (.xlsx).")
    parser.add_argument("--org", default="whs_cpt_in",
                        help="org_id to import nominations under (default: whs_cpt_in).")
    parser.add_argument("--cycle-id", default=DEFAULT_CYCLE_ID,
                        help="cycle_id to attach nominations to (default: h1-2026-backfill).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read-only — print stats, write nothing.")
    args = parser.parse_args()

    if not args.workbook.is_file():
        sys.exit(f"Workbook not found: {args.workbook}")

    logger.info("=== Importing H1 2026 nominations (org=%s, cycle=%s, dry_run=%s) ===",
                args.org, args.cycle_id, args.dry_run)
    stats = import_nominations(args.workbook, args.org, args.cycle_id, args.dry_run)
    logger.info("Stats: %s", stats)
    if args.dry_run:
        logger.info("(DRY RUN — nothing was written)")


if __name__ == "__main__":
    main()
