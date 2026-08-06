"""Program-level dashboard settings (admin-editable UI content).

Persists the five bits of UI content admins can edit in the browser —
chart/section headings, the Program Status cycle cards, the Resources &
Support list, the Nomination Guidelines, and the nomination deadline —
which previously lived in JS memory and reset on refresh.

Everything is stored as ONE JSON blob in a ``__settings__dashboard``
system row of the NpsOrgConfig table (the same "system record" pattern
the ``__user__``/``__leader__``/``__share__`` rows use; org listings
already exclude ``__``-prefixed rows, so no new table or IAM change is
needed). Settings are GLOBAL — program-level, not per-org — and writes
are whole-record, last-write-wins.
"""

import json
import os
from datetime import datetime, timezone

import boto3

SETTINGS_KEY = "__settings__dashboard"
MAX_SETTINGS_BYTES = 50_000  # sanity cap; the blob is a few KB in practice


def _get_table():
    table_name = os.environ.get("NPS_ORG_CONFIG_TABLE", "NpsOrgConfig")
    return boto3.resource("dynamodb").Table(table_name)


def get_default_settings() -> dict:
    """Empty-shaped defaults.

    The templates ship their own hardcoded defaults, so "no stored value"
    is expressed as empty/None here — the frontend only applies stored
    values that are actually present.
    """
    return {
        "chart_headings": {},
        "program_status": None,
        "program_resources": None,
        "nomination_guidelines": None,
        "nomination_deadline": "",
    }


def get_dashboard_settings() -> dict:
    """The stored settings blob, or defaults when none exists yet.

    Always includes ``updated_at``/``updated_by`` metadata (empty strings
    when the record has never been saved).
    """
    item = _get_table().get_item(Key={"org_id": SETTINGS_KEY}).get("Item")
    merged = get_default_settings()
    if item and item.get("data"):
        try:
            stored = json.loads(item["data"])
            if isinstance(stored, dict):
                merged.update(stored)
        except (TypeError, ValueError):
            pass  # corrupt blob: fall back to defaults rather than break the UI
    merged["updated_at"] = (item or {}).get("updated_at", "")
    merged["updated_by"] = (item or {}).get("updated_by", "")
    return merged


def save_dashboard_settings(settings: dict, updated_by: str) -> dict:
    """Overwrite the settings record (whole blob, last write wins).

    Raises ValueError for non-dict payloads or blobs over 50KB.
    """
    if not isinstance(settings, dict):
        raise ValueError("settings must be a JSON object")
    # Metadata is server-owned — strip anything the client echoed back.
    clean = {k: v for k, v in settings.items() if k not in ("updated_at", "updated_by")}
    raw = json.dumps(clean)
    if len(raw.encode("utf-8")) > MAX_SETTINGS_BYTES:
        raise ValueError("settings too large (max 50KB)")

    updated_at = datetime.now(timezone.utc).isoformat()
    _get_table().put_item(Item={
        "org_id": SETTINGS_KEY,
        "org_name": "Dashboard settings (system record)",
        "data": raw,
        "updated_at": updated_at,
        "updated_by": (updated_by or "").strip().lower(),
        "is_active": True,
    })
    return {"status": "ok", "updated_at": updated_at}
