# NPS Survey Automation — Session Handoff (July 2026)

Paste-ready context to resume in a new chat.

## ⭐ MASTER UPDATE 2026-07-25 (supersedes EVERYTHING below — start here)

### Current state, one paragraph
App is LIVE at **https://nps.whs-cpt.amazon.dev** behind a Midway-gated
ALB (Federate OIDC client `nps-survey-reminders-prod`). ASR review is
officially **Yellow / Ring-2 / self-certifiable**. Kale privacy
attestation SUBMITTED (In Review). PAPI directory integration is LIVE
in prod (any Amazon alias → name/title/leader prefill on the nomination
form). Nomination form is fully identity-driven: nominator + leader
come from Midway/server-side; leader is NEVER user-selectable;
nomination lists visible only to admins/editors/roster leaders.
Suite: **379 tests green**. Prod runs from laptop `main` via
`infra/ssm_deploy.py` (SSM chunked deploy) — **~24 commits ahead of
GitFarm mainline, CR pending (top priority)**.

### PENDING — CR / pipeline (top priority)
1. DONE 2026-07-25 (laptop): merged `internal/mainline` (BrazilPython
   conversion `7e4c9d8`) into `main` cleanly; pushed feature branch
   `main:h2-features` to GitFarm; GitHub mirror fast-forwarded
   (origin/main → 36bce1a). `main` now contains all of mainline
   (24 ahead, 0 behind). Runbook + CR description saved:
   `docs/cr_h2_features.md`, `docs/cr_h2_features_description.md`.
2. DONE 2026-07-25 (driven over SSH to dev desktop): raised
   **CR-292011675** vs mainline (`--parent mainline`), build GREEN (379
   tests). Rev 1 analyzers all PASS. **AutoSDE flagged a stored-XSS** in
   `app/templates/nps_leader_nominate.html` (server fields interpolated
   into innerHTML unescaped). FIXED: added `esc()` helper, escaped all
   interpolated values (renderRows/showAlert/dup-modal), replaced the
   inline `onclick` with a `data-remove-alias` + delegated click handler
   (commit ebe73d2, on main/h2-features). **CR revision 2 pushed** with
   the fix — AutoSDE re-reviewing. NO individual reviewer yet (CRUX team
   rule = 1 approval; add Riwjit, alias TBD; Vinay pending source access).
   NOTE: commits show CRUX "author mismatch" WARNING (GitHub noreply
   email) — non-blocking, not rewriting pushed history.
3. **Phase 3 Apollo deploy stages** on pipeline
   NPSSurveyAutomation-release (currently build-only, no deploy) — after
   this exists, retire `infra/ssm_deploy.py` (deploys then flow
   CR → pipeline → Apollo). SLAB Option A SDK swap also rides on this.

### PENDING — ASR / DI threat model / Kale
1. **DI threat model**: DONE 2026-07-25 — published **v747**
   (NPSSurveyReminders-747.html; 0 unmitigated / 33 mitigated / 1 FP;
   supersedes v449). Added PAPI internal-service boundary + transient
   "Employee directory record" data element (Confidential) + ALB/Midway
   edge (identity-driven form). Modeled on Page-1; Architecture page is
   presentation-only. All PAPI + ALB threats marked Mitigated (text in
   docs/papi_threat_model_delta.md). Threat Model ASR task = Complete.
   TODO: attach NPSSurveyReminders-747.html to the ASR Threat Model task
   (Attachments) as updated evidence.
2. **Kale**: add PAPI as a data source in the app description (Veritas
   33d9f777-6675-4612-bf3e-640960c021ad); review is In Review with
   kale-wrkplace-hlth-safety — NUDGE via Smruthi thread P441140532 if
   quiet >5 business days. Kale financial review branch (Tax/
   Accounting) = false-positive trigger, answer "no financial data",
   non-blocking.
3. **ASR critical path**: Kale approval → Privacy Compliance task
   auto-completes → Resolve Required Issues → SELF-certify (Yellow needs
   no external certifier — Sri confirmed; he's informed). Then paste
   engagement ARN into Slack install request → AmazonUC-SIGNAL unblocks.
4. ERB scoping questionnaire (ERB-3324 / V2300729846, child of privacy
   HRPRP-58885; tag @souzaja). **SCOPE CORRECTED 2026-07-26: this is
   GLOBAL, not IN/US/CA.** Data subjects are WHS/FC stakeholders across
   Amazon Operations sites worldwide, so EU/ERB countries ARE in scope
   (Germany, France, Poland, Italy, Spain, etc. all have FCs). Earlier
   "non-ERB / expect out-of-scope" assumption is WRONG — expect actual
   ERB engagement on its own pan-Amazon timeline. Filled questionnaire
   generated: `ERB_Questionnaire_nps-survey_Filled.docx` (repo root) —
   answered for global footprint; still has [CONFIRM] placeholders
   (business-line selections, total + per-ERB-country headcounts for
   data subjects & users, levels/job families, whether any Tier-1/
   associate-level subjects, 2 screenshots). NEXT: fill placeholders →
   upload to ERB-3324 → move SIM to "Scoping Template In-Progress" →
   tag @souzaja. Does NOT block the Yellow ASR self-cert, BUT it DOES
   gate launching in ERB countries (5-6 wk scoping clock, then possible
   works-council engagement). Also seek BLL + Labor & Employment Legal
   assessment per the AutoSIM note.
5. Data Dictionary Review SIM HRPRP-58884: "Out of Scope/No Data"
   comment posted (survey-tool criterion); change workflow step to
   Specialist Review if editable; non-blocking either way.

### PENDING — PAPI (integration is LIVE; loose ends)
1. **NA + FEC leader rosters empty** — leader auto-resolution only works
   for WHS CPT IN (6 Sandeep-directs loaded: bhanidhi, nehrwt, nsbhatia,
   prsaab, raabhas, royindr). NA workbook has 18 PoC names, FEC 30 —
   names only, NO aliases. Either kumruxl supplies aliases, or UBX
   re-submit to add `employeeSearchV2AutoCompleteLogin` (name→alias).
   Also confirm NA/FEC "PoCs" are truly the sponsor-directs equivalent.
2. PAPI config (for reference): role
   arn:aws:iam::220627861680:role/IAMAuth_nps_survey_us-east-1, endpoint
   https://us-east-1.prod.papi.people-data.amazon.dev (IAM-auth regional
   URL — papi.amazon.com is CORP-only), expand=`supervisor-chain` (full
   upward chain in one call), SigV4 with pre-encoded query. Gamma roles
   also issued (671313004605). Op allowlisted: employeeV2ByLogin only.
   TPS 10. Onboarding SIM V2300729875 (resolved).
3. Privacy: GREEN LIGHT (no DPIA), auto-approved except ERB countries.

### PENDING — smaller items
- go/nps-survey shortlink → https://nps.whs-cpt.amazon.dev/nps/dashboard
- Rotate Federate OIDC client secret (passed through chat during setup);
  update ALB listener + Secrets Manager `nps-survey/federate-oidc`
- Deactivate legacy `__user__admin` password user after browser
  verification (Midway auto-login confirmed working)
- SLAB API key rotation (shared in plaintext in ticket D490668297)
- Leaders roster admin UI (currently API-only: POST /nps/leaders/add
  {alias, name, org_id})
- Old parked: orphan ASR app 556dfa31 cleanup, CTI confirmation with
  manager, close CAZ ticket P449029619, kuvinu backup PAT (P426628259)

### Architecture quick-reference (as deployed today)
- User → ALB (Midway/Federate OIDC, cert nps.whs-cpt.amazon.dev) → EC2
  i-06ccd83e4b55fa98f gunicorn :5000 (SG: ALB-only; shell = SSM only;
  public 80/443/22 REVOKED; nginx retired)
- App auth: NPS_MIDWAY_AUTH=1 → X-Amzn-Oidc-Identity header → role from
  user store (kumruxl + kuvinu = admins, no passwords). Password form
  disabled in prod, kept for local dev.
- Nominate form: identity auto-detected; leader system-resolved
  (roster → PAPI chain → history); lists = privileged only; duplicates
  surface only via 409 conflict. Per-org share-token links (org-locked
  server-side).
- Env (systemd override): NPS_BEHIND_PROXY, NPS_ALLOWED_HOSTS,
  NPS_MIDWAY_AUTH, PAPI_ROLE_ARN, PAPI_ENDPOINT. Deploy:
  `python infra/ssm_deploy.py` (fresh ada creds for 399016860083;
  expire hourly).
- S3 bucket whs-cpt-nps-survey DELETED (was redundant workbook copies);
  6 DynamoDB tables (diagram says 6 now).

## UPDATE 2026-07-19 (superseded — historical)

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

UPDATE 2026-07-20: CR-290409853 MERGED (Riwjit approved; Vinay lacked
base source-code access — request filed, pending manager approval +
propagation). Pipeline **NPSSurveyAutomation-release** live (ID 9919991),
first build green (build.amazon.com/7939468486), package is a VS TARGET,
autobuild ON for NPSSurveyAutomation only. Sri message sent with links.
NEW FEATURE built on laptop (commits 4488cd4, deb554e, 0413c5b, local +
GitHub only): self-serve leader nomination form (/nps/nominate) — leader
roster, first-come-first-served per leader/cycle, share-token capability
link, invite-leaders email with deadline. 339 tests. MUST go to GitFarm
via feature branch + CR (do NOT push straight to mainline).

UPDATE 2026-07-24 (later): **Org-specific nomination links + alias
prefill SHIPPED** (commits 2a44608 + fix). Per-org share tokens
(`__share__nominate_form#<org>` rows; old global token dead); token
access locked server-side to its org (403 cross-org on context/list/
submit/remove/prefill); leader roster org-scoped (leader_org attr;
unscoped = all orgs); invites per org. New /nps/nominate/prefill:
alias → {name, designation, leader} from roster + nomination history
(workbook imports count) — nominator's leader auto-selects, stakeholder
details prepopulate. True org-chart resolution would need PAPI
(follow-up if wanted). Deployed + smoke-tested via SSM (prefill 200,
per-org tokens in context). Suite at 359. NOTE: prod leader rosters
are EMPTY (all 3 orgs) — add leaders per org via
POST /nps/leaders/add {alias, name, org_id}; no UI for this yet.

NEXT UP:
1. Nomination-feature CR: laptop `git pull internal mainline` (merge the
   BrazilPython commit), push GitHub; push feature branch to GitFarm
   (`git push internal main:leader-nominations`), dev desktop checkout ->
   brazil-build release -> cr --destination-branch mainline.
2. Fix CRUX team-review rule (team-level settings) so future CRs notify
   only chosen reviewers, not the whole team.
3. Vinay: confirm source-code access landed; re-add as reviewer on next CR.
4. Phase 3: Apollo deploy stages (pipeline Edit tab -> add environments).
5. SLAB Option A code (slab_helper.py + distribution-service swap) —
   runs in prod only after Apollo (coral-config needs Brazil runtime).
6. Then: drop Slack users:read scope; DI/reclassification follow-through.
7. Unchanged: Kale privacy reviewer chase, reviewer tasks nudge, SLAB key
   rotation, parked items (orphan ASR app, CTI, CAZ ticket).

## UPDATE 2026-07-23 — App LIVE behind Midway

- Sri confirmed: **Yellow = self-certified** — no external certifier
  needed once Privacy Compliance + Resolve Required Issues complete.
- App re-hosted (Yellow removed the Red-in-prod Shepherd blocker):
  **https://nps.whs-cpt.amazon.dev** behind an internet-facing ALB with
  Federate OIDC (Midway) auth. No `/` route — land on /nps/dashboard.
  Register a go/ shortlink (go/nps-survey) for the friendly URL.
- Built per docs/midway_alb_setup.md (now marked DONE): ACM cert,
  nps-alb + nps-tg (health /nps/auth/login, target healthy), Federate
  client nps-survey-reminders-prod (secret in Secrets Manager
  nps-survey/federate-oidc), Route 53 alias, NPS_BEHIND_PROXY=1 +
  NPS_ALLOWED_HOSTS via systemd drop-in, service enabled + active.
- **Instance SG locked down**: only :5000 from ALB SG remains; public
  80/443/22 revoked (SSH was world-open — now truly SSM-only, matching
  the threat model claim). nginx + nip.io + Let's Encrypt retired from
  the serving path.
- NOTE: Federate client secret was pasted in chat during setup —
  regenerate it in Federate + update listener/secret when convenient.
- **Midway auto-login SHIPPED (2026-07-24)**: NPS_MIDWAY_AUTH=1 — app
  reads X-Amzn-Oidc-Identity from the ALB, maps alias→role from the
  user store, password form disabled in prod (kept for local dev).
  Unknown aliases get an access-request page. /health endpoint added
  (unauthenticated, exempt from Host guard) — ALB health check moved
  to it; target HEALTHY. Deployed current main to EC2 via
  infra/ssm_deploy.py (chunked base64 over SSM; SSH is closed) — this
  also took the leader-nominations feature live (still needs its
  GitFarm CR; prod runs ahead of mainline temporarily). bcrypt
  installed on the instance (new dep). Users provisioned: kumruxl
  (admin), kuvinu (admin). Legacy __user__admin left ACTIVE as
  rollback insurance — deactivate after browser verification.

## Project
Internal NPS Survey tool (Flask + Python 3.11) for WHS CPT IN/NA + FEC
leadership. AWS account **399016860083** (ap-south-1), EC2
`i-06ccd83e4b55fa98f`. **Live at https://nps.whs-cpt.amazon.dev
(Midway-gated ALB)**. Repo: GitFarm
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
- ASR re-profiled: 32 answers resubmitted, DI/threat-model v449 linked
  (embedded diagram v283; supersedes v279),
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
4. **Finish DI + reclassification:** DONE 2026-07-21. Threat model
   **v449** published (0 unmitigated / 28 mitigated / 1 false-positive,
   non-blocking findings dismissed; embedded diagram v283). S3 removed
   from Architecture page (not used by code); data-element map matches
   code (responses→Asana API; Slack user ID→SLAB+DynamoDB+Slack API).
   Export `NPSSurveyReminders-449.html` attached to the Threat Model
   task. **Reclassification OFFICIAL: review now Yellow, Ring-2,
   Baseline only** — Red reviewer tasks removed. Critical path:
   Privacy Compliance Review (Kale) → Resolve Required Issues →
   certifier (sripathb@) sign-off.
   Kale (2026-07-21): discovered the privacy review was NEVER
   submitted (validation error on NpsNominations). Fixed: data object
   recreated with real 8-field schema + DSAR answers (leader field =
   Redact third-party; slack_user_id = cached copy, non-authoritative).
   **S3 bucket whs-cpt-nps-survey DELETED** (held redundant copies of
   the 3 admin workbooks, byte-identical to laptop copies; app never
   used it — no s3: in code or IAM role). Kale S3 data object removed
   to match. All 6 DynamoDB data objects fixed (Nominations/OrgConfig/
   Responses recreated with real schemas + per-field DSAR answers;
   ReminderLogs corrected to No-personal-data — failures field never
   populated in code; DeliveryFailures + ReminderLogs tables confirmed
   0 rows). App description fixed (SLAB lookup, chat:write only, Asana
   polling not webhooks). **Kale SUBMITTED 2026-07-21, Privacy Status:
   In Review** with kale-wrkplace-hlth-safety. Side quest: Kale spawned
   a Tax/Accounting financial review (false-positive trigger from the
   "Provide Amazon services" use case) — does NOT block ASR privacy
   approval; answer "no financial data" at leisure.
   Next: nudge kale-wrkplace-hlth-safety via Smruthi thread P441140532;
   good-news note to Sri.
5. **Message Sri:** pipeline in progress (build converted, setting up
   version set) — SDO fast-follow narrative.
6. **Chase Kale privacy reviewer** (Privacy Compliance task) -> gates
   Resolve Required Issues.
7. **Reviewer tasks** (Automated/Manual Code Review, Review Threat Model,
   Threat Mitigation Testing) — nudge Sri; Bandit already uploaded.
8. Parked: orphan ASR app `556dfa31` cleanup; confirm CTI with manager;
   close CAZ ticket P449029619.

## Honest notes
- Reclassification is the reviewer's call after seeing v449 DI. Dropping
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
