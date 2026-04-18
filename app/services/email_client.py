"""Amazon SES wrapper for sending BCC emails.

Uses boto3 SES client. All recipients are placed in BCC to preserve
stakeholder anonymity. No Microsoft Graph or Azure AD needed.
"""

import logging
import os

import boto3
from botocore.exceptions import ClientError

from app.db.models import EmailResult

logger = logging.getLogger(__name__)

_ses_client = None


def _get_ses_client():
    """Return a cached SES client."""
    global _ses_client
    if _ses_client is None:
        region = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
        _ses_client = boto3.client("ses", region_name=region)
    return _ses_client


def build_email_payload(
    subject: str, body: str, bcc_recipients: list[str]
) -> dict:
    """Build the SES SendEmail payload dict.

    All recipients are placed in BccAddresses only — no ToAddresses
    or CcAddresses — to preserve stakeholder anonymity.

    Exposed as a separate function for testing BCC enforcement.
    """
    return {
        "Destination": {
            "ToAddresses": [],
            "CcAddresses": [],
            "BccAddresses": bcc_recipients,
        },
        "Message": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Html": {"Data": body, "Charset": "UTF-8"},
            },
        },
    }


def send_bcc_email(
    subject: str,
    body: str,
    bcc_recipients: list[str],
    from_address: str,
) -> EmailResult:
    """Send an email with all recipients in BCC via Amazon SES.

    SES requires a verified sender (email or domain). BCC ensures
    no stakeholder can see other recipients (anonymity).

    Args:
        subject: Email subject line.
        body: HTML email body.
        bcc_recipients: List of recipient email addresses (placed in BCC).
        from_address: Verified SES sender address.

    Returns:
        EmailResult with ok=True on success, or ok=False with error details.
    """
    if not bcc_recipients:
        return EmailResult(ok=True)

    ses = _get_ses_client()
    payload = build_email_payload(subject, body, bcc_recipients)

    try:
        ses.send_email(
            Source=from_address,
            Destination=payload["Destination"],
            Message=payload["Message"],
        )
        return EmailResult(ok=True)
    except ClientError as exc:
        error_msg = f"SES error: {exc.response['Error']['Message']}"
        logger.error(error_msg)
        return EmailResult(ok=False, error=error_msg)
    except Exception as exc:
        error_msg = f"Email send failed: {exc}"
        logger.error(error_msg)
        return EmailResult(ok=False, error=error_msg)


def reset_ses_client() -> None:
    """Reset the cached SES client (useful for testing)."""
    global _ses_client
    _ses_client = None
