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

---

# Making & deploying changes (continuing development)

You (kuvinu@) are an **admin** in the app already, so you can manage cycles,
users, and settings from the UI. To change the CODE and ship it:

## Where things live
- `app/nps/routes.py`, `app/nps/auth_routes.py` — Flask routes + auth.
- `app/services/` — business logic. Key ones: `nps_access_service.py`
  (who-can-see-what: PAPI reporting + manual grants + L5+ gate),
  `papi_client.py` (directory lookups incl. `jobLevel`), `nps_leader_service.py`,
  `nps_distribution_service.py`, `nps_phase_service.py` (survey phases).
- `app/templates/nps_dashboard.html` — the whole dashboard SPA (inline JS).
- `app/templates/nps_leader_nominate.html` — the nomination form.
- `infra/ssm_deploy.py` — the deploy script.
- `docs/session_handoff.md` — **read the latest "LATEST STATE" first** for the
  current architecture and open items.

## Test before you commit
```bash
python -m pytest app -q          # full suite (~3 min); must be green
```
For a single area: `python -m pytest app/services/test_nps_access_service.py -q`.
If you edit a template's inline `<script>`, syntax-check it (Node required):
extract the `<script>` blocks, replace `{{ ... }}` with `null`, and run
`node --check`.

## Deploy to prod (EC2 i-06ccd83e4b55fa98f, ap-south-1)
The app is behind a Midway ALB at **https://nps.whs-cpt.amazon.dev**. Deploy
over SSM (no SSH):
```bash
# 1. Fresh admin creds (expire ~12h; re-run when SendCommand returns ExpiredToken)
ada credentials update --account=399016860083 --provider=conduit \
    --role=IibsAdminAccess-DO-NOT-DELETE --once
# 2. Ship app/ + run.py, restart the service, health-check
python infra/ssm_deploy.py       # prints "extracted ok / active / {status:ok}"
```
Notes:
- The deploy ships **only** `app/` + `run.py`. New **pip** deps must be
  installed into the ssm-user env separately (the service runs
  `/home/ssm-user/.local/bin/gunicorn`).
- The systemd override bakes prod env (incl. `NPS_DEMO_SAFE=1` which blocks
  real emails/Slack, `PAPI_*`, Midway). Don't remove `NPS_DEMO_SAFE` until you
  intend real sends.

## Verify a deploy (SSM curl as any alias — read-only, safe)
```bash
# 302 = admitted, 403 = denied. Add a cookie jar + follow-up GET for deeper checks.
curl -s -o /dev/null -w '%{http_code}' \
  -H 'Host: nps.whs-cpt.amazon.dev' -H 'X-Amzn-Oidc-Identity: <alias>' \
  http://localhost:5000/nps/auth/login
```

## Git
Work on a branch, commit with clear messages, and open a CR
(`cr`) rather than pushing to mainline. Never force-push. `git push` is fine
for your own feature branch; do not push directly to mainline.

## Managing access without code (from the UI)
Admin tab -> **User Access**: add admins or scoped viewers (per leader / per
org / all orgs). Leaders (directs of the org heads, L5+) are admitted
automatically from PAPI — no manual step. To change the org heads, set the
`org_heads` key in the dashboard settings blob.
