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
        leader_entry = next(
            (l for l in nps_leader_service.list_leaders() if l["name"] == leader),
            None,
        )
        allowed = leader_entry is not None and leader_entry["alias"] == requester

    if not allowed:
        raise PermissionError(
            "Only an admin, the nominator, or the leader can remove this nomination"
        )

    nps_nomination_repo.delete_nomination(org_id, cycle_id, nomination.email)
