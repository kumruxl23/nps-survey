"""Tests for Midway (ALB OIDC header) auto-login — NPS_MIDWAY_AUTH=1."""

import pytest
from moto import mock_aws

from app import create_app
from app.db import nps_org_config_repo
from app.services import auth_service


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


_HDR = "X-Amzn-Oidc-Identity"


@pytest.fixture
def client(monkeypatch):
    """Test client in Midway mode with one provisioned admin (kumruxl)."""
    monkeypatch.setenv("NPS_MIDWAY_AUTH", "1")
    with mock_aws():
        nps_org_config_repo._create_table()
        auth_service.create_user("kumruxl", "irrelevant-password", "admin", "Rohit")

        app = create_app({"TESTING": True})
        yield app.test_client()


class TestMidwayAutoLogin:
    def test_known_alias_reaches_protected_route(self, client):
        resp = client.get("/nps/orgs", headers={_HDR: "kumruxl"})
        assert resp.status_code == 200

    def test_alias_is_case_insensitive(self, client):
        resp = client.get("/nps/orgs", headers={_HDR: "  KumRuxl "})
        assert resp.status_code == 200

    def test_login_page_redirects_to_dashboard(self, client):
        resp = client.get("/nps/auth/login", headers={_HDR: "kumruxl"})
        assert resp.status_code == 302
        assert "/nps/dashboard" in resp.headers["Location"]

    def test_unknown_alias_gets_denied_page(self, client):
        resp = client.get("/nps/auth/login", headers={_HDR: "stranger"})
        assert resp.status_code == 403
        assert b"Access not provisioned" in resp.data
        assert b"stranger" in resp.data

    def test_unknown_alias_blocked_from_protected_route(self, client):
        resp = client.get("/nps/orgs", headers={_HDR: "stranger"},
                          content_type="application/json")
        # No session established -> redirect to login (page shows denial)
        assert resp.status_code in (302, 401)

    def test_deactivated_user_denied(self, client):
        auth_service.delete_user("kumruxl")
        resp = client.get("/nps/auth/login", headers={_HDR: "kumruxl"})
        assert resp.status_code == 403

    def test_password_login_disabled(self, client):
        resp = client.post("/nps/auth/login",
                           json={"username": "kumruxl", "password": "x"})
        assert resp.status_code == 403
        assert "Midway" in resp.get_json()["error"]

    def test_role_enforcement_still_applies(self, client):
        auth_service.create_user("viewer1", "pw", "viewer", "V")
        # Viewer can read orgs list...
        assert client.get("/nps/orgs", headers={_HDR: "viewer1"}).status_code == 200
        # ...but cannot hit an admin-only route.
        resp = client.post("/nps/orgs/add", headers={_HDR: "viewer1"},
                           json={"org_id": "x", "org_name": "X"})
        assert resp.status_code == 403

    def test_add_user_without_password_in_midway_mode(self, client):
        with client.session_transaction() as sess:
            sess["user"] = {"username": "kumruxl", "role": "admin", "display_name": "R"}
        resp = client.post("/nps/auth/users/add",
                           json={"username": "KuVinu", "role": "editor"})
        assert resp.status_code == 201
        # Username normalized to lowercase alias; usable via Midway header.
        assert auth_service.get_user("kuvinu")["role"] == "editor"


class TestPasswordModeUnaffected:
    @pytest.fixture
    def pw_client(self, monkeypatch):
        monkeypatch.delenv("NPS_MIDWAY_AUTH", raising=False)
        with mock_aws():
            nps_org_config_repo._create_table()
            auth_service.create_user("admin", "hunter2", "admin", "Admin")
            app = create_app({"TESTING": True})
            yield app.test_client()

    def test_form_login_still_works(self, pw_client):
        resp = pw_client.post("/nps/auth/login",
                              json={"username": "admin", "password": "hunter2"})
        assert resp.status_code == 200
        assert resp.get_json()["role"] == "admin"

    def test_header_ignored_without_flag(self, pw_client):
        resp = pw_client.get("/nps/orgs", headers={_HDR: "admin"},
                             content_type="application/json")
        assert resp.status_code in (302, 401)
