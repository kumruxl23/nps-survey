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


def add_leader(alias: str, name: str, org_id: str = "") -> dict:
    """Add a leader to the roster. Raises ValueError on bad input/duplicate.

    ``org_id`` scopes the leader to one org's nomination form. Empty means
    the leader appears for every org (legacy rows behave the same way).
    """
    alias = _normalize_alias(alias)
    name = (name or "").strip()
    org_id = (org_id or "").strip()
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
        "leader_org": org_id,
        "is_active": True,
    })
    return {"alias": alias, "name": name, "org_id": org_id}


def list_leaders(org_id: str = "") -> list[dict]:
    """Return active leaders as [{alias, name, org_id}], sorted by name.

    With ``org_id`` set, returns that org's leaders plus unscoped (legacy)
    leaders. Without it, returns everyone.
    """
    org_id = (org_id or "").strip()
    table = _get_table()
    response = table.scan()
    items = response.get("Items", [])
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    leaders = []
    for item in items:
        if not item["org_id"].startswith(LEADER_PREFIX) or not item.get("is_active", True):
            continue
        leader_org = item.get("leader_org", "") or ""
        if org_id and leader_org and leader_org != org_id:
            continue
        leaders.append({
            "alias": item["org_id"].removeprefix(LEADER_PREFIX),
            "name": item.get("org_name", ""),
            "org_id": leader_org,
        })
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


# ---------------------------------------------------------------------------
# Invite / reminder email to all leaders
# ---------------------------------------------------------------------------


def _demo_safe() -> bool:
    """True when NPS_DEMO_SAFE is set — blocks emails to REAL leaders."""
    return os.environ.get("NPS_DEMO_SAFE", "").lower() in ("1", "true", "yes")


def _build_invite_body(link: str, deadline: str, note: str) -> str:
    note_html = f"<p>{note}</p>" if note else ""
    return (
        "<p>Hello,</p>"
        "<p>Please nominate the stakeholders from your team who should "
        "receive the NPS survey. Use the form below — select your name as "
        "the leader (your directs can also nominate on your behalf by "
        "selecting your name).</p>"
        f'<p><a href="{link}">Open the nomination form</a></p>'
        f"<p><strong>Deadline: {deadline}</strong></p>"
        "<p>Notes: a stakeholder can only be nominated once per leader "
        "(first come, first served); the same stakeholder may be nominated "
        "by different leaders.</p>"
        f"{note_html}"
        "<p>Thank you!</p>"
    )


def send_nomination_invite(base_url: str, deadline: str, note: str = "", org_id: str = "") -> dict:
    """Email one org's leaders that org's nomination form share link.

    All recipients are BCC'd. Raises ValueError when org_id is missing,
    the roster is empty, the deadline is missing, or demo-safe mode is on.
    """
    from app.services import email_client, nps_share_link_service

    if _demo_safe():
        raise ValueError(
            "Demo-safe mode is ON (NPS_DEMO_SAFE) — invite emails to real "
            "leaders are disabled."
        )
    org_id = (org_id or "").strip()
    if not org_id:
        raise ValueError("org_id is required — invites are sent per org")
    deadline = (deadline or "").strip()
    if not deadline:
        raise ValueError("A nomination deadline is required")
    leaders = list_leaders(org_id)
    if not leaders:
        raise ValueError("The leader roster is empty — add leaders first")

    token = nps_share_link_service.get_or_create_token(org_id)
    link = f"{base_url.rstrip('/')}/nps/nominate/view?token={token}"

    subject = f"Action needed: nominate your NPS survey stakeholders by {deadline}"
    body = _build_invite_body(link, deadline, note.strip())
    recipients = sorted(f"{leader['alias']}@amazon.com" for leader in leaders)
    from_address = os.environ.get("NPS_FROM_ADDRESS", "")

    result = email_client.send_bcc_email(subject, body, recipients, from_address)
    if not result.ok:
        raise RuntimeError(result.error or "Invite email failed to send")

    logger.info("Nomination invite sent to %d leaders (deadline %s)", len(recipients), deadline)
    return {
        "sent_count": len(recipients),
        "leaders": [leader["name"] for leader in leaders],
        "deadline": deadline,
    }
