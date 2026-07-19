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
        assert result == {"alias": "nsbhatia", "name": "Navjyot Bhatia"}
        assert nps_leader_service.get_leader("nsbhatia") == {
            "alias": "nsbhatia",
            "name": "Navjyot Bhatia",
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


class TestNoOrgPollution:
    def test_leader_rows_not_listed_as_orgs(self, ddb_table):
        """Roster rows share the org-config table but must not appear as orgs."""
        nps_leader_service.add_leader("raabhas", "Abhas Rao")
        assert nps_org_config_service.list_all_orgs() == []
        assert nps_org_config_service.list_active_orgs() == []


class TestSendNominationInvite:
    _URL = "http://localhost:5000/"

    def _roster(self):
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia")
        nps_leader_service.add_leader("raabhas", "Abhas Rao")

    @patch("app.services.email_client.send_bcc_email")
    def test_invite_sent_to_all_leaders_bcc(self, mock_send, ddb_table):
        from app.db.models import EmailResult

        mock_send.return_value = EmailResult(ok=True)
        self._roster()

        result = nps_leader_service.send_nomination_invite(
            self._URL, "2026-08-01", note="Please prioritize."
        )

        assert result["sent_count"] == 2
        assert result["deadline"] == "2026-08-01"
        subject, body, recipients, _from = mock_send.call_args[0]
        assert "2026-08-01" in subject
        assert recipients == ["nsbhatia@amazon.com", "raabhas@amazon.com"]
        assert "/nps/nominate/view?token=" in body
        assert "Deadline: 2026-08-01" in body
        assert "Please prioritize." in body

    def test_requires_deadline(self, ddb_table):
        self._roster()
        with pytest.raises(ValueError, match="deadline"):
            nps_leader_service.send_nomination_invite(self._URL, "")

    def test_empty_roster_rejected(self, ddb_table):
        with pytest.raises(ValueError, match="roster is empty"):
            nps_leader_service.send_nomination_invite(self._URL, "2026-08-01")

    def test_demo_safe_blocks_invite(self, ddb_table, monkeypatch):
        self._roster()
        monkeypatch.setenv("NPS_DEMO_SAFE", "1")
        with pytest.raises(ValueError, match="Demo-safe"):
            nps_leader_service.send_nomination_invite(self._URL, "2026-08-01")

    @patch("app.services.email_client.send_bcc_email")
    def test_ses_failure_raises(self, mock_send, ddb_table):
        from app.db.models import EmailResult

        mock_send.return_value = EmailResult(ok=False, error="SES down")
        self._roster()
        with pytest.raises(RuntimeError, match="SES down"):
            nps_leader_service.send_nomination_invite(self._URL, "2026-08-01")
