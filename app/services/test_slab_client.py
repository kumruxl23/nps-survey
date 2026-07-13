"""Tests for the SLAB client (alias derivation + batch Slack ID lookup)."""

from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from app.services import slab_client
from app.services.slab_client import (
    SlackUserNotFoundError,
    alias_from_email,
    lookup_slack_id_by_alias,
    lookup_slack_ids_by_aliases,
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


class TestLookupSlackIdsByAliases:
    def setup_method(self):
        slab_client.clear_caches()

    def test_empty_input_returns_empty(self):
        assert lookup_slack_ids_by_aliases([]) == {}

    def test_missing_endpoint_raises_runtime(self, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "")
        with patch.object(slab_client, "DEFAULT_SLAB_ENDPOINT", ""):
            with pytest.raises(RuntimeError, match="SLAB_ENDPOINT"):
                lookup_slack_ids_by_aliases(["jdoe"])

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={"x-api-key": "k"})
    def test_dict_results_shape(self, _sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "slackIds": {"jdoe": "U1", "asmith": "U2"}}
        mock_post.return_value = mock_resp

        result = lookup_slack_ids_by_aliases(["JDoe", "asmith"])
        assert result == {"jdoe": "U1", "asmith": "U2"}

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={})
    def test_list_results_shape(self, _sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": False,
            "slackIds": [{"alias": "jdoe", "slackId": "U1"}],
            "aliasesNotFound": ["ghost"],
        }
        mock_post.return_value = mock_resp

        result = lookup_slack_ids_by_aliases(["jdoe", "ghost"])
        assert result == {"jdoe": "U1"}

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={})
    def test_dedupe_and_normalize(self, _sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "slackIds": {"jdoe": "U1"}}
        mock_post.return_value = mock_resp

        lookup_slack_ids_by_aliases(["JDoe", "jdoe", "  JDOE "])
        # One chunk sent; body should carry a single deduped alias
        sent_body = mock_post.call_args.kwargs["data"]
        assert sent_body.count("jdoe") == 1

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={})
    def test_chunks_over_600(self, _sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "slackIds": {}}
        mock_post.return_value = mock_resp

        aliases = [f"user{i}" for i in range(1300)]
        lookup_slack_ids_by_aliases(aliases)
        # 1300 -> 600 + 600 + 100 = 3 calls
        assert mock_post.call_count == 3

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={})
    def test_server_error_raises_runtime(self, _sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "internal error"
        mock_post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="500"):
            lookup_slack_ids_by_aliases(["jdoe"])

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={})
    def test_request_exception_raises_runtime(self, _sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_post.side_effect = req_lib.RequestException("timeout")

        with pytest.raises(RuntimeError, match="timeout"):
            lookup_slack_ids_by_aliases(["jdoe"])


class TestLookupSlackIdByAlias:
    def setup_method(self):
        slab_client.clear_caches()

    def test_empty_alias_raises_not_found(self):
        with pytest.raises(SlackUserNotFoundError):
            lookup_slack_id_by_alias("")

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={})
    def test_single_success(self, _sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "slackIds": {"jdoe": "U12345"}}
        mock_post.return_value = mock_resp

        assert lookup_slack_id_by_alias("jdoe") == "U12345"

    @patch("app.services.slab_client.requests.post")
    @patch("app.services.slab_client._signed_headers", return_value={})
    def test_single_not_found_raises(self, _sign, mock_post, monkeypatch):
        monkeypatch.setenv("SLAB_ENDPOINT", "https://slab.example.aws/lookup")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": False, "slackIds": {}, "aliasesNotFound": ["ghost"]}
        mock_post.return_value = mock_resp

        with pytest.raises(SlackUserNotFoundError):
            lookup_slack_id_by_alias("ghost")
