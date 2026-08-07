"""Tests for nps_access_service.resolve_access (manual + live-PAPI paths)."""

from unittest.mock import patch

import pytest

from app.services import nps_access_service as acc


class _Org:
    def __init__(self, org_id):
        self.org_id = org_id


_ACTIVE = [_Org("whs_cpt_in"), _Org("whs_cpt_na"), _Org("fec")]

_HEADS = [
    {"org_id": "whs_cpt_in", "head": "sakau"},
    {"org_id": "whs_cpt_na", "head": "mill"},
    {"org_id": "fec", "head": "terrickw"},
]


def _settings(user_access=None, org_heads=None):
    return {
        "user_access": user_access or [],
        "org_heads": org_heads if org_heads is not None else _HEADS,
    }


def _patches(settings=None, user=None, employees=None, papi_on=True, roster=None):
    """Context managers to stub every external dependency."""
    settings = settings if settings is not None else _settings()
    employees = employees or {}
    roster = roster or {}
    return [
        patch("app.services.nps_settings_service.get_dashboard_settings",
              return_value=settings),
        patch("app.services.nps_org_config_service.list_active_orgs",
              return_value=list(_ACTIVE)),
        patch("app.services.auth_service.get_user",
              side_effect=lambda a: user if (user and user_matches(user, a)) else None),
        patch("app.services.papi_client.is_configured", return_value=papi_on),
        patch("app.services.papi_client.get_employee",
              side_effect=lambda a: employees.get(a.lower())),
        patch("app.services.nps_leader_service.list_leaders",
              side_effect=lambda org_id="": roster.get(org_id, [])),
    ]


def user_matches(user, alias):
    return (user or {}).get("username", "").lower() == alias.lower().split("@")[0]


def _run(alias, **kw):
    acc.invalidate()          # tests reuse aliases; never serve a cached verdict
    ctxs = _patches(**kw)
    for c in ctxs:
        c.start()
    try:
        return acc.resolve_access(alias)
    finally:
        for c in reversed(ctxs):
            c.stop()


# ── manual grants ──────────────────────────────────────────────────────


def test_admin_user_record_is_full_admin():
    user = {"username": "kumruxl", "role": "admin", "display_name": "R"}
    r = _run("kumruxl", user=user)
    assert r["role"] == "admin"
    assert set(r["orgs"]) == {"whs_cpt_in", "whs_cpt_na", "fec"}
    assert r["is_super"] is True
    assert r["source"] == "manual"


def test_admin_grant_in_user_access_blob():
    s = _settings(user_access=[{"alias": "bob", "access": "admin", "org_id": "", "leader": ""}])
    r = _run("bob", settings=s)
    assert r["role"] == "admin" and r["is_super"] is True


def test_viewer_grant_single_org_is_super_in_that_org():
    s = _settings(user_access=[{"alias": "carol", "access": "viewer", "org_id": "whs_cpt_na", "leader": ""}])
    r = _run("carol", settings=s)
    assert r["role"] == "viewer"
    assert r["orgs"] == ["whs_cpt_na"]
    assert r["is_super"] is True          # no leader pin → sees all org feedback
    assert r["home_org"] == "whs_cpt_na"


def test_viewer_grant_with_leader_is_scoped():
    s = _settings(user_access=[{"alias": "dan", "access": "viewer", "org_id": "whs_cpt_in", "leader": "Abhishek Kumar Prasad"}])
    r = _run("dan", settings=s)
    assert r["role"] == "viewer"
    assert r["is_super"] is False
    assert r["leader_name"] == "Abhishek Kumar Prasad"


def test_viewer_grant_all_orgs_when_blank():
    s = _settings(user_access=[{"alias": "erin", "access": "viewer", "org_id": "", "leader": ""}])
    r = _run("erin", settings=s)
    assert set(r["orgs"]) == {"whs_cpt_in", "whs_cpt_na", "fec"}


def test_multiple_org_grants_union():
    s = _settings(user_access=[
        {"alias": "fin", "access": "viewer", "org_id": "whs_cpt_in", "leader": ""},
        {"alias": "fin", "access": "viewer", "org_id": "fec", "leader": ""},
    ])
    r = _run("fin", settings=s)
    assert set(r["orgs"]) == {"whs_cpt_in", "fec"}


# ── live PAPI ──────────────────────────────────────────────────────────


def test_direct_of_head_is_a_leader():
    emps = {"prsaab": {"login": "prsaab", "name": "Abhishek Kumar Prasad", "level": 7,
                       "manager_login": "sakau", "chain": ["sakau", "mill", "terrickw"]}}
    r = _run("prsaab", employees=emps)
    assert r["role"] == "viewer"
    assert r["orgs"] == ["whs_cpt_in"]
    assert r["is_leader"] is True
    assert r["leader_name"] == "Abhishek Kumar Prasad"
    assert r["is_super"] is False


def test_report_under_leader_maps_to_that_leader():
    emps = {
        "junior": {"login": "junior", "name": "Junior Dev", "level": 5,
                   "manager_login": "prsaab", "chain": ["prsaab", "sakau", "mill"]},
        "prsaab": {"login": "prsaab", "name": "Abhishek Kumar Prasad", "level": 7,
                   "manager_login": "sakau", "chain": ["sakau", "mill"]},
    }
    r = _run("junior", employees=emps)
    assert r["orgs"] == ["whs_cpt_in"]
    assert r["is_leader"] is False
    assert r["leader_name"] == "Abhishek Kumar Prasad"


def test_l4_report_is_denied():
    # An L4 reporting under a leader must NOT get automatic access.
    emps = {
        "l4dev": {"login": "l4dev", "name": "Elle Four", "level": 4,
                  "manager_login": "prsaab", "chain": ["prsaab", "sakau", "mill"]},
    }
    assert _run("l4dev", employees=emps) is None


def test_unknown_level_is_denied():
    emps = {"nolevel": {"login": "nolevel", "name": "No Level", "level": None,
                        "manager_login": "prsaab", "chain": ["prsaab", "sakau"]}}
    assert _run("nolevel", employees=emps) is None


def test_l4_can_be_granted_manually():
    # Manual grant bypasses the level gate.
    s = _settings(user_access=[{"alias": "l4dev", "access": "viewer", "org_id": "whs_cpt_in", "leader": ""}])
    r = _run("l4dev", settings=s)
    assert r["role"] == "viewer" and r["orgs"] == ["whs_cpt_in"]


def test_precedence_cpt_in_before_na_for_sandeeps_subtree():
    # A direct of sakau also has mill in their chain; CPT IN must win.
    emps = {"nsbhatia": {"login": "nsbhatia", "name": "Navjyot Bhatia", "level": 6,
                         "manager_login": "sakau", "chain": ["sakau", "mill", "terrickw"]}}
    r = _run("nsbhatia", employees=emps)
    assert r["orgs"] == ["whs_cpt_in"]


def test_cpt_na_direct_when_no_sakau_in_chain():
    emps = {"kraema": {"login": "kraema", "name": "Alexander Kraemer", "level": 7,
                       "manager_login": "mill", "chain": ["mill", "terrickw"]}}
    r = _run("kraema", employees=emps)
    assert r["orgs"] == ["whs_cpt_na"]
    assert r["is_leader"] is True


def test_head_gets_no_automatic_access():
    # Sandeep is the CPT IN head AND a direct of the CPT NA head (mill). She
    # must get NO automatic access anywhere (role assigned manually later).
    emps = {"sakau": {"login": "sakau", "name": "Sandeep Kaur", "level": 7,
                      "manager_login": "mill", "chain": ["mill", "terrickw"]}}
    r = _run("sakau", employees=emps)
    assert r is None


def test_head_with_manual_grant_still_works():
    # A head CAN be granted access manually (overrides the auto-exclusion).
    s = _settings(user_access=[{"alias": "sakau", "access": "admin", "org_id": "", "leader": ""}])
    r = _run("sakau", settings=s)
    assert r["role"] == "admin"


def test_outside_all_orgs_has_no_access():
    emps = {"stranger": {"login": "stranger", "name": "Str Anger", "level": 6,
                         "manager_login": "someoneelse", "chain": ["someoneelse", "ceo"]}}
    r = _run("stranger", employees=emps)
    assert r is None


def test_papi_disabled_and_no_manual_denies():
    r = _run("whoever", papi_on=False)
    assert r is None


def test_empty_alias_denies():
    assert acc.resolve_access("") is None
