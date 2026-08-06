"""Tests for nps_settings_service and the /nps/settings routes (moto)."""

import pytest
from moto import mock_aws

from app.db import nps_org_config_repo
from app.services import nps_settings_service


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


_SAMPLE = {
    "chart_headings": {"nps_by_leader": "Custom Heading"},
    "program_status": {"current": {"cycle": "H1 2026", "status": "closed"},
                       "next": {"cycle": "H2 2026", "status": "upcoming"}},
    "program_resources": [{"icon": "x", "label": "Wiki", "value": "https://w", "type": "link"}],
    "nomination_guidelines": [{"type": "rule", "text": "Be nice"}],
    "nomination_deadline": "2026-09-08T23:59:59+05:30",
}


class TestSettingsService:
    def test_defaults_when_no_record(self, ddb_table):
        s = nps_settings_service.get_dashboard_settings()
        assert s["chart_headings"] == {}
        assert s["program_status"] is None
        assert s["program_resources"] is None
        assert s["nomination_guidelines"] is None
        assert s["nomination_deadline"] == ""
        assert s["updated_at"] == "" and s["updated_by"] == ""

    def test_roundtrip_returns_stored_values(self, ddb_table):
        result = nps_settings_service.save_dashboard_settings(_SAMPLE, "kuvinu")
        assert result["status"] == "ok"
        assert result["updated_at"]

        s = nps_settings_service.get_dashboard_settings()
        assert s["chart_headings"]["nps_by_leader"] == "Custom Heading"
        assert s["program_status"]["next"]["cycle"] == "H2 2026"
        assert s["program_resources"][0]["label"] == "Wiki"
        assert s["nomination_guidelines"][0]["text"] == "Be nice"
        assert s["nomination_deadline"].startswith("2026-09-08")

    def test_save_records_updated_at_and_by(self, ddb_table):
        nps_settings_service.save_dashboard_settings(_SAMPLE, "KUVINU ")
        s = nps_settings_service.get_dashboard_settings()
        assert s["updated_by"] == "kuvinu"  # normalized
        assert s["updated_at"]

    def test_client_cannot_spoof_metadata(self, ddb_table):
        nps_settings_service.save_dashboard_settings(
            {**_SAMPLE, "updated_by": "spoofed", "updated_at": "1999-01-01"},
            "realuser",
        )
        s = nps_settings_service.get_dashboard_settings()
        assert s["updated_by"] == "realuser"
        assert not s["updated_at"].startswith("1999")

    def test_save_rejects_non_dict(self, ddb_table):
        with pytest.raises(ValueError, match="object"):
            nps_settings_service.save_dashboard_settings(["not", "a", "dict"], "a")

    def test_save_rejects_oversized_blob(self, ddb_table):
        big = {"chart_headings": {"k": "x" * 60_000}}
        with pytest.raises(ValueError, match="large"):
            nps_settings_service.save_dashboard_settings(big, "a")

    def test_settings_row_hidden_from_org_listings(self, ddb_table):
        nps_settings_service.save_dashboard_settings(_SAMPLE, "a")
        assert nps_org_config_repo.list_all_orgs() == []
        assert nps_org_config_repo.list_active_orgs() == []


class TestSettingsRoutes:
    @pytest.fixture
    def client(self, ddb_table):
        from app import create_app
        app = create_app({"TESTING": True})
        return app.test_client()

    def _login(self, client, role):
        with client.session_transaction() as sess:
            sess["user"] = {"username": f"{role}user", "role": role, "display_name": "X"}

    def test_get_returns_settings_for_authenticated_user(self, client):
        self._login(client, "viewer")
        resp = client.get("/nps/settings")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "chart_headings" in body and "nomination_deadline" in body

    def test_get_requires_login(self, client):
        resp = client.get("/nps/settings", headers={"Accept": "application/json"})
        assert resp.status_code in (302, 401)  # redirected to login / denied

    def test_post_requires_admin(self, client):
        self._login(client, "viewer")
        assert client.post("/nps/settings", json=_SAMPLE).status_code == 403
        self._login(client, "editor")
        assert client.post("/nps/settings", json=_SAMPLE).status_code == 403

    def test_post_admin_persists(self, client):
        self._login(client, "admin")
        resp = client.post("/nps/settings", json=_SAMPLE)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

        body = client.get("/nps/settings").get_json()
        assert body["chart_headings"]["nps_by_leader"] == "Custom Heading"
        assert body["updated_by"] == "adminuser"

    def test_post_rejects_non_object_body(self, client):
        self._login(client, "admin")
        assert client.post("/nps/settings", json=[1, 2, 3]).status_code == 400
        assert client.post("/nps/settings", data="not json",
                           content_type="application/json").status_code == 400

    def test_post_rejects_oversized_body(self, client):
        self._login(client, "admin")
        resp = client.post("/nps/settings",
                           json={"chart_headings": {"k": "x" * 60_000}})
        assert resp.status_code == 400
        assert "large" in resp.get_json()["error"]
