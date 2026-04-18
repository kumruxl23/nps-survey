"""Tests for the Slack Web API client."""

from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from app.db.models import SlackResult
from app.services.slack_client import (
    SlackUserNotFoundError,
    lookup_user_by_email,
    send_dm,
)


# ---------------------------------------------------------------------------
# lookup_user_by_email tests
# ---------------------------------------------------------------------------

class TestLookupUserByEmail:
    @patch("app.services.slack_client.requests.get")
    def test_successful_lookup(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": True,
            "user": {"id": "U12345"},
        }
        mock_get.return_value = mock_resp

        user_id = lookup_user_by_email("[email protected]", "xoxb-test-token")

        assert user_id == "U12345"
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["params"] == {"email": "[email protected]"}
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer xoxb-test-token"

    @patch("app.services.slack_client.requests.get")
    def test_user_not_found_raises(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False, "error": "users_not_found"}
        mock_get.return_value = mock_resp

        with pytest.raises(SlackUserNotFoundError, match="[email protected]"):
            lookup_user_by_email("[email protected]", "xoxb-token")

    @patch("app.services.slack_client.requests.get")
    def test_api_error_raises_runtime(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False, "error": "invalid_auth"}
        mock_get.return_value = mock_resp

        with pytest.raises(RuntimeError, match="invalid_auth"):
            lookup_user_by_email("[email protected]", "bad-token")

    @patch("app.services.slack_client.requests.get")
    def test_request_exception_raises_runtime(self, mock_get):
        mock_get.side_effect = req_lib.RequestException("Connection timeout")

        with pytest.raises(RuntimeError, match="Connection timeout"):
            lookup_user_by_email("[email protected]", "xoxb-token")

    @patch("app.services.slack_client.requests.get")
    def test_uses_correct_url(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "user": {"id": "U999"}}
        mock_get.return_value = mock_resp

        lookup_user_by_email("[email protected]", "xoxb-token")

        url = mock_get.call_args[0][0] if mock_get.call_args[0] else mock_get.call_args.kwargs.get("url")
        assert url == "https://slack.com/api/users.lookupByEmail"


# ---------------------------------------------------------------------------
# send_dm tests
# ---------------------------------------------------------------------------

class TestSendDm:
    @patch("app.services.slack_client.requests.post")
    def test_successful_dm(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "ts": "1234567890.123456"}
        mock_post.return_value = mock_resp

        result = send_dm("U12345", "Please complete the NPS survey", "xoxb-token")

        assert result == SlackResult(ok=True)
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["channel"] == "U12345"
        assert payload["text"] == "Please complete the NPS survey"

    @patch("app.services.slack_client.requests.post")
    def test_dm_api_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False, "error": "channel_not_found"}
        mock_post.return_value = mock_resp

        result = send_dm("U12345", "Hello", "xoxb-token")

        assert result.ok is False
        assert result.error == "channel_not_found"

    @patch("app.services.slack_client.requests.post")
    def test_dm_request_exception(self, mock_post):
        mock_post.side_effect = req_lib.RequestException("Connection refused")

        result = send_dm("U12345", "Hello", "xoxb-token")

        assert result.ok is False
        assert "Connection refused" in result.error

    @patch("app.services.slack_client.requests.post")
    def test_dm_uses_correct_url(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        send_dm("U12345", "msg", "xoxb-token")

        url = mock_post.call_args[0][0]
        assert url == "https://slack.com/api/chat.postMessage"

    @patch("app.services.slack_client.requests.post")
    def test_dm_authorization_header(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        send_dm("U12345", "msg", "xoxb-my-token")

        headers = mock_post.call_args.kwargs.get("headers") or mock_post.call_args[1].get("headers")
        assert headers["Authorization"] == "Bearer xoxb-my-token"

    @patch("app.services.slack_client.requests.post")
    def test_dm_unknown_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False}
        mock_post.return_value = mock_resp

        result = send_dm("U12345", "msg", "xoxb-token")

        assert result.ok is False
        assert result.error == "unknown_error"
