"""Service layer for NPS response processing and categorization.

Handles webhook response processing, NPS score categorization,
and writing results to ASANA custom fields. Preserves stakeholder
anonymity by storing responses without email or name.
"""

import logging
import uuid
from datetime import datetime, timezone

from app.db import (
    nps_cycle_repo,
    nps_delivery_failure_repo,
    nps_nomination_repo,
    nps_response_repo,
)
from app.db.models import DeliveryFailure, Nomination, NpsResponse
from app.services import asana_client, nps_cycle_service, nps_org_config_service

logger = logging.getLogger(__name__)


def categorize_score(score: int) -> str:
    """Categorize an NPS score into Promoter, Passive, or Detractor.

    Args:
        score: Integer NPS score (0-10).

    Returns:
        'Promoter' for 9-10, 'Passive' for 7-8, 'Detractor' for 0-6.

    Raises:
        ValueError: If score is outside the 0-10 range.
    """
    if not (0 <= score <= 10):
        raise ValueError(f"NPS score must be between 0 and 10, got {score}")
    if score >= 9:
        return "Promoter"
    if score >= 7:
        return "Passive"
    return "Detractor"


def process_response(payload: dict) -> None:
    """Process a pre-parsed NPS survey response.

    Expects a dict with keys: email, nps_score, org_id, cycle_id, task_gid.

    Flow:
    1. Validate the cycle is active (reject closed cycles per Req 8.5)
    2. Match email against nominations for the active cycle
    3. If matched: mark responded, store anonymous NpsResponse, write ASANA custom fields
    4. If unmatched: log to NpsDeliveryFailures with event_type 'unmatched_response'

    Args:
        payload: Dict with email, nps_score, org_id, cycle_id, task_gid.

    Raises:
        ValueError: If required fields are missing, cycle not found, or cycle is closed.
    """
    email = payload.get("email")
    nps_score = payload.get("nps_score")
    org_id = payload.get("org_id")
    cycle_id = payload.get("cycle_id")
    task_gid = payload.get("task_gid")

    if not all([email, org_id, cycle_id, task_gid]) or nps_score is None:
        raise ValueError("Payload must include email, nps_score, org_id, cycle_id, and task_gid")

    # Validate score range
    if not (0 <= nps_score <= 10):
        raise ValueError(f"NPS score must be between 0 and 10, got {nps_score}")

    # Check cycle exists
    cycle = nps_cycle_repo.get_cycle(org_id, cycle_id)
    if cycle is None:
        raise ValueError(f"Cycle '{cycle_id}' not found for org '{org_id}'")

    # Reject responses for closed cycles (Req 8.5)
    if not nps_cycle_service.is_cycle_active(cycle):
        logger.warning(
            "Response rejected: cycle '%s' for org '%s' is closed. Email: %s",
            cycle_id, org_id, email,
        )
        raise ValueError(
            f"Cycle '{cycle_id}' for org '{org_id}' is closed. Late responses are not accepted."
        )

    # Match email against nominations
    nomination = nps_nomination_repo.get_nomination(org_id, cycle_id, email)

    if nomination is None:
        # Check if auto-add is enabled for this org
        org = nps_org_config_service.get_org(org_id)
        if org and org.auto_add_unmatched:
            # Auto-add the respondent to the nomination list
            logger.info(
                "Auto-adding unmatched respondent '%s' for org '%s' cycle '%s'",
                email, org_id, cycle_id,
            )
            nomination = Nomination(
                org_id=org_id,
                cycle_id=cycle_id,
                email=email,
                name=email.split("@")[0].replace(".", " ").title(),
                leader="",
            )
            nps_nomination_repo.put_nomination(nomination)
        else:
            # Log as unmatched response
            logger.warning(
                "Unmatched response email '%s' for org '%s' cycle '%s'",
                email, org_id, cycle_id,
            )
            failure = DeliveryFailure(
                org_id=org_id,
                cycle_id=cycle_id,
                failure_id=str(uuid.uuid4()),
                email=email,
                error_reason=f"Response from unmatched email: {email}",
                event_type="unmatched_response",
                channel="asana_webhook",
            )
            nps_delivery_failure_repo.put_failure(failure)
            return

    # Categorize the score
    category = categorize_score(nps_score)

    # Mark nomination as responded
    nps_nomination_repo.update_responded(org_id, cycle_id, email)

    # Store anonymous NpsResponse (no email/name)
    response = NpsResponse(
        org_id=org_id,
        cycle_id=cycle_id,
        response_id=str(uuid.uuid4()),
        nps_score=nps_score,
        category=category,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )
    nps_response_repo.put_response(response)

    # Write to ASANA custom fields
    org = nps_org_config_service.get_org(org_id)
    if org is not None:
        custom_fields = {
            org.custom_field_nps_score_gid: nps_score,
            org.custom_field_category_gid: category,
            org.custom_field_org_name_gid: org.org_name,
        }
        try:
            asana_client.update_task_custom_fields(task_gid, custom_fields)
        except RuntimeError:
            logger.exception(
                "Failed to write ASANA custom fields for task '%s' (org '%s')",
                task_gid, org_id,
            )


def get_responses(org_id: str, cycle_id: str) -> list[NpsResponse]:
    """Retrieve all NPS responses for a given org and cycle.

    Args:
        org_id: Organization identifier.
        cycle_id: Survey cycle identifier.

    Returns:
        List of NpsResponse records.
    """
    return nps_response_repo.list_responses(org_id, cycle_id)
