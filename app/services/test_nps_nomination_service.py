"""Tests for nps_nomination_service using moto for DynamoDB and unittest.mock for quip_client."""

import pytest
from moto import mock_aws
from unittest.mock import patch

from app.db import nps_nomination_repo
from app.db.models import ImportResult, Nomination
from app.services import nps_nomination_service


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
        nps_nomination_repo._create_table()
        yield


_ORG = "org_alpha"
_CYCLE = "cycle_q1"


def _quip_spreadsheet_response(rows):
    """Build a minimal Quip API response dict with HTML table rows."""
    header = "<tr><th>Name</th><th>Email</th></tr>"
    data_rows = "".join(
        f"<tr><td>{r['name']}</td><td>{r['email']}</td></tr>" for r in rows
    )
    return {"html": f"<table>{header}{data_rows}</table>"}


class TestImportFromQuip:
    @patch("app.services.nps_nomination_service.quip_client")
    def test_import_all_new(self, mock_quip, ddb_table):
        rows = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ]
        spreadsheet = _quip_spreadsheet_response(rows)
        mock_quip.get_spreadsheet.return_value = spreadsheet
        mock_quip.parse_nominations.return_value = rows

        result = nps_nomination_service.import_from_quip(_ORG, _CYCLE, "quip_doc_1")

        assert result.imported_count == 2
        assert result.skipped_duplicates == 0
        assert result.total_in_source == 2

        noms = nps_nomination_service.list_nominations(_ORG, _CYCLE)
        emails = {n.email for n in noms}
        assert emails == {"alice@example.com", "bob@example.com"}

    @patch("app.services.nps_nomination_service.quip_client")
    def test_import_skips_duplicates(self, mock_quip, ddb_table):
        # Pre-add Alice
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Alice", "alice@example.com")

        rows = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ]
        mock_quip.get_spreadsheet.return_value = _quip_spreadsheet_response(rows)
        mock_quip.parse_nominations.return_value = rows

        result = nps_nomination_service.import_from_quip(_ORG, _CYCLE, "quip_doc_1")

        assert result.imported_count == 1
        assert result.skipped_duplicates == 1
        assert result.total_in_source == 2

    @patch("app.services.nps_nomination_service.quip_client")
    def test_import_empty_source(self, mock_quip, ddb_table):
        mock_quip.get_spreadsheet.return_value = {"html": "<table></table>"}
        mock_quip.parse_nominations.return_value = []

        result = nps_nomination_service.import_from_quip(_ORG, _CYCLE, "quip_doc_1")

        assert result.imported_count == 0
        assert result.skipped_duplicates == 0
        assert result.total_in_source == 0


class TestAddStakeholder:
    def test_add_returns_persisted_nomination(self, ddb_table):
        result = nps_nomination_service.add_stakeholder(
            _ORG, _CYCLE, "Alice", "alice@example.com"
        )

        assert result.org_id == _ORG
        assert result.cycle_id == _CYCLE
        assert result.name == "Alice"
        assert result.email == "alice@example.com"
        assert result.responded is False

    def test_add_rejects_duplicate_email(self, ddb_table):
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Alice", "alice@example.com")

        with pytest.raises(ValueError, match="already nominated"):
            nps_nomination_service.add_stakeholder(
                _ORG, _CYCLE, "Alice Dup", "alice@example.com"
            )

    def test_same_email_different_cycle_allowed(self, ddb_table):
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Alice", "alice@example.com")
        result = nps_nomination_service.add_stakeholder(
            _ORG, "cycle_q2", "Alice", "alice@example.com"
        )
        assert result.cycle_id == "cycle_q2"

    def test_same_email_different_org_allowed(self, ddb_table):
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Alice", "alice@example.com")
        result = nps_nomination_service.add_stakeholder(
            "org_beta", _CYCLE, "Alice", "alice@example.com"
        )
        assert result.org_id == "org_beta"


class TestRemoveStakeholder:
    def test_remove_existing(self, ddb_table):
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Alice", "alice@example.com")
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Bob", "bob@example.com")

        nps_nomination_service.remove_stakeholder(_ORG, _CYCLE, "alice@example.com")

        noms = nps_nomination_service.list_nominations(_ORG, _CYCLE)
        assert len(noms) == 1
        assert noms[0].email == "bob@example.com"

    def test_remove_nonexistent_is_noop(self, ddb_table):
        # Should not raise
        nps_nomination_service.remove_stakeholder(_ORG, _CYCLE, "nobody@example.com")


class TestListNominations:
    def test_list_empty(self, ddb_table):
        assert nps_nomination_service.list_nominations(_ORG, _CYCLE) == []

    def test_list_returns_all(self, ddb_table):
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Alice", "alice@example.com")
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Bob", "bob@example.com")

        noms = nps_nomination_service.list_nominations(_ORG, _CYCLE)
        assert len(noms) == 2


class TestGetReminderList:
    def test_returns_only_non_respondents(self, ddb_table):
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Alice", "alice@example.com")
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Bob", "bob@example.com")

        # Mark Alice as responded
        nps_nomination_repo.update_responded(_ORG, _CYCLE, "alice@example.com")

        reminder = nps_nomination_service.get_reminder_list(_ORG, _CYCLE)
        assert len(reminder) == 1
        assert reminder[0].email == "bob@example.com"

    def test_all_responded_returns_empty(self, ddb_table):
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Alice", "alice@example.com")
        nps_nomination_repo.update_responded(_ORG, _CYCLE, "alice@example.com")

        reminder = nps_nomination_service.get_reminder_list(_ORG, _CYCLE)
        assert len(reminder) == 0

    def test_none_responded_returns_all(self, ddb_table):
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Alice", "alice@example.com")
        nps_nomination_service.add_stakeholder(_ORG, _CYCLE, "Bob", "bob@example.com")

        reminder = nps_nomination_service.get_reminder_list(_ORG, _CYCLE)
        assert len(reminder) == 2


# ---------------------------------------------------------------------------
# Self-serve leader nomination form (nominate_stakeholder & friends)
# ---------------------------------------------------------------------------


@pytest.fixture
def form_tables():
    """Nomination + org-config tables (roster lives in the org-config table)."""
    from app.db import nps_org_config_repo

    with mock_aws():
        nps_nomination_repo._create_table()
        nps_org_config_repo._create_table()
        yield


class TestNominateStakeholder:
    def test_nominate_success_from_alias(self, form_tables):
        result = nps_nomination_service.nominate_stakeholder(
            _ORG, _CYCLE,
            stakeholder_alias="jdoe",
            name="John Doe",
            leader="Navjyot Bhatia",
            nominated_by="kumruxl",
            designation="Sr. Program Manager",
        )
        assert result.email == "jdoe@amazon.com"
        assert result.name == "John Doe"
        assert result.leader == "Navjyot Bhatia"
        assert result.nominated_by == "kumruxl"
        assert result.designation == "Sr. Program Manager"
        assert result.created_at  # set on write

    def test_full_email_and_mixed_case_normalized(self, form_tables):
        result = nps_nomination_service.nominate_stakeholder(
            _ORG, _CYCLE,
            stakeholder_alias="JDoe@Amazon.com",
            name="John Doe",
            leader="Navjyot Bhatia",
            nominated_by="KUMRUXL@amazon.com",
        )
        assert result.email == "jdoe@amazon.com"
        assert result.nominated_by == "kumruxl"

    def test_duplicate_under_same_leader_rejected_first_come_first_served(self, form_tables):
        nps_nomination_service.nominate_stakeholder(
            _ORG, _CYCLE, "jdoe", "John Doe", "Navjyot Bhatia", nominated_by="direct1"
        )
        with pytest.raises(nps_nomination_service.DuplicateNominationError) as exc_info:
            nps_nomination_service.nominate_stakeholder(
                _ORG, _CYCLE, "jdoe", "John Doe", "Navjyot Bhatia", nominated_by="direct2"
            )
        existing = exc_info.value.existing
        assert existing.nominated_by == "direct1"
        assert existing.leader == "Navjyot Bhatia"

    def test_same_stakeholder_under_different_leader_allowed(self, form_tables):
        first = nps_nomination_service.nominate_stakeholder(
            _ORG, _CYCLE, "jdoe", "John Doe", "Navjyot Bhatia", nominated_by="direct1"
        )
        second = nps_nomination_service.nominate_stakeholder(
            _ORG, _CYCLE, "jdoe", "John Doe", "Nidhi Bhagat", nominated_by="direct9"
        )
        from app.services.nomination_keys import base_email

        assert first.email == "jdoe@amazon.com"
        assert second.email != first.email  # suffixed key keeps rows unique
        assert base_email(second.email) == "jdoe@amazon.com"
        assert len(nps_nomination_service.list_nominations(_ORG, _CYCLE)) == 2

    def test_duplicate_check_resets_with_new_cycle(self, form_tables):
        nps_nomination_service.nominate_stakeholder(
            _ORG, _CYCLE, "jdoe", "John Doe", "Navjyot Bhatia", nominated_by="direct1"
        )
        # New cycle, same leader + stakeholder: allowed again
        result = nps_nomination_service.nominate_stakeholder(
            _ORG, "cycle_q2", "jdoe", "John Doe", "Navjyot Bhatia", nominated_by="direct2"
        )
        assert result.cycle_id == "cycle_q2"

    def test_missing_required_fields_rejected(self, form_tables):
        with pytest.raises(ValueError, match="required"):
            nps_nomination_service.nominate_stakeholder(
                _ORG, _CYCLE, "jdoe", "John Doe", leader="", nominated_by="kumruxl"
            )
        with pytest.raises(ValueError, match="required"):
            nps_nomination_service.nominate_stakeholder(
                _ORG, _CYCLE, "jdoe", "John Doe", leader="Navjyot Bhatia", nominated_by=""
            )
        with pytest.raises(ValueError, match="required"):
            nps_nomination_service.nominate_stakeholder(
                _ORG, _CYCLE, "", "John Doe", leader="Navjyot Bhatia", nominated_by="kumruxl"
            )


class TestListNominationsForLeader:
    def test_filters_by_leader(self, form_tables):
        nps_nomination_service.nominate_stakeholder(
            _ORG, _CYCLE, "a1", "Alice", "Navjyot Bhatia", nominated_by="d1"
        )
        nps_nomination_service.nominate_stakeholder(
            _ORG, _CYCLE, "b1", "Bob", "Nidhi Bhagat", nominated_by="d2"
        )
        rows = nps_nomination_service.list_nominations_for_leader(
            _ORG, _CYCLE, "Navjyot Bhatia"
        )
        assert [n.name for n in rows] == ["Alice"]


class TestRemoveLeaderNomination:
    def _nominate(self):
        nps_nomination_service.nominate_stakeholder(
            _ORG, _CYCLE, "jdoe", "John Doe", "Navjyot Bhatia", nominated_by="direct1"
        )

    def test_nominator_can_remove(self, form_tables):
        self._nominate()
        nps_nomination_service.remove_leader_nomination(
            _ORG, _CYCLE, "jdoe", "Navjyot Bhatia", requested_by="direct1"
        )
        assert nps_nomination_service.list_nominations(_ORG, _CYCLE) == []

    def test_privileged_role_can_remove(self, form_tables):
        self._nominate()
        nps_nomination_service.remove_leader_nomination(
            _ORG, _CYCLE, "jdoe", "Navjyot Bhatia",
            requested_by="someadmin", is_privileged=True,
        )
        assert nps_nomination_service.list_nominations(_ORG, _CYCLE) == []

    def test_leader_can_remove_via_roster_alias(self, form_tables):
        from app.services import nps_leader_service

        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia")
        self._nominate()
        nps_nomination_service.remove_leader_nomination(
            _ORG, _CYCLE, "jdoe", "Navjyot Bhatia", requested_by="nsbhatia"
        )
        assert nps_nomination_service.list_nominations(_ORG, _CYCLE) == []

    def test_stranger_cannot_remove(self, form_tables):
        self._nominate()
        with pytest.raises(PermissionError):
            nps_nomination_service.remove_leader_nomination(
                _ORG, _CYCLE, "jdoe", "Navjyot Bhatia", requested_by="rando"
            )
        assert len(nps_nomination_service.list_nominations(_ORG, _CYCLE)) == 1

    def test_remove_missing_nomination_raises(self, form_tables):
        with pytest.raises(ValueError, match="No nomination found"):
            nps_nomination_service.remove_leader_nomination(
                _ORG, _CYCLE, "ghost", "Navjyot Bhatia", requested_by="direct1"
            )

    def test_remove_only_targets_that_leaders_row(self, form_tables):
        """Removing under one leader must not touch the other leader's row."""
        nps_nomination_service.nominate_stakeholder(
            _ORG, _CYCLE, "jdoe", "John Doe", "Navjyot Bhatia", nominated_by="d1"
        )
        nps_nomination_service.nominate_stakeholder(
            _ORG, _CYCLE, "jdoe", "John Doe", "Nidhi Bhagat", nominated_by="d2"
        )
        nps_nomination_service.remove_leader_nomination(
            _ORG, _CYCLE, "jdoe", "Nidhi Bhagat", requested_by="d2"
        )
        remaining = nps_nomination_service.list_nominations(_ORG, _CYCLE)
        assert len(remaining) == 1
        assert remaining[0].leader == "Navjyot Bhatia"
