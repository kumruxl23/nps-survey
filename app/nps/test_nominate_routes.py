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
        # direct1 is an editor: privileged (may pick a leader explicitly).
        # The nominator identity is ALWAYS derived server-side from the
        # session/ALB — never from the request body.
        with client.session_transaction() as sess:
            sess["user"] = {"username": "direct1", "role": "editor", "display_name": "D"}
        yield client


def _set_user(client, username, role):
    with client.session_transaction() as sess:
        sess["user"] = {"username": username, "role": role, "display_name": username}


def _submit(client, **overrides):
    payload = {
        "org_id": _ORG,
        "leader": "Navjyot Bhatia",
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
        assert body["nominated_by"] == "direct1"  # from session identity

    def test_nominated_by_cannot_be_spoofed(self, client):
        resp = _submit(client, nominated_by="someone-else")
        assert resp.get_json()["nominated_by"] == "direct1"

    def test_duplicate_returns_409_with_existing_details(self, client):
        _submit(client)
        resp = _submit(client)
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["duplicate"] is True
        assert body["existing"]["nominated_by"] == "direct1"
        assert body["existing"]["leader"] == "Navjyot Bhatia"

    def test_regular_user_gets_system_resolved_leader(self, client):
        # Seed: kumruxl appears in history under Navjyot (workbook-style).
        _submit(client, stakeholder_alias="kumruxl", name="Rohit Kumar")
        # kumruxl (regular viewer) nominates: leader resolved from history,
        # client-supplied leader is ignored.
        _set_user(client, "kumruxl", "viewer")
        resp = _submit(client, stakeholder_alias="newguy", name="New Guy",
                       leader="Someone Else")
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["leader"] == "Navjyot Bhatia"
        assert body["nominated_by"] == "kumruxl"

    def test_regular_user_unresolvable_leader_rejected(self, client):
        _set_user(client, "ghost", "viewer")
        resp = _submit(client)
        assert resp.status_code == 400
        assert "leader" in resp.get_json()["error"].lower()

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
        # Leaders now ride on each org (org-scoped rosters).
        assert body["orgs"][0]["leaders"] == [
            {"alias": "nsbhatia", "name": "Navjyot Bhatia", "org_id": ""}
        ]
        assert body["locked_org"] is None
        assert body["viewer"]["alias"] == "direct1"
        assert body["viewer"]["privileged_orgs"][_ORG] is True  # editor

    def test_viewer_is_not_privileged(self, client):
        _set_user(client, "someguy", "viewer")
        body = client.get("/nps/nominate/context").get_json()
        assert body["viewer"]["privileged_orgs"][_ORG] is False

    def test_roster_leader_is_privileged(self, client):
        _set_user(client, "nsbhatia", "viewer")  # on the org roster
        body = client.get("/nps/nominate/context").get_json()
        assert body["viewer"]["privileged_orgs"][_ORG] is True

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

    def test_regular_user_cannot_list_nominations(self, client):
        _submit(client)
        _set_user(client, "someguy", "viewer")
        resp = client.get(
            f"/nps/nominate/list?org_id={_ORG}&leader=Navjyot%20Bhatia"
        )
        assert resp.status_code == 403

    def test_roster_leader_can_list_nominations(self, client):
        _submit(client)
        _set_user(client, "nsbhatia", "viewer")
        resp = client.get(
            f"/nps/nominate/list?org_id={_ORG}&leader=Navjyot%20Bhatia"
        )
        assert resp.status_code == 200
        assert len(resp.get_json()) == 1


class TestNominateRemove:
    def _remove(self, client):
        return client.post("/nps/nominate/remove", json={
            "org_id": _ORG,
            "leader": "Navjyot Bhatia",
            "stakeholder_alias": "jdoe",
        })

    def test_nominator_can_remove(self, client):
        _submit(client)  # nominated_by=direct1 (session identity)
        _set_user(client, "direct1", "viewer")  # same person, plain role
        resp = self._remove(client)
        assert resp.status_code == 200

    def test_stranger_gets_403(self, client):
        _submit(client)
        _set_user(client, "rando", "viewer")
        resp = self._remove(client)
        assert resp.status_code == 403

    def test_requested_by_in_body_is_ignored(self, client):
        _submit(client)
        _set_user(client, "rando", "viewer")
        resp = client.post("/nps/nominate/remove", json={
            "org_id": _ORG, "leader": "Navjyot Bhatia",
            "stakeholder_alias": "jdoe", "requested_by": "direct1",  # spoof try
        })
        assert resp.status_code == 403

    def test_admin_session_can_remove_regardless(self, client):
        _submit(client)
        _set_user(client, "admin", "admin")
        resp = self._remove(client)
        assert resp.status_code == 200


class TestLeaderRosterRoutes:
    def test_viewer_cannot_manage_roster(self, client):
        _set_user(client, "someguy", "viewer")
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

    def _get_token(self, client, org=_ORG):
        self._admin(client)
        resp = client.get("/nps/nominate/context")
        share_path = resp.get_json()["share_paths"][org]
        self._logout(client)
        return share_path.split("token=", 1)[1]

    def test_admin_context_includes_share_paths(self, client):
        self._admin(client)
        body = client.get("/nps/nominate/context").get_json()
        assert body["share_paths"][_ORG].startswith("/nps/nominate/view?token=")

    def test_viewer_context_has_no_share_paths(self, client):
        _set_user(client, "someguy", "viewer")
        body = client.get("/nps/nominate/context").get_json()
        assert "share_paths" not in body

    def test_token_grants_form_access_without_login(self, client, monkeypatch):
        token = self._get_token(client)
        # Page renders
        resp = client.get(f"/nps/nominate/view?token={token}")
        assert resp.status_code == 200
        # Context works, is locked to the org, and never leaks share links
        resp = client.get(f"/nps/nominate/context?token={token}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "share_paths" not in body
        assert body["locked_org"] == _ORG
        assert [o["org_id"] for o in body["orgs"]] == [_ORG]
        # Submit works — identity comes from the ALB header (Midway mode);
        # roster leader nsbhatia nominates, resolving to themselves.
        monkeypatch.setenv("NPS_MIDWAY_AUTH", "1")
        resp = client.post(f"/nps/nominate/submit?token={token}",
                           headers={"X-Amzn-Oidc-Identity": "nsbhatia"},
                           json={
                               "org_id": _ORG,
                               "stakeholder_alias": "tokuser",
                               "name": "Token User",
                           })
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["nominated_by"] == "nsbhatia"
        assert body["leader"] == "Navjyot Bhatia"  # roster self-resolution

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
        resp = client.post("/nps/nominate/share-link/rotate", json={"org_id": _ORG})
        assert resp.status_code == 200
        new_token = resp.get_json()["share_path"].split("token=", 1)[1]
        self._logout(client)
        assert client.get(f"/nps/nominate/view?token={token}").status_code == 302
        assert client.get(f"/nps/nominate/view?token={new_token}").status_code == 200

    def test_rotate_requires_admin(self, client):
        resp = client.post("/nps/nominate/share-link/rotate", json={"org_id": _ORG})
        assert resp.status_code == 403

    def test_token_locked_to_its_org(self, client):
        """A share token must not read or write another org's data."""
        token = self._get_token(client)
        resp = client.get(
            f"/nps/nominate/list?org_id=other_org&leader=X&token={token}")
        assert resp.status_code == 403
        resp = client.post(f"/nps/nominate/submit?token={token}", json={
            "org_id": "other_org", "leader": "X", "nominated_by": "a",
            "stakeholder_alias": "b", "name": "B",
        })
        assert resp.status_code == 403
        resp = client.get(
            f"/nps/nominate/prefill?org_id=other_org&alias=jdoe&token={token}")
        assert resp.status_code == 403


class TestNominateInviteRoute:
    def test_viewer_cannot_invite(self, client):
        _set_user(client, "someguy", "viewer")
        resp = client.post("/nps/nominate/invite", json={"deadline": "2026-08-01"})
        assert resp.status_code == 403

    def test_admin_invite_sends(self, client):
        from unittest.mock import patch
        from app.db.models import EmailResult

        with client.session_transaction() as sess:
            sess["user"] = {"username": "admin", "role": "admin", "display_name": "A"}
        with patch("app.services.email_client.send_bcc_email") as mock_send:
            mock_send.return_value = EmailResult(ok=True)
            resp = client.post("/nps/nominate/invite",
                               json={"deadline": "2026-08-01", "org_id": _ORG})
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


class TestPrefill:
    """Alias-driven prefill: leader auto-resolution + stakeholder details."""

    def test_stakeholder_history_prefill(self, client):
        # Seed one nomination via the form, then look the person up.
        _submit(client, stakeholder_alias="jdoe", name="John Doe",
                designation="Sr. PM")
        resp = client.get(f"/nps/nominate/prefill?org_id={_ORG}&alias=jdoe")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["found"] is True
        assert body["name"] == "John Doe"
        assert body["designation"] == "Sr. PM"
        assert body["leader"] == "Navjyot Bhatia"

    def test_nominator_resolves_to_their_leader(self, client):
        # jdoe sits under Navjyot in history -> nominating as jdoe should
        # surface Navjyot as the leader.
        _submit(client, stakeholder_alias="jdoe", name="John Doe")
        resp = client.get(f"/nps/nominate/prefill?org_id={_ORG}&alias=jdoe@amazon.com")
        assert resp.get_json()["leader"] == "Navjyot Bhatia"

    def test_roster_leader_resolves_to_self(self, client):
        resp = client.get(f"/nps/nominate/prefill?org_id={_ORG}&alias=nsbhatia")
        body = resp.get_json()
        assert body["found"] is True
        assert body["is_leader"] is True
        assert body["leader"] == "Navjyot Bhatia"

    def test_unknown_alias_not_found(self, client):
        resp = client.get(f"/nps/nominate/prefill?org_id={_ORG}&alias=ghost")
        assert resp.status_code == 200
        assert resp.get_json() == {"found": False}

    def test_requires_params(self, client):
        assert client.get("/nps/nominate/prefill").status_code == 400
