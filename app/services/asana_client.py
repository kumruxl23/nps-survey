"""ASANA REST API wrapper.

Supports two authentication modes (resolved in priority order on each call):

1. **PAT (Personal Access Token)** — preferred for prod.
   Source priority:
     a. ``ASANA_PAT`` env var (used in dev, or as override in prod)
     b. AWS Secrets Manager (secret id from ``ASANA_PAT_SECRET_ID`` env
        var, default ``nps-survey/asana-pat``; key ``ASANA_PAT``)
   PATs are static, long-lived tokens issued from Asana's UI. No refresh
   dance needed.

2. **OAuth2 Authorization Code flow** — fallback / future use.
   Refresh tokens stored in DynamoDB (NpsOrgConfig table). Auto-refreshed
   on 401. Kept in the codebase so we can re-enable OAuth (e.g. multi-user
   flows) without re-implementing it.

The active mode is determined by ``_resolve_token()`` — the first source
that yields a non-empty token wins. PAT sources are checked first.

Setup notes:
- Prod: store PAT in Secrets Manager (``nps-survey/asana-pat`` → key
  ``ASANA_PAT``). The EC2 IAM role needs ``secretsmanager:GetSecretValue``
  on that ARN.
- Dev: set ``ASANA_PAT`` env var directly (skip Secrets Manager).
"""

import json
import logging
import os
import secrets
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_TOKEN_URL = "https://app.asana.com/-/oauth_token"
ASANA_AUTHORIZE_URL = "https://app.asana.com/-/oauth_authorize"

DEFAULT_PAT_SECRET_ID = "nps-survey/asana-pat"
PAT_SECRET_KEY = "ASANA_PAT"

# In-memory caches. Cleared via clear_tokens() (used in tests).
_token_cache = {"access_token": "", "refresh_token": ""}
_pat_cache: dict = {"value": "", "source": ""}


# ── Configuration accessors ──────────────────────────────────────


def _get_client_id() -> str:
    return os.environ.get("ASANA_CLIENT_ID", "")


def _get_client_secret() -> str:
    return os.environ.get("ASANA_CLIENT_SECRET", "")


def _get_redirect_uri() -> str:
    return os.environ.get("ASANA_REDIRECT_URI", "http://localhost:5000/nps/auth/callback")


def _get_pat_secret_id() -> str:
    return os.environ.get("ASANA_PAT_SECRET_ID", DEFAULT_PAT_SECRET_ID)


# ── PAT resolution ───────────────────────────────────────────────


def _load_pat_from_env() -> str:
    return os.environ.get("ASANA_PAT", "").strip()


def _load_pat_from_secrets_manager() -> str:
    """Fetch PAT from AWS Secrets Manager.

    Expects the secret to be a JSON map with key ``ASANA_PAT``. If the
    secret is a bare string, that string is treated as the PAT directly.

    Returns empty string on any failure (caller decides what to do).
    """
    try:
        import boto3
    except ImportError:  # pragma: no cover — boto3 is a runtime dep
        return ""

    secret_id = _get_pat_secret_id()
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-south-1"
    try:
        client = boto3.client("secretsmanager", region_name=region)
        resp = client.get_secret_value(SecretId=secret_id)
    except Exception as exc:
        logger.debug("Could not load PAT from Secrets Manager (%s): %s", secret_id, exc)
        return ""

    raw = resp.get("SecretString", "")
    if not raw:
        return ""

    # Try JSON first (the recommended shape: {"ASANA_PAT": "..."})
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            value = parsed.get(PAT_SECRET_KEY) or parsed.get("pat") or ""
            return str(value).strip()
    except json.JSONDecodeError:
        pass

    # Fall back to treating the whole secret string as the PAT
    return raw.strip()


def _resolve_pat() -> str:
    """Resolve a PAT from env var or Secrets Manager.

    Cached after first successful resolution to avoid hitting Secrets
    Manager on every API call.
    """
    if _pat_cache.get("value"):
        return _pat_cache["value"]

    pat = _load_pat_from_env()
    if pat:
        _pat_cache["value"] = pat
        _pat_cache["source"] = "env"
        return pat

    pat = _load_pat_from_secrets_manager()
    if pat:
        _pat_cache["value"] = pat
        _pat_cache["source"] = "secrets_manager"
        return pat

    return ""


# ── OAuth2 helpers (unchanged, kept for fallback / future re-enable) ──


def generate_state() -> str:
    """Generate a random CSRF ``state`` value for the OAuth flow."""
    return secrets.token_urlsafe(32)


def get_authorize_url(state: str = "") -> str:
    """Build the ASANA OAuth2 authorization URL for user redirect."""
    params = {
        "client_id": _get_client_id(),
        "redirect_uri": _get_redirect_uri(),
        "response_type": "code",
        "scope": "default",
    }
    if state:
        params["state"] = state
    return f"{ASANA_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    """Exchange an authorization code for access + refresh tokens (OAuth)."""
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
    _save_tokens(data["access_token"], data["refresh_token"])
    return data


def _refresh_access_token() -> str:
    """Use the refresh token to get a new access token (OAuth path)."""
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
        raise RuntimeError(
            f"Token refresh failed: {resp.status_code} {resp.text}. "
            "Re-authorize at /nps/auth/asana"
        )

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


# ── Unified token resolution ─────────────────────────────────────


def _resolve_token() -> tuple[str, str]:
    """Resolve a usable Asana token from any configured source.

    Returns:
        (token, mode) — mode is "pat" or "oauth"

    Raises:
        RuntimeError: if no token is available from any source.
    """
    pat = _resolve_pat()
    if pat:
        return pat, "pat"

    if _token_cache.get("access_token"):
        return _token_cache["access_token"], "oauth"

    tokens = _load_tokens()
    if tokens.get("access_token"):
        return tokens["access_token"], "oauth"

    raise RuntimeError(
        "ASANA not authorized. Set ASANA_PAT (or ASANA_PAT_SECRET_ID for "
        "Secrets Manager), or complete OAuth at /nps/auth/asana."
    )


def _get_headers() -> dict:
    """Return authorization headers using whichever auth mode is active."""
    token, _ = _resolve_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _request_with_refresh(method: str, url: str, **kwargs) -> requests.Response:
    """Make an API request.

    On 401 in OAuth mode, refresh the access token and retry once.
    In PAT mode a 401 is propagated — the PAT itself is invalid or
    revoked and only a human can fix it.
    """
    _, mode = _resolve_token()
    kwargs["headers"] = _get_headers()
    kwargs.setdefault("timeout", 30)

    resp = getattr(requests, method)(url, **kwargs)

    if resp.status_code == 401 and mode == "oauth":
        logger.info("ASANA OAuth token expired, refreshing...")
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
    payload = {"data": {"resource": resource_gid, "target": target_url}}
    try:
        resp = _request_with_refresh("post", url, json=payload)
        if resp.status_code == 201:
            return resp.json()["data"]
        raise RuntimeError(f"ASANA API error {resp.status_code}: {resp.text}")
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc


def get_project_custom_fields(project_gid: str) -> list[dict]:
    """Fetch all custom field settings for a project."""
    url = f"{ASANA_BASE_URL}/projects/{project_gid}/custom_field_settings"
    try:
        resp = _request_with_refresh("get", url)
        if resp.status_code == 200:
            return resp.json()["data"]
        raise RuntimeError(f"ASANA API error {resp.status_code}: {resp.text}")
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc


def list_tasks_in_project(project_gid: str, opt_fields: str | None = None) -> list[dict]:
    """List every task in an Asana project, paginating through all pages.

    Args:
        project_gid: Asana project GID.
        opt_fields: Comma-separated field names to include in each task. Pass
            something like "name,custom_fields,created_at,assignee.name" to
            avoid extra round-trips. Default keeps the response minimal.

    Returns:
        Flat list of task dicts (across all pages).
    """
    if opt_fields is None:
        opt_fields = "name,custom_fields,created_at,completed_at,assignee.name,assignee.email"

    url = f"{ASANA_BASE_URL}/projects/{project_gid}/tasks"
    return _paginate_get(url, opt_fields)


def list_sections(project_gid: str) -> list[dict]:
    """List sections in an Asana project."""
    url = f"{ASANA_BASE_URL}/projects/{project_gid}/sections"
    try:
        resp = _request_with_refresh("get", url, params={"limit": 100})
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc
    if resp.status_code != 200:
        raise RuntimeError(f"ASANA API error {resp.status_code}: {resp.text}")
    return resp.json().get("data", [])


def list_tasks_in_section(section_gid: str, opt_fields: str | None = None) -> list[dict]:
    """List every task in an Asana section, paginating through all pages.

    Use this instead of ``list_tasks_in_project`` when you only want tasks
    from a specific section (e.g. the "H1 2026" section, ignoring archived
    sections from previous cycles).
    """
    if opt_fields is None:
        opt_fields = "name,custom_fields,created_at,completed_at,assignee.name,assignee.email"

    url = f"{ASANA_BASE_URL}/sections/{section_gid}/tasks"
    return _paginate_get(url, opt_fields)


def _paginate_get(url: str, opt_fields: str) -> list[dict]:
    """Helper: paginate a GET that returns ``{data, next_page}`` envelopes."""
    params: dict[str, str | int] = {"opt_fields": opt_fields, "limit": 100}
    out: list[dict] = []
    while True:
        try:
            resp = _request_with_refresh("get", url, params=params)
        except requests.RequestException as exc:
            raise RuntimeError(f"Request failed: {exc}") from exc

        if resp.status_code != 200:
            raise RuntimeError(f"ASANA API error {resp.status_code}: {resp.text}")

        body = resp.json()
        out.extend(body.get("data", []))

        next_page = body.get("next_page")
        if not next_page or not next_page.get("offset"):
            break
        params["offset"] = next_page["offset"]
    return out


def is_authorized() -> bool:
    """Check if ASANA is authorized via any auth mode (PAT or OAuth)."""
    try:
        _resolve_token()
        return True
    except RuntimeError:
        return False


def auth_mode() -> str:
    """Return the current auth mode: ``pat``, ``oauth``, or ``none``."""
    try:
        _, mode = _resolve_token()
        return mode
    except RuntimeError:
        return "none"


def clear_tokens() -> None:
    """Clear cached tokens (for testing)."""
    _token_cache["access_token"] = ""
    _token_cache["refresh_token"] = ""
    _pat_cache["value"] = ""
    _pat_cache["source"] = ""
