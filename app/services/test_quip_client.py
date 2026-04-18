"""Tests for the Quip API client."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.quip_client import (
    MalformedSpreadsheetError,
    QuipAPIError,
    get_spreadsheet,
    parse_nominations,
)


@pytest.fixture(autouse=True)
def _quip_env(monkeypatch):
    """Set required Quip API environment variable."""
    monkeypatch.setenv("QUIP_API_TOKEN", "test-quip-token")


# ---------------------------------------------------------------------------
# Helper to build a Quip-like spreadsheet response
# ---------------------------------------------------------------------------

def _make_spreadsheet_response(rows: list[list[str]], header: list[str] | None = None) -> dict:
    """Build a fake Quip API response with HTML table content."""
    if header is None:
        header = ["Name", "Email"]
    html_rows = ["<tr>" + "".join(f"<th>{h}</th>" for h in header) + "</tr>"]
    for row in rows:
        html_rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    html = "<table>" + "".join(html_rows) + "</table>"
    return {"html": html}


# ---------------------------------------------------------------------------
# get_spreadsheet tests
# ---------------------------------------------------------------------------

class TestGetSpreadsheet:
    @patch("app.services.quip_client.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"html": "<table></table>", "thread": {}}
        mock_get.return_value = mock_resp

        result = get_spreadsheet("ABC123")

        assert result == {"html": "<table></table>", "thread": {}}
        url = mock_get.call_args[0][0]
        assert url == "https://platform.quip.com/1/threads/ABC123"

    @patch("app.services.quip_client.requests.get")
    def test_authorization_header(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp

        get_spreadsheet("DOC1")

        headers = mock_get.call_args.kwargs.get("headers") or mock_get.call_args[1].get("headers")
        assert headers["Authorization"] == "Bearer test-quip-token"

    @patch("app.services.quip_client.requests.get")
    def test_404_raises_quip_api_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_get.return_value = mock_resp

        with pytest.raises(QuipAPIError) as exc_info:
            get_spreadsheet("INVALID_ID")

        assert exc_info.value.status_code == 404
        assert "INVALID_ID" in exc_info.value.message

    @patch("app.services.quip_client.requests.get")
    def test_500_raises_quip_api_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get.return_value = mock_resp

        with pytest.raises(QuipAPIError) as exc_info:
            get_spreadsheet("DOC1")

        assert exc_info.value.status_code == 500

    @patch("app.services.quip_client.time.sleep")
    @patch("app.services.quip_client.requests.get")
    def test_rate_limit_retries_then_succeeds(self, mock_get, mock_sleep):
        rate_resp = MagicMock()
        rate_resp.status_code = 429

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"html": "<table></table>"}

        mock_get.side_effect = [rate_resp, ok_resp]

        result = get_spreadsheet("DOC1")

        assert result == {"html": "<table></table>"}
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once_with(1)

    @patch("app.services.quip_client.time.sleep")
    @patch("app.services.quip_client.requests.get")
    def test_rate_limit_exhausts_retries(self, mock_get, mock_sleep):
        rate_resp = MagicMock()
        rate_resp.status_code = 429
        mock_get.return_value = rate_resp

        with pytest.raises(QuipAPIError) as exc_info:
            get_spreadsheet("DOC1")

        assert exc_info.value.status_code == 429
        assert mock_get.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("app.services.quip_client.time.sleep")
    @patch("app.services.quip_client.requests.get")
    def test_exponential_backoff_on_rate_limit(self, mock_get, mock_sleep):
        rate_resp = MagicMock()
        rate_resp.status_code = 429
        mock_get.return_value = rate_resp

        with pytest.raises(QuipAPIError):
            get_spreadsheet("DOC1")

        # Backoff: 1s, then 2s
        assert mock_sleep.call_args_list[0][0][0] == 1
        assert mock_sleep.call_args_list[1][0][0] == 2

    @patch("app.services.quip_client.time.sleep")
    @patch("app.services.quip_client.requests.get")
    def test_request_exception_retries(self, mock_get, mock_sleep):
        import requests as req_lib
        mock_get.side_effect = req_lib.RequestException("Connection error")

        with pytest.raises(QuipAPIError) as exc_info:
            get_spreadsheet("DOC1")

        assert "Connection error" in exc_info.value.message
        assert mock_get.call_count == 3


# ---------------------------------------------------------------------------
# parse_nominations tests
# ---------------------------------------------------------------------------

class TestParseNominations:
    def test_basic_parsing(self):
        spreadsheet = _make_spreadsheet_response([
            ["Alice", "[email protected]"],
            ["Bob", "[email protected]"],
        ])

        result = parse_nominations(spreadsheet)

        assert len(result) == 2
        assert result[0] == {"name": "Alice", "email": "[email protected]"}
        assert result[1] == {"name": "Bob", "email": "[email protected]"}

    def test_skips_header_row(self):
        spreadsheet = _make_spreadsheet_response([
            ["Jane", "[email protected]"],
        ])

        result = parse_nominations(spreadsheet)

        assert len(result) == 1
        assert result[0]["name"] == "Jane"

    def test_custom_column_indices(self):
        spreadsheet = _make_spreadsheet_response(
            [["dept", "[email protected]", "Charlie"]],
            header=["Department", "Email", "Name"],
        )

        result = parse_nominations(spreadsheet, name_column=2, email_column=1)

        assert len(result) == 1
        assert result[0] == {"name": "Charlie", "email": "[email protected]"}

    def test_empty_html_raises_error(self):
        with pytest.raises(MalformedSpreadsheetError, match="no HTML content"):
            parse_nominations({"html": ""})

    def test_missing_html_key_raises_error(self):
        with pytest.raises(MalformedSpreadsheetError, match="no HTML content"):
            parse_nominations({})

    def test_no_table_rows_raises_error(self):
        with pytest.raises(MalformedSpreadsheetError, match="No table rows"):
            parse_nominations({"html": "<div>No table here</div>"})

    def test_skips_rows_with_insufficient_columns(self):
        spreadsheet = _make_spreadsheet_response([
            ["Alice", "[email protected]"],
            ["OnlyName"],
            ["Bob", "[email protected]"],
        ])

        result = parse_nominations(spreadsheet)

        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Bob"

    def test_skips_empty_rows(self):
        spreadsheet = _make_spreadsheet_response([
            ["Alice", "[email protected]"],
            ["", ""],
            ["Bob", "[email protected]"],
        ])

        result = parse_nominations(spreadsheet)

        assert len(result) == 2

    def test_skips_rows_missing_email(self):
        spreadsheet = _make_spreadsheet_response([
            ["Alice", "[email protected]"],
            ["NoEmail", ""],
            ["Bob", "[email protected]"],
        ])

        result = parse_nominations(spreadsheet)

        assert len(result) == 2
        assert result[0]["email"] == "[email protected]"
        assert result[1]["email"] == "[email protected]"

    def test_strips_whitespace(self):
        spreadsheet = _make_spreadsheet_response([
            ["  Alice  ", "  [email protected]  "],
        ])

        result = parse_nominations(spreadsheet)

        assert result[0] == {"name": "Alice", "email": "[email protected]"}

    def test_header_only_returns_empty(self):
        """A spreadsheet with only a header row returns no nominations."""
        html = "<table><tr><th>Name</th><th>Email</th></tr></table>"
        result = parse_nominations({"html": html})
        assert result == []
