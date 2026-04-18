"""Tests for the Amazon SES email client."""

from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

import pytest

from app.db.models import EmailResult
from app.services import email_client
from app.services.email_client import build_email_payload, send_bcc_email


@pytest.fixture(autouse=True)
def _reset_ses():
    email_client.reset_ses_client()
    yield
    email_client.reset_ses_client()


# --- build_email_payload tests ---

class TestBuildEmailPayload:
    def test_all_recipients_in_bcc(self):
        recipients = ["a@example.com", "b@example.com"]
        payload = build_email_payload("Subject", "<p>Body</p>", recipients)

        assert payload["Destination"]["ToAddresses"] == []
        assert payload["Destination"]["CcAddresses"] == []
        assert payload["Destination"]["BccAddresses"] == recipients

    def test_subject_and_body_set(self):
        payload = build_email_payload("Hello", "<b>World</b>", ["a@example.com"])
        assert payload["Message"]["Subject"]["Data"] == "Hello"
        assert payload["Message"]["Body"]["Html"]["Data"] == "<b>World</b>"

    def test_empty_recipients(self):
        payload = build_email_payload("Sub", "Body", [])
        assert payload["Destination"]["BccAddresses"] == []
        assert payload["Destination"]["ToAddresses"] == []
        assert payload["Destination"]["CcAddresses"] == []

    def test_single_recipient(self):
        payload = build_email_payload("S", "B", ["solo@example.com"])
        assert payload["Destination"]["BccAddresses"] == ["solo@example.com"]


# --- send_bcc_email tests ---

class TestSendBccEmail:
    @patch("app.services.email_client._get_ses_client")
    def test_successful_send(self, mock_get_client):
        mock_ses = MagicMock()
        mock_ses.send_email.return_value = {"MessageId": "abc123"}
        mock_get_client.return_value = mock_ses

        result = send_bcc_email(
            "Survey", "<p>Please respond</p>",
            ["a@example.com", "b@example.com"],
            "nps@example.com",
        )

        assert result.ok is True
        assert result.error == ""
        mock_ses.send_email.assert_called_once()

        call_kwargs = mock_ses.send_email.call_args
        assert call_kwargs.kwargs["Source"] == "nps@example.com"
        dest = call_kwargs.kwargs["Destination"]
        assert dest["ToAddresses"] == []
        assert dest["CcAddresses"] == []
        assert set(dest["BccAddresses"]) == {"a@example.com", "b@example.com"}

    @patch("app.services.email_client._get_ses_client")
    def test_ses_client_error(self, mock_get_client):
        mock_ses = MagicMock()
        mock_ses.send_email.side_effect = ClientError(
            {"Error": {"Code": "MessageRejected", "Message": "Email not verified"}},
            "SendEmail",
        )
        mock_get_client.return_value = mock_ses

        result = send_bcc_email("Survey", "Body", ["a@example.com"], "nps@example.com")

        assert result.ok is False
        assert "not verified" in result.error

    @patch("app.services.email_client._get_ses_client")
    def test_generic_exception(self, mock_get_client):
        mock_ses = MagicMock()
        mock_ses.send_email.side_effect = RuntimeError("Connection refused")
        mock_get_client.return_value = mock_ses

        result = send_bcc_email("Survey", "Body", ["a@example.com"], "nps@example.com")

        assert result.ok is False
        assert "Connection refused" in result.error

    def test_empty_recipients_returns_ok(self):
        result = send_bcc_email("Survey", "Body", [], "nps@example.com")
        assert result.ok is True
