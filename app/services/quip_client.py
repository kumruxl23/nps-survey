"""Quip API wrapper for reading stakeholder nomination spreadsheets."""

import logging
import os
import time
from html.parser import HTMLParser

import requests

logger = logging.getLogger(__name__)

QUIP_API_BASE = "https://platform.quip.com/1"
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1


class QuipAPIError(Exception):
    """Raised when the Quip API returns an error."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Quip API error {status_code}: {message}")


class MalformedSpreadsheetError(Exception):
    """Raised when the spreadsheet HTML cannot be parsed into name/email rows."""


class _TableParser(HTMLParser):
    """Minimal HTML parser that extracts rows from <tr> tags."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str):
        if tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            cell_text = "".join(self._current_cell).strip() if self._current_cell else ""
            if self._current_row is not None:
                self._current_row.append(cell_text)
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None

    def handle_data(self, data: str):
        if self._in_cell and self._current_cell is not None:
            self._current_cell.append(data)


def _get_token() -> str:
    """Return the Quip API token from environment."""
    return os.environ["QUIP_API_TOKEN"]


def get_spreadsheet(doc_id: str) -> dict:
    """Fetch a Quip thread/document by doc ID.

    Args:
        doc_id: The Quip document identifier.

    Returns:
        The raw JSON response from the Quip API.

    Raises:
        QuipAPIError: On 404 (invalid doc ID) or other API errors.
    """
    token = _get_token()
    url = f"{QUIP_API_BASE}/threads/{doc_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    backoff = INITIAL_BACKOFF_SECONDS
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as exc:
            logger.error("Quip request failed (attempt %d): %s", attempt + 1, exc)
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise QuipAPIError(0, f"Request failed: {exc}") from exc

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 429:
            logger.warning("Quip rate limited (attempt %d), retrying...", attempt + 1)
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise QuipAPIError(429, "Rate limited after max retries")

        if resp.status_code == 404:
            raise QuipAPIError(404, f"Document not found: {doc_id}")

        raise QuipAPIError(resp.status_code, resp.text)

    # Should not reach here, but just in case
    raise QuipAPIError(0, "Max retries exceeded")


def parse_nominations(
    spreadsheet: dict,
    name_column: int = 0,
    email_column: int = 1,
) -> list[dict]:
    """Parse the HTML content from a Quip spreadsheet response to extract nominations.

    Args:
        spreadsheet: The raw Quip API response dict (from get_spreadsheet).
        name_column: Column index for stakeholder name (default 0).
        email_column: Column index for stakeholder email (default 1).

    Returns:
        List of dicts with 'name' and 'email' keys.

    Raises:
        MalformedSpreadsheetError: If the HTML has no table rows or columns
            are missing.
    """
    html = spreadsheet.get("html", "")
    if not html:
        raise MalformedSpreadsheetError("Spreadsheet response contains no HTML content")

    parser = _TableParser()
    parser.feed(html)

    if not parser.rows:
        raise MalformedSpreadsheetError("No table rows found in spreadsheet HTML")

    min_columns = max(name_column, email_column) + 1
    nominations: list[dict] = []

    # Skip the first row (header)
    data_rows = parser.rows[1:] if len(parser.rows) > 1 else []

    for i, row in enumerate(data_rows):
        if len(row) < min_columns:
            logger.warning(
                "Row %d has %d columns, expected at least %d — skipping",
                i + 1,
                len(row),
                min_columns,
            )
            continue

        name = row[name_column].strip()
        email = row[email_column].strip()

        # Skip empty rows
        if not name and not email:
            continue

        if not email:
            logger.warning("Row %d missing email — skipping", i + 1)
            continue

        nominations.append({"name": name, "email": email})

    return nominations
