# CI/CD Pipeline Setup Plan (SDO Phase 2–4) + SLAB Option A

Concrete blueprint to take NPSSurveyAutomation from NoOpBuild + manual
EC2 deploy to a real Brazil build + Pipelines/Apollo, and to wire SLAB
via the official SDK on the way.

> **Where this work happens:** a **Cloud Desktop / Brazil workspace** with
> Builder Toolbox — NOT a laptop shell. Pipelines and Apollo are internal
> tools (web consoles + CDK), not AWS-CLI resources. Kiro can generate the
> package/Config/CDK artifacts; creation + `brazil-build` + pipeline
> bootstrap are run in that environment.

## Prereqs (one-time, on Cloud Desktop)

- `mwinit -o` (WebAuthn isn't supported on Cloud Desktop SSH — use OTP).
- Builder Toolbox (brazil, cr, pipelines CLI).
- A Brazil **version set** for the app (see the blocker below).
- Decide the deployment target (see Phase 3 options).

## STATUS (2026-07-19): Phase 2 COMPLETE — blocker resolved

The "live lacks Flask/requests" conclusion was wrong: **Brazil package
names are case/name-sensitive**. The web stack IS in live under:
- `Python-Flask = 3.x` (capital F — `Python-flask` doesn't exist)
- `Requests = 2.x.x` (base package; `Python-requests-*` are add-ons like
  `-kerberos`/`-aws4auth`)
- `Python-moto = 5.x` (moto 5 `mock_aws` API works as-is)

What was done (all self-serve, no colleague needed):
1. Version set created via CLI (owner bindle WHS_AIFA):
   `brazil versionset create --versionSet NPSSurveyAutomation/release
   --from live --platforms AL2_x86_64 --bindleId <WHS_AIFA-id>
   --mailingList kumruxl@amazon.com`
2. `brazil ws use --versionSet NPSSurveyAutomation/release`, Config deps
   fixed to the names above, `brazil ws merge` (NOTE: merges are
   **local-only**; see step 4).
3. `brazil-build release` green: **291 tests x CPython 3.10 + 3.12**.
   Fixes needed: moto->5.x, Flask->3.x (Werkzeug 3 pairing), removed
   `doc_command` from setup.py, made test_reads_interval_from_env
   hermetic (monkeypatch.setenv instead of patching os.environ.get,
   which broke tzlocal on Linux).
4. Server-side VS populated via **build.amazon.com -> Version Set Merge**
   (source: live TIP, the 18 Config deps -> 235 major versions). Required
   because `brazil ws merge` only updates the local workspace copy — the
   CR Dry Run Build fails until this is done.
5. CR raised: https://code.amazon.com/reviews/CR-290409853
   (`cr` via `toolbox install cr`). GK notes: bcrypt bumped to 5.x on
   vendor guidance; Pytest stays 6.x (pytest 8 blocked by
   Pytest-html/py.xml incompat in BrazilPythonTestSupport chain).

DONE (2026-07-20): CR-290409853 MERGED (approved by Riwjit; Vinay blocked
on missing source-code access — request filed via
code.amazon.com/request-source-permissions). Pipeline CREATED:
**NPSSurveyAutomation-release** (pipelines.amazon.com, hand-managed,
version-set-based, bindle WHS_AIFA, pipeline ID 9919991). First build
green: https://build.amazon.com/7939468486 — package built into the VS
as a TARGET (mark-as-target anchors the merged deps past their 13-day
retention). Autobuild enabled for NPSSurveyAutomation/mainline only (do
NOT "Turn On All" — third-party packages update via merges from live).

Gotchas learned:
- `cr` reuses the existing revision if the commit is unchanged; to force a
  fresh workspace snapshot (e.g. after granting a reviewer package read),
  `git commit --amend --no-edit` then `cr -r <CR>`.
- CR reviewers need base Amazon source-code access, not just bindle
  grants on the package.
- A CRUX rule pins "WHS CPT IN AIFA team 1+" as reviewer (mass-notifies
  the team on every revision). Edit the rule at team level to quiet it.

Remaining: Phase 3 (Apollo deploy stages on this pipeline's Edit tab).

## Phase 2 — Real build with a test gate (replaces NoOpBuild)

Turn the package into a `BrazilPython`/`PythonDefault` build that runs the
259 pytest suite + static analysis as a build gate.

1. Replace the `Config` `build-system = no-op` with a Python build system
   and declare deps (Flask, boto3, pytest, bandit, moto, etc.) in the
   version set.
2. Add a build target that runs `pytest` (fail build on any failure) and
   `bandit -r app/` (SAST gate).
3. `brazil-build release` → must go green. Fix any packaging issues
   (imports, test discovery — note the app currently uses plain pytest).

Deliverable: every merge is gated on 259 tests + SAST.

## Phase 3 — Pipelines + Apollo

**Deployment target decision (pick one):**
- **A. Keep the EC2, deploy via Apollo** (lightest): create an Apollo
  environment + host class targeting the existing instance; Apollo pushes
  the build; systemd restart via an Apollo activation script. Least
  re-platforming.
- **B. Containerize → ECS/Fargate** (cleaner long-term, more work).
- **C. Lambda** (not a fit — long-lived Flask + scheduler).

Recommended: **A** for the first pipeline (fastest to certify), migrate to
B later if desired.

**Pipeline model (CDK package, e.g. `NPSSurveyAutomationCDK`):**
- Source: GitFarm mainline.
- Build stage: the Phase-2 build (tests + SAST).
- Stages: Beta → (integration check) → Gamma → **manual approval** → Prod.
- Deploy: Apollo environment per stage.
- Add deployment monitors + auto-rollback on the Prod stage.

**Steps (Cloud Desktop):**
1. Create the CDK pipeline package; model stages above.
2. Bootstrap the pipeline (Pipelines console / CDK deploy).
3. Create Apollo environments (Beta/Gamma/Prod) for the chosen target.
4. First deployment through the pipeline; verify the app serves.

## Phase 4 — Decommission manual deploy

Once pipeline deploys reliably: remove SSH/manual `git pull` as a normal
path; keep it break-glass only. Update the runbooks.

## SLAB Option A (folds into Phase 2/3)

Once the app is a Brazil package with an Apollo runtime + coral-config,
wire SLAB via the official SDK (per its README):

1. Version set: merge `OpusSLABPythonSDK` from live; add deps to `Config`:
   `Boto3, BotoCore, Aws-crt-python, PythonCoralConfig,
   OpusSLABClientConfig, OpusSLABPythonSDK`.
2. Add `app/services/slab_helper.py` from the SDK README; set
   `conf.get("OpusSLAB", "Base.Prod")` (Prod), `region="global"`,
   `signature_version="v4a"`, `x-api-key` from Secrets Manager
   (`nps-survey/slab-api-key`).
3. Replace the two lookup sites in `nps_distribution_service.py`:
   `client.opus_users_get_slack_id_from_alias(userAliases=[...])` →
   map alias→Slack ID; keep the existing caching + error handling.
4. Drop `users:read`/`users:read.email` from the Slack app; keep
   `chat:write`.
5. Remove the interim hand-rolled `slab_client.py` (or keep as a
   non-Brazil fallback).
6. Ask OPUS/ASR to confirm reclassification once live.

Note: coral-config resolves the SLAB endpoint at runtime in the
Apollo/Brazil env — which is exactly why Option A needs Phases 2–3 first.

## What Kiro can generate next (say the word)

- The Phase-2 `Config` (Python build + test/SAST gate) draft.
- The Pipelines CDK package skeleton (stages + Apollo deploy).
- The `slab_helper.py` + distribution-service swap, ready to drop in.

## What must be done in the Brazil/Cloud Desktop env (not the laptop)

- `brazil-build`, version-set merges, pipeline bootstrap, Apollo env
  creation, deployments.
