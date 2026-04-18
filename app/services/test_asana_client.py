"""Tests for the ASANA REST API client (OAuth2 version)."""

from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from app.services import asana_client
from app.services.asana_client import (
    ASANA_BASE_URL,
    create_task,
    get_task,
    register_webhook,
    update_task_custom_fields,
)


@pytest.fixture(autouse=True)
def _asana_env(monkeypatch):
    monkeypatch.setenv("ASANA_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("ASANA_CLIENT_SECRET", "test-client-secret")
    # Pre-load a fake token into the cache
    asana_client._token_cache["access_token"] = "fake-oauth-token"
    asana_client._token_cache["refresh_token"] = "fake-refresh-token"
    yield
    asana_client.clear_tokens()


class TestGetTask:
    @patch("app.services.asana_client.requests.get")
    def test_successful_get(self, mock_get):
        task_data = {"gid": "123", "name": "My Task"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": task_data}
        mock_get.return_value = mock_resp

        result = get_task("123")
        assert result == task_data

    @patch("app.services.asana_client.requests.get")
    def test_api_error_raises(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_get.return_value = mock_resp

        with pytest.raises(RuntimeError, match="404"):
            get_task("bad-gid")

    @patch("app.services.asana_client.requests.get")
    def test_request_exception_raises(self, mock_get):
        mock_get.side_effect = req_lib.RequestException("Connection refused")
        with pytest.raises(RuntimeError, match="Connection refused"):
            get_task("123")


class TestUpdateTaskCustomFields:
    @patch("app.services.asana_client.requests.put")
    def test_successful_update(self, mock_put):
        updated = {"gid": "123", "custom_fields": {"f1": "v1"}}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": updated}
        mock_put.return_value = mock_resp

        result = update_task_custom_fields("123", {"f1": "v1"})
        assert result == updated

    @patch("app.services.asana_client.requests.put")
    def test_api_error_raises(self, mock_put):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        mock_put.return_value = mock_resp

        with pytest.raises(RuntimeError, match="400"):
            update_task_custom_fields("123", {"f1": "v1"})


class TestCreateTask:
    @patch("app.services.asana_client.requests.post")
    def test_successful_create(self, mock_post):
        created = {"gid": "456", "name": "New Task"}
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"data": created}
        mock_post.return_value = mock_resp

        result = create_task("proj-1", "New Task", "Notes", {"cf1": 9})
        assert result == created

    @patch("app.services.asana_client.requests.post")
    def test_api_error_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="403"):
            create_task("proj-1", "T", "N", {})


class TestRegisterWebhook:
    @patch("app.services.asana_client.requests.post")
    def test_successful_register(self, mock_post):
        webhook_data = {"gid": "wh-1"}
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"data": webhook_data}
        mock_post.return_value = mock_resp

        result = register_webhook("proj-1", "https://example.com/webhook")
        assert result == webhook_data

    @patch("app.services.asana_client.requests.post")
    def test_api_error_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="500"):
            register_webhook("proj-1", "https://example.com/webhook")


class TestOAuthTokenUsage:
    @patch("app.services.asana_client.requests.get")
    def test_uses_oauth_bearer_token(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {}}
        mock_get.return_value = mock_resp

        get_task("123")

        headers = mock_get.call_args.kwargs.get("headers")
        assert headers["Authorization"] == "Bearer fake-oauth-token"

    @patch("app.services.asana_client.requests.post")
    @patch("app.services.asana_client.requests.get")
    def test_auto_refreshes_on_401(self, mock_get, mock_post):
        # First call returns 401, refresh succeeds, retry succeeds
        expired_resp = MagicMock()
        expired_resp.status_code = 401

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"data": {"gid": "123"}}

        mock_get.side_effect = [expired_resp, ok_resp]

        # Mock the token refresh
        refresh_resp = MagicMock()
        refresh_resp.status_code = 200
        refresh_resp.json.return_value = {
            "access_token": "new-token",
            "refresh_token": "new-refresh",
        }
        mock_post.return_value = refresh_resp

        with patch("app.services.asana_client._save_tokens"):
            result = get_task("123")

        assert result == {"gid": "123"}
        assert mock_get.call_count == 2
