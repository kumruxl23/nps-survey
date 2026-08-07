"""Central access-resolution for the NPS tool (org + role + feedback scope).

Access is derived from TWO sources, manual grants winning over the live
directory:

1. **Manual grants (admin-managed)** — the ``__user__<alias>`` role record
   (``admin``) and the ``user_access`` list in the dashboard settings blob
   (``admin`` / ``viewer`` grants, optionally scoped to specific orgs and/or a
   single leader). These are authoritative and never expire.

2. **Live PAPI reporting (dynamic)** — when there is no manual grant, a person
   is classified by their PAPI *upward* supervisor chain against the configured
   per-org "head" alias (e.g. CPT IN → ``sakau``). A person is a **leader** when
   their manager IS a head; anyone whose chain passes through a leader is a
   viewer scoped to that leader's feedback. Because this is computed live on
   every login, a re-org that moves someone out from under a head automatically
   removes their access, and a new direct of a head becomes a leader on next
   login — no roster edit required.

Precedence between orgs is the configured order (CPT IN → CPT NA → FEC), so
Sandeep Kaur's own directs land in CPT IN even though she reports into the CPT
NA head. The head alias itself gets NO automatic access (their role is assigned
manually later).

Returns a normalized ``Access`` dict consumed by the auth layer (login gate),
the dashboard (visible orgs) and the feedback view (row scoping).
"""

import logging
import os
import time

logger = logging.getLogger(__name__)

# Short per-alias cache so re-validating access on every request stays cheap
# (bounds how long a revoked grant lingers to this TTL, per worker).
_CACHE: dict = {}
_CACHE_TTL = int(os.environ.get("NPS_ACCESS_CACHE_TTL", "60"))

# Minimum job level for AUTOMATIC (PAPI-derived) access. Manual admin grants
# bypass this. Overridable via env for future tuning.
MIN_AUTO_LEVEL = int(os.environ.get("NPS_MIN_LEADER_LEVEL", "5"))

# Default org "heads" in precedence order. Overridable via the ``org_heads``
# key in the dashboard settings blob (list of {"org_id", "head"}).
_DEFAULT_ORG_HEADS = [
    {"org_id": "whs_cpt_in", "head": "sakau"},
    {"org_id": "whs_cpt_na", "head": "mill"},
    {"org_id": "fec", "head": "terrickw"},
]


def _norm(alias: str) -> str:
    return (alias or "").strip().lower().split("@", 1)[0]


def get_org_heads() -> list[dict]:
    """Ordered [{org_id, head}] precedence list (settings override or default)."""
    try:
        from app.services import nps_settings_service
        heads = nps_settings_service.get_dashboard_settings().get("org_heads")
        if isinstance(heads, list) and heads:
            cleaned = [
                {"org_id": (h.get("org_id") or "").strip(),
                 "head": _norm(h.get("head"))}
                for h in heads
                if isinstance(h, dict) and h.get("org_id") and h.get("head")
            ]
            if cleaned:
                return cleaned
    except Exception:
        logger.exception("Failed to read org_heads from settings; using default")
    return list(_DEFAULT_ORG_HEADS)


def _active_org_ids() -> list[str]:
    from app.services import nps_org_config_service
    try:
        return [o.org_id for o in nps_org_config_service.list_active_orgs()]
    except Exception:
        logger.exception("Failed to list active orgs")
        return []


# ── manual grants ─────────────────────────────────────────────────────


def _user_access_grants(alias: str) -> list[dict]:
    """The ``user_access`` grants for this alias from the settings blob."""
    try:
        from app.services import nps_settings_service
        grants = nps_settings_service.get_dashboard_settings().get("user_access")
        if not isinstance(grants, list):
            return []
        return [g for g in grants if isinstance(g, dict) and _norm(g.get("alias")) == alias]
    except Exception:
        logger.exception("Failed to read user_access grants")
        return []


def _resolve_manual(alias: str) -> dict | None:
    """Access from manual grants (``__user__`` role + ``user_access`` blob).

    Returns an Access dict, or None when the person has no manual grant.
    """
    from app.services import auth_service

    active = _active_org_ids()

    # 1) An explicit server role record. Only 'admin' is treated as a
    #    full grant here; 'viewer'/'editor' records still need scoping,
    #    which the user_access blob provides.
    rec = None
    try:
        rec = auth_service.get_user(alias)
    except Exception:
        logger.exception("get_user failed for %s", alias)
    if rec and rec.get("role") == "admin":
        return _access("admin", active, active[0] if active else "", "", True, "manual")
    if rec and rec.get("role") == "editor":
        return _access("editor", active, active[0] if active else "", "", True, "manual")

    grants = _user_access_grants(alias)
    if not grants:
        # A bare 'viewer' __user__ record with no scoping grant (legacy manual
        # add): allow read of org metrics but NOT feedback (is_super=False,
        # no leader) — identifiable feedback requires an explicit grant.
        if rec and rec.get("role") == "viewer":
            return _access("viewer", active, active[0] if active else "", "", False, "manual")
        return None

    if any((g.get("access") or "") == "admin" for g in grants):
        return _access("admin", active, active[0] if active else "", "", True, "manual")

    # Viewer grants: union of org scopes; blank org == all orgs. A grant tied
    # to a single leader restricts feedback to that leader (not super).
    all_orgs = False
    orgs: list[str] = []
    leader = ""
    for g in grants:
        oid = (g.get("org_id") or "").strip()
        if not oid:
            all_orgs = True
        elif oid not in orgs:
            orgs.append(oid)
        if (g.get("leader") or "").strip():
            leader = g["leader"].strip()
    scoped = active if all_orgs else [o for o in orgs if o in active]
    # Super (sees all feedback in scope) unless the grant pins a single leader.
    is_super = not leader
    return _access("viewer", scoped, scoped[0] if scoped else "", leader, is_super, "manual")


# ── live PAPI reporting ────────────────────────────────────────────────


def _resolve_papi(alias: str) -> dict | None:
    """Access derived from the live PAPI supervisor chain, or None."""
    from app.services import papi_client

    if not papi_client.is_configured():
        return None
    try:
        emp = papi_client.get_employee(alias)
    except papi_client.PapiError:
        logger.warning("PAPI lookup failed for %s; denying auto access", alias)
        return None
    if not emp:
        return None

    manager = _norm(emp.get("manager_login"))
    chain = [_norm(c) for c in (emp.get("chain") or [])]
    ancestors = [alias] + chain            # self first, then upward
    active = set(_active_org_ids())

    heads = get_org_heads()
    # A head themselves gets NO automatic access in ANY org (their role is
    # assigned manually later). This must be checked globally, because a head
    # can report into another org's head (e.g. the CPT IN head reports to the
    # CPT NA head) and would otherwise be misclassified as that org's leader.
    if alias in {h["head"] for h in heads}:
        return None

    # Level gate: automatic access is for L5+ only. Anyone below (or with an
    # unknown level) is denied here — an admin can still grant them manually.
    level = emp.get("level")
    if not isinstance(level, int) or level < MIN_AUTO_LEVEL:
        logger.info("Denying auto access to %s: level=%r < L%d", alias, level, MIN_AUTO_LEVEL)
        return None

    for entry in heads:
        org_id, head = entry["org_id"], entry["head"]
        if org_id not in active:
            continue
        if head not in ancestors:
            continue
        # This person sits under `head` → they belong to `org_id`.
        if manager == head:
            leader_alias, is_leader = alias, True          # a direct == a leader
        else:
            # The leader is the direct-of-head ancestor: the entry just BELOW
            # the head in the chain.
            try:
                hi = chain.index(head)
            except ValueError:
                hi = -1
            leader_alias = chain[hi - 1] if hi >= 1 else alias
            is_leader = False
        leader_name = _leader_name(org_id, leader_alias)
        acc = _access("viewer", [org_id], org_id, leader_name, False, "papi")
        acc["is_leader"] = is_leader
        acc["leader_alias"] = leader_alias
        return acc
    return None


def _leader_name(org_id: str, leader_alias: str) -> str:
    """Display name for the resolved leader — roster first, then PAPI."""
    from app.services import nps_leader_service, papi_client

    try:
        for ld in nps_leader_service.list_leaders(org_id):
            if _norm(ld.get("alias")) == leader_alias:
                return (ld.get("name") or "").strip()
    except Exception:
        logger.exception("roster lookup failed for %s", leader_alias)
    try:
        emp = papi_client.get_employee(leader_alias)
        if emp:
            return (emp.get("name") or "").strip()
    except Exception:
        logger.exception("PAPI name lookup failed for %s", leader_alias)
    return ""


# ── public API ─────────────────────────────────────────────────────────


def _access(role, orgs, home_org, leader_name, is_super, source):
    return {
        "role": role,
        "orgs": list(orgs),
        "home_org": home_org,
        "leader_name": leader_name,
        "is_super": bool(is_super),
        "source": source,
        "is_leader": False,   # set by _resolve_papi for PAPI-derived leaders
        "leader_alias": "",
    }


def resolve_access(alias: str, use_cache: bool = True) -> dict | None:
    """Resolve a person's access. Manual grants win; else live PAPI.

    Returns an Access dict, or None when the person has no access at all.
    Results are briefly cached (``_CACHE_TTL`` seconds) so re-validating on
    each request is cheap; pass ``use_cache=False`` to force a fresh resolve.
    """
    alias = _norm(alias)
    if not alias:
        return None
    now = time.time()
    if use_cache:
        hit = _CACHE.get(alias)
        if hit and hit[1] > now:
            return hit[0]
    result = _resolve_manual(alias) or _resolve_papi(alias)
    _CACHE[alias] = (result, now + _CACHE_TTL)
    return result


def invalidate(alias: str = "") -> None:
    """Drop cached access for one alias (or all) — call after a grant change."""
    if alias:
        _CACHE.pop(_norm(alias), None)
    else:
        _CACHE.clear()
