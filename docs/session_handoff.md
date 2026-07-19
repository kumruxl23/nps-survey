# NPS Survey Automation — Session Handoff (July 2026)

Paste-ready context to resume in a new chat.

## UPDATE 2026-07-19 (supersedes items below)

DONE this session:
- **Pipeline blocker RESOLVED** (was pending action #1). Root cause was
  package NAMING, not missing packages: live carries `Python-Flask = 3.x`
  (capital F), `Requests = 2.x.x` (base pkg), `Python-moto = 5.x`.
- Version set **NPSSurveyAutomation/release** created via
  `brazil versionset create --from live --platforms AL2_x86_64` (owner
  bindle WHS_AIFA, ID amzn1.bindle.resource.mmjuqvkd5bryeamw5iqq).
- `brazil-build release` GREEN: **291 tests x CPython 3.10 + 3.12**.
  Fixes: moto 5, Flask 3 (Werkzeug 3 pairing), bcrypt 5.x (GK vendor
  guidance), removed setup.py doc_command, hermetic scheduler test
  (monkeypatch.setenv; patching os.environ.get broke tzlocal on Linux).
  Pytest stays 6.x (pytest 8 blocked by Pytest-html/py.xml incompat).
- Server-side VS populated via build.amazon.com -> **Version Set Merge**
  (18 pkgs -> 235 majors). NOTE: `brazil ws merge` is LOCAL-ONLY; CR
  dry-run builds fail until the server-side merge is done.
- **CR-290409853** raised (Config, setup.py, setup.cfg), all analyzers
  PASS (GK needed the VS merge + fresh revision via `cr -r`). Published;
  awaiting Vinay Jain approval; auto-merge suggested.
- **SLAB item done**: secret `nps-survey/slab-api-key` created in
  Secrets Manager (ap-south-1); `AllowReadSlabApiKey` policy created +
  attached to `nps-survey-ec2-role`. Key rotation still pending.
- GitFarm push unblocked (was pending #3): all repos synced through
  1627d13; CR commit 75c73aa merges via CRUX.
- Docs updated: `docs/pipeline_setup_plan.md` (Phase 2 complete).
- Message to Sri drafted (CR + ASR re-profile) — send after CR merges.

NEXT UP:
1. CR-290409853: get Vinay approval -> merge -> sync laptop/dev-desktop.
2. Create pipeline at pipelines.amazon.com targeting the
   NPSSurveyAutomation/release VS (check dropdown next to "Create CDK
   pipeline" for classic option). Send Sri the message + links.
3. Phase 3: Apollo deploy stages (Beta -> Prod, manual approval).
4. SLAB Option A code (slab_helper.py + distribution-service swap) —
   runs in prod only after Apollo (coral-config needs Brazil runtime).
5. Then: drop Slack users:read scope; DI/reclassification follow-through.
6. Unchanged: Kale privacy reviewer chase, reviewer tasks nudge, key
   rotation, parked items (orphan ASR app, CTI, CAZ ticket).

## Project
Internal NPS Survey tool (Flask + Python 3.11) for WHS CPT IN/NA + FEC
leadership. AWS account **399016860083** (ap-south-1), EC2
`i-06ccd83e4b55fa98f`. Repo: GitFarm
`ssh://git.amazon.com/pkg/NPSSurveyAutomation` (authoritative) + GitHub
mirror `github.com/kumruxl23/nps-survey`. Owner **kumruxl@**, co-owner
**kuvinu@**. App is currently **OUT of production** (H1 cycle done). ASR:
**WHS_AIFA-1763314908**, still **Red / Ring-2, uncertified**. Certifier:
**Sripathi Bhat (sripathb@)**.

## Credentials / access
- Admin AWS via
  `ada credentials update --account=399016860083 --provider=conduit --role=IibsAdminAccess-DO-NOT-DELETE --once`
  (expires ~hourly). Read-only checks + additive/reversible changes OK;
  no unilateral prod-infra provisioning.
- Cloud Desktop: `dev-dsk-kumruxl-2b-74d03bb8` (Amazon Linux 2, us-west-2),
  zsh. Use `mwinit -o` (WebAuthn unsupported on the SSH console).

## Strategy
Slack DM reminders needed the high-risk `users:read` scope = the sole
driver of the Red ASR. Fix = drop `users:read`, resolve Slack IDs via the
internal OPUS SLAB API (`OpusUsersGetSlackIDFromAlias`). Interim =
email-only (already not-Red on its own).

## DONE this session
- bcrypt dependency fix pushed (fresh-clone self-serve testing).
- `.gitignore` hardened: emails, bandit output, threat-model HTML exports
  (`NPSSurveyReminders-*.html`), `index.html`, SLAB `README.md`,
  `Config-val`, local clone — all kept off the GitHub mirror.
- Bandit re-run: 0 High/0 Med/0 Open; uploaded to ASR.
- Demo tooling: `run_demo_realdata.py` (real DynamoDB, localhost,
  screen-share) with scheduler kill-switch (`NPS_DISABLE_SCHEDULER`) +
  `NPS_DEMO_SAFE` (blocks real-stakeholder reminders). `/nps/remind/test`
  + "Test Reminder (to me)" button = emails kumruxl@ only, no log writes.
- Proxy/Midway readiness: `NPS_BEHIND_PROXY` (ProxyFix + secure cookies) +
  `NPS_ALLOWED_HOSTS`; `docs/midway_alb_setup.md`. ALB NOT built (gated on
  reclassification).
- SLAB onboarding COMPLETE: ticket D490668297, CR-289008613 merged, prod
  API key received (in ticket; shared in plaintext -> rotate later), IAM
  `AllowInvokeSlab` (execute-api:Invoke) attached + verified.
- SLAB code: `app/services/slab_client.py` (interim hand-rolled) + tests.
  Real integration = OpusSLABPythonSDK (Brazil/Coral, coral-config
  endpoint, SigV4a, request field `userAliases`) -> chosen = Option A
  (SDK via pipeline).
- ASR re-profiled: 32 answers resubmitted, DI/threat-model v279 linked,
  TPS profile dropped. `docs/asr_reprofiling_answers.md` (before/after +
  DI deltas + copy-paste threat justifications). `docs/nps_architecture_diagram.drawio`
  updated (SLAB internal boundary, Slack = chat:write only).
- Pipeline (Phase 2) started on Cloud Desktop: `Config` converted
  NoOpBuild -> `build-system = brazilpython` (BrazilPython 3.0); Python
  3.10 + all deps resolve EXCEPT Flask/requests. Docs:
  `docs/pipeline_setup_plan.md`, `docs/brazil_build_conversion.md`.
- Tests: 291 passing locally. Asana test fixture made hermetic.
- All committed locally; pushed to origin (GitHub). GitFarm `internal`
  push is BEHIND — blocked on Midway/VPN SSH (fix: VPN + `mwinit -o`,
  then `git push internal main:mainline`).

## PENDING ACTIONS
1. **Pipeline blocker (top):** no usable version set carries Flask/
   requests. `live` lacks them; `HuPyFlask/dev` has Flask but is
   DEPRECATED. -> Create an OWNED version set (BuilderHub "Create Version
   Set", or pair with a Brazil-savvy colleague / ask: "new Python Flask
   service, which base VS has Python-flask?"). Then: point workspace at
   it -> `brazil-build release` -> 259 tests green as gate -> Phase 3
   Pipelines CDK + Apollo (target: keep EC2, deploy via Apollo). SLAB
   Option A folds in (`OpusSLABPythonSDK` + `slab_helper.py`, drop
   `users:read`).
2. **Store SLAB API key** in Secrets Manager (`nps-survey/slab-api-key`)
   + attach `AllowReadSlabApiKey` (policy in repo). Needs fresh `ada`
   creds. Rotate the key later (shared in plaintext).
3. **Push to GitFarm** once Midway/VPN fixed.
4. **Finish DI + reclassification:** make SLAB box a real component (not
   visual-only), re-run threat analysis, publish, attach
   `NPSSurveyReminders-279.html` to the Threat Model task, ask Sri to
   re-assess classification.
5. **Message Sri:** pipeline in progress (build converted, setting up
   version set) — SDO fast-follow narrative.
6. **Chase Kale privacy reviewer** (Privacy Compliance task) -> gates
   Resolve Required Issues.
7. **Reviewer tasks** (Automated/Manual Code Review, Review Threat Model,
   Threat Mitigation Testing) — nudge Sri; Bandit already uploaded.
8. Parked: orphan ASR app `556dfa31` cleanup; confirm CTI with manager;
   close CAZ ticket P449029619.

## Honest notes
- Reclassification is the reviewer's call after seeing v279 DI. Dropping
  `users:read` removes the Slack trigger, but credential handling +
  Confidential data likely keep it lower-rank Red or Yellow.
- Do NOT make the app internet-facing while ASR is uncertified Red
  (re-triggers Shepherd SIM D465560471). Demo = localhost + screen-share.

## Key files
- `docs/pipeline_setup_plan.md` — pipeline plan + version-set blocker
- `docs/brazil_build_conversion.md` — Phase-2 Config/setup.py drafts
- `docs/slab_onboarding_request.md` — SLAB status, contract, decision
- `docs/asr_reprofiling_answers.md` — reclassification kit + DI deltas
- `docs/asr_engagement_status.md` — overall ASR status
- `docs/midway_alb_setup.md` — ALB+Midway runbook (for later)
- `docs/co_owner_setup.md` — kuvinu@ local setup
- `infra/iam-policies/` — AllowInvokeSlab, AllowReadSlabApiKey, etc.
