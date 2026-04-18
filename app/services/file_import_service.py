"""Service for importing nominations from uploaded Excel/CSV files.

Supports .xlsx, .xls, and .csv files. Handles multiple CSV formats:
- Standard format: Name, Email, Leader columns
- Amazon NPS format: PoC, PoC Alias, Stakeholder, Stakeholder Alias,
  "Should this stakeholder be included..." columns.
  Aliases get @amazon.com appended automatically.
"""

import csv
import io
import logging
import re

from app.db import nps_nomination_repo
from app.db.models import ImportResult, Nomination

logger = logging.getLogger(__name__)

# Known column name patterns (case-insensitive)
_EMAIL_PATTERNS = ["email", "email address", "e-mail", "stakeholder email", "stakeholder alias"]
_NAME_PATTERNS = ["name", "full name", "stakeholder name", "stakeholder"]
_LEADER_PATTERNS = ["leader", "poc", "manager"]
_INCLUDE_PATTERNS = ["should this stakeholder be included", "include", "included"]


def import_from_excel(
    org_id: str,
    cycle_id: str,
    file_bytes: bytes,
    filename: str,
) -> ImportResult:
    """Import nominations from an uploaded Excel or CSV file."""
    lower = filename.lower()
    if lower.endswith(".csv"):
        rows = _parse_csv(file_bytes)
    elif lower.endswith((".xlsx", ".xls")):
        rows = _parse_excel(file_bytes)
    else:
        raise ValueError(f"Unsupported file format: {filename}. Use .xlsx, .xls, or .csv")

    total_in_source = len(rows)
    imported_count = 0
    skipped_duplicates = 0
    skipped_excluded = 0

    for row in rows:
        name = row["name"].strip()
        email = row["email"].strip().lower()
        leader = row.get("leader", "").strip()
        include = row.get("include", "yes").strip().lower()

        if not email:
            continue

        # Skip stakeholders marked as "no" for inclusion
        if include in ("no", "n", "false", "0"):
            skipped_excluded += 1
            continue

        # Append @amazon.com if email is just an alias (no @ sign)
        if "@" not in email:
            email = email + "@amazon.com"

        existing = nps_nomination_repo.get_nomination(org_id, cycle_id, email)
        if existing is not None:
            skipped_duplicates += 1
            continue

        nomination = Nomination(
            org_id=org_id,
            cycle_id=cycle_id,
            email=email,
            name=name,
            leader=leader,
        )
        nps_nomination_repo.put_nomination(nomination)
        imported_count += 1

    return ImportResult(
        imported_count=imported_count,
        skipped_duplicates=skipped_duplicates,
        total_in_source=total_in_source,
    )


def _parse_csv(file_bytes: bytes) -> list[dict]:
    """Parse a CSV file into standardized name/email/leader/include dicts."""
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    col_map = _detect_columns(fieldnames)

    rows = []
    for row in reader:
        name = row.get(col_map["name"], "").strip()
        email = row.get(col_map["email"], "").strip()
        leader = row.get(col_map.get("leader", ""), "").strip() if col_map.get("leader") else ""
        include = row.get(col_map.get("include", ""), "yes").strip() if col_map.get("include") else "yes"
        if email:
            rows.append({"name": name, "email": email, "leader": leader, "include": include})
    return rows


def _parse_excel(file_bytes: bytes) -> list[dict]:
    """Parse an Excel file into standardized name/email/leader/include dicts."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active

    header_row = []
    for cell in next(ws.iter_rows(min_row=1, max_row=1)):
        header_row.append(str(cell.value or "").strip())

    col_map = _detect_columns(header_row)
    name_idx = header_row.index(col_map["name"])
    email_idx = header_row.index(col_map["email"])
    leader_idx = header_row.index(col_map["leader"]) if col_map.get("leader") and col_map["leader"] in header_row else None
    include_idx = header_row.index(col_map["include"]) if col_map.get("include") and col_map["include"] in header_row else None

    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = str(row[name_idx] or "").strip() if name_idx < len(row) else ""
        email = str(row[email_idx] or "").strip() if email_idx < len(row) else ""
        leader = str(row[leader_idx] or "").strip() if leader_idx is not None and leader_idx < len(row) else ""
        include = str(row[include_idx] or "yes").strip() if include_idx is not None and include_idx < len(row) else "yes"
        if email:
            rows.append({"name": name, "email": email, "leader": leader, "include": include})

    wb.close()
    return rows


def _detect_columns(headers: list[str]) -> dict:
    """Auto-detect column mapping from headers.

    Handles both standard format (Name, Email, Leader) and
    Amazon NPS format (PoC, Stakeholder, Stakeholder Alias, etc.)
    """
    lower_map = {}
    for h in headers:
        key = h.lower().strip()
        if key not in lower_map:  # first occurrence wins (handles duplicate "Stakeholder" columns)
            lower_map[key] = h

    result = {}

    # Detect email column: "Stakeholder Alias" or "Email" variants
    for pattern in _EMAIL_PATTERNS:
        for key, original in lower_map.items():
            if pattern in key:
                result["email"] = original
                break
        if "email" in result:
            break

    # Detect name column: "Stakeholder" (but not "Stakeholder Alias")
    for pattern in _NAME_PATTERNS:
        for key, original in lower_map.items():
            if key == pattern or (pattern in key and "alias" not in key and "included" not in key and "respond" not in key and "interact" not in key):
                result["name"] = original
                break
        if "name" in result:
            break

    # Detect leader column: "PoC" or "Leader"
    for pattern in _LEADER_PATTERNS:
        for key, original in lower_map.items():
            if key == pattern or (pattern in key and "alias" not in key):
                result["leader"] = original
                break
        if "leader" in result:
            break

    # Detect include/exclude column
    for pattern in _INCLUDE_PATTERNS:
        for key, original in lower_map.items():
            if pattern in key:
                result["include"] = original
                break
        if "include" in result:
            break

    if "email" not in result:
        raise ValueError(
            f"Could not find email/alias column. Headers found: {headers}. "
            f"Expected one of: {_EMAIL_PATTERNS}"
        )
    if "name" not in result:
        raise ValueError(
            f"Could not find name column. Headers found: {headers}. "
            f"Expected one of: {_NAME_PATTERNS}"
        )

    logger.info("Detected columns: %s", result)
    return result
