"""Tests for the SLAB client (alias derivation + Slack ID lookup)."""

from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from app.services import slab_client
from app.services.slab_client import (
    SlackUserNotFoundError,
    alias_from_email,
    lookup_slack_id_by_alias,
)


class TestAliasFromEmail:
    def test_basic_amazon_email(self):
        assert alias_from_email("jdoe@amazon.com") == "jdoe"

    def test_uppercase_is_lowercased(self):
        assert alias_from_email("JDoe@amazon.com") == "jdoe"

    def test_strips_nomination_leader_suffix(self):
        # "email#leader" suffix used for shared stakeholders must not leak
        assert alias_from_email("jdoe@amazon.com#SomeLeader") == "jdoe"

    def test_whitespace_trimmed(self):
        assert alias_from_email("  jdoe@amazon.com  ") == "jdoe"

    def test_empty_returns_empty(self):
        assert alias_from_email("") == ""
        assert alias_from_email(None) == ""

    def test_non_amazon_domain_still_takes_local_part(self):
        assert alias_from_email("someone@example.com") == "someone"


class TestLookupSlackIdByAlias:
    def setup_method(self):
        slab_client.clear_caches()

    def test_empty_alias_raises_not_found(self):
        with pytest.raises(SlackUserNotFoundError):
            lookup_slack_id_by_alias("")

    def test_missing_endpoint_raises_runtime(self, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "")
        # DEFAULT_SLAB_ENDPOINT is also empty, so this must fail clearly
        with patch.object(slab_client, "DEFAULT_SLAB_ENDPOINT", ""):
            with pytest.raises(RuntimeError, match="SLAB_ENDPOINT"):
                lookup_slack_id_by_alias("jdoe")

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={"x-api-key": "k"})
    def test_successful_lookup(self, _mock_sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"slackId": "U12345"}
        mock_post.return_value = mock_resp

        assert lookup_slack_id_by_alias("jdoe") == "U12345"

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={})
    def test_404_raises_not_found(self, _mock_sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_post.return_value = mock_resp

        with pytest.raises(SlackUserNotFoundError):
            lookup_slack_id_by_alias("ghost")

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={})
    def test_server_error_raises_runtime(self, _mock_sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "internal error"
        mock_post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="500"):
            lookup_slack_id_by_alias("jdoe")

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={})
    def test_missing_slack_id_in_response_raises_not_found(self, _mock_sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_post.return_value = mock_resp

        with pytest.raises(SlackUserNotFoundError):
            lookup_slack_id_by_alias("jdoe")

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={})
    def test_request_exception_raises_runtime(self, _mock_sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_post.side_effect = req_lib.RequestException("timeout")

        with pytest.raises(RuntimeError, match="timeout"):
            lookup_slack_id_by_alias("jdoe")
