"""Service layer for NPS dashboard aggregation and score calculation.

Computes NPS scores, response rates, and per-cycle summaries for
leader-level dashboards. All calculations are org-partitioned.
"""

import logging

from app.db import nps_cycle_repo, nps_nomination_repo, nps_response_repo
from app.db.models import NpsSummary
from app.services.nps_response_service import categorize_score

logger = logging.getLogger(__name__)


def compute_nps(org_id: str, cycle_id: str) -> NpsSummary:
    """Calculate the NPS summary for a single org/cycle.

    NPS score formula: ((promoters - detractors) / total) * 100
    Response rate: total_responded / total_nominated (0 if no nominations)

    Args:
        org_id: Organization identifier.
        cycle_id: Survey cycle identifier.

    Returns:
        NpsSummary with counts, NPS score, and response rate.
    """
    responses = nps_response_repo.list_responses(org_id, cycle_id)
    nominations = nps_nomination_repo.list_nominations(org_id, cycle_id)

    promoter_count = 0
    passive_count = 0
    detractor_count = 0

    for resp in responses:
        category = categorize_score(resp.nps_score)
        if category == "Promoter":
            promoter_count += 1
        elif category == "Passive":
            passive_count += 1
        else:
            detractor_count += 1

    total_responded = promoter_count + passive_count + detractor_count
    total_nominated = len(nominations)

    if total_responded == 0:
        nps_score = 0.0
    else:
        nps_score = ((promoter_count - detractor_count) / total_responded) * 100

    if total_nominated == 0:
        response_rate = 0.0
    else:
        response_rate = total_responded / total_nominated

    return NpsSummary(
        org_id=org_id,
        cycle_id=cycle_id,
        total_nominated=total_nominated,
        total_responded=total_responded,
        promoter_count=promoter_count,
        passive_count=passive_count,
        detractor_count=detractor_count,
        nps_score=nps_score,
        response_rate=response_rate,
    )


def compute_nps_all_cycles(org_id: str) -> list[NpsSummary]:
    """Compute NPS summaries for all cycles of an org, for trend comparison.

    Args:
        org_id: Organization identifier.

    Returns:
        List of NpsSummary, one per cycle.
    """
    cycles = nps_cycle_repo.list_cycles(org_id)
    summaries = []
    for cycle in cycles:
        s = compute_nps(org_id, cycle.cycle_id)
        # Attach cycle_name for display
        s.cycle_name = getattr(cycle, "cycle_name", "") or f"{cycle.start_date} to {cycle.end_date}"
        summaries.append(s)
    return summaries


def compute_nps_by_leader(org_id: str, cycle_id: str) -> list[dict]:
    """Compute per-leader NPS breakdown for a given org/cycle.

    Groups responses by leader, calculates NPS score, counts, and
    response rate for each leader.

    Returns:
        List of dicts with leader name, counts, NPS score, and response rate.
    """
    responses = nps_response_repo.list_responses(org_id, cycle_id)
    nominations = nps_nomination_repo.list_nominations(org_id, cycle_id)

    # Group nominations by leader
    leader_nominations: dict[str, int] = {}
    leader_responded: dict[str, int] = {}
    for nom in nominations:
        leader = nom.leader or "Unassigned"
        leader_nominations[leader] = leader_nominations.get(leader, 0) + 1
        if nom.responded:
            leader_responded[leader] = leader_responded.get(leader, 0) + 1

    # Group responses by leader
    leader_scores: dict[str, list[int]] = {}
    for resp in responses:
        leader = resp.leader or "Unassigned"
        if leader not in leader_scores:
            leader_scores[leader] = []
        leader_scores[leader].append(resp.nps_score)

    # Build per-leader summaries
    all_leaders = sorted(set(list(leader_nominations.keys()) + list(leader_scores.keys())))
    result = []
    for leader in all_leaders:
        scores = leader_scores.get(leader, [])
        nominated = leader_nominations.get(leader, 0)
        responded = len(scores)
        pending = nominated - responded

        promoters = sum(1 for s in scores if s >= 9)
        passives = sum(1 for s in scores if 7 <= s <= 8)
        detractors = sum(1 for s in scores if s <= 6)

        if responded > 0:
            nps_score = ((promoters - detractors) / responded) * 100
            response_rate = responded / nominated if nominated > 0 else 0
        else:
            nps_score = 0.0
            response_rate = 0.0

        result.append({
            "leader": leader,
            "nominated": nominated,
            "responded": responded,
            "pending": pending,
            "promoter_count": promoters,
            "passive_count": passives,
            "detractor_count": detractors,
            "nps_score": round(nps_score, 1),
            "response_rate": round(response_rate, 4),
        })

    return result
