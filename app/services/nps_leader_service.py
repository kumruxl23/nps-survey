"""Leader roster for the self-serve nomination form.

Leaders (e.g. the directs of the org sponsor) are the people stakeholder
nominations are grouped under on the /nps/nominate form. The roster is
admin-managed and stored in the NpsOrgConfig DynamoDB table using a
``__leader__<alias>`` key prefix — the same "system record" pattern the
auth users use (``__user__``), so no new table or IAM change is needed.
Org listing code already excludes all ``__``-prefixed rows.
"""

import logging
import os

import boto3

logger = logging.getLogger(__name__)

LEADER_PREFIX = "__leader__"


def _get_table():
    table_name = os.environ.get("NPS_ORG_CONFIG_TABLE", "NpsOrgConfig")
    return boto3.resource("dynamodb").Table(table_name)


def _normalize_alias(alias: str) -> str:
    """Lowercase, trimmed alias without an email domain."""
    alias = (alias or "").strip().lower()
    return alias.split("@", 1)[0]


def add_leader(alias: str, name: str) -> dict:
    """Add a leader to the roster. Raises ValueError on bad input/duplicate."""
    alias = _normalize_alias(alias)
    name = (name or "").strip()
    if not alias or not name:
        raise ValueError("Leader alias and name are required")

    table = _get_table()
    key = f"{LEADER_PREFIX}{alias}"
    existing = table.get_item(Key={"org_id": key}).get("Item")
    if existing and existing.get("is_active", True):
        raise ValueError(f"Leader '{alias}' already exists")

    table.put_item(Item={
        "org_id": key,
        "org_name": name,
        "is_active": True,
    })
    return {"alias": alias, "name": name}


def list_leaders() -> list[dict]:
    """Return all active leaders as [{alias, name}], sorted by name."""
    table = _get_table()
    response = table.scan()
    items = response.get("Items", [])
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    leaders = [
        {
            "alias": item["org_id"].removeprefix(LEADER_PREFIX),
            "name": item.get("org_name", ""),
        }
        for item in items
        if item["org_id"].startswith(LEADER_PREFIX) and item.get("is_active", True)
    ]
    return sorted(leaders, key=lambda leader: leader["name"].lower())


def remove_leader(alias: str) -> None:
    """Deactivate a leader (kept as a record; nominations retain the name)."""
    alias = _normalize_alias(alias)
    table = _get_table()
    table.update_item(
        Key={"org_id": f"{LEADER_PREFIX}{alias}"},
        UpdateExpression="SET is_active = :a",
        ExpressionAttributeValues={":a": False},
    )


def get_leader(alias: str) -> dict | None:
    """Return {alias, name} for an active leader, or None."""
    alias = _normalize_alias(alias)
    table = _get_table()
    item = table.get_item(Key={"org_id": f"{LEADER_PREFIX}{alias}"}).get("Item")
    if not item or not item.get("is_active", True):
        return None
    return {"alias": alias, "name": item.get("org_name", "")}
