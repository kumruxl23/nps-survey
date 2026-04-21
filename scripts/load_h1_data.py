"""Load H1 2026 NPS data for CPT IN and FEC_Net.

Run on EC2: AWS_DEFAULT_REGION=ap-south-1 python3.11 scripts/load_h1_data.py
"""
import os, sys, uuid
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import nps_cycle_repo, nps_nomination_repo, nps_response_repo
from app.db.models import Nomination, NpsResponse, SurveyCycle
from app.services.nps_response_service import categorize_score

LEADER_MAP = {
    "raabhas": "Abhas Rao",
    "prsaab": "Abhishek Kumar Prasad",
    "royindr": "Indrajeet Roy",
    "nsbhatia": "Navjyot Bhatia",
    "bhanidhi": "Nidhi Bhagat",
    "nehrwt": "Neha Rawat",
}

# Full CPT IN nominations from Excel (alias, stakeholder, stakeholder_alias)
CPT_IN_NOMINATIONS = [
    ("raabhas", "Hiroyuki Toyoshima", "toyoshiv"),
    ("raabhas", "Jenn Brown", "jennbr"),
    ("raabhas", "Hocine Tasseda", "hocint"),
    ("raabhas", "Lukas Novak", "novakln"),
    ("raabhas", "Shimpei Shimizu", "sshimizu"),
    ("raabhas", "Karthik S Rao", "karthrao"),
    ("prsaab", "Varsha Jaisalmeria", "vjaisalm"),
    ("prsaab", "Alexander Kraemer", "kraema"),
    ("prsaab", "Wesley Gibson", "gibswesl"),
    ("prsaab", "Regner-Zimparow, Katarzyna", "regnerk"),
    ("prsaab", "Will Bond", "willbond"),
    ("prsaab", "Miguel Torres-Morales", "migueltm"),
    ("prsaab", "Ian Cohen", "imcohen"),
    ("prsaab", "Lukasz Pankowski", "lukapan"),
    ("prsaab", "Joseph Neel", "josneel"),
    ("prsaab", "William Paige", "mrquaid"),
    ("prsaab", "Lizzie Donald", "lombarde"),
    ("prsaab", "Ian Stities", "issti"),
    ("prsaab", "Abdul Salami", "absalami"),
    ("prsaab", "Meghan Fitzgerald", "meghaf"),
    ("prsaab", "Justin Barstow", "jbars"),
    ("prsaab", "Nadeem Yamin Saifi", "nadeemys"),
    ("prsaab", "Malik Awan", "mmuawan"),
    ("prsaab", "Greg Williams", "grewilli"),
    ("prsaab", "Francesco Raveggi", "raveggif"),
    ("prsaab", "Michael Eisenschmidt", "michschm"),
    ("prsaab", "Serge Kwasniewski", "kwaserge"),
    ("prsaab", "Rolf Wermers", "rwermers"),
    ("prsaab", "Jens Barlogie", "jbarlog"),
    ("prsaab", "Erica Finlayson", "effinlay"),
    ("prsaab", "Katesh Karan J", "jkateshk"),
    ("prsaab", "Alexey Kostesha", "kostesha"),
    ("prsaab", "Louise Sellami", "lsellami"),
    ("prsaab", "Muzn Shaheen", "muzns"),
    ("royindr", "Brian Butler", "bribut"),
    ("royindr", "Alexey Kostesha", "kostesha"),
    ("royindr", "Louise Sellami", "lsellami"),
    ("royindr", "Filreis, Stephanie", "filreiss"),
    ("royindr", "Hibbard, Melissa", "mhibbard"),
    ("royindr", "Christophe Mestre", "mestrecm"),
    ("royindr", "Tiffany Welch", "tifwelch"),
    ("royindr", "Michael Skros", "mpskros"),
    ("royindr", "Marc Farhat", "marfarha"),
    ("royindr", "Muzn Shaheen", "muzns"),
    ("royindr", "Karthik S Rao", "karthrao"),
    ("nsbhatia", "Altug Besiroglu", "altugb"),
    ("nsbhatia", "Anli Zhou", "anliyuez"),
    ("nsbhatia", "Daniel Wilson", "wilsonkc"),
    ("nsbhatia", "Divya Bhatnagar", "divybhat"),
    ("nsbhatia", "Donald Logan", "logando"),
    ("nsbhatia", "Elkan Polad", "poladelk"),
    ("nsbhatia", "Gabriel Cruz Rodarte", "gabecruz"),
    ("nsbhatia", "Gianluca Manuli Calameonte", "manuligm"),
    ("nsbhatia", "Hannah DekAY", "handekay"),
    ("nsbhatia", "Hohebeth Vega", "hohebet"),
    ("nsbhatia", "John Sarreal", "jsarreal"),
    ("nsbhatia", "Krzysiek Nawrocki", "knawrock"),
    ("nsbhatia", "Mariana Delgado", "mardl"),
    ("nsbhatia", "Michelle Fahey", "mmfahey"),
    ("nsbhatia", "Michelle Fraser", "micfras"),
    ("nsbhatia", "Neke-Kraus, Nyasule", "nnekraus"),
    ("nsbhatia", "Punreet Brar", "punreetb"),
    ("nsbhatia", "Ravi Garg", "ravigarg"),
    ("nsbhatia", "Rohit Keshari", "rokeshar"),
    ("nsbhatia", "Rohit Kiran", "rohitsrk"),
    ("nsbhatia", "Sanna Kodiganti", "skodigan"),
    ("nsbhatia", "Sharmin Pathan", "sharminp"),
    ("nsbhatia", "Sivan Almonsnino", "almosiva"),
    ("bhanidhi", "Bill Rains", "rainsbil"),
    ("bhanidhi", "Sha Martin", "ronshm"),
    ("bhanidhi", "Ratliff, Jesse", "jesserat"),
    ("bhanidhi", "Amy spalding", "amyspald"),
    ("bhanidhi", "Khalife, Joseph", "jkhalife"),
    ("bhanidhi", "Amanda Leon", "leoaman"),
    ("bhanidhi", "Browning, Morgan", "mmmcdoug"),
    ("bhanidhi", "Pomerantz, Todd", "todpomer"),
    ("bhanidhi", "Beth Jimison", "bethjim"),
    ("bhanidhi", "Tristan Hyde", "trishyde"),
    ("nehrwt", "Elkan Poland", "poladelk"),
]

# CPT IN responses from ASANA screenshots (stakeholder_alias -> score)
# Some stakeholders appear under multiple leaders - we record per leader
CPT_IN_RESPONSES = {
    # Abhas Rao's stakeholders
    ("raabhas", "toyoshiv"): 9,
    ("raabhas", "jennbr"): 10,
    ("raabhas", "hocint"): 8,
    ("raabhas", "novakln"): 9,
    ("raabhas", "sshimizu"): 7,
    ("raabhas", "karthrao"): 10,
    # Abhishek Kumar Prasad's stakeholders
    ("prsaab", "kraema"): 10,
    ("prsaab", "raveggif"): 9,
    ("prsaab", "vjaisalm"): 9,
    ("prsaab", "effinlay"): 9,
    ("prsaab", "kostesha"): 9,
    ("prsaab", "michschm"): 9,
    ("prsaab", "muzns"): 7,
    ("prsaab", "lsellami"): 9,
    ("prsaab", "jkateshk"): 10,
    ("prsaab", "rwermers"): 9,
    ("prsaab", "jbarlog"): 10,
    ("prsaab", "kwaserge"): 9,
    ("prsaab", "absalami"): 10,
    ("prsaab", "nadeemys"): 9,
    ("prsaab", "issti"): 9,
    ("prsaab", "gibswesl"): 10,
    ("prsaab", "lukapan"): 10,
    ("prsaab", "imcohen"): 10,
    ("prsaab", "filreiss"): 10,
    # Indrajeet Roy's stakeholders
    ("royindr", "filreiss"): 10,
    ("royindr", "bribut"): 9,
    ("royindr", "mpskros"): 9,
    ("royindr", "tifwelch"): 10,
    ("royindr", "kostesha"): 6,
    ("royindr", "mestrecm"): 10,
    ("royindr", "marfarha"): 10,
    ("royindr", "muzns"): 8,
    ("royindr", "karthrao"): 10,
    ("royindr", "lsellami"): None,  # no response in screenshots
    ("royindr", "mhibbard"): None,
    # Navjyot Bhatia's stakeholders
    ("nsbhatia", "rohitsrk"): 10,
    ("nsbhatia", "rokeshar"): 9,
    ("nsbhatia", "punreetb"): 10,
    ("nsbhatia", "knawrock"): 9,
    ("nsbhatia", "skodigan"): 8,
    ("nsbhatia", "ravigarg"): 9,
    # Nidhi Bhagat's stakeholders
    ("bhanidhi", "jkhalife"): 9,
    ("bhanidhi", "rainsbil"): 10,
    ("bhanidhi", "amyspald"): 8,
    ("bhanidhi", "todpomer"): 9,
    ("bhanidhi", "mmmcdoug"): 9,
    ("bhanidhi", "ronshm"): 9,
    ("bhanidhi", "bethjim"): 10,
    ("bhanidhi", "trishyde"): 10,
    ("bhanidhi", "jesserat"): 10,
    # Neha Rawat's stakeholders
    ("nehrwt", "poladelk"): 10,
}

# FEC_Net responses from ASANA screenshot
FEC_DATA = [
    ("Jay Dave", "Digna Vora", "dignavora", 8),
    ("Jay Dave", "Joy Goodman", "joygoodma", 10),
    ("Jay Dave", "Sonia Maleky", "soniamale", 7),
    ("Ashwini Davangere", "John Christian", "johnchr", 9),
    ("Amanda Leon", "Michael Mascitelli", "michaelma", 10),
    ("Jay Dave", "Denise Lackey", "deniselac", 7),
    ("Jay Dave", "Giulia Botti", "giuliabot", 9),
    ("Amanda Leon", "Subhashree Rengarajan", "subhashr", 9),
    ("Ashwini Davangere", "Dan Moore", "danmoore", 10),
    ("Jay Dave", "Keelin Benedicto", "keelinben", 10),
    ("Jay Dave", "Erik Brewer", "erikbrewe", 9),
    ("Jay Dave", "Tyler Reed", "tylerreed", 10),
    ("Jay Dave", "Mike Samaroo", "mikesamar", 10),
    ("Amanda Leon", "Dustin Schoffler", "dustinsch", 9),
    ("Jay Dave", "Sarah Goldstein", "sarahgold", 9),
    ("Amanda Leon", "Tim Johnson", "timjohnso", 9),
    ("Amanda Leon", "John", "john", 9),
    ("Jay Dave", "Abhinav Sidhu", "abhinavsi", 10),
    ("Jay Dave", "Hilda Padron", "hildapadr", 10),
    ("Jay Dave", "Ravi Jayakumar", "ravijayak", 7),
    ("Amanda Leon", "Sean Sutton", "seansutt", 3),
    ("Albert Fang", "Albert Fang", "albertfan", 7),
    ("Jay Dave", "Andres Carlos", "andrescar", 10),
]


def clean_org(org_id):
    print(f"  Cleaning {org_id}...")
    for cycle in nps_cycle_repo.list_cycles(org_id):
        cid = cycle.cycle_id
        pk = f"{org_id}#{cid}"
        for n in nps_nomination_repo.list_nominations(org_id, cid):
            nps_nomination_repo.delete_nomination(org_id, cid, n.email)
        for r in nps_response_repo.list_responses(org_id, cid):
            nps_response_repo._get_table().delete_item(Key={"org_id_cycle_id": pk, "response_id": r.response_id})
        nps_cycle_repo._get_table().delete_item(Key={"org_id": org_id, "cycle_id": cid})
        print(f"    Deleted cycle {cycle.cycle_name or cid[:8]}")


def create_cycle(org_id, name, start, end):
    c = SurveyCycle(org_id=org_id, cycle_id=str(uuid.uuid4()), start_date=start, end_date=end,
                    status="active", reminder_mode="manual", cycle_name=name)
    nps_cycle_repo.put_cycle(c)
    print(f"  Created: {name} ({c.cycle_id[:8]}...)")
    return c.cycle_id


def add_nom(org_id, cid, leader, name, alias):
    email = alias.lower() + "@amazon.com"
    # Check for duplicate email in this cycle
    existing = nps_nomination_repo.get_nomination(org_id, cid, email)
    if existing:
        return email  # already exists
    nom = Nomination(org_id=org_id, cycle_id=cid, email=email, name=name, leader=leader)
    nps_nomination_repo.put_nomination(nom)
    return email


def record_resp(org_id, cid, leader, email, score):
    cat = categorize_score(score)
    r = NpsResponse(org_id=org_id, cycle_id=cid, response_id=str(uuid.uuid4()),
                    nps_score=score, category=cat, leader=leader)
    nps_response_repo.put_response(r)
    nps_nomination_repo.update_responded(org_id, cid, email)


def main():
    print("=" * 60)
    print("  Loading H1 2026 NPS Data (Fresh)")
    print("=" * 60)

    # Step 1: Clean
    print("\nCleaning old data...")
    clean_org("whs_cpt_in")
    clean_org("fec_net")

    # Step 2: Create cycles
    print("\nCreating cycles...")
    cpt_cid = create_cycle("whs_cpt_in", "H1 2026", "2026-01-01", "2026-06-30")
    fec_cid = create_cycle("fec_net", "H1 2026", "2026-01-01", "2026-06-30")

    # Step 3: Load CPT IN nominations
    print(f"\nLoading CPT IN nominations ({len(CPT_IN_NOMINATIONS)} entries)...")
    nom_count = 0
    for leader_alias, name, alias in CPT_IN_NOMINATIONS:
        leader = LEADER_MAP.get(leader_alias, leader_alias)
        add_nom("whs_cpt_in", cpt_cid, leader, name, alias)
        nom_count += 1

    # Step 4: Record CPT IN responses
    resp_count = 0
    for (leader_alias, alias), score in CPT_IN_RESPONSES.items():
        if score is None:
            continue
        leader = LEADER_MAP.get(leader_alias, leader_alias)
        email = alias.lower() + "@amazon.com"
        record_resp("whs_cpt_in", cpt_cid, leader, email, score)
        resp_count += 1

    # CPT IN stats
    scores = [s for s in CPT_IN_RESPONSES.values() if s is not None]
    p = sum(1 for s in scores if s >= 9)
    pa = sum(1 for s in scores if 7 <= s <= 8)
    d = sum(1 for s in scores if s <= 6)
    nps = ((p - d) / len(scores)) * 100 if scores else 0
    noms = nps_nomination_repo.list_nominations("whs_cpt_in", cpt_cid)
    print(f"  CPT IN: {len(noms)} nominated, {resp_count} responded | P:{p} Pa:{pa} D:{d} | NPS: {nps:.1f}")

    # Step 5: Load FEC_Net
    print(f"\nLoading FEC_Net ({len(FEC_DATA)} entries)...")
    for leader, name, alias, score in FEC_DATA:
        email = add_nom("fec_net", fec_cid, leader, name, alias)
        record_resp("fec_net", fec_cid, leader, email, score)

    p2 = sum(1 for _, _, _, s in FEC_DATA if s >= 9)
    pa2 = sum(1 for _, _, _, s in FEC_DATA if 7 <= s <= 8)
    d2 = sum(1 for _, _, _, s in FEC_DATA if s <= 6)
    nps2 = ((p2 - d2) / len(FEC_DATA)) * 100
    print(f"  FEC_Net: {len(FEC_DATA)} nominated, {len(FEC_DATA)} responded | P:{p2} Pa:{pa2} D:{d2} | NPS: {nps2:.1f}")

    # Overall
    total_r = len(scores) + len(FEC_DATA)
    total_p = p + p2
    total_d = d + d2
    overall = ((total_p - total_d) / total_r) * 100
    print(f"\n  OVERALL: {total_r} responses | NPS: {overall:.1f}")
    print("\nDone!")


if __name__ == "__main__":
    main()
