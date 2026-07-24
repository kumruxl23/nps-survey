"""Tests for the PAPI directory client (papi_client)."""

from unittest.mock import MagicMock, patch

import pytest

from app.services import papi_client
from app.services.papi_client import PapiError


@pytest.fixture(autouse=True)
def papi_env(monkeypatch):
    monkeypatch.setenv("PAPI_ROLE_ARN", "arn:aws:iam::220627861680:role/IAMAuth_nps-survey_us-east-1")
    monkeypatch.setenv("PAPI_ENDPOINT", "https://papi.amazon.com")
    papi_client._cached_creds = {}


def _employee_payload(login="jdoe", first="John", last="Doe",
                      title="Sr. PM", manager="boss1"):
    return {
        "basicInfo": {
            "login": login,
            "firstName": first,
            "lastName": last,
            "businessTitle": title,
            "managerLogin": manager,
        }
    }


def _mock_response(status=200, payload=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload or {}
    resp.text = ""
    return resp


class TestGetEmployee:
    def test_unconfigured_raises(self, monkeypatch):
        monkeypatch.delenv("PAPI_ROLE_ARN")
        with pytest.raises(PapiError, match="not configured"):
            papi_client.get_employee("jdoe")
        assert papi_client.is_configured() is False

    @patch("app.services.papi_client._signed_get")
    def test_found(self, mock_get):
        mock_get.return_value = _mock_response(200, _employee_payload())
        emp = papi_client.get_employee("JDoe@amazon.com")
        assert emp == {
            "login": "jdoe", "name": "John Doe",
            "title": "Sr. PM", "manager_login": "boss1",
        }
        assert "login:jdoe" in mock_get.call_args[0][0]

    @patch("app.services.papi_client._signed_get")
    def test_unknown_alias_returns_none(self, mock_get):
        mock_get.return_value = _mock_response(404)
        assert papi_client.get_employee("ghost") is None

    @patch("app.services.papi_client._signed_get")
    def test_server_error_raises(self, mock_get):
        mock_get.return_value = _mock_response(500)
        with pytest.raises(PapiError, match="HTTP 500"):
            papi_client.get_employee("jdoe")

    @patch("app.services.papi_client._signed_get")
    def test_manager_login_alternate_shapes(self, mock_get):
        payload = {"basicInfo": {"login": "jdoe", "firstName": "J", "lastName": "D",
                                 "businessTitle": "PM"},
                   "manager": {"login": "BOSS2"}}
        mock_get.return_value = _mock_response(200, payload)
        assert papi_client.get_employee("jdoe")["manager_login"] == "boss2"


class TestResolveLeaderViaChain:
    @patch("app.services.papi_client.get_employee")
    @patch("app.services.nps_leader_service.list_leaders")
    def test_walks_chain_to_roster_member(self, mock_leaders, mock_emp):
        mock_leaders.return_value = [{"alias": "direct1", "name": "Direct One", "org_id": "o"}]
        # jdoe -> mid1 -> direct1 (on roster)
        mock_emp.side_effect = [
            {"login": "jdoe", "name": "J D", "title": "", "manager_login": "mid1"},
            {"login": "mid1", "name": "M One", "title": "", "manager_login": "direct1"},
        ]
        result = papi_client.resolve_leader_via_chain("o", "jdoe")
        assert result == {"leader_name": "Direct One", "leader_alias": "direct1", "hops": 2}

    @patch("app.services.nps_leader_service.list_leaders")
    def test_roster_leader_resolves_immediately(self, mock_leaders):
        mock_leaders.return_value = [{"alias": "direct1", "name": "Direct One", "org_id": "o"}]
        result = papi_client.resolve_leader_via_chain("o", "direct1")
        assert result["hops"] == 0  # no PAPI calls needed

    @patch("app.services.papi_client.get_employee")
    @patch("app.services.nps_leader_service.list_leaders")
    def test_chain_never_meets_roster(self, mock_leaders, mock_emp):
        mock_leaders.return_value = [{"alias": "direct1", "name": "Direct One", "org_id": "o"}]
        mock_emp.return_value = {"login": "x", "name": "X", "title": "", "manager_login": ""}
        assert papi_client.resolve_leader_via_chain("o", "outsider") is None

    @patch("app.services.nps_leader_service.list_leaders")
    def test_empty_roster_returns_none(self, mock_leaders):
        mock_leaders.return_value = []
        assert papi_client.resolve_leader_via_chain("o", "jdoe") is None


class TestLookupPersonPapiIntegration:
    """lookup_person prefers PAPI and falls back gracefully."""

    @patch("app.services.papi_client.resolve_leader_via_chain")
    @patch("app.services.papi_client.get_employee")
    @patch("app.services.nps_leader_service.list_leaders", return_value=[])
    def test_papi_result_used(self, _l, mock_emp, mock_chain):
        from app.services import nps_nomination_service
        mock_emp.return_value = {"login": "jdoe", "name": "John Doe",
                                 "title": "Sr. PM", "manager_login": "m"}
        mock_chain.return_value = {"leader_name": "Direct One",
                                   "leader_alias": "direct1", "hops": 2}
        result = nps_nomination_service.lookup_person("o", "jdoe")
        assert result["name"] == "John Doe"
        assert result["designation"] == "Sr. PM"
        assert result["leader"] == "Direct One"
        assert result["source"] == "papi"

    @patch("app.services.papi_client.get_employee", side_effect=PapiError("down"))
    @patch("app.services.nps_leader_service.list_leaders", return_value=[])
    @patch("app.services.nps_nomination_service._lookup_from_history")
    def test_papi_outage_falls_back_to_history(self, mock_hist, _l, _e):
        from app.services import nps_nomination_service
        mock_hist.return_value = {"name": "H", "designation": "", "leader": "L",
                                  "is_leader": False, "source": "history:c1"}
        result = nps_nomination_service.lookup_person("o", "jdoe")
        assert result["source"] == "history:c1"
