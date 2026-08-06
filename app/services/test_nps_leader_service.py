"""Tests for the leader roster service (nps_leader_service)."""

from unittest.mock import patch

import pytest
from moto import mock_aws

from app.db import nps_org_config_repo
from app.services import nps_leader_service, nps_org_config_service


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def ddb_table():
    with mock_aws():
        nps_org_config_repo._create_table()
        yield


class TestAddLeader:
    def test_add_and_get(self, ddb_table):
        result = nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia")
        assert result == {"alias": "nsbhatia", "name": "Navjyot Bhatia", "org_id": "", "notify_alias": ""}
        assert nps_leader_service.get_leader("nsbhatia") == {
            "alias": "nsbhatia",
            "name": "Navjyot Bhatia",
            "notify_alias": "",
        }

    def test_alias_normalized(self, ddb_table):
        nps_leader_service.add_leader("  NSBhatia@amazon.com ", "Navjyot Bhatia")
        assert nps_leader_service.get_leader("nsbhatia") is not None

    def test_duplicate_rejected(self, ddb_table):
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia")
        with pytest.raises(ValueError, match="already exists"):
            nps_leader_service.add_leader("nsbhatia", "Navjyot B.")

    def test_missing_fields_rejected(self, ddb_table):
        with pytest.raises(ValueError):
            nps_leader_service.add_leader("", "Name Only")
        with pytest.raises(ValueError):
            nps_leader_service.add_leader("aliasonly", "")

    def test_readd_after_remove_allowed(self, ddb_table):
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia")
        nps_leader_service.remove_leader("nsbhatia")
        result = nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia")
        assert result["alias"] == "nsbhatia"


class TestListLeaders:
    def test_sorted_by_name(self, ddb_table):
        nps_leader_service.add_leader("bhanidhi", "Nidhi Bhagat")
        nps_leader_service.add_leader("raabhas", "Abhas Rao")
        names = [l["name"] for l in nps_leader_service.list_leaders()]
        assert names == ["Abhas Rao", "Nidhi Bhagat"]

    def test_removed_leader_excluded(self, ddb_table):
        nps_leader_service.add_leader("raabhas", "Abhas Rao")
        nps_leader_service.remove_leader("raabhas")
        assert nps_leader_service.list_leaders() == []
        assert nps_leader_service.get_leader("raabhas") is None

    def test_org_scoping(self, ddb_table):
        nps_leader_service.add_leader("alpha1", "Alpha Leader", org_id="org_alpha")
        nps_leader_service.add_leader("beta1", "Beta Leader", org_id="org_beta")
        nps_leader_service.add_leader("legacy1", "Legacy Leader")  # unscoped

        alpha = [l["alias"] for l in nps_leader_service.list_leaders("org_alpha")]
        assert alpha == ["alpha1", "legacy1"]  # own + legacy, not beta's
        assert len(nps_leader_service.list_leaders()) == 3  # unscoped = all


class TestNoOrgPollution:
    def test_leader_rows_not_listed_as_orgs(self, ddb_table):
        """Roster rows share the org-config table but must not appear as orgs."""
        nps_leader_service.add_leader("raabhas", "Abhas Rao")
        assert nps_org_config_service.list_all_orgs() == []
        assert nps_org_config_service.list_active_orgs() == []


class TestSendNominationInvite:
    _URL = "http://localhost:5000/"
    _ORG = "org_alpha"

    def _roster(self):
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia", org_id=self._ORG)
        nps_leader_service.add_leader("raabhas", "Abhas Rao", org_id=self._ORG)

    @patch("app.services.email_client.send_bcc_email")
    def test_invite_sent_to_all_leaders_bcc(self, mock_send, ddb_table):
        from app.db.models import EmailResult

        mock_send.return_value = EmailResult(ok=True)
        self._roster()

        result = nps_leader_service.send_nomination_invite(
            self._URL, "2026-08-01", note="Please prioritize.", org_id=self._ORG
        )

        assert result["sent_count"] == 2
        assert result["deadline"] == "2026-08-01"
        subject, body, recipients, _from = mock_send.call_args[0]
        assert "2026-08-01" in subject
        assert recipients == ["nsbhatia@amazon.com", "raabhas@amazon.com"]
        assert "/nps/nominate/view?token=" in body
        assert "Deadline: 2026-08-01" in body
        assert "Please prioritize." in body

    @patch("app.services.email_client.send_bcc_email")
    def test_invite_scoped_to_org(self, mock_send, ddb_table):
        from app.db.models import EmailResult

        mock_send.return_value = EmailResult(ok=True)
        self._roster()
        nps_leader_service.add_leader("beta1", "Beta Leader", org_id="org_beta")

        result = nps_leader_service.send_nomination_invite(
            self._URL, "2026-08-01", org_id=self._ORG
        )

        assert result["sent_count"] == 2  # beta's leader NOT included
        _s, body, recipients, _f = mock_send.call_args[0]
        assert "beta1@amazon.com" not in recipients
        # Link carries the COMMON token — one link, org resolved per viewer.
        from app.services import nps_share_link_service
        assert nps_share_link_service.get_or_create_common_token() in body

    def test_requires_org(self, ddb_table):
        self._roster()
        with pytest.raises(ValueError, match="org_id"):
            nps_leader_service.send_nomination_invite(self._URL, "2026-08-01")

    def test_requires_deadline(self, ddb_table):
        self._roster()
        with pytest.raises(ValueError, match="deadline"):
            nps_leader_service.send_nomination_invite(self._URL, "", org_id=self._ORG)

    def test_empty_roster_rejected(self, ddb_table):
        with pytest.raises(ValueError, match="roster is empty"):
            nps_leader_service.send_nomination_invite(self._URL, "2026-08-01", org_id=self._ORG)

    def test_demo_safe_blocks_invite(self, ddb_table, monkeypatch):
        self._roster()
        monkeypatch.setenv("NPS_DEMO_SAFE", "1")
        with pytest.raises(ValueError, match="Demo-safe"):
            nps_leader_service.send_nomination_invite(self._URL, "2026-08-01", org_id=self._ORG)

    @patch("app.services.email_client.send_bcc_email")
    def test_ses_failure_raises(self, mock_send, ddb_table):
        from app.db.models import EmailResult

        mock_send.return_value = EmailResult(ok=False, error="SES down")
        self._roster()
        with pytest.raises(RuntimeError, match="SES down"):
            nps_leader_service.send_nomination_invite(self._URL, "2026-08-01", org_id=self._ORG)


# ---------------------------------------------------------------------------
# Notify-alias (test redirect) + leader reminders (email + Slack)
# ---------------------------------------------------------------------------


def _put_org(org_id="org_alpha", slack_bot_token=""):
    from app.db import nps_org_config_repo
    from app.db.models import OrgConfig

    nps_org_config_repo.put_org(OrgConfig(
        org_id=org_id, org_name="Alpha Org", asana_project_gid="",
        asana_form_url="", custom_field_nps_score_gid="",
        custom_field_category_gid="", custom_field_org_name_gid="",
        slack_bot_token=slack_bot_token,
    ))


class TestNotifyAlias:
    def test_add_leader_with_notify_alias(self, ddb_table):
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia", notify_alias="kumruxl")
        assert nps_leader_service.get_leader("nsbhatia")["notify_alias"] == "kumruxl"

    def test_set_notify_alias(self, ddb_table):
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia")
        nps_leader_service.set_notify_alias("nsbhatia", "kuvinu")
        assert nps_leader_service.get_leader("nsbhatia")["notify_alias"] == "kuvinu"

    def test_set_notify_alias_missing_leader(self, ddb_table):
        with pytest.raises(ValueError, match="not found"):
            nps_leader_service.set_notify_alias("ghost", "kumruxl")


class TestSendLeaderReminders:
    @patch("app.services.slack_client.send_dm")
    @patch("app.services.slab_client.lookup_slack_id_by_alias")
    @patch("app.services.email_client.send_bcc_email")
    def test_reminders_redirect_to_test_alias(self, mock_email, mock_lookup, mock_dm, ddb_table):
        from app.db.models import EmailResult, SlackResult

        _put_org(slack_bot_token="xoxb-test")
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia", org_id="org_alpha", notify_alias="kumruxl")
        nps_leader_service.add_leader("raabhas", "Abhas Rao", org_id="org_alpha", notify_alias="kuvinu")
        mock_email.return_value = EmailResult(ok=True)
        mock_lookup.return_value = "U123"
        mock_dm.return_value = SlackResult(ok=True)

        result = nps_leader_service.send_leader_reminders("http://localhost/", "org_alpha")

        assert result["email_sent"] == 2
        assert result["slack_sent"] == 2
        # Reminders went to the TEST aliases, never the real leaders.
        emailed = [call.args[2][0] for call in mock_email.call_args_list]
        assert "kumruxl@amazon.com" in emailed and "kuvinu@amazon.com" in emailed
        assert "nsbhatia@amazon.com" not in emailed
        # SLAB is queried by ALIAS (no email, no users:read).
        looked = [call.args[0] for call in mock_lookup.call_args_list]
        assert "kumruxl" in looked and "nsbhatia" not in looked

    @patch("app.services.email_client.send_bcc_email")
    def test_no_slack_token_reports_and_still_emails(self, mock_email, ddb_table):
        from app.db.models import EmailResult

        _put_org(slack_bot_token="")  # no Slack configured
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia", org_id="org_alpha", notify_alias="kumruxl")
        mock_email.return_value = EmailResult(ok=True)

        result = nps_leader_service.send_leader_reminders("http://localhost/", "org_alpha")
        assert result["email_sent"] == 1
        assert result["slack_sent"] == 0
        assert any("no bot token" in e for e in result["reminders"][0]["errors"])

    @patch("app.services.email_client.send_bcc_email")
    def test_demo_safe_skips_leaders_without_test_alias(self, mock_email, ddb_table, monkeypatch):
        from app.db.models import EmailResult

        _put_org()
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia", org_id="org_alpha")  # no redirect
        monkeypatch.setenv("NPS_DEMO_SAFE", "1")
        mock_email.return_value = EmailResult(ok=True)

        result = nps_leader_service.send_leader_reminders(
            "http://localhost/", "org_alpha", channels=("email",)
        )
        assert result["email_sent"] == 0
        assert "demo-safe" in result["reminders"][0]["errors"][0]

    def test_empty_roster_rejected(self, ddb_table):
        _put_org(org_id="org_empty")
        with pytest.raises(ValueError, match="roster is empty"):
            nps_leader_service.send_leader_reminders("http://localhost/", "org_empty")


class TestSendNominationOpen:
    @patch("app.services.slack_client.send_dm")
    @patch("app.services.slab_client.lookup_slack_id_by_alias")
    @patch("app.services.email_client.send_bcc_email")
    def test_notifies_via_email_and_slack_redirected_to_test_alias(
        self, mock_email, mock_lookup, mock_dm, ddb_table
    ):
        from app.db.models import EmailResult, SlackResult

        _put_org(slack_bot_token="xoxb-test")
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia", org_id="org_alpha", notify_alias="kumruxl")
        nps_leader_service.add_leader("raabhas", "Abhas Rao", org_id="org_alpha", notify_alias="kuvinu")
        mock_email.return_value = EmailResult(ok=True)
        mock_lookup.return_value = "U123"
        mock_dm.return_value = SlackResult(ok=True)

        result = nps_leader_service.send_nomination_open(
            "http://localhost/", "org_alpha", deadline="2026-08-15"
        )

        assert result["email_sent"] == 2
        assert result["slack_sent"] == 2
        assert result["deadline"] == "2026-08-15"
        assert len(result["notifications"]) == 2
        # Went to TEST aliases, never the real leaders.
        emailed = [call.args[2][0] for call in mock_email.call_args_list]
        assert "kumruxl@amazon.com" in emailed and "kuvinu@amazon.com" in emailed
        assert "nsbhatia@amazon.com" not in emailed
        # Subject + body signal a kickoff (not a reminder).
        subjects = [call.args[0] for call in mock_email.call_args_list]
        assert all("now open" in s.lower() for s in subjects)

    @patch("app.services.email_client.send_bcc_email")
    def test_no_slack_token_reports_and_still_emails(self, mock_email, ddb_table):
        from app.db.models import EmailResult

        _put_org(slack_bot_token="")  # no Slack configured
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia", org_id="org_alpha", notify_alias="kumruxl")
        mock_email.return_value = EmailResult(ok=True)

        result = nps_leader_service.send_nomination_open("http://localhost/", "org_alpha")
        assert result["email_sent"] == 1
        assert result["slack_sent"] == 0
        assert any("no bot token" in e for e in result["notifications"][0]["errors"])

    @patch("app.services.email_client.send_bcc_email")
    def test_demo_safe_skips_leaders_without_test_alias(self, mock_email, ddb_table, monkeypatch):
        from app.db.models import EmailResult

        _put_org()
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia", org_id="org_alpha")  # no redirect
        monkeypatch.setenv("NPS_DEMO_SAFE", "1")
        mock_email.return_value = EmailResult(ok=True)

        result = nps_leader_service.send_nomination_open(
            "http://localhost/", "org_alpha", channels=("email",)
        )
        assert result["email_sent"] == 0
        assert "demo-safe" in result["notifications"][0]["errors"][0]

    @patch("app.services.email_client.send_bcc_email")
    def test_email_only_channel(self, mock_email, ddb_table):
        from app.db.models import EmailResult

        _put_org(slack_bot_token="xoxb-test")
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia", org_id="org_alpha", notify_alias="kumruxl")
        mock_email.return_value = EmailResult(ok=True)

        result = nps_leader_service.send_nomination_open(
            "http://localhost/", "org_alpha", channels=("email",)
        )
        assert result["email_sent"] == 1
        assert result["slack_sent"] == 0

    def test_empty_roster_rejected(self, ddb_table):
        _put_org(org_id="org_empty")
        with pytest.raises(ValueError, match="roster is empty"):
            nps_leader_service.send_nomination_open("http://localhost/", "org_empty")

    def test_org_id_required(self, ddb_table):
        with pytest.raises(ValueError, match="org_id is required"):
            nps_leader_service.send_nomination_open("http://localhost/", "")

    @patch("app.services.slab_client.lookup_slack_id_by_alias")
    @patch("app.services.email_client.send_bcc_email")
    def test_slab_failure_reported_per_row_email_still_ok(self, mock_email, mock_slab, ddb_table):
        from app.db.models import EmailResult
        from app.services import slab_client

        _put_org(slack_bot_token="xoxb-test")
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia", org_id="org_alpha", notify_alias="kumruxl")
        mock_email.return_value = EmailResult(ok=True)
        # SLAB can't resolve — must be caught per row, never break the batch.
        mock_slab.side_effect = slab_client.SlackUserNotFoundError("no mapping")

        result = nps_leader_service.send_nomination_open("http://localhost/", "org_alpha")
        assert result["email_sent"] == 1
        assert result["slack_sent"] == 0
        assert any("slack:" in e for e in result["notifications"][0]["errors"])

    @patch("app.services.slab_client.lookup_slack_id_by_alias")
    @patch("app.services.email_client.send_bcc_email")
    def test_slab_not_configured_reported_per_row(self, mock_email, mock_slab, ddb_table):
        from app.db.models import EmailResult

        _put_org(slack_bot_token="xoxb-test")
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia", org_id="org_alpha", notify_alias="kumruxl")
        mock_email.return_value = EmailResult(ok=True)
        # SLAB_ENDPOINT missing -> RuntimeError; batch must survive.
        mock_slab.side_effect = RuntimeError("SLAB_ENDPOINT is not configured")

        result = nps_leader_service.send_nomination_open("http://localhost/", "org_alpha")
        assert result["email_sent"] == 1
        assert result["slack_sent"] == 0
        assert any("slack:" in e for e in result["notifications"][0]["errors"])


class TestCheckSlackResolution:
    """SLAB alias→Slack-ID diagnostic (read-only; no bot token needed)."""

    def test_empty_alias_is_reported_not_raised(self):
        row = nps_leader_service.check_slack_resolution("")
        assert row["ok"] is False
        assert "required" in row["error"]

    @patch("app.services.slab_client.lookup_slack_id_by_alias")
    def test_success_returns_slack_id(self, mock_slab):
        mock_slab.return_value = "U12345"
        row = nps_leader_service.check_slack_resolution("KumRuxl@amazon.com")
        assert row == {"alias": "kumruxl", "ok": True, "slack_id": "U12345", "error": ""}

    @patch("app.services.slab_client.lookup_slack_id_by_alias")
    def test_not_found_reported(self, mock_slab):
        from app.services import slab_client

        mock_slab.side_effect = slab_client.SlackUserNotFoundError("no mapping")
        row = nps_leader_service.check_slack_resolution("ghost")
        assert row["ok"] is False
        assert "not found" in row["error"]

    @patch("app.services.slab_client.lookup_slack_id_by_alias")
    def test_transport_error_reported_not_raised(self, mock_slab):
        mock_slab.side_effect = RuntimeError("SLAB_ENDPOINT is not configured")
        row = nps_leader_service.check_slack_resolution("kumruxl")
        assert row["ok"] is False
        assert "SLAB_ENDPOINT" in row["error"]
