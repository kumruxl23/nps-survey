"""Bulk load H1 2026 NPS data for WHS CPT IN and FEC_Net.

Run on EC2: AWS_DEFAULT_REGION=ap-south-1 python3.11 scripts/load_h1_2026_data.py

This script:
1. Cleans up old test cycles/nominations/responses
2. Creates H1 2026 cycles for both orgs
3. Imports all nominations with leader tags
4. Records all NPS responses
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
from app.services import nps_cycle_service, nps_response_service

# ── WHS CPT IN data ──
CPT_IN_DATA = [
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

# ── FEC_Net data ──
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


def make_email(name):
    """Generate a placeholder email from a name."""
    return name.lower().replace(" ", ".") + "@amazon.com"


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
        print(f"    Deleted cycle {cid[:8]}... ({len(noms)} noms, {len(resps)} resps)")


def load_org_data(org_id, cycle_name, start_date, end_date, data):
    """Create cycle, nominations, and responses for an org."""
    print(f"\n  Loading {org_id} — {cycle_name}...")

    # Create cycle
    cycle = nps_cycle_service.create_cycle(org_id, start_date, end_date, cycle_name=cycle_name)
    cid = cycle.cycle_id
    print(f"    Created cycle: {cycle_name} ({cid[:8]}...)")

    # Track unique stakeholders (some appear under multiple leaders)
    seen_emails = set()
    nom_count = 0
    resp_count = 0

    for leader, stakeholder, score in data:
        email = make_email(stakeholder)

        # Add nomination (skip if already added under different leader)
        if email not in seen_emails:
            nom = Nomination(
                org_id=org_id, cycle_id=cid,
                email=email, name=stakeholder, leader=leader,
            )
            nps_nomination_repo.put_nomination(nom)
            seen_emails.add(email)
            nom_count += 1

        # Record response
        category = nps_response_service.categorize_score(score)
        resp = NpsResponse(
            org_id=org_id, cycle_id=cid,
            response_id=str(uuid.uuid4()),
            nps_score=score, category=category,
            leader=leader,
        )
        nps_response_repo.put_response(resp)

        # Mark as responded
        nps_nomination_repo.update_responded(org_id, cid, email)
        resp_count += 1

    # Calculate NPS
    scores = [d[2] for d in data]
    promoters = sum(1 for s in scores if s >= 9)
    passives = sum(1 for s in scores if 7 <= s <= 8)
    detractors = sum(1 for s in scores if s <= 6)
    total = len(scores)
    nps = ((promoters - detractors) / total) * 100 if total > 0 else 0

    print(f"    Nominations: {nom_count}")
    print(f"    Responses: {resp_count}")
    print(f"    Promoters: {promoters} | Passives: {passives} | Detractors: {detractors}")
    print(f"    NPS Score: {nps:.1f}")


if __name__ == "__main__":
    print("=" * 60)
    print("  Loading H1 2026 NPS Data")
    print("=" * 60)

    # Clean old data
    print("\nStep 1: Cleaning old test data...")
    clean_org_data("whs_cpt_in")
    clean_org_data("fec_net")

    # Load new data
    print("\nStep 2: Loading H1 2026 data...")
    load_org_data("whs_cpt_in", "H1 2026", "2026-01-01", "2026-06-30", CPT_IN_DATA)
    load_org_data("fec_net", "H1 2026", "2026-01-01", "2026-06-30", FEC_DATA)

    print("\n" + "=" * 60)
    print("  Done! Check the dashboard.")
    print("=" * 60)
