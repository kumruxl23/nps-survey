"""SLAB client — resolve Slack user IDs from Amazon aliases.

Purpose
-------
Replaces the Slack ``users.lookupByEmail`` call (which needs the high-risk
``users:read`` scope and drives the Red ASR) with SLAB's
``OpusUsersGetSlackIDFromAlias`` API. SLAB is an internal Amazon service,
so the lookup no longer needs the broad Slack directory scope and no
employee email is sent to Slack for resolution.

Per the SLAB KB (ticket D490637982):
- Auth: SigV4 (IAM role with ``execute-api:Invoke``) + an ``x-api-key``
  header. Gamma and Prod issue DIFFERENT keys.
- ``OpusUsersGetSlackIDFromAlias`` needs NO appsec review (admin APIs do).
- Batch API: up to **600 aliases per invocation**. Aliases are
  case-insensitive; returned IDs are lowercase-keyed. Response includes
  ``ok`` (bool), ``aliasesNotFound`` (definitive misses), and
  ``aliasesUnprocessed`` (transient — safe to retry).

IMPORTANT — pending onboarding
------------------------------
The endpoint URL, SigV4 region, and the exact request/response FIELD
NAMES are confirmed from the OpusSLABClient Python docs / onboarding
ticket. They are env-overridable constants so finalizing is a CONFIG
change, not a code change. The success-results field name
(``RESPONSE_RESULTS_FIELD``) in particular MUST be confirmed. Alias
derivation, batching, signing, and error handling are final.
"""

from __future__ import annotations

import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

MAX_ALIASES_PER_CALL = 600

# ── Config (override via env; confirm real values at onboarding) ──────
DEFAULT_SLAB_ENDPOINT = ""  # MUST be set from onboarding (Gamma or Prod)
DEFAULT_SLAB_REGION = "us-east-1"
DEFAULT_SLAB_SERVICE_NAME = "execute-api"
DEFAULT_SLAB_API_KEY_SECRET_ID = "nps-survey/slab-api-key"
API_KEY_SECRET_KEY = "SLAB_API_KEY"

# Request/response field names — confirm from the Python client docs.
REQUEST_ALIASES_FIELD = "aliases"
RESPONSE_RESULTS_FIELD = "slackIds"          # map/list of resolved results
RESPONSE_NOT_FOUND_FIELD = "aliasesNotFound"
RESPONSE_UNPROCESSED_FIELD = "aliasesUnprocessed"

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


def _parse_results(data: dict) -> dict:
    """Normalize the SLAB success payload to a ``{alias: slack_id}`` map.

    Handles either a dict ({alias: id}) or a list of objects
    ([{"alias": a, "slackId": s}, ...]) under RESPONSE_RESULTS_FIELD,
    since the exact shape is confirmed at onboarding.
    """
    results = (data or {}).get(RESPONSE_RESULTS_FIELD)
    mapping: dict = {}
    if isinstance(results, dict):
        for alias, slack_id in results.items():
            if alias and slack_id:
                mapping[str(alias).strip().lower()] = str(slack_id)
    elif isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            alias = item.get("alias")
            slack_id = item.get("slackId") or item.get("slack_id") or item.get("id")
            if alias and slack_id:
                mapping[str(alias).strip().lower()] = str(slack_id)
    return mapping


def lookup_slack_ids_by_aliases(aliases: list[str]) -> dict:
    """Batch-resolve aliases to Slack IDs.

    Returns a ``{alias: slack_id}`` map (aliases lowercased) for those
    found. Aliases not present in the map were not found. Automatically
    de-duplicates and chunks to the 600-per-call limit.

    Raises:
        RuntimeError: config missing or a SLAB call failed hard.
    """
    # Normalize + dedupe, preserving nothing but valid aliases.
    normalized = []
    seen = set()
    for a in aliases or []:
        a = (a or "").strip().lower()
        if a and a not in seen:
            seen.add(a)
            normalized.append(a)
    if not normalized:
        return {}

    endpoint = _get_endpoint()
    if not endpoint:
        raise RuntimeError(
            "SLAB_ENDPOINT is not configured — set it from SLAB onboarding before use"
        )

    api_key = _load_api_key()
    resolved: dict = {}

    for start in range(0, len(normalized), MAX_ALIASES_PER_CALL):
        chunk = normalized[start:start + MAX_ALIASES_PER_CALL]
        body = json.dumps({REQUEST_ALIASES_FIELD: chunk})
        try:
            headers = _signed_headers(body, api_key)
            resp = requests.post(endpoint, data=body, headers=headers, timeout=30)
        except requests.RequestException as exc:
            raise RuntimeError(f"SLAB request failed: {exc}") from exc

        if resp.status_code >= 400:
            raise RuntimeError(f"SLAB error {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"SLAB returned non-JSON response: {exc}") from exc

        resolved.update(_parse_results(data))

        unprocessed = (data or {}).get(RESPONSE_UNPROCESSED_FIELD) or []
        if unprocessed:
            logger.warning(
                "SLAB returned %d unprocessed aliases (transient) — safe to retry later",
                len(unprocessed),
            )

    return resolved


def lookup_slack_id_by_alias(alias: str) -> str:
    """Resolve a single alias to a Slack ID (convenience wrapper).

    Raises:
        SlackUserNotFoundError: alias has no mapped Slack ID.
        RuntimeError: config missing or SLAB call failed.
    """
    alias = (alias or "").strip().lower()
    if not alias:
        raise SlackUserNotFoundError("Empty alias")

    resolved = lookup_slack_ids_by_aliases([alias])
    slack_id = resolved.get(alias)
    if not slack_id:
        raise SlackUserNotFoundError(f"No Slack ID mapped for alias: {alias}")
    return slack_id


def clear_caches() -> None:
    """Test helper — reset the in-memory API-key cache."""
    _api_key_cache["value"] = ""
