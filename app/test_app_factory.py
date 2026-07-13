"""Tests for reverse-proxy (Midway/ALB) config and Host allowlisting."""

import os
from unittest.mock import patch

from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app


class TestProxyConfig:
    def test_proxy_off_by_default(self):
        app = create_app({"TESTING": True})
        assert app.config.get("SESSION_COOKIE_SECURE") is not True
        assert not isinstance(app.wsgi_app, ProxyFix)

    def test_proxy_on_when_env_set(self, monkeypatch):
        monkeypatch.setenv("NPS_BEHIND_PROXY", "1")
        app = create_app({"TESTING": True})
        assert app.config["SESSION_COOKIE_SECURE"] is True
        assert app.config["SESSION_COOKIE_HTTPONLY"] is True
        assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
        assert app.config["PREFERRED_URL_SCHEME"] == "https"
        assert isinstance(app.wsgi_app, ProxyFix)


class TestSchedulerKillSwitch:
    @patch("app.services.auth_service.ensure_default_admin")
    @patch("app.services.nps_scheduler.init_scheduler")
    def test_scheduler_started_by_default(self, mock_init, _mock_admin):
        create_app()  # non-TESTING path
        assert mock_init.called

    @patch("app.services.auth_service.ensure_default_admin")
    @patch("app.services.nps_scheduler.init_scheduler")
    def test_scheduler_disabled_via_env(self, mock_init, _mock_admin, monkeypatch):
        monkeypatch.setenv("NPS_DISABLE_SCHEDULER", "1")
        create_app()  # non-TESTING path
        assert not mock_init.called


class TestAllowedHosts:
    def test_no_allowlist_permits_any_host(self):
        app = create_app({"TESTING": True})
        client = app.test_client()
        # Root has no route -> 404, but NOT 400 (host check absent)
        resp = client.get("/", headers={"Host": "evil.example.com"})
        assert resp.status_code != 400

    def test_allowlist_blocks_unknown_host(self, monkeypatch):
        monkeypatch.setenv("NPS_ALLOWED_HOSTS", "nps.aifa.amazon.dev")
        app = create_app({"TESTING": True})
        client = app.test_client()
        resp = client.get("/nps/dashboard", headers={"Host": "evil.example.com"})
        assert resp.status_code == 400

    def test_allowlist_permits_known_host(self, monkeypatch):
        monkeypatch.setenv("NPS_ALLOWED_HOSTS", "nps.aifa.amazon.dev")
        app = create_app({"TESTING": True})
        client = app.test_client()
        resp = client.get("/nps/dashboard", headers={"Host": "nps.aifa.amazon.dev"})
        assert resp.status_code != 400
