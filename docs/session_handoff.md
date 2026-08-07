# NPS Survey Automation — Session Handoff (July 2026)

Paste-ready context to resume in a new chat.

## 🟢 LATEST STATE 2026-08-07 (PART 8) — RBAC, L5+ gating, admin tools, feedback polish

Handover to backup owner (kuvinu@). Everything below is DEPLOYED to prod
(EC2 `i-06ccd83e4b55fa98f`, ap-south-1) and committed to git. Build green:
**464 tests pass** (`python -m pytest app -q`).

### Access control (the big one) — `app/services/nps_access_service.py` (NEW)
Single source of truth for who-can-see-what. `resolve_access(alias)` returns
`{role, orgs, home_org, leader_name, is_super, is_leader, source}` or None.
- **Manual grants win**, else **live PAPI reporting**:
  - `__user__<alias>` role record: `admin`/`editor` → full; bare `viewer` →
    org metrics only (no feedback).
  - `user_access` blob grants (admin page): admin, or viewer scoped to a
    leader / one-or-more orgs / all orgs (blank org).
  - Otherwise PAPI: a person under a configured **org head** is classified
    into that org. **Head = manager** ⇒ that person is a *leader*; anyone
    whose chain passes a leader is a viewer scoped to that leader's feedback.
- **Org heads (precedence order)** default in code, override via `org_heads`
  settings key: CPT IN=`sakau` → CPT NA=`mill` → FEC=`terrickw`. Precedence
  puts Sandeep's directs in CPT IN even though she reports to the CPT NA head.
  **Heads themselves get NO auto access** (role assigned manually later).
- **L5+ gate**: PAPI now parses `jobLevel` (`papi_client`). Auto access requires
  level >= `MIN_AUTO_LEVEL` (env `NPS_MIN_LEADER_LEVEL`, default 5); below/unknown
  -> denied. Manual grants bypass. **Nominating** also requires L5+ (except
  admins/editors) — enforced in `/nominate/submit` + `/nominate/bulk-submit`
  (skipped when PAPI unconfigured, i.e. local/tests).
- **Session re-validation**: auth decorators (`auth_routes._establish_session`)
  re-resolve from the ALB header on every request (short TTL cache in
  `nps_access_service`, `invalidate()` on grant changes), so removing a grant
  revokes a live session within ~60s instead of never.
- Tests: `test_nps_access_service.py` (18), plus updated midway/papi/nominate.

### Dashboard / admin (in `nps_dashboard.html` + `routes.py`)
- **Tab gating**: non-admins see only Read Me + their own org (Metrics) +
  Feedback (own rows). **Program Performance (cross-org) + Admin tabs are
  admin-only.** Server filters visible orgs from the session scope.
- **Admin -> User Access** manager: type alias -> PAPI name autofill; Access =
  Admin / Viewer; Org (specific / All orgs / add multiple); optional Specific
  leader (alias or name -> autofill). Add both **provisions the real Midway
  login** (`/nps/auth/users/*`) AND saves the grant; Remove revokes. Table lists
  ALL grants (not filtered by the scope selector).
- **Admin -> Performance Targets**: per-YEAR targets (Default / year); a year
  applies to both H1 & H2. Drives the Perf page vs-target.
- **Admin org-scope selector** defaults the User Access add-row org.

### Program Performance page
- Ranking TABLE removed -> per-org **metric boxes ranked by NPS** (top->bottom)
  with rank badge + **vs Target** deltas on NPS & Response Rate.
- **Program Targets heading is dynamic** (tracks the selected cycle's year).
- **Category Distribution** moved up beside Program Targets (2-col).

### Feedback tab
- Score badge is a **themed pill** (full Promoter/Passive/Detractor, no crop).
- Cards with a "What was missing" box now label the quote **FEEDBACK** to
  disambiguate. Per-leader / super-viewer gating via `_feedback_scope`.

### Nominate tab
- Admins/editors get an **"All leaders"** option -> sees every nomination for
  the cycle (leader shown per row), can remove any. (Root cause of "admin can't
  see all": leader dropdown is roster-fed, and the roster no longer enumerates
  PAPI-derived leaders.)

### Deploy / verify (unchanged workflow)
`python infra/ssm_deploy.py` (needs fresh `ada` creds for 399016860083;
`ada credentials update --account=399016860083 --provider=conduit
--role=IibsAdminAccess-DO-NOT-DELETE --once`). Ships `app/` + `run.py` only.
Verify via SSM curl with `Host: nps.whs-cpt.amazon.dev` +
`X-Amzn-Oidc-Identity: <alias>` against localhost:5000. Always `node --check`
the inline `<script>` of edited templates before deploy.

### Open / caveats
- **`kuvinu` = admin** (active). `raabhas` = admin grant. Org heads
  `sakau`/`mill`/`terrickw` baked in code (override via `org_heads` settings).
- Feedback row scoping matches leader **name**; a PAPI-name vs nomination-name
  mismatch could drop rows — watch for gaps.
- gunicorn runs **2 workers** -> scheduler + access cache are per-worker
  (duplicate-send risk pre-existing; `NPS_DEMO_SAFE=1` blocks real sends).
- Slack bot token was shared in plaintext earlier — **rotate** it.
- Kale privacy review: chase POC (see the OnePrivacy Slack draft in chat).

## 🟢 LATEST STATE 2026-08-06 (PART 7) — Admin-defined survey phases + cadence notifications

DONE + deployed + verified live (EC2 `i-06ccd83e4b55fa98f`, ap-south-1):

- **New service `app/services/nps_phase_service.py`** — admin models a cycle's
  timeline as an ordered list of phases. Each phase: `id`, `name`, `audience_type`
  (`leaders` / `stakeholders` / `leaders-response-summary` / `non-responders`),
  `cadence` (`once` / `daily` / `alternate_day` / `weekly` / `manual`), `start_date`,
  `end_date`, `order`, `last_sent`, `sent_once`. Persisted as ONE JSON blob in a
  `__phase_schedule__` NpsOrgConfig row keyed `org_id -> cycle_id -> [phases]`
  (200KB cap, whole-blob last-write-wins). Pure cadence fns `is_active_phase` /
  `phase_send_due`. `dispatch_phase` routes by audience to the existing leader /
  distribution delivery paths (so `NPS_DEMO_SAFE` + per-leader `notify_alias`
  redirect are inherited), then writes a Send_Audit_Record onto `NpsReminderLogs`.
- **`nps_leader_service.send_response_summary`** — emails/Slacks each roster leader
  the live response count (from `nps_asana_dashboard_service.get_dashboard_summary`).
- **`nps_scheduler.phase_send_job`** — new job iterating active orgs/cycles,
  dispatching due phases; registered as `id="nps_phase_send"` alongside the existing
  `nps_reminder_check` (both on the same interval). `test_nps_scheduler.py` updated
  for the 2nd job — 26 tests pass.
- **Routes (admin-only, `role_required("admin")`):** `GET /nps/phases`,
  `POST /nps/phases`, `POST /nps/phases/send-now`.
- **Frontend:** "📅 Survey Phases" editor card in `#adminPane` (org/cycle selectors,
  phase table with name/audience/cadence/start/end, Add phase, Save phases, per-row
  Send now for manual phases, remove). `initPhases()` gated to `BOOT.role === 'admin'`.
  Inline `<script>` passes `node --check`.

Verified: `GET /nps/phases?org_id=whs_cpt_in&cycle_id=h1-2026` → `200 []`; app boots
clean (health ok) so `init_scheduler` registered both jobs.

CAVEATS / next:
- gunicorn runs **2 sync workers** → the BackgroundScheduler starts in each worker,
  so both `nps_reminder_check` and `nps_phase_send` can fire once per worker
  (pre-existing behavior, not introduced here). `NPS_DEMO_SAFE=1` blocks real sends
  today; before go-live, move the scheduler to a single owner (e.g. a lock, a
  dedicated worker, or `--preload` + worker-id guard) to avoid duplicate sends.
- App-logger INFO lines (incl. "NPS reminder scheduler started") aren't captured by
  systemd/journald — only gunicorn's own logs are. Cosmetic; wire app logging to
  stdout if startup confirmation is wanted in journalctl.
- All PART 7 work is **UNCOMMITTED** in git.

## 🟢 LATEST STATE 2026-08-06 (PART 6) — Feedback tab + identity capture

DONE + deployed + verified live:
- **Separate "💬 Feedback" tab** (`#feedbackPane`). Visible to admins, super
  leaders (admin_leaders), and any leader (`canSeeFeedback` = isAdminViewer ||
  isLeaderViewer). Org+cycle pickers → `GET /nps/feedback` → grouped-by-leader
  table: Score/Category, Stakeholder (photo+name), Feedback, What was missing, Date.
- **`/nps/feedback`** (new) reads LIVE Asana via `nps_asana_dashboard_service.get_feedback`
  (real identity, not the stale DynamoDB leader-as-name data). Gated by shared
  `_feedback_scope()` helper: admins + admin_leaders = all; a leader = own rows;
  else nothing. `/nps/responses` refactored to use the same helper.
- **Respondent identity plumbing**: OrgConfig gained
  `custom_field_respondent_name_gid` + `custom_field_respondent_email_gid`
  (model + repo + `/nps/orgs/update` allowlist). `get_feedback` reads Name/Email
  from those GIDs; alias derived from email → phonetool photo.
- Verified: `/nps/feedback?org_id=fec&cycle_id=h1-2026` → 200, live rows with
  score/category/feedback/date/leader. Name/email BLANK until GIDs set.

**NAMES + PHOTOS NOW WORK (2026-08-06):** probed the Asana tasks — no Name/Email
custom fields. Respondent NAME is in the **task title** "<Leader>, <Stakeholder>";
respondent EMAIL is in the task **description/notes** ("Email address: x@amazon.com").
`get_feedback` now: parses name via `_respondent_name` (strip leader prefix from
title), and email via `_email_from_notes` (regex on notes, prefers the "Email
address:" label, else first email). Route derives alias = email local-part →
phonetool badge photo. Verified live: `/nps/feedback?org_id=whs_cpt_in&cycle_id=h1-2026`
→ 72 rows, **71 with alias** (e.g. Priank Upadhyay→uppriank, Hannah DeKay→handekay);
1 row had no email line → name-only (graceful). Still prefers explicit
`custom_field_respondent_name_gid`/`_email_gid` if ever configured. PII: feedback
now shows identifiable stakeholder name+photo+score+feedback (gated) — confirm vs
Kale/IRIS attestation before wide rollout.

**(superseded) earlier note — set the two Asana field GIDs**
per org. The survey form has "Name" + "Email address" fields — get their custom
field GIDs from the Asana project and set `custom_field_respondent_name_gid` /
`custom_field_respondent_email_gid` on each org (via `/nps/orgs/update` POST or
directly in DynamoDB NpsOrgConfig). NOTE: the `/nps/orgs/view` admin HTML page
does NOT yet have inputs for these two fields — either add them there or set via
API/DDB. Privacy: feedback now exposes identifiable stakeholder feedback+score
(gated) — confirm against Kale/IRIS attestation.

## 🟢 LATEST STATE 2026-08-06 (PART 5) — avatars fix, table redesign, feedback photos

- **Badge photo fix**: `ptAvatar` now tries `https://badgephotos.corp.amazon.com/?login=<alias>`
  first, falls back to legacy `internal-cdn.amazon.com/badgephotos.amazon.com/?uid=`,
  then hides (the old iCDN-only URL rendered as broken glyphs).
- **Leader Performance table redesigned** → columns: Leader (avatar) | Nominations |
  Response Received | NPS | Promoters/Passives/Detractors (one cell, colored) |
  Action Status (single cell "NN% c/t") | Remind. Backend `get_leader_breakdown`
  now returns per-leader `nominated` (grouped from nominations) + `actions_completed`.
  Table is now 7 cols (skeleton/empty colspans updated 8→7).
- **Stakeholder photos + score in View Feedback**: `/nps/responses` now returns
  `respondent_alias`, derived by joining `respondent_name` → nomination `email`
  (responses stay anonymous; nominations carry the email). Feedback modal shows the
  stakeholder's phonetool avatar next to their name (score + feedback already shown).
  Alias is best-effort by exact name match (blank avatar if no match).

REMAINING (flagged): **per-leader feedback scoping** — today the feedback modal
shows ALL leaders' stakeholders to any org viewer (client-groupable). To restrict a
leader to only THEIR OWN stakeholders' feedback needs a viewer-alias → leader-name
map + a SERVER-SIDE filter in `/nps/responses` when role is not admin/editor
(BOOT.viewer + BOOT.leaderAliases are available to build it). Not done — real ACL,
didn't want to rush it. PII note: feedback view now exposes stakeholder identity +
score + written feedback to whoever can open it (currently org viewers).

## 🟢 LATEST STATE 2026-08-06 (PART 4) — leader avatars + Admin tab

Inspired by the OpEx project-status dashboard (person photo + update column).
DONE + deployed + render-verified (dashboard 200):
- **Leader Phone Tool avatars** in Leader Performance table. Backend adds
  `leader_aliases` (name→alias) + `viewer_alias` to the dashboard BOOT
  (routes.py `dashboard()`); frontend `ptAvatar(alias,name)` + `leaderAlias(name)`
  render badge photo `https://internal-cdn.amazon.com/badgephotos.amazon.com/?uid=<alias>`
  linked to phonetool, `onerror` hides. `.pt-avatar`/`.person-cell` CSS.
- **Consolidated Admin tab** (`#adminPane`, tab `data-tab="admin"`). Moved the
  Export card + Visibility panel OFF the Read Me page into it, plus an
  **Admin Access (leaders)** manager (`admin_leaders` settings key; admins
  edit; those aliases + all admins see the Admin tab via `isAdminViewer()`).
  Gating: visibility edit admin-only (card hidden for non-admins); export UI
  shows for isAdminViewer but the route is still admin/editor server-side.

FLAGGED (NOT built — need user decision):
- **Stakeholder phonetool + feedback + score to leaders**: BLOCKED — responses
  store `respondent_name` only, NO alias (anonymity). Needs respondent alias
  captured on responses + privacy re-check (overlaps Kale/IRIS). PII-sensitive.
- **Per-leader-only visibility** (leader sees only own row/stakeholders):
  auth-model change; feedback half moot until the above.
- If designated (rule-based) leaders must actually EXPORT, the
  `/nps/admin/export.xlsx` route (admin/editor) needs to also honor
  `admin_leaders` — a deliberate PII-export ACL change, flagged for confirm.

## 🟢 LATEST STATE 2026-08-06 (PART 3) — Dashboard change backlog

Working a dashboard change list (deployed via ssm_deploy.py). DONE + deployed:
1. Tab "Program Status" → **"Read Me"**.
3+5. Performance page: **Program Targets + Team Ranking side-by-side directly below the KPI boxes** (`.perf-targets-rank` grid); Category Distribution full-width below.
4. KPI boxes: `.stat-row` now `flex-wrap:nowrap` + shrink + overflow-x — **all 7 stay on one line**.
2. **"About the NPS Program" admin-editable** (intro / targets label / targets / teams) via settings key `about_program`; Edit btn mirrors Resources.
9. **Admin visibility toggle** — generic `data-hideable="key"`/`data-hide-label` + "👁️ Table & Section Visibility" panel on Read Me; persisted in settings `hidden_sections`; `applyHidden()` adds `.hidden-by-admin`. Tagged: perf_targets, perf_ranking, perf_comparison, perf_trends, perf_category. Extend by adding the two data- attrs anywhere.
11. **Admin XLSX export** — `nps_export_service.build_cycle_export(cycle_id, org_id="")` (openpyxl); route `GET /nps/admin/export.xlsx` (admin/editor); "📥 Export Cycle Data" card on Read Me. Cols: Org, Leader, Stakeholder, NPS Category, What Was Missing, Feedback, Action Taken(=admin_comment); blank when missing. 4 tests green; verified live (5KB xlsx for h2-2026).

ALL 11 backlog items DONE + deployed + render-verified (dashboard 200, all new ids present; inline JS passes `node --check`):
- 6. **Per-org metric boxes** on Performance page (`#perfOrgBoxes`, `.perf-org-grid`) from `entry.orgs[team]` (NPS/RR/Promoters/Passives/Detractors/Responded), rendered in `renderPerf`.
- 7. **Target Revision History** admin-editable card on Read Me (`target_history` settings key; effective `YYYY-MM` + what changed; newest first).
- 8. **Cycle timelines**: the Read Me "Current Cycle Status" editor already declared nomination/survey/action/complete dates + status per cycle slot; ADDED a **Leadership Notification Date** field (`leader_notify`) to editor + display.
- 10. **Action Taken** editable table at bottom of org pane (`#actionTakenCard`; settings key `action_taken` keyed by org_id; categories → rows {feedback, did}; admin-only edit via admin-only /nps/settings route).

New settings keys total: about_program, hidden_sections, action_taken, target_history (+ program_status now carries leader_notify). `nps_export_service` + `/nps/admin/export.xlsx` for export. All admin-editable content persists through the single `__settings__dashboard` blob (50KB cap — watch growth if action_taken gets large).

Settings = ONE JSON blob in NpsOrgConfig `__settings__dashboard` (`nps_settings_service`, 50KB cap). Frontend keys: chart_headings, program_status, program_resources, nomination_*, about_program, hidden_sections.

## 🟢 LATEST STATE 2026-08-06 (PART 2) — Slack DM to leaders is LIVE

Steps 4 + 5 DONE. Slack DMs to leaders now work end-to-end in prod.

- **Step 4 (Slack app):** app `A0B5WB9GC68` ("NPS Survey Reminders")
  re-scoped to **`chat:write` + `chat:write.customize` + `im:write`** (Bot
  Token Scopes only; ALL User Token Scopes incl. `users:read` removed →
  no high-risk scope → OPUS **auto-approved**, no Talos). Approved+installed
  on workspaces Operations / World Wide Consumer / Amazon. Bot token stored
  in `NpsOrgConfig` item `whs_cpt_in` → `slack_bot_token` (via DynamoDB
  update-item). **ROTATE this token** (it was shared in plaintext during
  setup): Slack app → OAuth & Permissions → Regenerate, then re-run the
  DynamoDB update or set via `/nps/orgs/view`.
- **Step 5 (deploy):** shipped via `infra/ssm_deploy.py`. `awscrt 0.36.1`
  pip-installed into the gunicorn env (`/home/ssm-user/.local`, python3.11)
  — the deploy script does NOT install requirements, so this was a separate
  SSM `pip install --user awscrt` (remember to redo if the host is rebuilt).
- **Fix during deploy:** `_load_api_key()` no longer falls back to
  `_get_region()` (which is the SLAB SigV4a region-set "*", invalid for a
  Secrets Manager client) — now uses AWS_REGION/AWS_DEFAULT_REGION or lets
  boto3 resolve (IMDS) on EC2.
- **VERIFIED LIVE on the EC2:**
  - SLAB resolve under the allowlisted role: `kumruxl → W01BGFKFQCD`.
  - `send_leader_reminders(whs_cpt_in, channels=('slack',))` →
    **slack_sent=2** (DMs to kumruxl + kuvinu via the nsbhatia/raabhas test
    redirects); 4 real leaders correctly skipped by demo-safe.
- **NOTE:** the running systemd service does NOT set AWS_REGION; boto3 gets
  region from IMDS (works). Manual `python` invocations must set AWS_REGION
  themselves.
- **Still uncommitted** — the SLAB SigV4a / DM / slack-check changes are
  deployed but not committed to git.

## 🟢 LATEST STATE 2026-08-06 (read this FIRST)

**SLAB alias→Slack-ID client (Option B interim) — Step 2 COMPLETE.**
Finished the hand-rolled `app/services/slab_client.py` so the Slack app can
drop the high-risk `users:read` scope (exits Red ASR). Everything below is
confirmed from Amazon source / the onboarding ticket, not guessed:

- **Endpoint** (from `OpusSLABClientConfig/coral-config/OpusSLABProd.config`):
  `https://api.prod.slack-admin.enterprise-engineering.aws.dev` + Coral path
  `/opus.users.getSlackIdFromAlias`. Baked into `DEFAULT_SLAB_ENDPOINT`.
- **Signing switched to SigV4a** (`botocore.crt.auth.CrtSigV4AsymAuth`,
  service `execute-api`, region-set `*`). Region `*` = valid at any regional
  gateway (SLAB is multi-region active-active; our EC2 is ap-south-1 with no
  guaranteed local deployment). Added `awscrt>=0.19.0` to `requirements.txt`
  (installed + verified locally: `awscrt 0.36.1`, botocore 1.35.99).
- **Response contract fixed** to the real `aliasToSlackIdMap` list of
  `{alias, slackId, isActive}` (was a guessed `slackIds`). `isActive:false`
  is treated as not-found. Request field `userAliases` (already correct).
- **API key**: issued + posted to onboarding ticket **D490668297** (now
  Closed, resolution "API Key Created"). NOT pasted into the repo — pull
  from the ticket. Local test: `export SLAB_API_KEY=<key>`.
- Tests: `test_slab_client.py` + `test_nps_leader_service.py` = **50 passed**;
  diagnostics clean. **NOT yet committed/deployed.**

**Step 3 (Secrets Manager + IAM) — ALREADY DONE (verified 2026-08-06).**
Set up during onboarding, no changes needed:
- Secret `nps-survey/slab-api-key` (ap-south-1) is populated with the exact
  ticket key (plain 40-char string; `_load_api_key()` handles that form).
- Managed policy `AllowReadSlabApiKey` grants `secretsmanager:GetSecretValue`
  on `secret:nps-survey/slab-api-key*` and is attached to `nps-survey-ec2-role`,
  alongside `AllowInvokeSlab` (execute-api:Invoke). So the EC2 role can read
  the key AND invoke SLAB today.

**Slack DM logic to leaders — CODE COMPLETE.** Both `send_leader_reminders`
and `send_nomination_open` resolve alias→Slack-ID via SLAB (SigV4a) then
`slack_client.send_dm(user_id, msg, bot_token)` with the org's `chat:write`
token; degrade gracefully per row (no token / not-found / transport) and
never break the batch. Demo-safe blocks real leaders. Admin can set the org
token via the existing org-update route (`slack_bot_token` field).
- **NEW diagnostic:** `GET /nps/leaders/slack-check?alias=<alias>` (admin/editor,
  read-only, no bot token) → `{alias, ok, slack_id, error}`. Proves the SLAB
  half works on the deployed host independently of the blocked Slack app.
  Helper: `nps_leader_service.check_slack_resolution()`. Tests: 54 passed.

**Remaining before a real Slack DM sends end-to-end:**
- **Step 4 (deferred, Red app out of scope):** enterprise Slack app as
  **`chat:write`-only**; drop its token into the org's `slack_bot_token`.
  Until then Slack rows report "no bot token configured for this org".
- **Step 5:** deploy via `infra/ssm_deploy.py` (needs fresh `ada` creds).
  `awscrt` must install on the EC2 (Amazon Linux wheel exists). After deploy,
  hit `/nps/leaders/slack-check?alias=kumruxl` to confirm SLAB resolves under
  the allowlisted EC2 role (email works now; full DM once Step 4 lands).

## 🟢 LATEST STATE 2026-07-28 (read this first, then the MASTER UPDATE below)

Co-owner handoff note (for Vinay, opening this folder in his own Kiro):
this folder was shared directly (no git remote on your machine). **Do NOT
run git push / brazil-build / cr / the SSM deploy** — kumruxl@ owns those on
his side. Your Kiro is for **local edits + local tests (pytest)** only.

Shipped + LIVE in prod since the master update (deployed directly via
`infra/ssm_deploy.py`, ahead of CR; committed on branch
`h2-nominate-enhancements` = commits c8a998b feat + 54d970f docs):

- **Nomination form (`/nps/nominate/view`) enhancements** — left-side
  per-leader **counts table** (numbers only, public to any org viewer);
  prominent **active-cycle banner** at the top; **"Add from last cycle"**
  carry-forward of the prior CLOSED cycle's *responded* stakeholders
  (duplicates disabled, showing the existing nominator); **bulk add**
  (paste aliases or carry-forward). The current-cycle who-nominated-whom
  list stays **privileged** (admin/editor/roster leader) — a nomination is
  gauged at the leader (Navjyot) level. Leader is always system-resolved
  (never client-chosen). Code: `app/nps/routes.py`,
  `app/services/nps_nomination_service.py`, template
  `app/templates/nps_leader_nominate.html`; tests green.
- **Cycle rollover DONE** (all 3 orgs): `h1-2026` CLOSED (previous cycle,
  holds responders for carry-forward), `h2-2026` ACTIVE (empty; Aug 1–Dec
  31 2026).
- **Leader-reminder flow** (email + Slack DM) with a per-leader
  `notify_alias` **TEST redirect**. Prod runs **`NPS_DEMO_SAFE=1`** so only
  leaders WITH a test alias send; real leaders are skipped. Set:
  `nsbhatia→kumruxl`, `raabhas→kuvinu` (whs_cpt_in). Email works.
  **Slack DM is BLOCKED**: no `slack_bot_token` for whs_cpt_in AND the
  Slack app install is gated on Talos/ASR; alias→Slack-id needs `users:read`
  (being dropped) or SLAB (not cut over). Recommended test path =
  `notify_slack_id` (DM a member ID with `chat:write` only) — **NOT yet
  implemented** (next code task). Code: `app/services/nps_leader_service.py`,
  route `/nps/leaders/remind`, UI button "Remind leaders (test)".
- **ERB**: scope is **GLOBAL** (WHS/FC stakeholders worldwide incl. EU) —
  expect real ERB engagement; gates ERB-country launch, not the Yellow ASR
  self-cert. Filled questionnaire: `ERB_Questionnaire_nps-survey_Filled.docx`.
- **Kale / Privacy (2026-07-28 update):**
  - **Legal Privacy/AI review (HRPRP-58885) RESOLVED** — risk LOW,
    conditional approval stands, **no DPIA**. Conditional approval does
    NOT cover ERB countries (do ERB-3324 for those).
  - **IRIS Ecosystem Block CLEARED** (duplicate-ASR issue no longer shows).
  - BUT Kale **Privacy Status = In Review** with **12 IRIS attestation
    blockers** (must clear for Kale -> Approved -> ASR Privacy task
    completes). Blockers: (a) new "nps-survey app logs / Application log
    stream" table needs data-subject types + Authoritative Source=No +
    >=1 DACL field; (b) NpsReminderLogs (DynamoDB) mis-attested as having
    personal data -> set personal-data=No + business use case + retention
    (90 days); (c) 2 empty data objects (NpsReminderLogs +
    NpsDeliveryFailures, both 0 rows) need DACL classification; (d) attest
    Data Access Requests (2/2) + Deletion Service (1/2).
  - Verified 2026-07-28: NpsReminderLogs + NpsDeliveryFailures are EMPTY
    (0 rows). ReminderLogs schema has NO PII -> answer No. DeliveryFailures
    schema HAS an `email` field -> attest personal-data=Yes (recipient
    email, Confidential) even though currently empty.
  - **UPDATE 2026-08-04: Kale SUBMITTED CLEAN for privacy review.** All 12
    blockers cleared, then a 2nd IRIS sync surfaced 2 more, now also cleared:
    (1) "nps-survey app logs" — set BOTH the data store AND its Application
    log stream table to personal-data=**No** (reason: *Not Personal Data*),
    because HR-only log data belongs in UBX not Kale, and Kale requires the
    store/table personal-data answers to agree (store=Yes + table=No threw a
    validation error). (2) NpsDeliveryFailures — re-tagged its `email` field
    with a **DACE element** (Work Email; Authoritative=No, DSAR=Provide As Is,
    Confidential) since the earlier tag didn't persist through the sync.
    Application Description reworded to explain the 3-field PDC count (NPS
    score = numeric, feedback = optional free text; employee/HR data only) —
    that item was **Should Address / non-blocking**. **Submit succeeded with
    0 must-resolve blockers.**
  - **NEW 2026-08-04 (Option B, Step 1): Slack DM now resolves IDs via SLAB,
    not `users:read`.** Both `send_leader_reminders` and `send_nomination_open`
    now call `slab_client.lookup_slack_id_by_alias(alias)` (Opus SLAB
    `OpusUsersGetSlackIDFromAlias`) instead of
    `slack_client.lookup_user_by_email` — so the Slack app can drop `users:read`
    and hold only `chat:write` (exits the Red ASR). `send_dm` (chat:write)
    unchanged. SLAB failures / not-configured are caught per row (email still
    fires, batch never breaks). Tests updated + added (31 passed). SLAB
    onboarding is DONE: prod API key issued (ticket D490668297), role
    allowlisted (CR-289008613). REMAINING to go live on Slack: (Step 2)
    finalize `slab_client.py` config — raw `SLAB_ENDPOINT` URL + confirm
    signing is SigV4a (client currently plain v4; needs aws-crt-python) +
    response field name; (Step 3) store key in Secrets Manager
    `nps-survey/slab-api-key` + add `secretsmanager:GetSecretValue` to the EC2
    role; (Step 4) a `chat:write` bot token from the enterprise Slack app
    (the Red-app install is OUT OF SCOPE for now per owner — code reports
    "no bot token" gracefully until then). Email path works today regardless.
  - **NEW 2026-08-04: nomination-OPEN kickoff notification (email + Slack).**
    Added `nps_leader_service.send_nomination_open(base_url, org_id, deadline,
    note, channels)` — a distinct "nominations are now OPEN" announcement to
    all roster leaders, separate from the periodic reminder. Reuses the proven
    reminder delivery rules: per-leader `notify_alias` TEST redirect, org Slack
    bot token from OrgConfig (skipped+reported per row when missing), demo-safe
    (`NPS_DEMO_SAFE`) blocks real leaders. Returns
    `{org_id, link, deadline, email_sent, slack_sent, notifications:[...]}`.
    Route `POST /nps/leaders/notify-open` (admin/editor). UI: new
    "📣 Notify: nominations open (test)" button on the nominate form (next to
    Remind). Message bodies are PLACEHOLDERS (copy TBD). 6 new tests, all green
    (29 passed in test_nps_leader_service.py). Files: `nps_leader_service.py`,
    `app/nps/routes.py`, `app/templates/nps_leader_nominate.html`,
    `app/services/test_nps_leader_service.py`. NOT yet committed/deployed.
  - **RECONCILE 2026-08-04: pulled Vinay's prod changes back into this copy.**
    Vinay deployed directly to prod from his own folder (never committed/pushed),
    so this repo had drifted behind prod. Both copies were on the same commit
    `54d970f`, so his uncommitted working-tree edits were copied in file-for-file
    (all except `docs/session_handoff.md`, which keeps the Kale updates above).
    His changes (NOT cosmetic — additive, no conflict with nominate/reminder core):
    NEW `app/services/nps_asana_dashboard_service.py` (live Asana-backed dashboard,
    reads the "Ongoing Survey" section in real time; nominations stay DynamoDB),
    NEW `app/services/nps_settings_service.py` (admin-editable dashboard content in
    a `__settings__dashboard` system row of NpsOrgConfig), big `nps_dashboard.html`
    rewrite, `routes.py` +217 (new endpoints), plus small edits to
    `nps_nomination_service`, `nps_leader_service`, `nps_share_link_service`,
    `models`, `nps_cycle_repo`. Affected-test subset GREEN (129 passed). NOT yet
    committed — pending the new nominate/reminder/communication work on top.
  - **NEXT (2026-08-04):** wait for the next IRIS twice-daily sync -> confirm
    IRIS shows 0 blockers -> THEN ping the PBR (njoneago) on HRPRP-58885 /
    #help-workplace-trust to prioritize. Do NOT ping before the sync (they'd
    see stale blockers). PBR approves -> Kale Approved -> ASR Privacy
    Compliance task auto-completes -> Resolve Required Issues -> self-certify
    **Yellow** -> paste engagement ARN into the Slack install request.
  - Duplicate Veritas app deprecate ticket (NPSSurveyReminders 556dfa31)
    still to be submitted/confirmed; keep canonical 33d9f777.
- **CR-292011675** (rev 3) still pending 1 team approval; auto-merge on.
- NOTE: `infra/ssm_deploy.py` is **gitignored** (not in repo) — deploy
  tooling is shared separately.

Open/next: implement `notify_slack_id` + get a Slack bot token (Slack DM is
a must); submit the Veritas deprecate ticket + resubmit Kale; credential
rotations (Federate OIDC secret, SLAB API key); CR approval → merge →
Apollo Phase 3 deploy stages.

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
