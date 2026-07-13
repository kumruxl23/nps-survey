"""SLAB client — resolve a Slack user ID from an Amazon alias.

Purpose
-------
This replaces the Slack ``users.lookupByEmail`` call (which requires the
high-risk ``users:read`` scope and drives the Red ASR) with SLAB's
``OpusUsersGetSlackIDFromAlias`` API. SLAB is an internal Amazon service,
so the lookup no longer needs the broad Slack directory scope and no
employee email is sent to Slack for resolution.

Auth: SigV4 (EC2 instance role credentials) + an API key.
Onboarding: request via AmazonUC-SIGNAL / OPUS (SLA ~7 days). See
``docs/slab_onboarding_request.md``.

IMPORTANT — pending onboarding
------------------------------
The exact endpoint, SigV4 service name, request field, and response
shape are confirmed during SLAB onboarding. They are defined here as
env-overridable constants so that finalizing the integration is a
CONFIG change, not a code change. The values below are best-effort
placeholders and MUST be verified against the SLAB onboarding docs
before enabling in production. Everything else (alias derivation,
signing, error handling) is final.
"""

from __future__ import annotations

import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

# ── Config (override via env; confirm real values at onboarding) ──────
#   SLAB_ENDPOINT          full URL of OpusUsersGetSlackIDFromAlias
#   SLAB_REGION            AWS region for SigV4 signing
#   SLAB_SERVICE_NAME      SigV4 service name (e.g. "execute-api")
#   SLAB_API_KEY_SECRET_ID Secrets Manager id holding the API key
DEFAULT_SLAB_ENDPOINT = ""  # MUST be set from onboarding
DEFAULT_SLAB_REGION = "us-east-1"
DEFAULT_SLAB_SERVICE_NAME = "execute-api"
DEFAULT_SLAB_API_KEY_SECRET_ID = "nps-survey/slab-api-key"
API_KEY_SECRET_KEY = "SLAB_API_KEY"

# Request/response field names — confirm at onboarding.
REQUEST_ALIAS_FIELD = "alias"
RESPONSE_SLACK_ID_FIELD = "slackId"

_api_key_cache: dict = {"value": ""}


class SlackUserNotFoundError(Exception):
    """Raised when SLAB cannot resolve a Slack ID for an alias."""


def alias_from_email(email: str) -> str:
    """Derive an Amazon alias from an email address.

    ``jdoe@amazon.com`` -> ``jdoe``. Also strips any nomination ``#leader``
    suffix defensively and lowercases. Returns "" for falsy input.
    """
    if not email:
        return ""
    local = email.split("#", 1)[0].strip().split("@", 1)[0]
    return local.strip().lower()


# ── Config accessors ──────────────────────────────────────────────────


def _get_endpoint() -> str:
    return os.environ.get("SLAB_ENDPOINT", DEFAULT_SLAB_ENDPOINT).strip()


def _get_region() -> str:
    return os.environ.get("SLAB_REGION", DEFAULT_SLAB_REGION).strip()


def _get_service_name() -> str:
    return os.environ.get("SLAB_SERVICE_NAME", DEFAULT_SLAB_SERVICE_NAME).strip()


def _get_api_key_secret_id() -> str:
    return os.environ.get("SLAB_API_KEY_SECRET_ID", DEFAULT_SLAB_API_KEY_SECRET_ID).strip()


def _load_api_key() -> str:
    """Resolve the SLAB API key from env or Secrets Manager (cached)."""
    if _api_key_cache.get("value"):
        return _api_key_cache["value"]

    env_key = os.environ.get("SLAB_API_KEY", "").strip()
    if env_key:
        _api_key_cache["value"] = env_key
        return env_key

    try:
        import boto3
    except ImportError:  # pragma: no cover — boto3 is a runtime dep
        return ""

    secret_id = _get_api_key_secret_id()
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or _get_region()
    try:
        client = boto3.client("secretsmanager", region_name=region)
        raw = client.get_secret_value(SecretId=secret_id).get("SecretString", "")
    except Exception as exc:
        logger.debug("Could not load SLAB API key from Secrets Manager (%s): %s", secret_id, exc)
        return ""

    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            value = parsed.get(API_KEY_SECRET_KEY) or parsed.get("api_key") or ""
            _api_key_cache["value"] = str(value).strip()
            return _api_key_cache["value"]
    except json.JSONDecodeError:
        pass
    _api_key_cache["value"] = raw.strip()
    return _api_key_cache["value"]


def _signed_headers(body: str, api_key: str) -> dict:
    """Build SigV4-signed headers (instance-role creds) plus the API key."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    import boto3

    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials available for SigV4 signing")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    aws_req = AWSRequest(method="POST", url=_get_endpoint(), data=body, headers=headers)
    SigV4Auth(credentials, _get_service_name(), _get_region()).add_auth(aws_req)
    return dict(aws_req.headers)


def lookup_slack_id_by_alias(alias: str) -> str:
    """Resolve a Slack user ID for an Amazon alias via SLAB.

    Raises:
        SlackUserNotFoundError: alias has no mapped Slack ID.
        RuntimeError: config missing or SLAB call failed.
    """
    alias = (alias or "").strip().lower()
    if not alias:
        raise SlackUserNotFoundError("Empty alias")

    endpoint = _get_endpoint()
    if not endpoint:
        raise RuntimeError(
            "SLAB_ENDPOINT is not configured — set it from SLAB onboarding before use"
        )

    body = json.dumps({REQUEST_ALIAS_FIELD: alias})
    try:
        headers = _signed_headers(body, _load_api_key())
        resp = requests.post(endpoint, data=body, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"SLAB request failed: {exc}") from exc

    if resp.status_code == 404:
        raise SlackUserNotFoundError(f"No Slack ID mapped for alias: {alias}")
    if resp.status_code >= 400:
        raise RuntimeError(f"SLAB error {resp.status_code}: {resp.text[:200]}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"SLAB returned non-JSON response: {exc}") from exc

    slack_id = (data or {}).get(RESPONSE_SLACK_ID_FIELD)
    if not slack_id:
        raise SlackUserNotFoundError(f"No Slack ID in SLAB response for alias: {alias}")
    return str(slack_id)


def clear_caches() -> None:
    """Test helper — reset the in-memory API-key cache."""
    _api_key_cache["value"] = ""
