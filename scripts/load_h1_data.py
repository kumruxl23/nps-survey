"""Load H1 2026 NPS data for CPT IN and FEC_Net from ASANA screenshots.

Run on EC2: AWS_DEFAULT_REGION=ap-south-1 python3.11 scripts/load_h1_data.py

This script:
1. Cleans up old test cycles/nominations/responses
2. Creates H1 2026 cycles for both orgs
3. Imports stakeholder nominations with leaders
4. Records NPS responses
"""

import os
import sys
import uuid

os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import (
    nps_cycle_repo, nps_nomination_repo, nps_response_repo,
    nps_delivery_failure_repo, nps_reminder_log_repo,
)
from app.db.models import Nomination, NpsResponse, SurveyCycle
from app.services import nps_org_config_service, nps_cycle_service
from app.services.nps_response_service import categorize_score


def clean_org_data(org_id):
    """Delete all cycles, nominations, responses for an org."""
    print(f"  Cleaning {org_id}...")
    cycles = nps_cycle_repo.list_cycles(org_id)
    for cycle in cycles:
        cid = cycle.cycle_id
        pk = f"{org_id}#{cid}"
        # Delete nominations
        noms = nps_nomination_repo.list_nominations(org_id, cid)
        for n in noms:
            nps_nomination_repo.delete_nomination(org_id, cid, n.email)
        # Delete responses
        resps = nps_response_repo.list_responses(org_id, cid)
        for r in resps:
            table = nps_response_repo._get_table()
            table.delete_item(Key={"org_id_cycle_id": pk, "response_id": r.response_id})
        # Delete cycle
        table = nps_cycle_repo._get_table()
        table.delete_item(Key={"org_id": org_id, "cycle_id": cid})
        print(f"    Deleted cycle {cid[:8]}... ({len(noms)} noms, {len(resps)} responses)")


def create_cycle(org_id, name, start, end):
    """Create a cycle directly (bypassing service validation for speed)."""
    cycle = SurveyCycle(
        org_id=org_id, cycle_id=str(uuid.uuid4()),
        start_date=start, end_date=end,
        status="active", reminder_mode="manual",
        cycle_name=name,
    )
    nps_cycle_repo.put_cycle(cycle)
    print(f"  Created cycle: {name} ({cycle.cycle_id[:8]}...)")
    return cycle.cycle_id


def add_nomination(org_id, cycle_id, leader, stakeholder, email=""):
    """Add a nomination."""
    if not email:
        email = stakeholder.lower().replace(" ", ".") + "@placeholder.com"
    nom = Nomination(
        org_id=org_id, cycle_id=cycle_id,
        email=email, name=stakeholder, leader=leader,
    )
    nps_nomination_repo.put_nomination(nom)


def record_response(org_id, cycle_id, leader, stakeholder, score, email=""):
    """Record a response and mark as responded."""
    if not email:
        email = stakeholder.lower().replace(" ", ".") + "@placeholder.com"
    category = categorize_score(score)
    resp = NpsResponse(
        org_id=org_id, cycle_id=cycle_id,
        response_id=str(uuid.uuid4()),
        nps_score=score, category=category, leader=leader,
    )
    nps_response_repo.put_response(resp)
    nps_nomination_repo.update_responded(org_id, cycle_id, email)


# ── CPT IN H1 2026 Data ──────────────────────────────────────────
CPT_IN_DATA = [
    # (leader, stakeholder, score)
    ("Abhishek Kumar Prasad", "Alex Kraemer", 10),
    ("Nidhi Bhagat", "Joseph Khalife", 9),
    ("Abhishek Kumar Prasad", "Francesco Raveggi", 9),
    ("Navjyot Bhatia", "S Rohit Kiran", 10),
    ("Abhishek Kumar Prasad", "Stephanie Filreis", 10),
    ("Indrajeet Roy", "Stephanie Filreis", 10),
    ("Abhishek Kumar Prasad", "Varsha Jaisalmeria", 9),
    ("Navjyot Bhatia", "Rohit Keshari", 9),
    ("Navjyot Bhatia", "Valentina Ferro", 9),
    ("Abhishek Kumar Prasad", "Erica Finlayson", 9),
    ("Indrajeet Roy", "Brian Butler", 9),
    ("Indrajeet Roy", "Michael Skros", 9),
    ("Indrajeet Roy", "Tiffany Welch", 10),
    ("Abhishek Kumar Prasad", "Alexey Kostesha", 9),
    ("Indrajeet Roy", "Alexey Kostesha", 6),
    ("Navjyot Bhatia", "Krzysztof Nawrocki", 9),
    ("Abhishek Kumar Prasad", "Michael Eisenschmidt", 9),
    ("Nidhi Bhagat", "Bill Rains", 10),
    ("Nidhi Bhagat", "Amy Spalding", 8),
    ("Indrajeet Roy", "Roopa Vaidy", 10),
    ("Indrajeet Roy", "Christophe Mestre", 10),
    ("Indrajeet Roy", "Marc Farhat", 10),
    ("Navjyot Bhatia", "Ravi Garg", 9),
    ("Abhishek Kumar Prasad", "Lukasz Pankowski", 10),
    ("Navjyot Bhatia", "Punreet Brar", 10),
    ("Abhas Rao", "Jenn Brown", 10),
    ("Nidhi Bhagat", "Tristan Hyde", 10),
    ("Abhishek Kumar Prasad", "Muzn Shaheen", 7),
    ("Indrajeet Roy", "Muzn Shaheen", 8),
    ("Abhas Rao", "Lukas Novak", 9),
    ("Abhas Rao", "Shimizu Shimpei", 7),
    ("Abhishek Kumar Prasad", "Louise Sellami", 9),
    ("Abhishek Kumar Prasad", "Katesh Karan", 10),
    ("Nidhi Bhagat", "Todd Pomerantz", 9),
    ("Nidhi Bhagat", "Morgan Browning", 9),
    ("Abhishek Kumar Prasad", "Rolf Wermers", 9),
    ("Navjyot Bhatia", "Sanna Kodiganti", 8),
    ("Nidhi Bhagat", "Sha Martin", 9),
    ("Abhishek Kumar Prasad", "Jens Barlogie", 10),
    ("Abhas Rao", "Karthik", 10),
    ("Indrajeet Roy", "Karthik", 10),
    ("Abhas Rao", "Tasseda Hocine", 8),
    ("Abhas Rao", "Hiroyuki Toyoshima", 9),
    ("Abhishek Kumar Prasad", "Serge", 9),
    ("Abhishek Kumar Prasad", "Abdul Salami", 10),
    ("Abhishek Kumar Prasad", "Nadeem Yamin Saifi", 9),
    ("Abhishek Kumar Prasad", "Ian Stites", 9),
    ("Nidhi Bhagat", "Beth Jimison", 10),
    ("Abhishek Kumar Prasad", "Wesley Gibson", 10),
    ("Nidhi Bhagat", "Jesse Ratliff", 10),
    ("Abhishek Kumar Prasad", "Ian Cohen", 10),
    ("Neha Rawat", "Elkan Polad", 10),
]

# ── FEC_Net H1 2026 Data ─────────────────────────────────────────
FEC_DATA = [
    ("Jay Dave", "Digna Vora", 8),
    ("Jay Dave", "Joy Goodman", 10),
    ("Jay Dave", "Sonia Maleky", 7),
    ("Ashwini Davangere", "John Christian", 9),
    ("Amanda Leon", "Michael Mascitelli", 10),
    ("Jay Dave", "Denise Lackey", 7),
    ("Jay Dave", "Giulia Botti", 9),
    ("Amanda Leon", "Subhashree Rengarajan", 9),
    ("Ashwini Davangere", "Dan Moore", 10),
    ("Jay Dave", "Keelin Benedicto", 10),
    ("Jay Dave", "Erik Brewer", 9),
    ("Jay Dave", "Tyler Reed", 10),
    ("Jay Dave", "Mike Samaroo", 10),
    ("Amanda Leon", "Dustin Schoffler", 9),
    ("Jay Dave", "Sarah Goldstein", 9),
    ("Amanda Leon", "Tim Johnson", 9),
    ("Amanda Leon", "John", 9),
    ("Jay Dave", "Abhinav Sidhu", 10),
    ("Jay Dave", "Hilda Padron", 10),
    ("Jay Dave", "Ravi Jayakumar", 7),
    ("Amanda Leon", "Sean Sutton", 3),
    ("Albert Fang", "Albert Fang", 7),
    ("Jay Dave", "Andres Carlos", 10),
]


def main():
    print("=" * 60)
    print("  Loading H1 2026 NPS Data")
    print("=" * 60)

    # Clean existing data
    print("\nStep 1: Cleaning old data...")
    clean_org_data("whs_cpt_in")
    clean_org_data("fec_net")

    # Create H1 2026 cycles
    print("\nStep 2: Creating H1 2026 cycles...")
    cpt_cycle = create_cycle("whs_cpt_in", "H1 2026", "2026-01-01", "2026-06-30")
    fec_cycle = create_cycle("fec_net", "H1 2026", "2026-01-01", "2026-06-30")

    # Load CPT IN data
    print(f"\nStep 3: Loading CPT IN data ({len(CPT_IN_DATA)} responses)...")
    for leader, stakeholder, score in CPT_IN_DATA:
        email = stakeholder.lower().replace(" ", ".") + "@amazon.com"
        add_nomination("whs_cpt_in", cpt_cycle, leader, stakeholder, email)
        record_response("whs_cpt_in", cpt_cycle, leader, stakeholder, score, email)

    # Count CPT IN stats
    p = sum(1 for _, _, s in CPT_IN_DATA if s >= 9)
    pa = sum(1 for _, _, s in CPT_IN_DATA if 7 <= s <= 8)
    d = sum(1 for _, _, s in CPT_IN_DATA if s <= 6)
    t = len(CPT_IN_DATA)
    nps = ((p - d) / t) * 100
    print(f"  CPT IN: {t} responses | P:{p} Pa:{pa} D:{d} | NPS: {nps:.1f}")

    # Load FEC data
    print(f"\nStep 4: Loading FEC_Net data ({len(FEC_DATA)} responses)...")
    for leader, stakeholder, score in FEC_DATA:
        email = stakeholder.lower().replace(" ", ".") + "@amazon.com"
        add_nomination("fec_net", fec_cycle, leader, stakeholder, email)
        record_response("fec_net", fec_cycle, leader, stakeholder, score, email)

    # Count FEC stats
    p2 = sum(1 for _, _, s in FEC_DATA if s >= 9)
    pa2 = sum(1 for _, _, s in FEC_DATA if 7 <= s <= 8)
    d2 = sum(1 for _, _, s in FEC_DATA if s <= 6)
    t2 = len(FEC_DATA)
    nps2 = ((p2 - d2) / t2) * 100
    print(f"  FEC_Net: {t2} responses | P:{p2} Pa:{pa2} D:{d2} | NPS: {nps2:.1f}")

    # Overall
    total = t + t2
    total_p = p + p2
    total_d = d + d2
    overall = ((total_p - total_d) / total) * 100
    print(f"\n  OVERALL: {total} responses | NPS: {overall:.1f}")
    print("\nDone! Check the dashboard.")


if __name__ == "__main__":
    main()
