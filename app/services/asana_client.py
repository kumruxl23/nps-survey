"""ASANA REST API wrapper using OAuth2 authentication.

Uses OAuth2 Authorization Code flow. Tokens are stored in DynamoDB
(NpsOrgConfig table as a system record) and auto-refreshed when expired.

Setup flow:
1. User visits /nps/auth/asana → redirected to ASANA login
2. ASANA redirects back to /nps/auth/callback with an auth code
3. App exchanges code for access_token + refresh_token
4. Tokens stored in DynamoDB, used for all API calls
5. When access_token expires, refresh_token is used to get a new one
"""

import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_TOKEN_URL = "https://app.asana.com/-/oauth_token"
ASANA_AUTHORIZE_URL = "https://app.asana.com/-/oauth_authorize"

# In-memory token cache (loaded from DynamoDB on first use)
_token_cache = {"access_token": "", "refresh_token": ""}


def _get_client_id() -> str:
    return os.environ.get("ASANA_CLIENT_ID", "")


def _get_client_secret() -> str:
    return os.environ.get("ASANA_CLIENT_SECRET", "")


def _get_redirect_uri() -> str:
    return os.environ.get("ASANA_REDIRECT_URI", "http://localhost:5000/nps/auth/callback")


def get_authorize_url() -> str:
    """Build the ASANA OAuth2 authorization URL for user redirect."""
    return (
        f"{ASANA_AUTHORIZE_URL}"
        f"?client_id={_get_client_id()}"
        f"&redirect_uri={_get_redirect_uri()}"
        f"&response_type=code"
    )


def exchange_code_for_token(code: str) -> dict:
    """Exchange an authorization code for access + refresh tokens.

    Args:
        code: The authorization code from ASANA callback.

    Returns:
        Dict with access_token, refresh_token, expires_in, etc.

    Raises:
        RuntimeError: If token exchange fails.
    """
    resp = requests.post(ASANA_TOKEN_URL, data={
        "grant_type": "authorization_code",
        "client_id": _get_client_id(),
        "client_secret": _get_client_secret(),
        "redirect_uri": _get_redirect_uri(),
        "code": code,
    }, timeout=30)

    if resp.status_code != 200:
        raise RuntimeError(f"Token exchange failed: {resp.status_code} {resp.text}")

    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["refresh_token"] = data["refresh_token"]

    # Persist tokens to DynamoDB
    _save_tokens(data["access_token"], data["refresh_token"])

    return data


def _refresh_access_token() -> str:
    """Use the refresh token to get a new access token.

    Returns:
        The new access token.

    Raises:
        RuntimeError: If refresh fails (user needs to re-authorize).
    """
    refresh_token = _token_cache.get("refresh_token") or _load_tokens().get("refresh_token", "")
    if not refresh_token:
        raise RuntimeError("No refresh token available. Please authorize at /nps/auth/asana")

    resp = requests.post(ASANA_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": _get_client_id(),
        "client_secret": _get_client_secret(),
        "refresh_token": refresh_token,
    }, timeout=30)

    if resp.status_code != 200:
        raise RuntimeError(f"Token refresh failed: {resp.status_code} {resp.text}. Re-authorize at /nps/auth/asana")

    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    if "refresh_token" in data:
        _token_cache["refresh_token"] = data["refresh_token"]

    _save_tokens(_token_cache["access_token"], _token_cache["refresh_token"])
    return data["access_token"]


def _save_tokens(access_token: str, refresh_token: str) -> None:
    """Persist OAuth tokens to DynamoDB (NpsOrgConfig table, system record)."""
    try:
        import boto3
        table_name = os.environ.get("NPS_ORG_CONFIG_TABLE", "NpsOrgConfig")
        table = boto3.resource("dynamodb").Table(table_name)
        table.put_item(Item={
            "org_id": "__asana_oauth__",
            "org_name": "ASANA OAuth Tokens (system)",
            "asana_project_gid": "",
            "asana_form_url": "",
            "custom_field_nps_score_gid": "",
            "custom_field_category_gid": "",
            "custom_field_org_name_gid": "",
            "is_active": False,
            "slack_bot_token": json.dumps({
                "access_token": access_token,
                "refresh_token": refresh_token,
            }),
        })
    except Exception:
        logger.exception("Failed to save ASANA OAuth tokens to DynamoDB")


def _load_tokens() -> dict:
    """Load OAuth tokens from DynamoDB."""
    try:
        import boto3
        table_name = os.environ.get("NPS_ORG_CONFIG_TABLE", "NpsOrgConfig")
        table = boto3.resource("dynamodb").Table(table_name)
        resp = table.get_item(Key={"org_id": "__asana_oauth__"})
        item = resp.get("Item")
        if item and item.get("slack_bot_token"):
            tokens = json.loads(item["slack_bot_token"])
            _token_cache["access_token"] = tokens.get("access_token", "")
            _token_cache["refresh_token"] = tokens.get("refresh_token", "")
            return tokens
    except Exception:
        logger.exception("Failed to load ASANA OAuth tokens from DynamoDB")
    return {}


def _get_access_token() -> str:
    """Get a valid access token, refreshing if needed."""
    if _token_cache.get("access_token"):
        return _token_cache["access_token"]

    # Try loading from DynamoDB
    tokens = _load_tokens()
    if tokens.get("access_token"):
        return tokens["access_token"]

    raise RuntimeError("ASANA not authorized. Please visit /nps/auth/asana to connect.")


def _get_headers() -> dict:
    """Return authorization headers using OAuth2 access token."""
    token = _get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _request_with_refresh(method: str, url: str, **kwargs) -> requests.Response:
    """Make an API request, auto-refreshing the token on 401."""
    headers = _get_headers()
    kwargs["headers"] = headers
    kwargs.setdefault("timeout", 30)

    resp = getattr(requests, method)(url, **kwargs)

    if resp.status_code == 401:
        # Token expired — refresh and retry once
        logger.info("ASANA token expired, refreshing...")
        new_token = _refresh_access_token()
        kwargs["headers"] = {
            "Authorization": f"Bearer {new_token}",
            "Content-Type": "application/json",
        }
        resp = getattr(requests, method)(url, **kwargs)

    return resp


# ── Public API functions ─────────────────────────────────────────


def get_task(task_gid: str) -> dict:
    """Fetch a single ASANA task by its GID."""
    url = f"{ASANA_BASE_URL}/tasks/{task_gid}"
    try:
        resp = _request_with_refresh("get", url)
        if resp.status_code == 200:
            return resp.json()["data"]
        raise RuntimeError(f"ASANA API error {resp.status_code}: {resp.text}")
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc


def update_task_custom_fields(task_gid: str, custom_fields: dict) -> dict:
    """Update custom fields on an existing ASANA task."""
    url = f"{ASANA_BASE_URL}/tasks/{task_gid}"
    payload = {"data": {"custom_fields": custom_fields}}
    try:
        resp = _request_with_refresh("put", url, json=payload)
        if resp.status_code == 200:
            return resp.json()["data"]
        raise RuntimeError(f"ASANA API error {resp.status_code}: {resp.text}")
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc


def create_task(project_gid: str, name: str, notes: str, custom_fields: dict) -> dict:
    """Create a new task in an existing ASANA project."""
    url = f"{ASANA_BASE_URL}/tasks"
    payload = {
        "data": {
            "projects": [project_gid],
            "name": name,
            "notes": notes,
            "custom_fields": custom_fields,
        }
    }
    try:
        resp = _request_with_refresh("post", url, json=payload)
        if resp.status_code == 201:
            return resp.json()["data"]
        raise RuntimeError(f"ASANA API error {resp.status_code}: {resp.text}")
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc


def register_webhook(resource_gid: str, target_url: str) -> dict:
    """Register a webhook on an ASANA resource."""
    url = f"{ASANA_BASE_URL}/webhooks"
    payload = {
        "data": {
            "resource": resource_gid,
            "target": target_url,
        }
    }
    try:
        resp = _request_with_refresh("post", url, json=payload)
        if resp.status_code == 201:
            return resp.json()["data"]
        raise RuntimeError(f"ASANA API error {resp.status_code}: {resp.text}")
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc


def get_project_custom_fields(project_gid: str) -> list[dict]:
    """Fetch all custom field settings for a project.

    Useful for discovering custom field GIDs during setup.
    """
    url = f"{ASANA_BASE_URL}/projects/{project_gid}/custom_field_settings"
    try:
        resp = _request_with_refresh("get", url)
        if resp.status_code == 200:
            return resp.json()["data"]
        raise RuntimeError(f"ASANA API error {resp.status_code}: {resp.text}")
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc


def is_authorized() -> bool:
    """Check if ASANA OAuth tokens are available."""
    try:
        _get_access_token()
        return True
    except RuntimeError:
        return False


def clear_tokens() -> None:
    """Clear cached tokens (for testing)."""
    _token_cache["access_token"] = ""
    _token_cache["refresh_token"] = ""
