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


def add_leader(alias: str, name: str, org_id: str = "", notify_alias: str = "") -> dict:
    """Add a leader to the roster. Raises ValueError on bad input/duplicate.

    ``org_id`` scopes the leader to one org's nomination form. Empty means
    the leader appears for every org (legacy rows behave the same way).

    ``notify_alias`` is an OPTIONAL redirect target for leader reminders
    (email / Slack DM). When set, reminders that would go to this leader are
    sent to ``notify_alias`` instead — used for TESTING so a real leader
    (e.g. Navjyot) routes to a tester (e.g. kumruxl). Empty = send to the
    leader's own alias.
    """
    alias = _normalize_alias(alias)
    name = (name or "").strip()
    org_id = (org_id or "").strip()
    notify_alias = _normalize_alias(notify_alias)
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
        "notify_alias": notify_alias,
        "is_active": True,
    })
    return {"alias": alias, "name": name, "org_id": org_id, "notify_alias": notify_alias}


def set_notify_alias(alias: str, notify_alias: str) -> dict:
    """Set/clear the reminder redirect (test) alias for an existing leader."""
    alias = _normalize_alias(alias)
    notify_alias = _normalize_alias(notify_alias)
    table = _get_table()
    key = f"{LEADER_PREFIX}{alias}"
    if not table.get_item(Key={"org_id": key}).get("Item"):
        raise ValueError(f"Leader '{alias}' not found")
    table.update_item(
        Key={"org_id": key},
        UpdateExpression="SET notify_alias = :n",
        ExpressionAttributeValues={":n": notify_alias},
    )
    return {"alias": alias, "notify_alias": notify_alias}


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
            "notify_alias": item.get("notify_alias", "") or "",
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
    return {
        "alias": alias,
        "name": item.get("org_name", ""),
        "notify_alias": item.get("notify_alias", "") or "",
    }


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

    token = nps_share_link_service.get_or_create_common_token()
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


# ---------------------------------------------------------------------------
# Leader reminders (email + Slack DM) with a per-leader TEST redirect alias
# ---------------------------------------------------------------------------
#
# Reminds each roster leader (to nominate their stakeholders) over email and
# a Slack DM. For testing, a leader's ``notify_alias`` redirects both channels
# to a tester (e.g. Navjyot -> kumruxl, Abhas -> kuvinu) so we never contact a
# real leader while validating the flow. The message bodies below are
# PLACEHOLDERS — the final copy/template will be refined later.


def _recipient_alias(leader: dict) -> str:
    """Where a leader's reminder actually goes: the test redirect if set."""
    return (leader.get("notify_alias") or leader.get("alias") or "").strip().lower()


def _slack_sender_name() -> str:
    """Custom Slack DM sender display name (chat:write.customize).

    Set ``NPS_SLACK_SENDER_NAME`` to make DMs read as a person/team (e.g.
    "Vinay Jain") instead of the app's default. Empty = app default name.
    """
    return os.environ.get("NPS_SLACK_SENDER_NAME", "").strip()


def _reminder_subject(cycle_name: str = "") -> str:
    tail = f" ({cycle_name})" if cycle_name else ""
    return f"[NPS Survey] Reminder: nominate your stakeholders{tail}"


def _build_leader_reminder_email(leader_name: str, link: str, note: str) -> str:
    """PLACEHOLDER reminder email body (HTML). Copy to be refined later."""
    import html

    safe_name = html.escape(leader_name or "there")
    note_html = f"<p>{html.escape(note)}</p>" if note else ""
    return (
        f"<p>Hi {safe_name},</p>"
        "<p>[TEMPLATE PLACEHOLDER] This is a reminder to nominate the "
        "stakeholders from your team who should receive the NPS survey this "
        "cycle. Please use the form below.</p>"
        f'<p><a href="{link}">Open the nomination form</a></p>'
        f"{note_html}"
        "<p>Thank you!</p>"
    )


def _build_leader_reminder_slack(leader_name: str, link: str, note: str) -> str:
    """PLACEHOLDER reminder Slack DM text. Copy to be refined later."""
    msg = (
        f"Hi {leader_name or 'there'}, [TEMPLATE PLACEHOLDER] reminder to "
        f"nominate your NPS survey stakeholders this cycle.\nOpen the form: {link}"
    )
    return msg + (f"\n{note}" if note else "")


def _nomination_open_subject(cycle_name: str = "") -> str:
    tail = f" ({cycle_name})" if cycle_name else ""
    return f"[NPS Survey] Nominations are now open{tail}"


def _build_nomination_open_email(leader_name: str, link: str, deadline: str, note: str) -> str:
    """PLACEHOLDER "nominations opened" email body (HTML). Copy TBD later."""
    import html

    safe_name = html.escape(leader_name or "there")
    deadline_html = (
        f"<p><strong>Deadline: {html.escape(deadline)}</strong></p>" if deadline else ""
    )
    note_html = f"<p>{html.escape(note)}</p>" if note else ""
    return (
        f"<p>Hi {safe_name},</p>"
        "<p>[TEMPLATE PLACEHOLDER] Nominations for the NPS survey are now "
        "<strong>OPEN</strong>. Please nominate the stakeholders from your "
        "team who should receive the survey this cycle, using the form "
        "below. Your directs can also nominate on your behalf by selecting "
        "your name as the leader.</p>"
        f'<p><a href="{link}">Open the nomination form</a></p>'
        f"{deadline_html}"
        f"{note_html}"
        "<p>Thank you!</p>"
    )


def _build_nomination_open_slack(leader_name: str, link: str, deadline: str, note: str) -> str:
    """PLACEHOLDER "nominations opened" Slack DM text. Copy TBD later."""
    msg = (
        f"Hi {leader_name or 'there'}, [TEMPLATE PLACEHOLDER] nominations "
        f"for the NPS survey are now OPEN. Please nominate your team's "
        f"stakeholders this cycle.\nOpen the form: {link}"
    )
    if deadline:
        msg += f"\nDeadline: {deadline}"
    if note:
        msg += f"\n{note}"
    return msg


def send_nomination_open(
    base_url: str,
    org_id: str,
    deadline: str = "",
    note: str = "",
    channels: tuple = ("email", "slack"),
) -> dict:
    """Notify an org's roster leaders that nominations have OPENED.

    A kickoff announcement (distinct from the periodic reminder): email +
    Slack DM to each leader when a nomination cycle begins. Reuses the same
    delivery rules as reminders — each notification goes to the leader's
    ``notify_alias`` (TEST redirect) when set, Slack uses the org's bot
    token from OrgConfig (skipped + reported per row when missing), and
    demo-safe mode (``NPS_DEMO_SAFE``) blocks sends to leaders WITHOUT a
    test redirect so real leaders are never contacted during testing.

    Returns:
        {org_id, link, deadline, email_sent, slack_sent, notifications: [
            {leader, recipient_alias, email_ok, slack_ok, errors}
        ]}
    """
    from app.services import (
        email_client,
        nps_org_config_service,
        nps_share_link_service,
        slab_client,
        slack_client,
    )

    org_id = (org_id or "").strip()
    if not org_id:
        raise ValueError("org_id is required — notifications are sent per org")
    deadline = (deadline or "").strip()
    leaders = list_leaders(org_id)
    if not leaders:
        raise ValueError("The leader roster is empty — add leaders first")

    token = nps_share_link_service.get_or_create_common_token()
    link = f"{base_url.rstrip('/')}/nps/nominate/view?token={token}"
    from_address = os.environ.get("NPS_FROM_ADDRESS", "")

    org = next(
        (o for o in nps_org_config_service.list_all_orgs() if o.org_id == org_id),
        None,
    )
    bot_token = (getattr(org, "slack_bot_token", "") if org else "") or ""

    want_email = "email" in channels
    want_slack = "slack" in channels
    demo = _demo_safe()
    subject = _nomination_open_subject()
    notifications = []

    for leader in leaders:
        recipient = _recipient_alias(leader)
        overridden = bool(leader.get("notify_alias"))
        row = {
            "leader": leader["name"],
            "recipient_alias": recipient,
            "email_ok": False,
            "slack_ok": False,
            "errors": [],
        }

        if demo and not overridden:
            row["errors"].append("skipped: demo-safe on and no test alias set")
            notifications.append(row)
            continue
        if not recipient:
            row["errors"].append("no recipient alias")
            notifications.append(row)
            continue

        recipient_email = f"{recipient}@amazon.com"

        if want_email:
            result = email_client.send_bcc_email(
                subject,
                _build_nomination_open_email(leader["name"], link, deadline, note),
                [recipient_email],
                from_address,
            )
            row["email_ok"] = result.ok
            if not result.ok:
                row["errors"].append(f"email: {result.error}")

        if want_slack:
            if not bot_token:
                row["errors"].append("slack: no bot token configured for this org")
            else:
                try:
                    # Resolve Slack ID via SLAB (no users:read scope needed).
                    user_id = slab_client.lookup_slack_id_by_alias(recipient)
                    dm = slack_client.send_dm(
                        user_id,
                        _build_nomination_open_slack(leader["name"], link, deadline, note),
                        bot_token,
                        username=_slack_sender_name(),
                    )
                    row["slack_ok"] = dm.ok
                    if not dm.ok:
                        row["errors"].append(f"slack: {dm.error}")
                except slab_client.SlackUserNotFoundError as exc:
                    row["errors"].append(f"slack: {exc}")
                except Exception as exc:  # SLAB config/transport/other — never break the batch
                    row["errors"].append(f"slack: {exc}")

        notifications.append(row)

    logger.info(
        "Nomination-open notification: org=%s email_sent=%d slack_sent=%d",
        org_id,
        sum(1 for r in notifications if r["email_ok"]),
        sum(1 for r in notifications if r["slack_ok"]),
    )
    return {
        "org_id": org_id,
        "link": link,
        "deadline": deadline,
        "email_sent": sum(1 for r in notifications if r["email_ok"]),
        "slack_sent": sum(1 for r in notifications if r["slack_ok"]),
        "notifications": notifications,
    }


def check_slack_resolution(alias: str) -> dict:
    """Diagnose the SLAB alias→Slack-ID half of the DM path (read-only).

    Resolves ``alias`` to a Slack user ID via SLAB, WITHOUT needing a Slack
    bot token — so the SLAB integration can be verified independently of the
    (still-pending) ``chat:write`` app token. Intended for a quick admin
    "does Slack resolution work on this host?" check after deploy, since SLAB
    only accepts the allowlisted EC2 role.

    Returns ``{alias, ok, slack_id, error}`` — never raises; a failure is
    reported in ``error`` (not-configured, not-found, or transport).
    """
    alias = _normalize_alias(alias)
    row = {"alias": alias, "ok": False, "slack_id": "", "error": ""}
    if not alias:
        row["error"] = "alias is required"
        return row

    from app.services import slab_client

    try:
        row["slack_id"] = slab_client.lookup_slack_id_by_alias(alias)
        row["ok"] = True
    except slab_client.SlackUserNotFoundError as exc:
        row["error"] = f"not found: {exc}"
    except Exception as exc:  # config/transport — surface, don't raise
        row["error"] = str(exc)
    return row


def send_leader_reminders(
    base_url: str,
    org_id: str,
    note: str = "",
    channels: tuple = ("email", "slack"),
) -> dict:
    """Send an email + Slack DM reminder to each roster leader in an org.

    Each reminder goes to the leader's ``notify_alias`` when set (the TEST
    redirect), else the leader's own alias. Slack uses the org's bot token
    (from OrgConfig); if it's missing, Slack is skipped and reported per row.

    Demo-safe (``NPS_DEMO_SAFE``) blocks sends to leaders WITHOUT a test
    redirect, so real leaders are never contacted during testing.

    Returns:
        {org_id, link, email_sent, slack_sent, reminders: [
            {leader, recipient_alias, email_ok, slack_ok, errors}
        ]}
    """
    from app.services import (
        email_client,
        nps_org_config_service,
        nps_share_link_service,
        slab_client,
        slack_client,
    )

    org_id = (org_id or "").strip()
    if not org_id:
        raise ValueError("org_id is required — reminders are sent per org")
    leaders = list_leaders(org_id)
    if not leaders:
        raise ValueError("The leader roster is empty — add leaders first")

    token = nps_share_link_service.get_or_create_common_token()
    link = f"{base_url.rstrip('/')}/nps/nominate/view?token={token}"
    from_address = os.environ.get("NPS_FROM_ADDRESS", "")

    org = next(
        (o for o in nps_org_config_service.list_all_orgs() if o.org_id == org_id),
        None,
    )
    bot_token = (getattr(org, "slack_bot_token", "") if org else "") or ""

    want_email = "email" in channels
    want_slack = "slack" in channels
    demo = _demo_safe()
    reminders = []

    for leader in leaders:
        recipient = _recipient_alias(leader)
        overridden = bool(leader.get("notify_alias"))
        row = {
            "leader": leader["name"],
            "recipient_alias": recipient,
            "email_ok": False,
            "slack_ok": False,
            "errors": [],
        }

        if demo and not overridden:
            row["errors"].append("skipped: demo-safe on and no test alias set")
            reminders.append(row)
            continue
        if not recipient:
            row["errors"].append("no recipient alias")
            reminders.append(row)
            continue

        recipient_email = f"{recipient}@amazon.com"

        if want_email:
            result = email_client.send_bcc_email(
                _reminder_subject(),
                _build_leader_reminder_email(leader["name"], link, note),
                [recipient_email],
                from_address,
            )
            row["email_ok"] = result.ok
            if not result.ok:
                row["errors"].append(f"email: {result.error}")

        if want_slack:
            if not bot_token:
                row["errors"].append("slack: no bot token configured for this org")
            else:
                try:
                    # Resolve Slack ID via SLAB (no users:read scope needed).
                    user_id = slab_client.lookup_slack_id_by_alias(recipient)
                    dm = slack_client.send_dm(
                        user_id,
                        _build_leader_reminder_slack(leader["name"], link, note),
                        bot_token,
                        username=_slack_sender_name(),
                    )
                    row["slack_ok"] = dm.ok
                    if not dm.ok:
                        row["errors"].append(f"slack: {dm.error}")
                except slab_client.SlackUserNotFoundError as exc:
                    row["errors"].append(f"slack: {exc}")
                except Exception as exc:  # SLAB config/transport/other — never break the batch
                    row["errors"].append(f"slack: {exc}")

        reminders.append(row)

    return {
        "org_id": org_id,
        "link": link,
        "email_sent": sum(1 for r in reminders if r["email_ok"]),
        "slack_sent": sum(1 for r in reminders if r["slack_ok"]),
        "reminders": reminders,
    }


def _build_response_summary_email(leader_name: str, count: int, link: str) -> str:
    import html
    safe = html.escape(leader_name or "there")
    return (
        f"<p>Hi {safe},</p>"
        f"<p>Quick NPS survey update: <strong>{count}</strong> response"
        f"{'' if count == 1 else 's'} received so far this cycle.</p>"
        f'<p><a href="{link}">Open the dashboard</a> for the live breakdown.</p>'
        "<p>Thank you!</p>"
    )


def _build_response_summary_slack(leader_name: str, count: int, link: str) -> str:
    return (
        f"Hi {leader_name or 'there'}, NPS survey update: *{count}* response"
        f"{'' if count == 1 else 's'} received so far this cycle.\n{link}"
    )


def send_response_summary(
    base_url: str,
    org_id: str,
    cycle_id: str,
    channels: tuple = ("email", "slack"),
) -> dict:
    """Email + Slack DM each roster leader the count of responses so far.

    The count comes from the existing live response-count source
    (``nps_asana_dashboard_service.get_dashboard_summary``). Reuses the same
    per-leader delivery rules as ``send_leader_reminders`` (notify_alias TEST
    redirect, org Slack bot token, demo-safe gate, per-row error capture).

    Returns {org_id, cycle_id, response_count, email_sent, slack_sent, notifications}.
    """
    from app.services import (
        email_client,
        nps_asana_dashboard_service,
        nps_org_config_service,
        slab_client,
        slack_client,
    )

    org_id = (org_id or "").strip()
    cycle_id = (cycle_id or "").strip()
    if not org_id or not cycle_id:
        raise ValueError("org_id and cycle_id are required")
    leaders = list_leaders(org_id)
    if not leaders:
        raise ValueError("The leader roster is empty — add leaders first")

    try:
        summary = nps_asana_dashboard_service.get_dashboard_summary(org_id, cycle_id)
        response_count = int(summary.get("total_responses", 0))
    except Exception:
        response_count = 0

    link = f"{base_url.rstrip('/')}/nps/dashboard"
    from_address = os.environ.get("NPS_FROM_ADDRESS", "")

    org = next(
        (o for o in nps_org_config_service.list_all_orgs() if o.org_id == org_id),
        None,
    )
    bot_token = (getattr(org, "slack_bot_token", "") if org else "") or ""

    want_email = "email" in channels
    want_slack = "slack" in channels
    demo = _demo_safe()
    subject = f"[NPS Survey] {response_count} responses received so far"
    notifications = []

    for leader in leaders:
        recipient = _recipient_alias(leader)
        overridden = bool(leader.get("notify_alias"))
        row = {"leader": leader["name"], "recipient_alias": recipient,
               "email_ok": False, "slack_ok": False, "errors": []}

        if demo and not overridden:
            row["errors"].append("skipped: demo-safe on and no test alias set")
            notifications.append(row)
            continue
        if not recipient:
            row["errors"].append("no recipient alias")
            notifications.append(row)
            continue

        if want_email:
            result = email_client.send_bcc_email(
                subject,
                _build_response_summary_email(leader["name"], response_count, link),
                [f"{recipient}@amazon.com"],
                from_address,
            )
            row["email_ok"] = result.ok
            if not result.ok:
                row["errors"].append(f"email: {result.error}")

        if want_slack:
            if not bot_token:
                row["errors"].append("slack: no bot token configured for this org")
            else:
                try:
                    user_id = slab_client.lookup_slack_id_by_alias(recipient)
                    dm = slack_client.send_dm(
                        user_id,
                        _build_response_summary_slack(leader["name"], response_count, link),
                        bot_token,
                        username=_slack_sender_name(),
                    )
                    row["slack_ok"] = dm.ok
                    if not dm.ok:
                        row["errors"].append(f"slack: {dm.error}")
                except slab_client.SlackUserNotFoundError as exc:
                    row["errors"].append(f"slack: {exc}")
                except Exception as exc:
                    row["errors"].append(f"slack: {exc}")

        notifications.append(row)

    return {
        "org_id": org_id,
        "cycle_id": cycle_id,
        "response_count": response_count,
        "email_sent": sum(1 for r in notifications if r["email_ok"]),
        "slack_sent": sum(1 for r in notifications if r["slack_ok"]),
        "notifications": notifications,
    }
