"""SLAB client — resolve Slack user IDs from Amazon aliases.

Purpose
-------
Replaces the Slack ``users.lookupByEmail`` call (which needs the high-risk
``users:read`` scope and drives the Red ASR) with SLAB's
``OpusUsersGetSlackIDFromAlias`` API. SLAB is an internal Amazon service,
so the lookup no longer needs the broad Slack directory scope and no
employee email is sent to Slack for resolution.

Per the SLAB KB (onboarding ticket D490668297, now closed):
- Auth: **SigV4a** (asymmetric) + an ``x-api-key`` header. SLAB is a
  multi-region active-active API Gateway behind latency-based DNS, so we
  sign with a region-set of ``*`` — the signature is valid at whichever
  regional gateway DNS routes us to (our EC2 is in ap-south-1, which may
  have no local SLAB deployment). This mirrors the boto3 ``opusslab`` SDK
  (``signature_version="v4a"`` / ``region="global"``). Requires ``awscrt``.
  Gamma and Prod issue DIFFERENT keys.
- ``OpusUsersGetSlackIDFromAlias`` needs NO appsec review (admin APIs do).
- Batch API: up to **600 aliases per invocation**. Aliases are
  case-insensitive; returned IDs are lowercase-keyed. Response carries an
  ``aliasToSlackIdMap`` list of ``{alias, slackId, isActive}`` objects,
  plus ``aliasesNotFound`` (definitive misses) and ``aliasesUnprocessed``
  (transient — safe to retry).

Endpoint (confirmed)
--------------------
The prod endpoint is fixed by OpusSLABClientConfig's coral-config
(``https://api.prod.slack-admin.enterprise-engineering.aws.dev``); the
Coral REST/JSON binding maps the method to ``/opus.users.getSlackIdFromAlias``.
All values below are env-overridable so a future change is CONFIG, not code.
"""

from __future__ import annotations

import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

MAX_ALIASES_PER_CALL = 600

# ── Config (override via env) ─────────────────────────────────────────
# Prod endpoint is fixed by OpusSLABClientConfig coral-config
# (OpusSLABProd.config → api.prod.slack-admin.enterprise-engineering.aws.dev).
# The Coral REST/JSON binding maps OpusUsersGetSlackIDFromAlias to the
# /opus.users.getSlackIdFromAlias path — so we hit that path directly.
DEFAULT_SLAB_ENDPOINT = (
    "https://api.prod.slack-admin.enterprise-engineering.aws.dev"
    "/opus.users.getSlackIdFromAlias"
)
# SigV4a region-set. "*" makes the signature valid at any regional gateway
# (SLAB is multi-region active-active behind latency-based DNS). SLAB is an
# API Gateway, so the SigV4 signing service name is "execute-api".
DEFAULT_SLAB_REGION = "*"
DEFAULT_SLAB_SERVICE_NAME = "execute-api"
DEFAULT_SLAB_API_KEY_SECRET_ID = "nps-survey/slab-api-key"
API_KEY_SECRET_KEY = "SLAB_API_KEY"

# Request field CONFIRMED from OpusSLABPythonSDK README: `userAliases`.
# Response field CONFIRMED from the OpusSLABModel Smithy contract: an
# `aliasToSlackIdMap` list of {alias, slackId, isActive} objects, plus the
# `aliasesNotFound` / `aliasesUnprocessed` string lists.
REQUEST_ALIASES_FIELD = "userAliases"
RESPONSE_RESULTS_FIELD = "aliasToSlackIdMap"
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
    # NB: do NOT fall back to _get_region() here — that returns the SLAB
    # SigV4a region-set ("*"), which is not a valid AWS region. Use an
    # explicit AWS region if provided, else let boto3 resolve it (env /
    # IMDS / config) — on EC2 that yields the instance region.
    region = (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "").strip()
    try:
        client = (
            boto3.client("secretsmanager", region_name=region)
            if region
            else boto3.client("secretsmanager")
        )
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
    """Build SigV4a-signed headers (instance-role creds) plus the API key.

    SLAB sits behind a multi-region active-active API Gateway with
    latency-based DNS, so we sign asymmetrically (SigV4a) with a region-set
    of "*": the signature is accepted at whichever regional gateway the
    request lands on. Needs ``awscrt`` (botocore's CRT signer) — the same
    dependency the boto3 ``opusslab`` SDK relies on for v4a.
    """
    from botocore.awsrequest import AWSRequest
    import boto3

    try:
        from botocore.crt.auth import CrtSigV4AsymAuth
    except ImportError as exc:  # pragma: no cover — awscrt is a runtime dep
        raise RuntimeError(
            "SigV4a signing needs the 'awscrt' package (pip install awscrt)"
        ) from exc

    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials available for SigV4a signing")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    aws_req = AWSRequest(method="POST", url=_get_endpoint(), data=body, headers=headers)
    CrtSigV4AsymAuth(credentials, _get_service_name(), _get_region()).add_auth(aws_req)
    return dict(aws_req.headers)


def _parse_results(data: dict) -> dict:
    """Normalize the SLAB success payload to a ``{alias: slack_id}`` map.

    The ``OpusUsersGetSlackIDFromAlias`` response carries an
    ``aliasToSlackIdMap`` list of ``{alias, slackId, isActive}`` objects
    (OpusSLABModel Smithy contract). Entries whose ``isActive`` is
    explicitly False are treated as not-found — an inactive user won't
    receive a DM anyway. A dict shape ({alias: id}) is tolerated defensively.
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
            if item.get("isActive") is False:
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
