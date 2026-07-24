"""Per-org shareable-link tokens for the self-serve nomination form.

Leaders and their directs don't have app accounts, so the nomination form
can be opened with a capability URL instead: /nps/nominate/view?token=...
Each org has its OWN token, so a link only ever exposes that org's
leaders, cycle, and nominations. The token grants access to the
nomination form routes ONLY — the rest of the app still requires a
login session.

Tokens are stored as ``__share__nominate_form#<org_id>`` system rows in
the NpsOrgConfig table (same pattern as ``__user__``/``__leader__`` rows,
which org listings already exclude). Admins can rotate a link per org if
it leaks.
"""

import os
import secrets

import boto3

SHARE_PREFIX = "__share__nominate_form#"
# Pre-org-scoping key — treated as invalid; rotate created per-org rows.
LEGACY_SHARE_KEY = "__share__nominate_form"


def _get_table():
    table_name = os.environ.get("NPS_ORG_CONFIG_TABLE", "NpsOrgConfig")
    return boto3.resource("dynamodb").Table(table_name)


def get_or_create_token(org_id: str) -> str:
    """Return the org's current share token, creating one on first use."""
    if not org_id:
        raise ValueError("org_id is required for a share token")
    table = _get_table()
    item = table.get_item(Key={"org_id": f"{SHARE_PREFIX}{org_id}"}).get("Item")
    if item and item.get("token"):
        return item["token"]
    return rotate_token(org_id)


def rotate_token(org_id: str) -> str:
    """Issue a fresh share token for one org, invalidating its old link."""
    if not org_id:
        raise ValueError("org_id is required for a share token")
    token = secrets.token_urlsafe(24)
    _get_table().put_item(Item={
        "org_id": f"{SHARE_PREFIX}{org_id}",
        "org_name": f"Nomination form share token ({org_id})",
        "token": token,
        "is_active": True,
    })
    return token


def resolve_token(token: str) -> str | None:
    """Return the org_id a presented token belongs to, or None.

    Constant-time comparison against every stored org token (org count is
    single digits, so a scan is fine).
    """
    if not token:
        return None
    table = _get_table()
    response = table.scan()
    items = response.get("Items", [])
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    match = None
    for item in items:
        key = item.get("org_id", "")
        if not key.startswith(SHARE_PREFIX):
            continue
        stored = item.get("token", "")
        # Compare every row (no early exit) to keep timing uniform.
        if stored and secrets.compare_digest(token, stored):
            match = key.removeprefix(SHARE_PREFIX)
    return match
