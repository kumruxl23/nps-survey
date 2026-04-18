"""Slack Web API wrapper for sending individual DM reminders."""

import logging

import requests

from app.db.models import SlackResult

logger = logging.getLogger(__name__)

SLACK_LOOKUP_URL = "https://slack.com/api/users.lookupByEmail"
SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


class SlackUserNotFoundError(Exception):
    """Raised when a Slack user cannot be found by email."""


def lookup_user_by_email(email: str, bot_token: str) -> str:
    """Look up a Slack user ID by email address.

    Args:
        email: The email address to look up.
        bot_token: Slack Bot Token (per-org, stored in OrgConfig).

    Returns:
        The Slack user ID string.

    Raises:
        SlackUserNotFoundError: If the user is not found.
        RuntimeError: If the Slack API returns an unexpected error.
    """
    headers = {"Authorization": f"Bearer {bot_token}"}
    try:
        resp = requests.get(
            SLACK_LOOKUP_URL,
            params={"email": email},
            headers=headers,
            timeout=30,
        )
        data = resp.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Slack API request failed: {exc}") from exc

    if data.get("ok"):
        return data["user"]["id"]

    error = data.get("error", "unknown_error")
    if error == "users_not_found":
        raise SlackUserNotFoundError(f"Slack user not found for email: {email}")

    raise RuntimeError(f"Slack API error: {error}")


def send_dm(user_id: str, message: str, bot_token: str) -> SlackResult:
    """Send a direct message to a Slack user.

    Uses chat.postMessage with the user_id as the channel to open
    a 1:1 DM conversation, preserving stakeholder anonymity.

    Args:
        user_id: The Slack user ID to send the DM to.
        message: The message text to send.
        bot_token: Slack Bot Token (per-org, stored in OrgConfig).

    Returns:
        SlackResult with ok=True on success, or ok=False with error details.
    """
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
    }
    payload = {"channel": user_id, "text": message}

    try:
        resp = requests.post(
            SLACK_POST_MESSAGE_URL,
            json=payload,
            headers=headers,
            timeout=30,
        )
        data = resp.json()
    except requests.RequestException as exc:
        error_msg = f"Slack API request failed: {exc}"
        logger.error(error_msg)
        return SlackResult(ok=False, error=error_msg)

    if data.get("ok"):
        return SlackResult(ok=True)

    error_msg = data.get("error", "unknown_error")
    logger.error("Slack chat.postMessage failed: %s", error_msg)
    return SlackResult(ok=False, error=error_msg)
