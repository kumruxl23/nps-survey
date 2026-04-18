"""Tests for nps_distribution_service using moto for DynamoDB and unittest.mock for clients."""

import pytest
from moto import mock_aws
from unittest.mock import patch, MagicMock

from app.db import (
    nps_cycle_repo,
    nps_delivery_failure_repo,
    nps_nomination_repo,
    nps_org_config_repo,
    nps_reminder_log_repo,
)
from app.db.models import (
    EmailResult,
    Nomination,
    OrgConfig,
    SlackResult,
    SurveyCycle,
)
from app.services import nps_distribution_service


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("NPS_FROM_ADDRESS", "nps@example.com")


@pytest.fixture
def ddb_tables():
    with mock_aws():
        nps_org_config_repo._create_table()
        nps_cycle_repo._create_table()
        nps_nomination_repo._create_table()
        nps_delivery_failure_repo._create_table()
        nps_reminder_log_repo._create_table()
        yield


_ORG = "org_alpha"
_CYCLE = "cycle_q1"


def _seed_org(reminder_channels=None, slack_bot_token=""):
    """Create a default OrgConfig in DynamoDB."""
    org = OrgConfig(
        org_id=_ORG,
        org_name="Alpha Org",
        asana_project_gid="proj_123",
        asana_form_url="https://form.asana.com/?k=test",
        custom_field_nps_score_gid="cf_score",
        custom_field_category_gid="cf_cat",
        custom_field_org_name_gid="cf_org",
        reminder_channels=reminder_channels or ["email"],
        slack_bot_token=slack_bot_token,
    )
    nps_org_config_repo.put_org(org)
    return org


def _seed_cycle(distributed_at=""):
    """Create a default SurveyCycle in DynamoDB."""
    cycle = SurveyCycle(
        org_id=_ORG,
        cycle_id=_CYCLE,
        start_date="2025-01-01",
        end_date="2025-03-31",
        status="active",
        reminder_mode="manual",
        asana_project_gid="proj_123",
        asana_form_url="https://form.asana.com/?k=test",
        distributed_at=distributed_at,
    )
    nps_cycle_repo.put_cycle(cycle)
    return cycle


def _seed_nominations(emails):
    """Create nominations for the given email list."""
    for i, email in enumerate(emails):
        nom = Nomination(
            org_id=_ORG,
            cycle_id=_CYCLE,
            email=email,
            name=f"User{i}",
        )
        nps_nomination_repo.put_nomination(nom)


# ── distribute_survey tests ──────────────────────────────────────────


class TestDistributeSurvey:
    @patch("app.services.nps_distribution_service.email_client")
    def test_successful_distribution(self, mock_email, ddb_tables):
        _seed_org()
        _seed_cycle()
        _seed_nominations(["a@example.com", "b@example.com"])
        mock_email.send_bcc_email.return_value = EmailResult(ok=True)

        result = nps_distribution_service.distribute_survey(_ORG, _CYCLE)

        assert result.sent_count == 2
        assert result.failed_count == 0
        assert result.already_distributed is False

        # Verify cycle updated with distributed_at
        cycle = nps_cycle_repo.get_cycle(_ORG, _CYCLE)
        assert cycle.distributed_at != ""

        # Verify email was called with BCC recipients
        mock_email.send_bcc_email.assert_called_once()
        call_kwargs = mock_email.send_bcc_email.call_args
        assert set(call_kwargs.kwargs["bcc_recipients"]) == {"a@example.com", "b@example.com"}

    @patch("app.services.nps_distribution_service.email_client")
    def test_idempotent_already_distributed(self, mock_email, ddb_tables):
        _seed_org()
        _seed_cycle(distributed_at="2025-01-15T10:00:00+00:00")
        _seed_nominations(["a@example.com"])

        result = nps_distribution_service.distribute_survey(_ORG, _CYCLE)

        assert result.already_distributed is True
        assert result.sent_count == 0
        mock_email.send_bcc_email.assert_not_called()

    @patch("app.services.nps_distribution_service.email_client")
    def test_email_failure_logs_delivery_failures(self, mock_email, ddb_tables):
        _seed_org()
        _seed_cycle()
        _seed_nominations(["a@example.com", "b@example.com"])
        mock_email.send_bcc_email.return_value = EmailResult(ok=False, error="Graph API 500")

        result = nps_distribution_service.distribute_survey(_ORG, _CYCLE)

        assert result.sent_count == 0
        assert result.failed_count == 2

        failures = nps_delivery_failure_repo.list_failures(_ORG, _CYCLE)
        assert len(failures) == 2
        assert all(f.channel == "email" for f in failures)
        assert all(f.event_type == "distribution" for f in failures)

    @patch("app.services.nps_distribution_service.email_client")
    def test_empty_nominations_still_marks_distributed(self, mock_email, ddb_tables):
        _seed_org()
        _seed_cycle()
        # No nominations

        result = nps_distribution_service.distribute_survey(_ORG, _CYCLE)

        assert result.sent_count == 0
        assert result.failed_count == 0
        cycle = nps_cycle_repo.get_cycle(_ORG, _CYCLE)
        assert cycle.distributed_at != ""
        mock_email.send_bcc_email.assert_not_called()

    def test_cycle_not_found_raises(self, ddb_tables):
        _seed_org()
        with pytest.raises(ValueError, match="not found"):
            nps_distribution_service.distribute_survey(_ORG, "nonexistent")

    @patch("app.services.nps_distribution_service.email_client")
    def test_org_not_found_raises(self, mock_email, ddb_tables):
        _seed_cycle()
        with pytest.raises(ValueError, match="not found"):
            nps_distribution_service.distribute_survey(_ORG, _CYCLE)


# ── send_reminder tests ──────────────────────────────────────────────


class TestSendReminderEmail:
    @patch("app.services.nps_distribution_service.email_client")
    def test_email_reminder_success(self, mock_email, ddb_tables):
        _seed_org(reminder_channels=["email"])
        _seed_cycle(distributed_at="2025-01-15T10:00:00+00:00")
        _seed_nominations(["a@example.com", "b@example.com"])
        mock_email.send_bcc_email.return_value = EmailResult(ok=True)

        result = nps_distribution_service.send_reminder(_ORG, _CYCLE, "manual")

        assert result.email_sent_count == 2
        assert result.slack_sent_count == 0
        assert result.failed_count == 0
        assert "email" in result.channels_used

        # Verify reminder log created
        logs = nps_reminder_log_repo.list_logs(_ORG, _CYCLE)
        assert len(logs) == 1
        assert logs[0].trigger_type == "manual"
        assert logs[0].recipient_count == 2

        # Verify cycle updated with last_reminder_at
        cycle = nps_cycle_repo.get_cycle(_ORG, _CYCLE)
        assert cycle.last_reminder_at != ""

    @patch("app.services.nps_distribution_service.email_client")
    def test_email_reminder_failure_logs(self, mock_email, ddb_tables):
        _seed_org(reminder_channels=["email"])
        _seed_cycle(distributed_at="2025-01-15T10:00:00+00:00")
        _seed_nominations(["a@example.com"])
        mock_email.send_bcc_email.return_value = EmailResult(ok=False, error="timeout")

        result = nps_distribution_service.send_reminder(_ORG, _CYCLE, "automated")

        assert result.email_sent_count == 0
        assert result.failed_count == 1

        failures = nps_delivery_failure_repo.list_failures(_ORG, _CYCLE)
        assert len(failures) == 1
        assert failures[0].channel == "email"
        assert failures[0].event_type == "reminder"

    @patch("app.services.nps_distribution_service.email_client")
    def test_no_non_respondents_returns_empty(self, mock_email, ddb_tables):
        _seed_org()
        _seed_cycle(distributed_at="2025-01-15T10:00:00+00:00")
        # No nominations at all

        result = nps_distribution_service.send_reminder(_ORG, _CYCLE, "manual")

        assert result.email_sent_count == 0
        assert result.slack_sent_count == 0
        mock_email.send_bcc_email.assert_not_called()


class TestSendReminderSlack:
    @patch("app.services.nps_distribution_service.slack_client")
    @patch("app.services.nps_distribution_service.email_client")
    def test_slack_only_reminder(self, mock_email, mock_slack, ddb_tables):
        _seed_org(reminder_channels=["slack"], slack_bot_token="xoxb-test-token")
        _seed_cycle(distributed_at="2025-01-15T10:00:00+00:00")
        _seed_nominations(["a@example.com", "b@example.com"])

        mock_slack.lookup_user_by_email.side_effect = lambda email, token: f"U_{email.split('@')[0]}"
        mock_slack.send_dm.return_value = SlackResult(ok=True)

        result = nps_distribution_service.send_reminder(_ORG, _CYCLE, "manual")

        assert result.slack_sent_count == 2
        assert result.email_sent_count == 0
        assert result.failed_count == 0
        assert "slack" in result.channels_used

        # Verify email was NOT called
        mock_email.send_bcc_email.assert_not_called()

        # Verify send_dm called once per stakeholder
        assert mock_slack.send_dm.call_count == 2

    @patch("app.services.nps_distribution_service.slack_client")
    @patch("app.services.nps_distribution_service.email_client")
    def test_slack_caches_user_id(self, mock_email, mock_slack, ddb_tables):
        _seed_org(reminder_channels=["slack"], slack_bot_token="xoxb-test-token")
        _seed_cycle(distributed_at="2025-01-15T10:00:00+00:00")
        _seed_nominations(["a@example.com"])

        mock_slack.lookup_user_by_email.return_value = "U_alice"
        mock_slack.send_dm.return_value = SlackResult(ok=True)

        nps_distribution_service.send_reminder(_ORG, _CYCLE, "manual")

        # Verify slack_user_id was cached on the nomination
        nom = nps_nomination_repo.get_nomination(_ORG, _CYCLE, "a@example.com")
        assert nom.slack_user_id == "U_alice"

    @patch("app.services.nps_distribution_service.slack_client")
    @patch("app.services.nps_distribution_service.email_client")
    def test_slack_uses_cached_user_id(self, mock_email, mock_slack, ddb_tables):
        _seed_org(reminder_channels=["slack"], slack_bot_token="xoxb-test-token")
        _seed_cycle(distributed_at="2025-01-15T10:00:00+00:00")

        # Pre-seed nomination with cached slack_user_id
        nom = Nomination(
            org_id=_ORG, cycle_id=_CYCLE, email="a@example.com",
            name="Alice", slack_user_id="U_cached",
        )
        nps_nomination_repo.put_nomination(nom)

        mock_slack.send_dm.return_value = SlackResult(ok=True)

        nps_distribution_service.send_reminder(_ORG, _CYCLE, "manual")

        # lookup should NOT have been called since ID was cached
        mock_slack.lookup_user_by_email.assert_not_called()
        mock_slack.send_dm.assert_called_once()
        call_args = mock_slack.send_dm.call_args
        assert call_args[0][0] == "U_cached"

    @patch("app.services.nps_distribution_service.slack_client")
    @patch("app.services.nps_distribution_service.email_client")
    def test_slack_user_not_found_logs_failure(self, mock_email, mock_slack, ddb_tables):
        from app.services.slack_client import SlackUserNotFoundError

        _seed_org(reminder_channels=["slack"], slack_bot_token="xoxb-test-token")
        _seed_cycle(distributed_at="2025-01-15T10:00:00+00:00")
        _seed_nominations(["a@example.com"])

        mock_slack.lookup_user_by_email.side_effect = SlackUserNotFoundError("not found")
        # Re-bind the exception class so isinstance checks work in the service
        mock_slack.SlackUserNotFoundError = SlackUserNotFoundError

        result = nps_distribution_service.send_reminder(_ORG, _CYCLE, "manual")

        assert result.slack_sent_count == 0
        assert result.failed_count == 1

        failures = nps_delivery_failure_repo.list_failures(_ORG, _CYCLE)
        assert len(failures) == 1
        assert failures[0].channel == "slack"

    @patch("app.services.nps_distribution_service.slack_client")
    @patch("app.services.nps_distribution_service.email_client")
    def test_slack_dm_failure_logs_and_continues(self, mock_email, mock_slack, ddb_tables):
        _seed_org(reminder_channels=["slack"], slack_bot_token="xoxb-test-token")
        _seed_cycle(distributed_at="2025-01-15T10:00:00+00:00")
        _seed_nominations(["a@example.com", "b@example.com"])

        mock_slack.lookup_user_by_email.side_effect = lambda email, token: f"U_{email.split('@')[0]}"
        # First DM fails, second succeeds
        mock_slack.send_dm.side_effect = [
            SlackResult(ok=False, error="channel_not_found"),
            SlackResult(ok=True),
        ]

        result = nps_distribution_service.send_reminder(_ORG, _CYCLE, "manual")

        assert result.slack_sent_count == 1
        assert result.failed_count == 1

    @patch("app.services.nps_distribution_service.slack_client")
    @patch("app.services.nps_distribution_service.email_client")
    def test_slack_no_bot_token_skips_slack(self, mock_email, mock_slack, ddb_tables):
        _seed_org(reminder_channels=["slack"], slack_bot_token="")
        _seed_cycle(distributed_at="2025-01-15T10:00:00+00:00")
        _seed_nominations(["a@example.com"])

        result = nps_distribution_service.send_reminder(_ORG, _CYCLE, "manual")

        assert result.slack_sent_count == 0
        mock_slack.send_dm.assert_not_called()


class TestSendReminderBothChannels:
    @patch("app.services.nps_distribution_service.slack_client")
    @patch("app.services.nps_distribution_service.email_client")
    def test_both_channels(self, mock_email, mock_slack, ddb_tables):
        _seed_org(
            reminder_channels=["email", "slack"],
            slack_bot_token="xoxb-test-token",
        )
        _seed_cycle(distributed_at="2025-01-15T10:00:00+00:00")
        _seed_nominations(["a@example.com"])

        mock_email.send_bcc_email.return_value = EmailResult(ok=True)
        mock_slack.lookup_user_by_email.return_value = "U_alice"
        mock_slack.send_dm.return_value = SlackResult(ok=True)

        result = nps_distribution_service.send_reminder(_ORG, _CYCLE, "manual")

        assert result.email_sent_count == 1
        assert result.slack_sent_count == 1
        assert result.failed_count == 0
        assert set(result.channels_used) == {"email", "slack"}

        # Both clients called
        mock_email.send_bcc_email.assert_called_once()
        mock_slack.send_dm.assert_called_once()
