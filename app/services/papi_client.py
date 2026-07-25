"""PAPI (People API) client — directory lookups for form prefill.

Resolves any Amazon alias to {name, title, manager_login} via PAPI's
``GET /v2/employee/login:{alias}`` using IAM Auth: the EC2 role assumes
the cross-account PAPI role (from UBX onboarding), then signs requests
with SigV4 (service=execute-api).

Entirely inert until BOTH env vars are set (see
docs/papi_onboarding_request.md):

    PAPI_ROLE_ARN  — IAMAuth_nps-survey_<region> role from onboarding
    PAPI_ENDPOINT  — https://papi.amazon.com (prod)

Only standard-tier attributes are requested (name, business title,
manager). No highly-confidential data.
"""

import datetime
import logging
import os

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 6
_SIGNING_REGION = os.environ.get("PAPI_SIGNING_REGION", "us-east-1")

# Cached assumed-role credentials (module-level; refreshed near expiry).
_cached_creds: dict = {}


class PapiError(RuntimeError):
    """PAPI call failed (auth, availability, or unexpected response)."""


def _enabled() -> bool:
    return bool(os.environ.get("PAPI_ROLE_ARN") and os.environ.get("PAPI_ENDPOINT"))


def _get_credentials() -> Credentials:
    """Assume the PAPI cross-account role, caching until near expiry."""
    global _cached_creds
    now = datetime.datetime.now(datetime.timezone.utc)
    if _cached_creds and _cached_creds["expiry"] > now + datetime.timedelta(minutes=5):
        c = _cached_creds
        return Credentials(c["key"], c["secret"], c["token"])

    resp = boto3.client("sts").assume_role(
        RoleArn=os.environ["PAPI_ROLE_ARN"],
        RoleSessionName="nps-survey-papi",
        DurationSeconds=3600,
    )
    creds = resp["Credentials"]
    _cached_creds = {
        "key": creds["AccessKeyId"],
        "secret": creds["SecretAccessKey"],
        "token": creds["SessionToken"],
        "expiry": creds["Expiration"],
    }
    return Credentials(_cached_creds["key"], _cached_creds["secret"], _cached_creds["token"])


def _signed_get(url: str) -> requests.Response:
    """GET with SigV4 (service=execute-api) using the assumed-role creds."""
    aws_req = AWSRequest(method="GET", url=url)
    SigV4Auth(_get_credentials(), "execute-api", _SIGNING_REGION).add_auth(aws_req)
    return requests.get(url, headers=dict(aws_req.headers), timeout=TIMEOUT_SECONDS)


def _parse_employee(data: dict) -> dict:
    """Normalize a PAPI employee payload to the fields the form needs.

    ``chain`` is the ordered upward supervisor chain (immediate manager
    first) as lowercase logins, from the ``supervisor-chain`` expand.
    """
    basic = data.get("basicInfo", data) or {}
    first = (basic.get("firstName") or "").strip()
    last = (basic.get("lastName") or "").strip()
    chain = [
        str(sup.get("login") or "").lower()
        for sup in (data.get("supervisorChain") or [])
        if sup.get("login")
    ]
    return {
        "login": (basic.get("login") or "").lower(),
        "name": f"{first} {last}".strip(),
        "title": basic.get("businessTitle") or "",
        "manager_login": str(basic.get("managerLogin") or "").lower(),
        "chain": chain,
    }


def get_employee(alias: str) -> dict | None:
    """Look up one employee by login, including their supervisor chain.

    Returns {login, name, title, manager_login, chain} or None for
    unknown aliases. Raises PapiError on transport/auth failures so
    callers can fall back to org-history prefill.
    """
    if not _enabled():
        raise PapiError("PAPI is not configured (PAPI_ROLE_ARN/PAPI_ENDPOINT)")
    alias = (alias or "").strip().lower().split("@", 1)[0]
    if not alias:
        return None

    endpoint = os.environ["PAPI_ENDPOINT"].rstrip("/")
    url = f"{endpoint}/v2/employee/login:{alias}?expand=supervisor-chain"
    try:
        resp = _signed_get(url)
    except requests.RequestException as exc:
        raise PapiError(f"PAPI request failed: {exc}") from exc

    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise PapiError(f"PAPI returned HTTP {resp.status_code}: {resp.text[:200]}")
    return _parse_employee(resp.json())


def resolve_leader_via_chain(org_id: str, alias: str, employee: dict | None = None) -> dict | None:
    """Find the org's leader within a person's span — single PAPI call.

    "Highest leader within the span": starting with the alias itself (a
    roster leader resolves to themselves), scan the upward supervisor
    chain; the FIRST roster member found is the leader. Returns
    {leader_name, leader_alias, hops} or None when the chain never meets
    the roster (person outside the org, or roster empty).

    Pass ``employee`` (from get_employee) to avoid a duplicate lookup.
    """
    from app.services import nps_leader_service

    roster = {
        leader["alias"]: leader["name"]
        for leader in nps_leader_service.list_leaders(org_id)
    }
    if not roster:
        return None

    current = (alias or "").strip().lower().split("@", 1)[0]
    if current in roster:
        return {"leader_name": roster[current], "leader_alias": current, "hops": 0}

    if employee is None:
        employee = get_employee(current)
    if not employee:
        return None
    for hop, login in enumerate(employee.get("chain", []), start=1):
        if login in roster:
            return {"leader_name": roster[login], "leader_alias": login, "hops": hop}
    return None


def is_configured() -> bool:
    """Public check used by the service layer to pick the prefill source."""
    return _enabled()
