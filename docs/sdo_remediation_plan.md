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
| Branch protection | ✅ Enabled on mainline (CRUX-gated) | None |
| Code Reviews (CRs) | ⚠️ Not enforced historically; code pushed direct to mainline during solo build | **Enforce CR-only merges going forward** |
| CI/CD Pipeline | ❌ No pipeline; deployed manually (git pull + systemctl restart on one EC2) | **Stand up Pipelines + Apollo** |
| Automated tests in build | ⚠️ 259 unit tests exist and pass locally, but not wired into a build/pipeline gate | **Run tests in pipeline build stage** |
| No manual prod changes | ❌ Manual deploy to EC2 | **Deploy only via pipeline** |

## What is already solid

- **Brazil package**: `ssh://git.amazon.com/pkg/NPSSurveyAutomation`,
  mainline with branch protection on.
- **Test coverage**: 259 unit tests, all passing
  (`python -m pytest` → 259 passed). Covers repos, services,
  distribution, reminders, dashboard aggregation, auth.
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
- Confirm/enable mainline branch protection so **every change requires a
  CR via CRUX** — no direct pushes.
- Document the CR workflow for the team.
- **Effort**: config change, ~1 hour.

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

## Tracking

- Follow-up ticket for the pipeline work: (to be created)
- Owner: kumruxl@ · Backup: kuvinu@
