# ASR Engagement Status — NPS Survey Reminder Slack workspace install

Snapshot of the Amazon Security Review (ASR) and related security
workflows as of 2026-06-01. Update this file whenever a task status
changes so the work doesn't get lost across sessions.

## Engagement identifiers

| Item | Value |
|---|---|
| ASR Application Name | WHS_AIFA-1763314908 |
| ASR Application ID | 33d9f777-6675-4612-bf3e-640960c021ad |
| ASR URL | https://asr.security.amazon.dev/applications/33d9f777-6675-4612-bf3e-640960c021ad |
| Bindle | WHS_AIFA |
| Owner | kumruxl@ |
| Backup | kuvinu@ (planned) |
| Classification | Red, Ring-3, Red Rank Score 3.39 |
| Profiles | Baseline + Red + Third Party Security |
| Code package | ssh://git.amazon.com/pkg/NPSSurveyAutomation |
| Slack workspace | T016NEJQWE9 (Amazon enterprise) |
| Slack app | NPS Survey Reminders (install request submitted, blocked on ASR) |

## Why we're going through ASR

Slack workspace admin (AmazonUC-SIGNAL) requires a Talos / ASR engagement
ARN before approving the bot install. Slack flagged `users:read` as
high-risk; `users:read.email` requires it as a parent scope per Slack
platform rule. Bot only calls `users.lookupByEmail` and `chat.postMessage`
— no event subscriptions, no callbacks. Full reasoning in
`docs/slack_talos_review_request.md`.

## ACTIVE PIVOT — exit Red by dropping `users:read` (SLAB)

Per AmazonUC-SIGNAL/OPUS guidance (Farzin Nickman): `users:read` is
classified High-risk because it grants the full Enterprise Grid directory,
regardless of us only calling `users.lookupByEmail`. There is **no 1P
shortcut** — but we can **avoid the Red ASR entirely** by dropping
`users:read` and using SLAB's `OpusUsersGetSlackIDFromAlias` API
(alias→Slack ID, SigV4 + API key, internal Amazon service). Their Red ASR
took ~7 weeks; SLAB onboarding SLA is ~7 days.

Decision: pursue SLAB in parallel while keeping the Red ASR warm as
fallback. Once SLAB is live and `users:read` removed, ask OPUS/ASR to
confirm reclassification out of Red.

Progress:
- [x] `app/services/slab_client.py` written (alias derivation + SigV4 +
      API-key SLAB lookup; endpoint/schema are env-overridable pending
      onboarding). 13 unit tests passing.
- [x] Fire SLAB onboarding request — SIGNAL ticket **D490637982**
      (https://t.corp.amazon.com/D490637982). Awaiting API contract.
- [ ] Confirm API contract (endpoint, request/response fields, service).
- [ ] Create `nps-survey/slab-api-key` secret + IAM grant.
- [ ] Swap the two lookup sites in `nps_distribution_service.py`.
- [ ] Remove `users:read` from the Slack app; keep only `chat:write`.
- [ ] OPUS/ASR confirm reclassification out of Red.

## Task status

### Application Owner tasks — DONE

| Task | Status | Evidence |
|---|---|---|
| Threat Model (Baseline) | ✅ Complete | DI project NPSSurveyReminders, 14 threats triaged (13 Mitigated + 1 False Positive), exported HTML uploaded |
| Permissions (Red) | ✅ Complete | IAM role `nps-survey-ec2-role` scoped to least privilege; AmazonDynamoDBFullAccess + AmazonSESFullAccess replaced with AllowNpsDynamoDB + AllowNpsSESSend (see `infra/iam-policies/`) |
| Incident Response Plan (Red) | ✅ Complete | `docs/incident_response_plan.md` |
| Third Party Security Review | ✅ Complete | TPTA0027224 (Asana) + TPTA0050664 (Slack), both Tier 4, "Amazon 3P Security Bar Met" |

### Application Owner tasks — BLOCKED on external

| Task | Status | Blocked on |
|---|---|---|
| Privacy Compliance Review (Baseline) | Incomplete | Kale review awaiting privacy reviewer (kale-wrkplace-hlth-safety group); Veritas ID 33d9f777-...c021ad |
| Resolve Required Issues (Baseline) | Incomplete | Privacy Compliance must complete first |

### Reviewer-assigned tasks — BLOCKED on reviewer assignment

| Task | Status | Notes |
|---|---|---|
| Automated Code Review (Red) | Incomplete | Reviewer-side; we uploaded local Bandit CSV (487 Low, 0 Medium, 0 High, all auto-triaged FP) to give the reviewer a head start |
| Review Threat Model (Red) | Incomplete | Reviewer-side |
| Threat Mitigation Testing (Red) | Incomplete | Reviewer-side |
| Manual Code Review (Red) | Incomplete | Reviewer-side; package linked: NPSSurveyAutomation |

## Reviewer Status

- ASR reviewer: **sripathb@amazon.com** agreed to certify (SC under L8 org,
  currently reviewing another Red app). Found via
  https://reviewers.security.amazon.dev/reviewers. No other certifiers in
  our org chain.
- Kale reviewer group: **kale-wrkplace-hlth-safety** — CANNOT be changed;
  derived from the Access Control Bindle's team ownership (confirmed by
  Smruthi on P441140532). Kale is mapped to the ASR; awaiting reviewer
  pickup.

## Why this is a Red review (not Yellow)

The Red classification is NOT from data tier — the app only handles
Confidential data (employee name/email/NPS scores). The Red comes from
the **third-party Slack integration's access profile**:
- high-risk `users:read` scope (parent of `users:read.email` per Slack)
- `chat:write` (write access into the Slack workspace)
- sharing non-public Amazon data (employee email -> Slack user ID) with a
  third-party SaaS

This is a legitimate Red trigger regardless of data classification. Do NOT
attempt to reclassify down to Yellow — the Red is correct.

## Related tickets

- **P441140532** — Smruthi comms thread (Kale↔ASR mapping, reviewer group)
- **P451747385** — SC Core team, how to find a Security Certifier
- **D465560471** — "Uncertified Red Application In Production" campaign SIM;
  filed with business justification + compensating controls. Release date
  2026-04-01 confirmed accurate, NOT changed (scenario 1).

## Production status (2026-06-17)

The application has been taken OUT of production. The H1 2026 NPS cycle
closed; the app was used to demo the dashboard to leaders and is no
longer actively serving. `nps-survey.service` is stopped + disabled on
EC2 i-06ccd83e4b55fa98f (optionally the instance is stopped too).

Rationale: clears the "Uncertified Red Application in Production"
Shepherd finding without user impact (cycle is done). DynamoDB data is
untouched and persists independently of the EC2.

Re-deployment plan: bring the service back ONLY after the ASR review is
certified, for the H2 2026 cycle. Do not return to production
uncertified.

## Shepherd findings status (2026-06-17)

| Finding | State |
|---|---|
| Javascript Resources Hosted on External CDNs | Fixed — Bootstrap self-hosted (commit ffacccb), deployed; auto-resolves next scan |
| Update operating system | Fixed — AL2023 kernel upgraded + rebooted, dnf-automatic enabled; auto-resolves next scan |
| Uncertified Red App (live 33d9f777) | Clears — app taken out of production 2026-06-17; SIM D465560471 updated |
| Uncertified Red App (orphan 556dfa31) | Duplicate; clear via ASR support merge/remove. Do NOT use ring dispute. |

## Open dependencies

1. **Kale reviewer assignment** — 5-day SLA from Smruthi (06/03/2026). Sent reply asking about the right reviewer group.
2. **ASR reviewer assignment** — typical SLA 1-3 business days.
3. **AmazonUC-SIGNAL Slack install approval** — gated on this ASR completing.
4. **CTI confirmation** — placeholder TBD; need manager confirmation. Wrong CTI routes follow-up tickets incorrectly.
5. **Backup PAT holder (kuvinu@)** — file follow-up on P426628259.

## Things to do once reviewers respond

- Triage any OneSAST findings the security reviewer surfaces in Automated Code Review
- Address any Privacy Compliance follow-up questions from Kale reviewer
- Once both are clean, the certification flips green and we get the engagement ARN
- Paste the engagement ARN back into the original Slack install request to unblock workspace install

## Operational notes

- Code repo: GitFarm (authoritative) + GitHub mirror at github.com/kumruxl23/nps-survey (laptop dev)
- IAM policies live in `infra/iam-policies/` (intentionally un-ignored from infra/)
- Bandit CSV converter at `scripts/bandit_to_shepherd_csv.py`
- DI project at https://design-inspector.a2z.com/#NPSSurveyReminders

## Related artifacts (in repo)

- `docs/slack_talos_review_request.md` — Slack security review writeup
- `docs/asr_threat_model_workbook.md` — Threat model rationale + STRIDE playbook
- `docs/incident_response_plan.md` — IR runbook
- `docs/nps_architecture_diagram.drawio` — DI architecture diagram XML source
- `infra/iam-policies/` — least-privilege policies for nps-survey-ec2-role
