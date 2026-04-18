"""Local development entry point with mocked AWS (no real AWS needed).

Usage:
    python run_local.py

Then open http://localhost:5000/nps/dashboard in your browser.
"""

import os
import uuid
import random

os.environ.setdefault("AWS_ACCESS_KEY_ID", "local-dev")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local-dev")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("GRAPH_CLIENT_ID", "local-dev")
os.environ.setdefault("GRAPH_CLIENT_SECRET", "local-dev")
os.environ.setdefault("GRAPH_TENANT_ID", "local-dev")
os.environ.setdefault("QUIP_API_TOKEN", "local-dev")
os.environ.setdefault("ASANA_PAT", "local-dev")
os.environ.setdefault("NPS_FROM_ADDRESS", "nps-survey@example.com")

from moto import mock_aws

mock = mock_aws()
mock.start()

from app import create_app

app = create_app()


def _generate_scores(count, promoter_pct, passive_pct, detractor_pct):
    promoters = round(count * promoter_pct / 100)
    passives = round(count * passive_pct / 100)
    detractors = count - promoters - passives
    scores = []
    for _ in range(promoters):
        scores.append(random.choice([9, 10]))
    for _ in range(passives):
        scores.append(random.choice([7, 8]))
    for _ in range(detractors):
        scores.append(random.choice([1, 2, 3, 4, 5, 6]))
    random.shuffle(scores)
    return scores


def _make_names(seed_str, count):
    first_names = [
        "Aarav", "Priya", "Rohan", "Sneha", "Vikram", "Ananya", "Karthik", "Divya",
        "Arjun", "Pooja", "Rahul", "Meera", "Siddharth", "Kavita", "Aditya", "Nisha",
        "Varun", "Swati", "Nikhil", "Ritu", "Amit", "Pallavi", "Suresh", "Lakshmi",
        "Gaurav", "Anjali", "Manish", "Deepa", "Rajesh", "Sunita", "Vivek", "Rekha",
        "Harsh", "Sonal", "Pranav", "Bhavna", "Tushar", "Jyoti", "Kunal", "Shweta",
        "Ashish", "Neelam", "Sachin", "Parul", "Mohit", "Isha", "Tarun", "Komal",
    ]
    last_names = [
        "Sharma", "Patel", "Singh", "Kumar", "Gupta", "Reddy", "Nair", "Joshi",
        "Verma", "Iyer", "Rao", "Mishra", "Pillai", "Desai", "Mehta", "Bhat",
        "Chopra", "Malhotra", "Srinivasan", "Kulkarni", "Menon", "Saxena", "Tiwari",
        "Agarwal", "Banerjee", "Chatterjee", "Das", "Ghosh", "Mukherjee", "Sen",
    ]
    random.seed(hash(seed_str) + count)
    names, used = [], set()
    for _ in range(count):
        while True:
            name = f"{random.choice(first_names)} {random.choice(last_names)}"
            if name not in used:
                used.add(name)
                names.append(name)
                break
    return names


def seed_demo_data():
    from app.services import nps_org_config_service, nps_cycle_service, nps_nomination_service
    from app.services import nps_response_service
    from app.db import nps_response_repo, nps_nomination_repo
    from app.db.models import NpsResponse

    random.seed(42)

    # ── WHS CPT IN ──────────────────────────────────────────────────
    print("\n  Creating WHS CPT IN org...")
    try:
        nps_org_config_service.add_org(
            org_id="whs_cpt_in",
            org_name="WHS CPT IN",
            asana_project_gid="proj_whs_cpt_in",
            asana_form_url="https://form.asana.com/?k=whs_cpt_in_nps",
            custom_field_nps_score_gid="cf_score_whs",
            custom_field_category_gid="cf_cat_whs",
            custom_field_org_name_gid="cf_org_whs",
        )
    except ValueError:
        pass

    # Q2 2025 cycle (current active)
    cycle = nps_cycle_service.create_cycle(
        "whs_cpt_in", "2025-04-01", "2025-06-30", cycle_name="Q2 2025"
    )
    cid = cycle.cycle_id
    print(f"  Created cycle: Q2 2025 ({cid[:8]}...)")

    # 6 leaders under Sandeep Kaur — directs from the org chart
    leaders = [
        {
            "name": "Abhas Rao",
            "stakeholders": 20,
            "responded": 20,  # ALL responded
            "promoter_pct": 72, "passive_pct": 16, "detractor_pct": 12,
        },
        {
            "name": "Abhishek Kumar Prasad",
            "stakeholders": 32,
            "responded": 25,
            "promoter_pct": 64, "passive_pct": 20, "detractor_pct": 16,
        },
        {
            "name": "Indrajeet Roy",
            "stakeholders": 12,
            "responded": 10,
            "promoter_pct": 80, "passive_pct": 10, "detractor_pct": 10,
        },
        {
            "name": "Navjyot Bhatia",
            "stakeholders": 45,
            "responded": 30,
            "promoter_pct": 53, "passive_pct": 27, "detractor_pct": 20,
        },
        {
            "name": "Neha Rawat",
            "stakeholders": 15,
            "responded": 8,
            "promoter_pct": 62, "passive_pct": 25, "detractor_pct": 13,
        },
        {
            "name": "Nidhi Bhagat",
            "stakeholders": 18,
            "responded": 12,
            "promoter_pct": 67, "passive_pct": 17, "detractor_pct": 16,
        },
    ]

    total_nom = total_resp = total_p = total_pa = total_d = 0

    print(f"\n  {'Leader':<28s} {'Nom':>4s} {'Resp':>5s} {'Pend':>5s}  {'P':>3s} {'Pa':>3s} {'D':>3s}  {'NPS':>6s}")
    print("  " + "-" * 72)

    for leader in leaders:
        lname = leader["name"]
        nom_count = leader["stakeholders"]
        resp_count = leader["responded"]

        names = _make_names(lname, nom_count)

        # Add nominations tagged with leader
        for name in names:
            email = name.lower().replace(" ", ".") + "@amazon.com"
            try:
                nps_nomination_service.add_stakeholder(
                    "whs_cpt_in", cid, name, email, leader=lname
                )
            except ValueError:
                pass

        # Generate scores
        scores = _generate_scores(
            resp_count, leader["promoter_pct"], leader["passive_pct"], leader["detractor_pct"]
        )

        p = sum(1 for s in scores if s >= 9)
        pa = sum(1 for s in scores if 7 <= s <= 8)
        d = sum(1 for s in scores if s <= 6)

        # Record responses tagged with leader
        for j, score in enumerate(scores):
            email = names[j].lower().replace(" ", ".") + "@amazon.com"
            category = nps_response_service.categorize_score(score)
            resp = NpsResponse(
                org_id="whs_cpt_in", cycle_id=cid,
                response_id=str(uuid.uuid4()),
                nps_score=score, category=category,
                leader=lname,
            )
            nps_response_repo.put_response(resp)
            nps_nomination_repo.update_responded("whs_cpt_in", cid, email)

        pending = nom_count - resp_count
        nps = ((p - d) / resp_count) * 100 if resp_count > 0 else 0
        print(f"  {lname:<28s} {nom_count:>4d} {resp_count:>5d} {pending:>5d}  {p:>3d} {pa:>3d} {d:>3d}  {nps:>+6.1f}")

        total_nom += nom_count
        total_resp += resp_count
        total_p += p
        total_pa += pa
        total_d += d

    overall_nps = ((total_p - total_d) / total_resp) * 100 if total_resp > 0 else 0
    print("  " + "-" * 72)
    print(f"  {'OVERALL':<28s} {total_nom:>4d} {total_resp:>5d} {total_nom - total_resp:>5d}  "
          f"{total_p:>3d} {total_pa:>3d} {total_d:>3d}  {overall_nps:>+6.1f}")
    print(f"\n  Response Rate: {total_resp/total_nom*100:.0f}%")

    # Also seed a closed Q1 2025 cycle with historical data
    print("\n  Seeding historical Q1 2025 cycle (closed)...")
    cycle_q1 = nps_cycle_service.create_cycle(
        "whs_cpt_in", "2025-01-01", "2025-03-31", cycle_name="Q1 2025"
    )
    cid_q1 = cycle_q1.cycle_id
    nps_cycle_service.close_cycle("whs_cpt_in", cid_q1)

    # Seed some historical responses for Q1 (simpler — just overall numbers)
    q1_scores = _generate_scores(90, 60, 22, 18)
    q1_names = _make_names("q1_historical", 100)
    for name in q1_names:
        email = name.lower().replace(" ", ".") + ".q1@amazon.com"
        try:
            nps_nomination_service.add_stakeholder("whs_cpt_in", cid_q1, name, email)
        except ValueError:
            pass
    for j, score in enumerate(q1_scores):
        email = q1_names[j].lower().replace(" ", ".") + ".q1@amazon.com"
        category = nps_response_service.categorize_score(score)
        resp = NpsResponse(
            org_id="whs_cpt_in", cycle_id=cid_q1,
            response_id=str(uuid.uuid4()),
            nps_score=score, category=category,
        )
        nps_response_repo.put_response(resp)
        nps_nomination_repo.update_responded("whs_cpt_in", cid_q1, email)
    print(f"  Q1 2025: 100 nominated, 90 responded (closed)")

    # ── RISC ────────────────────────────────────────────────────────
    print("\n  Creating RISC org (no active cycle, no data)...")
    try:
        nps_org_config_service.add_org(
            org_id="risc",
            org_name="RISC",
            asana_project_gid="proj_risc",
            asana_form_url="https://form.asana.com/?k=risc_nps",
            custom_field_nps_score_gid="cf_score_risc",
            custom_field_category_gid="cf_cat_risc",
            custom_field_org_name_gid="cf_org_risc",
        )
    except ValueError:
        pass
    print("  RISC org created — no cycles or data")


with app.app_context():
    print("\n" + "=" * 60)
    print("  Seeding realistic demo data...")
    print("=" * 60)
    seed_demo_data()
    print("\n  Done!")

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  NPS Survey Automation — Local Development Server")
    print("=" * 60)
    print()
    print("  Dashboard:    http://localhost:5000/nps/dashboard")
    print("  Orgs:         http://localhost:5000/nps/orgs/view")
    print("  Nominations:  http://localhost:5000/nps/nominations/view")
    print("  Cycles:       http://localhost:5000/nps/cycles/view")
    print()
    print("  Orgs: WHS CPT IN (with data), RISC (empty)")
    print("  Press Ctrl+C to stop")
    print()
    app.run(debug=False, port=5000)
