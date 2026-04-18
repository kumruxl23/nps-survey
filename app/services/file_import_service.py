"""Service for importing nominations from uploaded Excel/CSV files.

Supports .xlsx, .xls, and .csv files. Extracts stakeholder name, email,
and optionally leader columns. Skips duplicates within the same org/cycle.
"""

import csv
import io
import logging

from app.db import nps_nomination_repo
from app.db.models import ImportResult, Nomination

logger = logging.getLogger(__name__)


def import_from_excel(
    org_id: str,
    cycle_id: str,
    file_bytes: bytes,
    filename: str,
    name_column: str = "Name",
    email_column: str = "Email",
    leader_column: str = "Leader",
) -> ImportResult:
    """Import nominations from an uploaded Excel or CSV file.

    Args:
        org_id: Organization identifier.
        cycle_id: Survey cycle identifier.
        file_bytes: Raw file content bytes.
        filename: Original filename (used to detect format).
        name_column: Column header for stakeholder name.
        email_column: Column header for stakeholder email.
        leader_column: Column header for leader (optional).

    Returns:
        ImportResult with imported, skipped, and total counts.

    Raises:
        ValueError: If file format is unsupported or required columns missing.
    """
    lower = filename.lower()
    if lower.endswith(".csv"):
        rows = _parse_csv(file_bytes, name_column, email_column, leader_column)
    elif lower.endswith((".xlsx", ".xls")):
        rows = _parse_excel(file_bytes, name_column, email_column, leader_column)
    else:
        raise ValueError(f"Unsupported file format: {filename}. Use .xlsx, .xls, or .csv")

    total_in_source = len(rows)
    imported_count = 0
    skipped_duplicates = 0

    for row in rows:
        name = row["name"].strip()
        email = row["email"].strip().lower()
        leader = row.get("leader", "").strip()

        if not email:
            continue

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


def _parse_csv(
    file_bytes: bytes, name_col: str, email_col: str, leader_col: str
) -> list[dict]:
    """Parse a CSV file into name/email/leader dicts."""
    text = file_bytes.decode("utf-8-sig")  # handle BOM
    reader = csv.DictReader(io.StringIO(text))

    # Find matching columns (case-insensitive)
    fieldnames = reader.fieldnames or []
    col_map = _find_columns(fieldnames, name_col, email_col, leader_col)

    rows = []
    for row in reader:
        name = row.get(col_map["name"], "").strip()
        email = row.get(col_map["email"], "").strip()
        leader = row.get(col_map.get("leader", ""), "").strip() if col_map.get("leader") else ""
        if email:
            rows.append({"name": name, "email": email, "leader": leader})
    return rows


def _parse_excel(
    file_bytes: bytes, name_col: str, email_col: str, leader_col: str
) -> list[dict]:
    """Parse an Excel file into name/email/leader dicts."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active

    # Read header row
    header_row = []
    for cell in next(ws.iter_rows(min_row=1, max_row=1)):
        header_row.append(str(cell.value or "").strip())

    col_map = _find_columns(header_row, name_col, email_col, leader_col)
    name_idx = header_row.index(col_map["name"])
    email_idx = header_row.index(col_map["email"])
    leader_idx = header_row.index(col_map["leader"]) if col_map.get("leader") and col_map["leader"] in header_row else None

    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = str(row[name_idx] or "").strip() if name_idx < len(row) else ""
        email = str(row[email_idx] or "").strip() if email_idx < len(row) else ""
        leader = str(row[leader_idx] or "").strip() if leader_idx is not None and leader_idx < len(row) else ""
        if email:
            rows.append({"name": name, "email": email, "leader": leader})

    wb.close()
    return rows


def _find_columns(
    headers: list[str], name_col: str, email_col: str, leader_col: str
) -> dict:
    """Find column names case-insensitively. Raises ValueError if required columns missing."""
    lower_headers = {h.lower().strip(): h for h in headers}

    name_key = lower_headers.get(name_col.lower())
    email_key = lower_headers.get(email_col.lower())
    leader_key = lower_headers.get(leader_col.lower())

    if not email_key:
        # Try common alternatives
        for alt in ["email", "email address", "e-mail", "stakeholder email"]:
            if alt in lower_headers:
                email_key = lower_headers[alt]
                break

    if not name_key:
        for alt in ["name", "full name", "stakeholder name", "stakeholder"]:
            if alt in lower_headers:
                name_key = lower_headers[alt]
                break

    if not email_key:
        raise ValueError(
            f"Could not find email column. Headers found: {headers}. "
            f"Expected a column named '{email_col}' (case-insensitive)."
        )
    if not name_key:
        raise ValueError(
            f"Could not find name column. Headers found: {headers}. "
            f"Expected a column named '{name_col}' (case-insensitive)."
        )

    result = {"name": name_key, "email": email_key}
    if leader_key:
        result["leader"] = leader_key
    return result
