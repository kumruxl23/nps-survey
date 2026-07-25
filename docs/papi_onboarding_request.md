# PAPI (People API) Onboarding — Directory-backed prefill

Goal: resolve ANY Amazon alias on the nomination form — full name, job
title, and the right leader (walk the manager chain up until we hit
someone on the org's leader roster). Replaces the history-only prefill
limitation; required for multi-org rollout across Amazon.

## Why PAPI

PAPI (People API) is the Tier-1 internal service behind PhoneTool data:
employee lookup by login, autocomplete, manager chain. Non-highly-
confidential attributes (name, title, manager, login, email) are
standard-tier and auto-approve through self-service onboarding.
We do NOT need HC data (addresses, personal phones) — do not request it.

## Step 1 — UBX self-service onboarding (kumruxl, ~10 min, browser)

1. Go to https://onboard.papi.people-data.amazon.dev
2. Create application: `nps-survey`
3. Authentication scheme: **IAM Auth** (we're NAWS — EC2 + IAM role)
4. Endpoints (be minimal):
   - `employeeV2ByLogin` — GET /v2/employee/login:{alias} (name, title,
     manager — the prefill + leader-chain walk)
   - `employeeSearchV2AutoCompleteLogin` — optional, for future alias
     autocomplete in the form; include it now to avoid a re-submit
5. AWS account IDs: **399016860083** (prod; add any future stages now —
   forgetting one means AccessDenied later and a re-submit)
6. Submit. Non-sensitive endpoints auto-approve in minutes; the SIM
   comment will contain the cross-account role ARNs, shaped like:
   `arn:aws:iam::220627861680:role/IAMAuth_nps-survey_us-east-1` (prod)

## Step 2 — App configuration (done in code, flips on via env)

The app-side client is already implemented (`app/services/papi_client.py`),
gated on env vars. Once the role ARN arrives, set in the systemd
override and restart:

```
Environment=PAPI_ROLE_ARN=arn:aws:iam::220627861680:role/IAMAuth_nps-survey_us-east-1
Environment=PAPI_ENDPOINT=https://papi.amazon.com
```

Auth flow: EC2 role -> STS AssumeRole(PAPI role) -> SigV4-signed HTTPS
(service=execute-api). Add `AllowAssumePapiRole` (in
`infra/iam-policies/`) to `nps-survey-ec2-role`.

## Step 3 — Compliance deltas (before H2 traffic)

- **Threat model (DI)**: add PAPI as an internal Amazon service boundary
  (same pattern as OPUS SLAB, v449) + data element "employee directory
  record (name/title/manager)" in transit. Publish new version.
- **Kale**: no new stored data — PAPI responses are used transiently for
  prefill; what gets STORED is still the nomination record already
  documented. Add PAPI to the app description as a data source.
- **ASR**: no profiling answer changes — PAPI is 1P internal
  (third-party answers stay No); data remains Confidential.

## Leader resolution algorithm ("highest leader within span")

Roster per org = the sponsor's directs (e.g., Sandeep's directs).
For a nominator alias: fetch employee -> manager -> manager... (max 10
hops); the FIRST ancestor (or self) whose login is on the org's leader
roster is the leader. Self counts first, so a roster leader resolves to
themselves. Works identically for any org once its roster is entered.

## Fallback order in the app

1. PAPI (when configured) — any Amazon alias
2. Leader roster + nomination history (today's behavior)
3. Manual entry with a hint

## Status

- [x] UBX intake completed (2026-07-25): attributes trimmed to Public-only
      set (login, preferredName, workEmail, jobTitle, supervisorChainLogin,
      reportingChainInformation); endpoint employeeV2ByLogin only; IAM
      auth, client `nps_survey`, account 399016860083 (gamma+prod),
      TPS 10. Data dictionary completed in catalog.hcm-data.amazon.dev
      (6 rows, sources = PeopleAPIService; slack_user_id row moved to
      Kale-only — SLAB not in FPDS source catalog).
- [x] **Privacy review: GREEN LIGHT** (no DPIA; auto-approved except ERB
      countries). SIM 65afe819-3c61-460c-a051-2f577949870f.
- [ ] ERB scoping questionnaire (SIM 40fc8061-b0c4-421b-8c4c-c6e3a912a923,
      tag @souzaja) — deployment is IN/US/CA only (non-ERB), expect out
      of scope; 5-6 week clock, non-blocking for current launch.
- [x] UBX submitted → auto-onboarded SAME DAY (gamma + prod). SIM
      V2300729875 (resolved) has the role ARNs. Allowlisted op:
      employeeV2ByLogin; account 399016860083.
- [x] **LIVE IN PROD (2026-07-25)**: AllowAssumePapiRole attached;
      env PAPI_ROLE_ARN=arn:aws:iam::220627861680:role/
      IAMAuth_nps_survey_us-east-1, PAPI_ENDPOINT=
      https://us-east-1.prod.papi.people-data.amazon.dev (IAM-auth
      regional URL — papi.amazon.com is CORP/CloudAuth only).
      Gotchas fixed: SigV4 query pre-encoding; valid expand option is
      `supervisor-chain` (full upward chain in one call — client scans
      it, no hop-walking). Verified live: kumruxl/kuvinu resolve
      name+title, source=papi.
- [x] papi_client.py + single-call chain resolution + tests (370 green)
- [ ] Leader rosters per org (ONLY remaining blocker for leader
      auto-select — chain data verified flowing)
- [ ] ERB questionnaire (SIM 40fc8061, non-blocking for IN/NA launch)
- [ ] DI threat model updated + published (add PAPI internal boundary)
- [ ] Kale description updated (add PAPI as data source)
