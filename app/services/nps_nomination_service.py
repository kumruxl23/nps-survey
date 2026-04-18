"""Service layer for NPS stakeholder nomination management.

Delegates persistence to app.db.nps_nomination_repo and uses
app.services.quip_client for Quip spreadsheet imports.
"""

from app.db import nps_nomination_repo
from app.db.models import ImportResult, Nomination
from app.services import quip_client


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
