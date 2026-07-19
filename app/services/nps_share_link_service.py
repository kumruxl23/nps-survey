"""Shareable-link token for the self-serve nomination form.

Leaders and their directs don't have app accounts, so the nomination form
can be opened with a capability URL instead: /nps/nominate/view?token=...
The token grants access to the nomination form routes ONLY — the rest of
the app still requires a login session.

The token is stored as a ``__share__`` system row in the NpsOrgConfig
table (same pattern as ``__user__``/``__leader__`` rows, which org
listings already exclude). Admins can rotate it if the link leaks.
"""

import os
import secrets

import boto3

SHARE_KEY = "__share__nominate_form"


def _get_table():
    table_name = os.environ.get("NPS_ORG_CONFIG_TABLE", "NpsOrgConfig")
    return boto3.resource("dynamodb").Table(table_name)


def get_or_create_token() -> str:
    """Return the current share token, creating one on first use."""
    table = _get_table()
    item = table.get_item(Key={"org_id": SHARE_KEY}).get("Item")
    if item and item.get("token"):
        return item["token"]
    return rotate_token()


def rotate_token() -> str:
    """Generate and store a fresh share token, invalidating the old link."""
    token = secrets.token_urlsafe(24)
    _get_table().put_item(Item={
        "org_id": SHARE_KEY,
        "org_name": "Nomination form share token",
        "token": token,
        "is_active": True,
    })
    return token


def verify_token(token: str) -> bool:
    """Constant-time check of a presented token against the stored one."""
    if not token:
        return False
    item = _get_table().get_item(Key={"org_id": SHARE_KEY}).get("Item")
    stored = (item or {}).get("token", "")
    if not stored:
        return False
    return secrets.compare_digest(token, stored)
