"""Service layer for NPS stakeholder nomination management.

Delegates persistence to app.db.nps_nomination_repo and uses
app.services.quip_client for Quip spreadsheet imports.
"""

from app.db import nps_nomination_repo
from app.db.models import ImportResult, Nomination
from app.services import nps_leader_service, quip_client
from app.services.nomination_keys import (
    base_email,
    encode_for_leader,
    find_nomination_for_leader,
)


class DuplicateNominationError(ValueError):
    """Raised when a stakeholder is already nominated under the same leader.

    Carries the existing nomination so callers can tell the submitter who
    got there first (first-come-first-served rule).
    """

    def __init__(self, existing: Nomination):
        self.existing = existing
        nominator = existing.nominated_by or "someone"
        super().__init__(
            f"'{existing.name or base_email(existing.email)}' has already been "
            f"nominated under leader '{existing.leader}' by {nominator}"
        )


def import_from_quip(org_id: str, cycle_id: str, quip_doc_id: str) -> ImportResult:
    """Import stakeholder nominations from a Quip spreadsheet.

    Fetches the Quip document, parses name/email rows, and adds each
    nomination that doesn't already exist for this org/cycle.

    Returns an ImportResult with imported, skipped, and total counts.
    """
    spreadsheet = quip_client.get_spreadsheet(quip_doc_id)
    rows = quip_client.parse_nominations(spreadsheet)
    total_in_source = len(rows)

    imported_count = 0
    skipped_duplicates = 0

    for row in rows:
        name = row["name"]
        email = row["email"]

        existing = nps_nomination_repo.get_nomination(org_id, cycle_id, email)
        if existing is not None:
            skipped_duplicates += 1
            continue

        nomination = Nomination(
            org_id=org_id,
            cycle_id=cycle_id,
            email=email,
            name=name,
        )
        nps_nomination_repo.put_nomination(nomination)
        imported_count += 1

    return ImportResult(
        imported_count=imported_count,
        skipped_duplicates=skipped_duplicates,
        total_in_source=total_in_source,
    )


def add_stakeholder(org_id: str, cycle_id: str, name: str, email: str, leader: str = "") -> Nomination:
    """Manually add a single stakeholder nomination.

    Raises ValueError if the email already exists for this org/cycle.
    """
    existing = nps_nomination_repo.get_nomination(org_id, cycle_id, email)
    if existing is not None:
        raise ValueError(
            f"Stakeholder with email '{email}' is already nominated for "
            f"org '{org_id}' cycle '{cycle_id}'"
        )

    nomination = Nomination(
        org_id=org_id,
        cycle_id=cycle_id,
        email=email,
        name=name,
        leader=leader,
    )
    nps_nomination_repo.put_nomination(nomination)
    return nps_nomination_repo.get_nomination(org_id, cycle_id, email)


def remove_stakeholder(org_id: str, cycle_id: str, email: str) -> None:
    """Remove a stakeholder from the nomination list."""
    nps_nomination_repo.delete_nomination(org_id, cycle_id, email)


def list_nominations(org_id: str, cycle_id: str) -> list[Nomination]:
    """List all nominations for a given org and cycle."""
    return nps_nomination_repo.list_nominations(org_id, cycle_id)


def get_reminder_list(org_id: str, cycle_id: str) -> list[Nomination]:
    """Return only non-respondent nominations (the reminder list)."""
    return nps_nomination_repo.query_non_respondents(org_id, cycle_id)


# ---------------------------------------------------------------------------
# Self-serve leader nomination form (/nps/nominate)
# ---------------------------------------------------------------------------


def _alias_to_email(alias_or_email: str) -> str:
    """Normalize an Amazon alias (or full address) to a lowercase email."""
    value = (alias_or_email or "").strip().lower()
    if not value:
        return ""
    if "@" not in value:
        value = f"{value}@amazon.com"
    return value


def nominate_stakeholder(
    org_id: str,
    cycle_id: str,
    stakeholder_alias: str,
    name: str,
    leader: str,
    nominated_by: str,
    designation: str = "",
) -> Nomination:
    """Add a stakeholder nomination from the self-serve leader form.

    Enforces the first-come-first-served rule: a stakeholder may appear only
    once under a given leader per cycle (raises DuplicateNominationError with
    the existing row). The same stakeholder under a DIFFERENT leader is
    allowed — the row gets a ``#<leader>``-suffixed sort key via
    nomination_keys so distribution still dedups to one email/DM.
    """
    email = _alias_to_email(stakeholder_alias)
    name = (name or "").strip()
    leader = (leader or "").strip()
    nominated_by = (nominated_by or "").strip().lower().split("@", 1)[0]
    designation = (designation or "").strip()

    if not all([org_id, cycle_id, email, name, leader, nominated_by]):
        raise ValueError(
            "org_id, cycle_id, stakeholder alias, name, leader, and "
            "nominator alias are all required"
        )

    existing_rows = nps_nomination_repo.list_nominations(org_id, cycle_id)

    duplicate = find_nomination_for_leader(existing_rows, email, leader)
    if duplicate is not None:
        raise DuplicateNominationError(duplicate)

    taken_keys = {n.email for n in existing_rows}
    sort_key = encode_for_leader(email, leader, taken_keys)

    nomination = Nomination(
        org_id=org_id,
        cycle_id=cycle_id,
        email=sort_key,
        name=name,
        leader=leader,
        designation=designation,
        nominated_by=nominated_by,
    )
    nps_nomination_repo.put_nomination(nomination)
    return nps_nomination_repo.get_nomination(org_id, cycle_id, sort_key)


def _lookup_from_history(org_id: str, email: str) -> dict | None:
    """Newest-first search of nomination records for this email."""
    from app.db import nps_cycle_repo

    cycles = sorted(
        nps_cycle_repo.list_cycles(org_id),
        key=lambda c: c.start_date or "",
        reverse=True,
    )
    for cycle in cycles:
        for nomination in nps_nomination_repo.list_nominations(org_id, cycle.cycle_id):
            if base_email(nomination.email) == email:
                return {
                    "name": nomination.name,
                    "designation": nomination.designation,
                    "leader": nomination.leader,
                    "is_leader": False,
                    "source": f"history:{cycle.cycle_id}",
                }
    return None


def _lookup_from_papi(org_id: str, plain_alias: str) -> dict | None:
    """Directory lookup via PAPI + manager-chain leader resolution.

    Returns None when PAPI is unconfigured, unavailable, or the alias is
    unknown — callers fall through to history. A found employee whose
    chain never meets the org roster still returns name/title with an
    empty leader (the form asks for a manual pick).
    """
    from app.services import papi_client

    if not papi_client.is_configured():
        return None
    try:
        employee = papi_client.get_employee(plain_alias)
        if not employee:
            return None
        chain = papi_client.resolve_leader_via_chain(org_id, plain_alias, employee=employee)
        return {
            "name": employee["name"],
            "designation": employee["title"],
            "leader": chain["leader_name"] if chain else "",
            "is_leader": bool(chain and chain["hops"] == 0),
            "source": "papi",
        }
    except papi_client.PapiError as exc:
        # Directory down/misconfigured must never break the form.
        import logging
        logging.getLogger(__name__).warning("PAPI lookup failed, falling back: %s", exc)
        return None


def lookup_person(org_id: str, alias: str) -> dict | None:
    """Best-effort person lookup for form prefill.

    Sources, in order:
    1. The org's leader roster — if the alias IS a leader, their own name
       comes back as the leader (a leader nominating for themselves).
    2. PAPI directory (when onboarded/configured): any Amazon alias —
       name + business title, and the leader found by walking the
       manager chain up to the first person on the org's roster
       ("highest leader within the span").
    3. Nomination history (newest cycle first, incl. workbook imports).

    Returns {name, designation, leader, is_leader, source} or None when
    the alias is unknown everywhere.
    """
    email = _alias_to_email(alias)
    if not org_id or not email:
        return None
    plain_alias = email.split("@", 1)[0]

    roster = nps_leader_service.list_leaders(org_id)
    for leader_entry in roster:
        if leader_entry["alias"] == plain_alias:
            return {
                "name": leader_entry["name"],
                "designation": "",
                "leader": leader_entry["name"],
                "is_leader": True,
                "source": "roster",
            }

    papi_result = _lookup_from_papi(org_id, plain_alias)
    if papi_result:
        # History can still fill gaps PAPI leaves (e.g. leader when the
        # chain didn't meet the roster, or a self-reported designation).
        if not papi_result["leader"]:
            history = _lookup_from_history(org_id, email)
            if history and history["leader"]:
                papi_result["leader"] = history["leader"]
                papi_result["source"] = "papi+history"
        return papi_result

    return _lookup_from_history(org_id, email)


def list_nominations_for_leader(org_id: str, cycle_id: str, leader: str) -> list[Nomination]:
    """Return nominations under one leader for the given org/cycle."""
    leader = (leader or "").strip()
    return [
        n
        for n in nps_nomination_repo.list_nominations(org_id, cycle_id)
        if (n.leader or "").strip() == leader
    ]


def remove_leader_nomination(
    org_id: str,
    cycle_id: str,
    stakeholder_alias: str,
    leader: str,
    requested_by: str,
    is_privileged: bool = False,
) -> None:
    """Remove a form nomination, enforcing who may remove it.

    Allowed: privileged app roles (admin/editor), the person who submitted
    the nomination, or the leader it sits under (matched via the leader
    roster alias). Raises PermissionError otherwise; ValueError if the
    nomination doesn't exist.
    """
    email = _alias_to_email(stakeholder_alias)
    leader = (leader or "").strip()
    requester = (requested_by or "").strip().lower().split("@", 1)[0]

    rows = nps_nomination_repo.list_nominations(org_id, cycle_id)
    nomination = find_nomination_for_leader(rows, email, leader)
    if nomination is None:
        raise ValueError(
            f"No nomination found for '{email}' under leader '{leader}'"
        )

    allowed = is_privileged or (requester and requester == nomination.nominated_by)
    if not allowed and requester:
        # Scope the roster lookup to THIS org — otherwise a leader with the
        # same display name in another org could satisfy the check and remove
        # a nomination here (cross-org authorization gap). org_id is always
        # in scope; every other call site is already org-scoped.
        leader_entry = next(
            (l for l in nps_leader_service.list_leaders(org_id) if l["name"] == leader),
            None,
        )
        allowed = leader_entry is not None and leader_entry["alias"] == requester

    if not allowed:
        raise PermissionError(
            "Only an admin, the nominator, or the leader can remove this nomination"
        )

    nps_nomination_repo.delete_nomination(org_id, cycle_id, nomination.email)


# ---------------------------------------------------------------------------
# Nomination-form enhancements: per-leader counts, prior-cycle carry-forward,
# and bulk nomination (Sprint: dashboard/nominate visibility changes)
# ---------------------------------------------------------------------------


def count_nominations_by_leader(org_id: str, cycle_id: str) -> list[dict]:
    """Return [{leader, count}] for a cycle, one row per roster leader.

    Counts current-cycle nominations grouped by leader, and always includes
    every roster leader (0 if none yet). This is a COUNTS-ONLY view — it
    exposes no nominee/nominator identities, so it is safe to show to any
    viewer of the org's nomination page.
    """
    rows = nps_nomination_repo.list_nominations(org_id, cycle_id)
    counts: dict[str, int] = {}
    for n in rows:
        leader = (n.leader or "").strip()
        if leader:
            counts[leader] = counts.get(leader, 0) + 1
    # Ensure every active roster leader appears, even with zero nominations.
    for leader_entry in nps_leader_service.list_leaders(org_id):
        counts.setdefault(leader_entry["name"], 0)
    return sorted(
        ({"leader": leader, "count": count} for leader, count in counts.items()),
        key=lambda row: row["leader"].lower(),
    )


def _most_recent_closed_cycle(org_id: str):
    """Return the most recent CLOSED cycle for an org, or None."""
    from app.db import nps_cycle_repo

    closed = [c for c in nps_cycle_repo.list_cycles(org_id) if c.status == "closed"]
    if not closed:
        return None
    return sorted(closed, key=lambda c: c.start_date or "", reverse=True)[0]


def list_prior_cycle_responded(org_id: str, cycle_id: str, leader: str) -> dict:
    """Prior CLOSED cycle's stakeholders under a leader who RESPONDED.

    Non-respondents from the prior cycle are dropped. Each returned
    stakeholder is annotated with whether they are ALREADY nominated under
    the same leader in the current (``cycle_id``) cycle, and by whom — so
    the UI can disable "Add" and show the existing nominator on a duplicate.

    Returns:
        {prior_cycle_id, prior_cycle_name, stakeholders: [
            {email, name, designation, already_nominated, existing_nominated_by}
        ]}
    """
    leader = (leader or "").strip()
    prev = _most_recent_closed_cycle(org_id)
    if not prev:
        return {"prior_cycle_id": "", "prior_cycle_name": "", "stakeholders": []}

    # Current-cycle rows under this leader → for duplicate annotation.
    current_rows = nps_nomination_repo.list_nominations(org_id, cycle_id)

    stakeholders = []
    for n in nps_nomination_repo.list_nominations(org_id, prev.cycle_id):
        if (n.leader or "").strip() != leader:
            continue
        if not n.responded:
            continue  # only carry forward those who actually responded
        email = base_email(n.email)
        existing = find_nomination_for_leader(current_rows, email, leader)
        stakeholders.append({
            "email": email,
            "name": n.name,
            "designation": n.designation,
            "already_nominated": existing is not None,
            "existing_nominated_by": existing.nominated_by if existing else "",
        })
    stakeholders.sort(key=lambda s: (s["name"] or s["email"]).lower())
    return {
        "prior_cycle_id": prev.cycle_id,
        "prior_cycle_name": prev.cycle_name or prev.cycle_id,
        "stakeholders": stakeholders,
    }


def bulk_nominate_stakeholders(
    org_id: str,
    cycle_id: str,
    leader: str,
    nominated_by: str,
    stakeholders: list[dict],
) -> dict:
    """Nominate several stakeholders under one leader in a single call.

    ``leader`` is the nominator's already-resolved leader (never client
    chosen) and ``nominated_by`` is the server-side identity — both are
    passed straight through to :func:`nominate_stakeholder`, so every row
    is subject to the same first-come-first-served duplicate rule.

    Returns a per-row breakdown:
        {added: [{alias, name}],
         duplicates: [{alias, existing_nominated_by}],
         errors: [{alias, error}]}
    """
    added: list[dict] = []
    duplicates: list[dict] = []
    errors: list[dict] = []

    for item in stakeholders or []:
        alias = (item.get("stakeholder_alias") or "").strip()
        name = (item.get("name") or "").strip()
        # Bulk paste often supplies aliases only — backfill the name from the
        # directory/history so the row isn't rejected for a missing name.
        if alias and not name:
            person = lookup_person(org_id, alias)
            if person and person.get("name"):
                name = person["name"]
        try:
            nomination = nominate_stakeholder(
                org_id=org_id,
                cycle_id=cycle_id,
                stakeholder_alias=alias,
                name=name,
                leader=leader,
                nominated_by=nominated_by,
                designation=item.get("designation", ""),
            )
            added.append({
                "alias": base_email(nomination.email).split("@", 1)[0],
                "name": nomination.name,
            })
        except DuplicateNominationError as exc:
            duplicates.append({
                "alias": alias,
                "existing_nominated_by": exc.existing.nominated_by,
            })
        except ValueError as exc:
            errors.append({"alias": alias, "error": str(exc)})

    return {"added": added, "duplicates": duplicates, "errors": errors}
