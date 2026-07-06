# SDO Remediation Plan — NPS Survey Automation

Prepared for the ASR security-certification review with the certifier
(sripathb@). Documents the current software-development posture honestly
and the concrete plan to reach the SDO (Software Development Operations)
bar.

## Honest current state

This application began as a solo-built internal prototype and grew
organically. As a result it does not yet meet the full SDO bar:

| SDO expectation | Current state | Gap |
|---|---|---|
| Code in a Brazil package | ✅ `NPSSurveyAutomation` on GitFarm | None |
| Version control | ✅ GitFarm mainline (+ GitHub dev mirror) | None |
| Code Reviews (CRs) enforced | ⚠️ Not enforced historically; during the solo build, code was pushed direct to mainline. Mainline branch protection needs to be set to require a CR before merge. | **Enable CR-required branch protection; no direct pushes going forward** |
| CI/CD Pipeline | ❌ No pipeline; deployed manually (git pull + systemctl restart on one EC2) | **Stand up Pipelines + Apollo** |
| Automated tests in build | ⚠️ 259 unit tests exist and pass (`python -m pytest` → 259 passed, ~3 min, verified 2026-07-06), but not wired into a build/pipeline gate — package is NoOpBuild | **Run tests in pipeline build stage** |
| No manual prod changes | ❌ Manual deploy to EC2 | **Deploy only via pipeline** |

## What is already solid

- **Brazil package**: `ssh://git.amazon.com/pkg/NPSSurveyAutomation`,
  mainline with branch protection on.
- **Test coverage**: 259 unit tests, all passing
  (`python -m pytest` → 259 passed in ~3 min, verified 2026-07-06).
  Covers repos, services, distribution, reminders, dashboard
  aggregation, auth. Not yet a build gate (package is NoOpBuild) —
  addressed in Phase 2.
- **Security hardening already done**:
  - Least-privilege IAM (`nps-survey-ec2-role` scoped to Nps* tables +
    verified SES sender only; over-broad managed policies removed)
  - bcrypt password hashing (migrated from salted SHA-256, with
    transparent legacy upgrade)
  - Self-hosted static assets (removed external CDN dependency)
  - Secrets in Secrets Manager (Asana PAT) / DynamoDB (Slack token,
    admin-redacted)
  - TLS 1.2+ end to end
  - Threat model complete (14 threats, 0 unmitigated)
  - Third-party integrations TPS-certified (Asana TPTA0027224,
    Slack TPTA0050664)
  - Incident Response Plan documented
- **Current production status**: OUT of production (H1 cycle closed).
  No live production is being changed manually right now — clean window
  to put proper SDLC in place before the next (H2) cycle.

## Remediation plan

### Phase 1 — Enforce code reviews (fast, before/at cert)
- **CRUX Auto Added Reviewer rule** on `mainline`: require 1 locked
  approval (team WHS CPT IN AIFA, or kuvinu@ to avoid self-approval).
  This guarantees an approver on every CR. Done via CRUX Rules.
- **Adopt AutoSDE (policy-as-code)**: author an `AUTOSDE.yaml` in the
  package defining the SDO policy (mandatory review + required checks),
  validate with `autosde lint`, commit to mainline, then point a CRUX
  "AutoSDE Rule Config" rule at its blob URL. This is the first-class
  SDO-enforcement mechanism and directly answers the "not following SDO
  guidelines" concern.
  - **Order matters**: file first (lint + commit) THEN create the rule.
    A missing/invalid `AUTOSDE.yaml` blocks all merges on the scope.
  - **Open**: need the canonical `AUTOSDE.yaml` schema / required-policy
    bar — confirm with certifier or AutoSDE docs before authoring.
- Note: the package already inherits org-level CRUX analysis gates
  (Security Code Scanner, Software Assurance, Integration Tests,
  Coverlay) that require 'Pass' to merge a CR.
- **Open item**: confirm the exact mechanism that hard-blocks direct
  pushes to mainline (Permissions tab is package access control, not
  branch protection — no push-block toggle found there). Likely AutoSDE
  or a GitFarm setting; question queued for the certifier.
- **Effort**: reviewer rule ~15 min; AutoSDE ~half day once schema known.

### Phase 2 — Real build with tests (short)
- Replace the NoOpBuild `Config` with a Python build that runs
  `pytest` on `brazil-build`, so the 259 tests become a build gate.
- Add static analysis (Bandit / OneSAST) into the build.
- **Effort**: ~1 day.

### Phase 3 — CI/CD Pipeline (main lift)
- Model a Pipelines + Apollo pipeline: build → unit tests → static
  analysis → deploy to a beta/gamma stage → approval → prod.
- Replace the manual git-pull deploy on EC2 with pipeline-driven
  deployment (Apollo environment on the same or a fresh host).
- Add automated rollback + deployment monitors.
- **Effort**: ~3–5 days (pipeline CDK, Apollo env setup, deploy config).

### Phase 4 — Decommission manual deploy
- Once the pipeline deploys reliably, remove SSH/manual-deploy access
  as a normal path; keep it only as break-glass.

## Proposed sequencing vs certification

- **Phase 1 (CR enforcement)** can be done immediately — proposing to
  complete before/at cert.
- **Phases 2–4** proposed as a tracked fast-follow with a SIM/Taskei
  ticket and target dates, given the app is currently out of production
  and low-risk (internal, Confidential-only data).
- Open question for the certifier: what is the **minimum** SDO bar
  required for certification vs what is acceptable as a documented
  fast-follow.

### Target timeline

- **Certification target: end of July 2026.** The H2 NPS cycle starts in
  August and the app's launch is planned for then; certifying in July
  keeps us ahead of the cycle and supports the leadership follow-up.
- **Acceptable fallback ECD: Aug 2026, week 2** — workable but tighter
  against the launch, so end-of-July is strongly preferred.
- Phase 1 (CR enforcement): before/at the SDO call.
- Phases 2–4 (build gate → pipeline → decommission manual deploy):
  tracked fast-follow, targeted to complete around the H2 launch.

## Tracking

- Follow-up ticket for the pipeline work: draft in
  `docs/sdo_tracking_ticket.md` (record the filed TASK/SIM ID here once
  created).
- Owner: kumruxl@ · Backup: kuvinu@

---

## Call agenda & talking points (SDO call with sripathb@)

Drive the call from this. Goal: agree on the **minimum SDO bar for
certification** vs what's an acceptable tracked **fast-follow**.

### 1. Frame it honestly, up front (30 sec)
"This started as a solo internal prototype and grew. It's not at the
full SDO bar yet, and I'm not asking you to look past that — I've written
down exactly where the gaps are and a phased plan to close them. What I
want from this call is your read on the minimum bar to certify vs what
can be a tracked fast-follow."

### 2. Lead with what's already solid
- Real Brazil package on GitFarm mainline.
- **259 unit tests, all passing** (verified today, ~3 min run).
- Security work already done: least-privilege IAM, bcrypt, self-hosted
  assets, secrets in Secrets Manager, TLS 1.2+, threat model (14
  threats / 0 unmitigated), TPS certs (Asana + Slack), IR plan.
- **App is OUT of production right now** — H1 cycle closed. So there is
  zero live risk while we put proper SDLC in place, and a clean window
  before the H2 cycle (August).

### 3. The gaps, and the plan (don't hide these)
- CRs not historically enforced → **fixing immediately** (Phase 1, CR-
  required branch protection, ~1 hr).
- NoOpBuild, tests not gated → Phase 2 (~1 day).
- No pipeline, manual EC2 deploy → Phase 3 (~3–5 days).

### 4. The concrete asks (get answers to these)
1. **What is the minimum SDO bar to certify?** Specifically: is enforced
   CR-only merge (Phase 1) + documented fast-follow enough, or does the
   pipeline (Phase 3) have to exist before you'll certify?
2. **Does CR enforcement need to be live before you certify, or is a
   committed date acceptable?** (I can enable it on the call.)
3. **Do the 259 tests need to be a build gate for cert, or is
   "documented + ticketed" acceptable given the app is out of prod?**
4. **Will you accept a SIM/Taskei-tracked fast-follow** for Phases 2–4
   with target dates, so cert isn't blocked on the full pipeline?

### 5. What I'll offer proactively
- Enable **CR-required merges on mainline immediately** (today) as a
  good-faith first step.
- Create a **tracking ticket** for Phases 2–4 with owners + target dates
  before the call ends.
- Timeline anchor: **H2 cycle starts August** — pipeline work fits
  before redeploy.

### 6. Leverage / context to keep in pocket
- Package inherits **org-level CRUX rules** (Security Code Scanner,
  Software Assurance, Integration Tests, coverage — all require Pass),
  so once CRs are enforced, those gates apply automatically.
- Data is **Confidential-only** (employee name/email/NPS score); Red
  comes from the Slack 3P scope, not data tier.
- No user impact from any of this work — cycle is done.

### 7. Immediately after the call
- Enable CR enforcement if agreed.
- File the Phase 2–4 tracking ticket with the dates Sripath accepts.
- Update this doc + `asr_engagement_status.md` with the agreed bar.
