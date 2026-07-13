"""Real-data DEMO runner — real DynamoDB, localhost, screen-share only.

Runs the ACTUAL app against the real Nps* tables in ap-south-1 using your
current AWS credentials (ada / Conduit / IibsAdminAccess). Intended purely
to screen-share your real H1 numbers to a leader.

SAFETY:
  * The reminder scheduler is DISABLED here (NPS_DISABLE_SCHEDULER=1), so
    NO reminder emails are ever sent while demoing.
  * This points at LIVE data. Treat it as read-only — do NOT create/close
    cycles, import, or send anything during the demo.
  * localhost only. It is NOT internet-facing, so it does not put the app
    "in production" and does not trigger the uncertified-Red-app finding.

Usage:
    # 1. Make sure your creds are fresh (admin/read for account 399016860083):
    #    ada credentials update --account=399016860083 --provider=conduit \
    #        --role=IibsAdminAccess-DO-NOT-DELETE --once
    #    aws sts get-caller-identity   # confirm
    # 2. Run:
    python run_demo_realdata.py
    # 3. Open http://localhost:5000/nps/dashboard and log in with a REAL
    #    admin account. Screen-share.
"""

import os

# Point at the real region/tables. Do NOT set fake AWS keys — use the
# ambient ada/Conduit credentials from the default profile.
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
os.environ.setdefault("AWS_REGION", "ap-south-1")

# Prod tables already exist and the app must not try to create them.
os.environ.pop("NPS_ENSURE_TABLES", None)

# Hard safety: never start the reminder scheduler in demo mode.
os.environ["NPS_DISABLE_SCHEDULER"] = "1"

from app import create_app  # noqa: E402

app = create_app()


if __name__ == "__main__":
    print("\n" + "=" * 64)
    print("  NPS Survey — REAL-DATA DEMO (localhost, screen-share only)")
    print("=" * 64)
    print()
    print("  Region:       ap-south-1 (LIVE DynamoDB)")
    print("  Scheduler:    DISABLED (no reminder emails will be sent)")
    print("  Dashboard:    http://localhost:5000/nps/dashboard")
    print("  Orgs:         http://localhost:5000/nps/orgs/view")
    print("  Nominations:  http://localhost:5000/nps/nominations/view")
    print("  Cycles:       http://localhost:5000/nps/cycles/view")
    print()
    print("  Log in with a REAL admin account.")
    print("  ** This is LIVE data — read-only demo. Do NOT mutate. **")
    print("  Press Ctrl+C to stop")
    print()
    app.run(debug=False, port=5000)
