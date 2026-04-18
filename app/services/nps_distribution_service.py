"""Service layer for NPS survey distribution and multi-channel reminders.

Orchestrates email distribution via email_client, Slack DM reminders
via slack_client, and logs events/failures to the appropriate repos.
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from app.db import (
    nps_cycle_repo,
    nps_delivery_failure_repo,
    nps_nomination_repo,
    nps_reminder_log_repo,
)
from app.db.models import (
    DeliveryFailure,
    DistributionResult,
    ReminderLog,
    ReminderResult,
)
from app.services import email_client, nps_nomination_service, nps_org_config_service
from app.services import slack_client
from app.services.slack_client import SlackUserNotFoundError

logger = logging.getLogger(__name__)

_DISTRIBUTION_SUBJECT = "NPS Survey - Your Feedback Matters"
_REMINDER_SUBJECT = "Reminder: NPS Survey - We'd Love Your Feedback"


def _build_survey_body(form_url: str) -> str:
    """Build the HTML email body containing the ASANA form link."""
    return (
        "<p>Hello,</p>"
        "<p>You have been selected to participate in our NPS survey. "
        "Your feedback is valuable and helps us improve.</p>"
        f'<p>Please complete the survey here: <a href="{form_url}">{form_url}</a></p>'
        "<p>Thank you!</p>"
    )


def _build_reminder_body(form_url: str) -> str:
    """Build the HTML reminder email body."""
    return (
        "<p>Hello,</p>"
        "<p>This is a friendly reminder that we haven't received your NPS survey response yet. "
        "Your feedback is important to us.</p>"
        f'<p>Please complete the survey here: <a href="{form_url}">{form_url}</a></p>'
        "<p>Thank you!</p>"
    )


def _build_slack_reminder_message(form_url: str) -> str:
    """Build the Slack DM reminder message."""
    return (
        "Hi! This is a friendly reminder that we haven't received your "
        "NPS survey response yet. Your feedback is important to us.\n\n"
        f"Please complete the survey here: {form_url}\n\nThank you!"
    )


def _log_failure(
    org_id: str,
    cycle_id: str,
    email: str,
    error_reason: str,
    event_type: str,
    channel: str,
) -> None:
    """Log a delivery failure to the NpsDeliveryFailures table."""
    failure = DeliveryFailure(
        org_id=org_id,
        cycle_id=cycle_id,
        failure_id=str(uuid.uuid4()),
        email=email,
        error_reason=error_reason,
        event_type=event_type,
        channel=channel,
    )
    nps_delivery_failure_repo.put_failure(failure)


def distribute_survey(org_id: str, cycle_id: str) -> DistributionResult:
    """Distribute the NPS survey to all nominated stakeholders.

    Sends a BCC email with the ASANA form link to all nominations.
    Idempotent: returns early if the cycle has already been distributed.

    Args:
        org_id: Organization identifier.
        cycle_id: Survey cycle identifier.

    Returns:
        DistributionResult with sent/failed counts and idempotency flag.

    Raises:
        ValueError: If cycle or org config is not found.
    """
    cycle = nps_cycle_repo.get_cycle(org_id, cycle_id)
    if cycle is None:
        raise ValueError(f"Cycle '{cycle_id}' not found for org '{org_id}'")

    # Idempotent: already distributed
    if cycle.distributed_at:
        return DistributionResult(sent_count=0, failed_count=0, already_distributed=True)

    org = nps_org_config_service.get_org(org_id)
    if org is None:
        raise ValueError(f"Org '{org_id}' not found")

    nominations = nps_nomination_repo.list_nominations(org_id, cycle_id)
    if not nominations:
        # Nothing to send — still mark as distributed
        now = datetime.now(timezone.utc).isoformat()
        nps_cycle_repo.update_cycle(org_id, cycle_id, distributed_at=now)
        return DistributionResult(sent_count=0, failed_count=0)

    bcc_recipients = [n.email for n in nominations]
    body = _build_survey_body(org.asana_form_url)

    from_address = os.environ.get("NPS_FROM_ADDRESS", "nps-survey@example.com")
    result = email_client.send_bcc_email(
        subject=_DISTRIBUTION_SUBJECT,
        body=body,
        bcc_recipients=bcc_recipients,
        from_address=from_address,
    )

    now = datetime.now(timezone.utc).isoformat()

    if result.ok:
        nps_cycle_repo.update_cycle(org_id, cycle_id, distributed_at=now)
        return DistributionResult(sent_count=len(bcc_recipients), failed_count=0)
    else:
        # Email send failed for the entire batch
        for email_addr in bcc_recipients:
            _log_failure(
                org_id=org_id,
                cycle_id=cycle_id,
                email=email_addr,
                error_reason=result.error or "Unknown email error",
                event_type="distribution",
                channel="email",
            )
        # Still mark as distributed so we don't retry indefinitely
        nps_cycle_repo.update_cycle(org_id, cycle_id, distributed_at=now)
        return DistributionResult(sent_count=0, failed_count=len(bcc_recipients))


def send_reminder(
    org_id: str, cycle_id: str, trigger_type: str = "manual"
) -> ReminderResult:
    """Send reminders to non-respondent stakeholders via configured channels.

    Reads reminder_channels from OrgConfig to determine which channels
    to use (email, Slack, or both). Logs reminder events and failures.

    Args:
        org_id: Organization identifier.
        cycle_id: Survey cycle identifier.
        trigger_type: 'automated' or 'manual'.

    Returns:
        ReminderResult with per-channel counts and failures.

    Raises:
        ValueError: If org config or cycle is not found.
    """
    org = nps_org_config_service.get_org(org_id)
    if org is None:
        raise ValueError(f"Org '{org_id}' not found")

    cycle = nps_cycle_repo.get_cycle(org_id, cycle_id)
    if cycle is None:
        raise ValueError(f"Cycle '{cycle_id}' not found for org '{org_id}'")

    non_respondents = nps_nomination_service.get_reminder_list(org_id, cycle_id)
    if not non_respondents:
        return ReminderResult()

    channels = org.reminder_channels or ["email"]
    result = ReminderResult(channels_used=list(channels))
    failed_count = 0

    from_address = os.environ.get("NPS_FROM_ADDRESS", "nps-survey@example.com")
    form_url = org.asana_form_url

    # --- Email channel ---
    if "email" in channels:
        bcc_recipients = [n.email for n in non_respondents]
        body = _build_reminder_body(form_url)
        email_result = email_client.send_bcc_email(
            subject=_REMINDER_SUBJECT,
            body=body,
            bcc_recipients=bcc_recipients,
            from_address=from_address,
        )
        if email_result.ok:
            result.email_sent_count = len(bcc_recipients)
        else:
            for email_addr in bcc_recipients:
                _log_failure(
                    org_id=org_id,
                    cycle_id=cycle_id,
                    email=email_addr,
                    error_reason=email_result.error or "Unknown email error",
                    event_type="reminder",
                    channel="email",
                )
            failed_count += len(bcc_recipients)

    # --- Slack channel ---
    if "slack" in channels:
        slack_message = _build_slack_reminder_message(form_url)
        bot_token = org.slack_bot_token

        if not bot_token:
            logger.warning(
                "Slack channel enabled for org '%s' but no slack_bot_token configured. "
                "Skipping Slack reminders.",
                org_id,
            )
        else:
            for nomination in non_respondents:
                # Resolve Slack user ID (use cached value if available)
                slack_user_id = nomination.slack_user_id
                if not slack_user_id:
                    try:
                        slack_user_id = slack_client.lookup_user_by_email(
                            nomination.email, bot_token
                        )
                        # Cache the resolved ID on the nomination
                        nps_nomination_repo.update_nomination(
                            org_id, cycle_id, nomination.email,
                            slack_user_id=slack_user_id,
                        )
                    except SlackUserNotFoundError:
                        _log_failure(
                            org_id=org_id,
                            cycle_id=cycle_id,
                            email=nomination.email,
                            error_reason=f"Slack user not found for email: {nomination.email}",
                            event_type="reminder",
                            channel="slack",
                        )
                        failed_count += 1
                        continue
                    except RuntimeError as exc:
                        _log_failure(
                            org_id=org_id,
                            cycle_id=cycle_id,
                            email=nomination.email,
                            error_reason=str(exc),
                            event_type="reminder",
                            channel="slack",
                        )
                        failed_count += 1
                        continue

                # Send individual DM
                dm_result = slack_client.send_dm(slack_user_id, slack_message, bot_token)
                if dm_result.ok:
                    result.slack_sent_count += 1
                else:
                    _log_failure(
                        org_id=org_id,
                        cycle_id=cycle_id,
                        email=nomination.email,
                        error_reason=dm_result.error or "Unknown Slack error",
                        event_type="reminder",
                        channel="slack",
                    )
                    failed_count += 1

    result.failed_count = failed_count

    # Log reminder event
    reminder_log = ReminderLog(
        org_id=org_id,
        cycle_id=cycle_id,
        log_id=str(uuid.uuid4()),
        sent_at=datetime.now(timezone.utc).isoformat(),
        trigger_type=trigger_type,
        recipient_count=result.email_sent_count + result.slack_sent_count,
        channels=list(channels),
    )
    nps_reminder_log_repo.put_log(reminder_log)

    # Update cycle with last_reminder_at
    nps_cycle_repo.update_cycle(
        org_id, cycle_id,
        last_reminder_at=datetime.now(timezone.utc).isoformat(),
    )

    return result
