# Co-owner setup — run the NPS tool locally (real-data demo)

For kuvinu@ (co-owner). Gets the tool running on your machine against the
real data, safely, for demos. localhost only — nothing internet-facing.

## Prerequisites (one-time)

- **Midway**: `mwinit` (run it first; re-run when it prompts / ~daily).
- **Python 3.11+** and **pip**.
- **git** with Amazon SSH access (Builder Toolbox sets this up).
- **ada** CLI + **AWS CLI** (both from Builder Toolbox).
- WHS_AIFA **bindle membership** with Conduit access to account
  399016860083 (already granted).

## 1. Get the code (GitFarm)

```bash
mwinit                       # refresh Midway first (SSH to git.amazon.com needs it)
git clone ssh://git.amazon.com/pkg/NPSSurveyAutomation
cd NPSSurveyAutomation
```

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

## 3. Load AWS credentials (account 399016860083)

A **read-only** Conduit role is enough for a demo (it only reads DynamoDB)
and is safer than admin:

```bash
ada credentials update --account=399016860083 --provider=conduit \
    --role=<ReadOnlyRoleName> --once
aws sts get-caller-identity      # confirm the account/role
```

(If you also need to run infra/AWS-write work, use the admin role
`IibsAdminAccess-DO-NOT-DELETE` instead. Creds expire ~hourly — re-run to
refresh.)

## 4. Set the SES sender (needed only if you'll demo the test reminder)

```bash
# Windows (PowerShell):
$env:NPS_FROM_ADDRESS="nps-survey@whs-cpt.amazon.dev"
# macOS/Linux:
export NPS_FROM_ADDRESS="nps-survey@whs-cpt.amazon.dev"
# Optional: send the test reminder to yourself instead of kumruxl@
#   $env:NPS_TEST_REMINDER_RECIPIENT="kuvinu@amazon.com"
```

## 5. Run it

```bash
python run_demo_realdata.py
```

Open **http://localhost:5000/nps/dashboard** and log in with a real
admin/editor account (get the login from kumruxl@ out-of-band, or have an
admin create you a user in the app).

## Built-in safety (already on in run_demo_realdata.py)

- **Scheduler disabled** — no scheduled reminder emails fire.
- **Demo-safe mode ON** — Send / Send Reminder to Pending / per-leader are
  BLOCKED. Only **🧪 Test Reminder (to me)** sends (to kumruxl@ or your
  `NPS_TEST_REMINDER_RECIPIENT`). Real stakeholders are never contacted.
- **localhost only** — not internet-facing, so it does not put the app in
  production / does not trigger the uncertified-Red-app finding.

## Notes

- This reads LIVE data. Treat it as read-only during a demo — don't
  create/close cycles or import.
- The dashboard takes a moment to populate on first load (fetching real
  DynamoDB data) — expected.
