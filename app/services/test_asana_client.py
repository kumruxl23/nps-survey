"""Tests for the ASANA REST API client.

Covers both auth modes:
- PAT (Personal Access Token) — env var or Secrets Manager
- OAuth2 (Authorization Code with refresh) — fallback
"""

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import requests as req_lib

from app.services import asana_client
from app.services.asana_client import (
    ASANA_BASE_URL,
    auth_mode,
    create_task,
    generate_state,
    get_authorize_url,
    get_task,
    is_authorized,
    register_webhook,
    update_task_custom_fields,
)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Fresh client state per test, OAuth env defaults set."""
    monkeypatch.setenv("ASANA_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("ASANA_CLIENT_SECRET", "test-client-secret")
    # Make sure no PAT leaks in from the host environment
    monkeypatch.delenv("ASANA_PAT", raising=False)
    asana_client.clear_tokens()
    yield
    asana_client.clear_tokens()


# ── OAuth-mode fixture (used by the bulk of existing tests) ──────


@pytest.fixture
def oauth_token_loaded():
    """Pre-load fake OAuth tokens into the cache."""
    asana_client._token_cache["access_token"] = "fake-oauth-token"
    asana_client._token_cache["refresh_token"] = "fake-refresh-token"
    yield
    asana_client.clear_tokens()


# ── PAT-mode tests ───────────────────────────────────────────────


class TestPATResolution:
    def test_env_pat_takes_priority(self, monkeypatch):
        monkeypatch.setenv("ASANA_PAT", "env-pat-value")
        assert is_authorized() is True
        assert auth_mode() == "pat"

    def test_no_token_anywhere_means_unauthorized(self):
        assert is_authorized() is False
        assert auth_mode() == "none"

    def test_pat_used_in_request_headers(self, monkeypatch):
        monkeypatch.setenv("ASANA_PAT", "my-personal-token")
        with patch("app.services.asana_client.requests.get") as mock_get:
            mock_resp = MagicMock(status_code=200)
            mock_resp.json.return_value = {"data": {"gid": "123"}}
            mock_get.return_value = mock_resp
            get_task("123")
            headers = mock_get.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer my-personal-token"

    def test_pat_401_does_not_attempt_oauth_refresh(self, monkeypatch):
        """In PAT mode, a 401 means the PAT is bad — no refresh dance."""
        monkeypatch.setenv("ASANA_PAT", "revoked-pat")
        with patch("app.services.asana_client.requests.get") as mock_get, \
             patch("app.services.asana_client.requests.post") as mock_post:
            mock_get.return_value = MagicMock(status_code=401, text="Unauthorized")
            with pytest.raises(RuntimeError, match="401"):
                get_task("123")
            # Crucially: no token-refresh POST happened
            mock_post.assert_not_called()


class TestPATFromSecretsManager:
    def test_secrets_manager_json_format(self, monkeypatch):
        """Secret stored as JSON {"ASANA_PAT": "..."} is recognized."""
        fake_client = MagicMock()
        fake_client.get_secret_value.return_value = {
            "SecretString": '{"ASANA_PAT": "secret-pat-value"}'
        }
        with patch("boto3.client", return_value=fake_client):
            pat = asana_client._load_pat_from_secrets_manager()
        assert pat == "secret-pat-value"

    def test_secrets_manager_plain_string(self, monkeypatch):
        """Secret stored as a bare string is also accepted."""
        fake_client = MagicMock()
        fake_client.get_secret_value.return_value = {"SecretString": "raw-pat-string"}
        with patch("boto3.client", return_value=fake_client):
            pat = asana_client._load_pat_from_secrets_manager()
        assert pat == "raw-pat-string"

    def test_secrets_manager_failure_returns_empty(self, monkeypatch):
        """Any AWS error yields empty string — caller falls back."""
        fake_client = MagicMock()
        fake_client.get_secret_value.side_effect = Exception("AccessDenied")
        with patch("boto3.client", return_value=fake_client):
            pat = asana_client._load_pat_from_secrets_manager()
        assert pat == ""

    def test_secrets_manager_used_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("ASANA_PAT", raising=False)
        fake_client = MagicMock()
        fake_client.get_secret_value.return_value = {
            "SecretString": '{"ASANA_PAT": "from-secrets"}'
        }
        with patch("boto3.client", return_value=fake_client):
            assert is_authorized() is True
            assert auth_mode() == "pat"


# ── OAuth-mode tests (existing) ──────────────────────────────────


class TestGetTask:
    @patch("app.services.asana_client.requests.get")
    def test_successful_get(self, mock_get, oauth_token_loaded):
        task_data = {"gid": "123", "name": "My Task"}
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"data": task_data}
        mock_get.return_value = mock_resp
        assert get_task("123") == task_data

    @patch("app.services.asana_client.requests.get")
    def test_api_error_raises(self, mock_get, oauth_token_loaded):
        mock_get.return_value = MagicMock(status_code=404, text="Not Found")
        with pytest.raises(RuntimeError, match="404"):
            get_task("bad-gid")

    @patch("app.services.asana_client.requests.get")
    def test_request_exception_raises(self, mock_get, oauth_token_loaded):
        mock_get.side_effect = req_lib.RequestException("Connection refused")
        with pytest.raises(RuntimeError, match="Connection refused"):
            get_task("123")


class TestUpdateTaskCustomFields:
    @patch("app.services.asana_client.requests.put")
    def test_successful_update(self, mock_put, oauth_token_loaded):
        updated = {"gid": "123", "custom_fields": {"f1": "v1"}}
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"data": updated}
        mock_put.return_value = mock_resp
        assert update_task_custom_fields("123", {"f1": "v1"}) == updated

    @patch("app.services.asana_client.requests.put")
    def test_api_error_raises(self, mock_put, oauth_token_loaded):
        mock_put.return_value = MagicMock(status_code=400, text="Bad Request")
        with pytest.raises(RuntimeError, match="400"):
            update_task_custom_fields("123", {"f1": "v1"})


class TestCreateTask:
    @patch("app.services.asana_client.requests.post")
    def test_successful_create(self, mock_post, oauth_token_loaded):
        created = {"gid": "456", "name": "New Task"}
        mock_resp = MagicMock(status_code=201)
        mock_resp.json.return_value = {"data": created}
        mock_post.return_value = mock_resp
        assert create_task("proj-1", "New Task", "Notes", {"cf1": 9}) == created

    @patch("app.services.asana_client.requests.post")
    def test_api_error_raises(self, mock_post, oauth_token_loaded):
        mock_post.return_value = MagicMock(status_code=403, text="Forbidden")
        with pytest.raises(RuntimeError, match="403"):
            create_task("proj-1", "T", "N", {})


class TestRegisterWebhook:
    @patch("app.services.asana_client.requests.post")
    def test_successful_register(self, mock_post, oauth_token_loaded):
        webhook_data = {"gid": "wh-1"}
        mock_resp = MagicMock(status_code=201)
        mock_resp.json.return_value = {"data": webhook_data}
        mock_post.return_value = mock_resp
        assert register_webhook("proj-1", "https://example.com/webhook") == webhook_data

    @patch("app.services.asana_client.requests.post")
    def test_api_error_raises(self, mock_post, oauth_token_loaded):
        mock_post.return_value = MagicMock(status_code=500, text="Internal Server Error")
        with pytest.raises(RuntimeError, match="500"):
            register_webhook("proj-1", "https://example.com/webhook")


class TestOAuthTokenUsage:
    @patch("app.services.asana_client.requests.get")
    def test_uses_oauth_bearer_token(self, mock_get, oauth_token_loaded):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"data": {}}
        mock_get.return_value = mock_resp
        get_task("123")
        headers = mock_get.call_args.kwargs.get("headers")
        assert headers["Authorization"] == "Bearer fake-oauth-token"

    @patch("app.services.asana_client.requests.post")
    @patch("app.services.asana_client.requests.get")
    def test_auto_refreshes_on_401(self, mock_get, mock_post, oauth_token_loaded):
        """OAuth-mode 401 triggers a refresh + retry."""
        expired_resp = MagicMock(status_code=401)
        ok_resp = MagicMock(status_code=200)
        ok_resp.json.return_value = {"data": {"gid": "123"}}
        mock_get.side_effect = [expired_resp, ok_resp]

        refresh_resp = MagicMock(status_code=200)
        refresh_resp.json.return_value = {
            "access_token": "new-token",
            "refresh_token": "new-refresh",
        }
        mock_post.return_value = refresh_resp

        with patch("app.services.asana_client._save_tokens"):
            result = get_task("123")

        assert result == {"gid": "123"}
        assert mock_get.call_count == 2


# ── Authorize URL tests ──────────────────────────────────────────


class TestAuthorizeUrl:
    def test_generate_state_is_unique(self):
        assert generate_state() != generate_state()

    def test_authorize_url_includes_required_params(self, monkeypatch):
        monkeypatch.setenv("ASANA_REDIRECT_URI", "https://example.com/nps/auth/callback")
        url = get_authorize_url(state="abc123")
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        assert parsed.path.endswith("/oauth_authorize")
        assert qs["client_id"] == ["test-client-id"]
        assert qs["redirect_uri"] == ["https://example.com/nps/auth/callback"]
        assert qs["response_type"] == ["code"]
        assert qs["state"] == ["abc123"]

    def test_authorize_url_omits_state_when_empty(self):
        url = get_authorize_url()
        qs = parse_qs(urlparse(url).query)
        assert "state" not in qs
