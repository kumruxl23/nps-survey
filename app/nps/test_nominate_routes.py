"""Route tests for the self-serve leader nomination form (/nps/nominate/*)."""

import pytest
from moto import mock_aws

from app import create_app
from app.db import nps_cycle_repo, nps_nomination_repo, nps_org_config_repo
from app.db.models import OrgConfig, SurveyCycle
from app.services import nps_leader_service


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


_ORG = "org_alpha"
_CYCLE = "cycle_q1"


@pytest.fixture
def client():
    """Flask test client with tables, one org + active cycle, and a leader."""
    with mock_aws():
        nps_org_config_repo._create_table()
        nps_cycle_repo._create_table()
        nps_nomination_repo._create_table()

        nps_org_config_repo.put_org(OrgConfig(
            org_id=_ORG,
            org_name="Alpha Org",
            asana_project_gid="p1",
            asana_form_url="https://form.asana.com/alpha",
            custom_field_nps_score_gid="cf1",
            custom_field_category_gid="cf2",
            custom_field_org_name_gid="cf3",
        ))
        nps_cycle_repo.put_cycle(SurveyCycle(
            org_id=_ORG,
            cycle_id=_CYCLE,
            start_date="2026-01-01",
            end_date="2026-12-31",
            status="active",
            reminder_mode="manual",
            cycle_name="H2 2026",
        ))
        nps_leader_service.add_leader("nsbhatia", "Navjyot Bhatia")

        app = create_app({"TESTING": True})
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user"] = {"username": "viewer1", "role": "viewer", "display_name": "V"}
        yield client


def _submit(client, **overrides):
    payload = {
        "org_id": _ORG,
        "leader": "Navjyot Bhatia",
        "nominated_by": "direct1",
        "stakeholder_alias": "jdoe",
        "name": "John Doe",
        "designation": "Sr. PM",
    }
    payload.update(overrides)
    return client.post("/nps/nominate/submit", json=payload)


class TestNominateSubmit:
    def test_submit_success(self, client):
        resp = _submit(client)
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["email"] == "jdoe@amazon.com"
        assert body["leader"] == "Navjyot Bhatia"
        assert body["nominated_by"] == "direct1"

    def test_duplicate_returns_409_with_existing_details(self, client):
        _submit(client)
        resp = _submit(client, nominated_by="direct2")
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["duplicate"] is True
        assert body["existing"]["nominated_by"] == "direct1"
        assert body["existing"]["leader"] == "Navjyot Bhatia"

    def test_no_active_cycle_rejected(self, client):
        nps_cycle_repo.update_cycle(_ORG, _CYCLE, status="closed")
        resp = _submit(client)
        assert resp.status_code == 400
        assert "active" in resp.get_json()["error"].lower()

    def test_requires_login(self, client):
        with client.session_transaction() as sess:
            sess.pop("user", None)
        resp = _submit(client)
        assert resp.status_code == 401


class TestNominateListAndContext:
    def test_context_returns_orgs_and_leaders(self, client):
        resp = client.get("/nps/nominate/context")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["orgs"][0]["org_id"] == _ORG
        assert body["orgs"][0]["active_cycle"]["cycle_name"] == "H2 2026"
        assert body["leaders"] == [{"alias": "nsbhatia", "name": "Navjyot Bhatia"}]

    def test_list_for_leader(self, client):
        _submit(client)
        resp = client.get(
            f"/nps/nominate/list?org_id={_ORG}&leader=Navjyot%20Bhatia"
        )
        assert resp.status_code == 200
        rows = resp.get_json()
        assert len(rows) == 1
        assert rows[0]["email"] == "jdoe@amazon.com"
        assert rows[0]["nominated_by"] == "direct1"


class TestNominateRemove:
    def _remove(self, client, requested_by):
        return client.post("/nps/nominate/remove", json={
            "org_id": _ORG,
            "leader": "Navjyot Bhatia",
            "stakeholder_alias": "jdoe",
            "requested_by": requested_by,
        })

    def test_nominator_can_remove(self, client):
        _submit(client)
        resp = self._remove(client, "direct1")
        assert resp.status_code == 200

    def test_stranger_gets_403(self, client):
        _submit(client)
        resp = self._remove(client, "rando")
        assert resp.status_code == 403

    def test_admin_session_can_remove_regardless(self, client):
        _submit(client)
        with client.session_transaction() as sess:
            sess["user"] = {"username": "admin", "role": "admin", "display_name": "A"}
        resp = self._remove(client, "rando")
        assert resp.status_code == 200


class TestLeaderRosterRoutes:
    def test_viewer_cannot_manage_roster(self, client):
        resp = client.post("/nps/leaders/add", json={"alias": "x", "name": "X"})
        assert resp.status_code == 403

    def test_admin_can_add_and_remove(self, client):
        with client.session_transaction() as sess:
            sess["user"] = {"username": "admin", "role": "admin", "display_name": "A"}
        resp = client.post("/nps/leaders/add", json={"alias": "raabhas", "name": "Abhas Rao"})
        assert resp.status_code == 201
        resp = client.get("/nps/leaders")
        names = [l["name"] for l in resp.get_json()]
        assert "Abhas Rao" in names
        resp = client.post("/nps/leaders/remove", json={"alias": "raabhas"})
        assert resp.status_code == 200

    def test_form_page_renders(self, client):
        resp = client.get("/nps/nominate/view")
        assert resp.status_code == 200
        assert b"Nominate Stakeholders" in resp.data


class TestShareLink:
    def _logout(self, client):
        with client.session_transaction() as sess:
            sess.pop("user", None)

    def _admin(self, client):
        with client.session_transaction() as sess:
            sess["user"] = {"username": "admin", "role": "admin", "display_name": "A"}

    def _get_token(self, client):
        self._admin(client)
        resp = client.get("/nps/nominate/context")
        share_path = resp.get_json()["share_path"]
        self._logout(client)
        return share_path.split("token=", 1)[1]

    def test_admin_context_includes_share_path(self, client):
        self._admin(client)
        body = client.get("/nps/nominate/context").get_json()
        assert body["share_path"].startswith("/nps/nominate/view?token=")

    def test_viewer_context_has_no_share_path(self, client):
        body = client.get("/nps/nominate/context").get_json()
        assert "share_path" not in body

    def test_token_grants_form_access_without_login(self, client):
        token = self._get_token(client)
        # Page renders
        resp = client.get(f"/nps/nominate/view?token={token}")
        assert resp.status_code == 200
        # Context works, but never leaks the share link to token users
        resp = client.get(f"/nps/nominate/context?token={token}")
        assert resp.status_code == 200
        assert "share_path" not in resp.get_json()
        # Submit works
        resp = client.post(f"/nps/nominate/submit?token={token}", json={
            "org_id": _ORG,
            "leader": "Navjyot Bhatia",
            "nominated_by": "leaderx",
            "stakeholder_alias": "tokuser",
            "name": "Token User",
        })
        assert resp.status_code == 201

    def test_bad_token_rejected(self, client):
        self._logout(client)
        resp = client.post("/nps/nominate/submit?token=wrong", json={"org_id": _ORG})
        assert resp.status_code == 401
        # Page request redirects to login instead of erroring
        resp = client.get("/nps/nominate/view?token=wrong")
        assert resp.status_code == 302

    def test_token_does_not_open_other_routes(self, client):
        token = self._get_token(client)
        resp = client.get(
            f"/nps/nominations?org_id={_ORG}&cycle_id={_CYCLE}&token={token}",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_rotate_invalidates_old_token(self, client):
        token = self._get_token(client)
        self._admin(client)
        resp = client.post("/nps/nominate/share-link/rotate")
        assert resp.status_code == 200
        new_token = resp.get_json()["share_path"].split("token=", 1)[1]
        self._logout(client)
        assert client.get(f"/nps/nominate/view?token={token}").status_code == 302
        assert client.get(f"/nps/nominate/view?token={new_token}").status_code == 200

    def test_rotate_requires_admin(self, client):
        resp = client.post("/nps/nominate/share-link/rotate")
        assert resp.status_code == 403


class TestNominateInviteRoute:
    def test_viewer_cannot_invite(self, client):
        resp = client.post("/nps/nominate/invite", json={"deadline": "2026-08-01"})
        assert resp.status_code == 403

    def test_admin_invite_sends(self, client):
        from unittest.mock import patch
        from app.db.models import EmailResult

        with client.session_transaction() as sess:
            sess["user"] = {"username": "admin", "role": "admin", "display_name": "A"}
        with patch("app.services.email_client.send_bcc_email") as mock_send:
            mock_send.return_value = EmailResult(ok=True)
            resp = client.post("/nps/nominate/invite", json={"deadline": "2026-08-01"})
        assert resp.status_code == 200
        assert resp.get_json()["sent_count"] == 1  # fixture seeds one leader
        # Link in the email uses the request host
        body = mock_send.call_args[0][1]
        assert "http://localhost/nps/nominate/view?token=" in body

    def test_missing_deadline_400(self, client):
        with client.session_transaction() as sess:
            sess["user"] = {"username": "admin", "role": "admin", "display_name": "A"}
        resp = client.post("/nps/nominate/invite", json={})
        assert resp.status_code == 400
