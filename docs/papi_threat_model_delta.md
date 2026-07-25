# PAPI DI / Threat-Model / Kale delta — post-PAPI

Companion to `docs/asr_reprofiling_answers.md` (the SLAB pattern). PAPI
directory integration is LIVE in prod; this brings the DI threat model
and Kale privacy record up to date. Current published DI = **v449**
(embedded diagram v283) — publish a new version after these edits.

App: NPS Survey Automation · ASR WHS_AIFA-1763314908 · Owner kumruxl@ ·
Co-owner kuvinu@ · Kale/Veritas 33d9f777-6675-4612-bf3e-640960c021ad.

## What changed since v449

| | v449 (published) | Now (this update) |
|---|---|---|
| Directory lookup | none — prefill from nomination history only | **PAPI People API** (`employeeV2ByLogin`, `expand=supervisor-chain`) resolves any alias to name / title / supervisor chain |
| Auth to PAPI | n/a | **IAM Auth** — EC2 role assumes cross-account role `arn:aws:iam::220627861680:role/IAMAuth_nps_survey_us-east-1` (STS), then SigV4 (service=execute-api). No stored secret/API key. |
| Nominator / leader identity | app session (password) | **Midway (ALB OIDC) `X-Amzn-Oidc-Identity`**, server-side; leader is system-resolved (roster → PAPI supervisor-chain → history), never client-chosen |
| New data element | — | **Employee directory record (name, business title, supervisor-chain logins)** — used **transiently** for form prefill; **NOT persisted** |
| Data classification | Confidential | **Unchanged — Confidential.** name/title/manager are standard-tier directory attributes; no highly-confidential data (no home address, personal phone, DOB) requested |
| Third-party egress | none new | **None** — PAPI is 1P internal Amazon; third-party answers stay No |

Key point for the reviewer: PAPI is an **internal Amazon service**, IAM-auth,
**no secret to leak**, and the directory data it returns is **transient**
(prefill only) — nothing new is stored.

## DI diagram updates (Design Inspector)

The repo reference diagram `docs/nps_architecture_diagram.drawio` is
already updated — import it or mirror these edits in DI:

1. **Trust boundary:** add **"PAPI People API — internal Amazon service
   (acct 220627861680)"** as an *internal* boundary (NOT third-party),
   same treatment as the OPUS SLAB boundary.
2. **Component:** add **PAPI `employeeV2ByLogin` (IAM Auth, SigV4
   execute-api)** in that boundary.
3. **Flow — add** Flask/EC2 → PAPI:
   - Transport HTTPS; auth STS AssumeRole (cross-account IAM role) + SigV4.
   - Data out: alias (Amazon login).
   - Data in: name, business title, supervisor-chain logins — **transient**.
4. **Identity flow (reflect the identity-driven form):** the nominator
   and leader identities are derived from the **ALB Midway header
   server-side**; annotate the User → ALB → EC2 flow that the app trusts
   `X-Amzn-Oidc-Identity` (SG admits ALB only, so it cannot be spoofed)
   and that the leader is **system-resolved, never client-supplied**.
5. **Assets:** add "Employee directory record (name/title/supervisor
   chain)" as a **transient / in-transit** Confidential asset. **No new
   stored asset** and **no new secret** (PAPI is pure IAM auth).
6. Re-run DI threat analysis, re-mark using the justifications below,
   export HTML, upload to the ASR Threat Model task, publish new version.

## Threat-model deltas

- **New (all Mitigated):**
  - Spoofing of the PAPI endpoint → fixed regional PAPI URL
    (`us-east-1.prod.papi.people-data.amazon.dev`) over TLS; SigV4-signed
    with STS-vended credentials from the assumed cross-account role.
  - Tampering in transit (app → PAPI) → HTTPS + SigV4 (payload integrity
    from the signature).
  - Information disclosure of directory data → response used transiently
    for prefill only; **never persisted** and never logged; the app
    stores only the nomination record already documented in v449.
  - Elevation via the cross-account role → the role is IAM-auth, scoped
    to a single allowlisted op (`employeeV2ByLogin`) at TPS 10; the EC2
    role's `AllowAssumePapiRole` is limited to the specific PAPI role ARNs
    (see `infra/iam-policies/AllowAssumePapiRole.json`).
  - Spoofed nominator/leader identity → identity comes from the ALB
    Midway header server-side (instance SG admits ALB only); the leader
    is system-resolved, never taken from the client body.
- **Unchanged:** DynamoDB/SES/Slack/Asana flows; no new stored data; no
  new third-party.

## DI threat-marking — copy/paste justifications

**Spoofing of the PAPI endpoint (mark → Mitigated):**
> Mitigated — calls target the fixed regional PAPI URL
> (us-east-1.prod.papi.people-data.amazon.dev) over TLS. Requests are
> SigV4-signed (service=execute-api) using STS credentials from the
> cross-account IAM-auth role. No unauthenticated path.

**Tampering in transit, app -> PAPI (mark → Mitigated):**
> Mitigated — HTTPS with SigV4 request signing; payload integrity is
> covered by the signature.

**Information disclosure of employee directory data (mark → Mitigated):**
> Mitigated — PAPI returns only standard-tier directory attributes
> (name, business title, supervisor-chain logins). The response is used
> transiently to prefill the nomination form and is never persisted or
> logged; stored data is unchanged from v449 (the nomination record).

**Over-broad cross-account access (mark → Mitigated):**
> Mitigated — the EC2 role may assume only the specific PAPI IAM-auth
> role ARNs (AllowAssumePapiRole); the PAPI client is allowlisted to one
> operation (employeeV2ByLogin) at TPS 10. No secret is stored (pure IAM
> auth), so there is no API key to leak.

**Spoofed nominator / leader identity (mark → Mitigated):**
> Mitigated — nominator identity is read from the ALB-verified Midway
> header (X-Amzn-Oidc-Identity) server-side; the instance security group
> admits only the ALB, so the header cannot be spoofed. The leader is
> system-resolved (roster / PAPI supervisor-chain / history) and is never
> accepted from the client request body.

## Kale (privacy) — app-description delta

Add PAPI as a data SOURCE in the Kale app description (Veritas
33d9f777-...c021ad). Suggested wording:

> The tool calls the internal Amazon People API (PAPI, `employeeV2ByLogin`)
> to resolve an entered Amazon alias to the person's name, business title,
> and supervisor chain, solely to prefill the nomination form and to
> auto-resolve the correct leader. This directory data is standard-tier
> (no highly-confidential attributes), is used transiently at request
> time, and is NOT stored — the only records persisted remain the
> nomination fields already documented (alias/email, name, designation,
> leader, nominated_by). PAPI is a first-party Amazon service accessed via
> IAM auth; no employee data is sent to any third party for this lookup.

No new Kale data OBJECT is required (nothing new is stored). If Kale asks
"where does this field originate," the source for name/title/leader is
now PeopleAPIService (PAPI) in addition to the existing sources.

## Not changed (confirm, don't re-open)

- ASR profiling answers: **no change** — PAPI is 1P internal; third-party
  answers stay No; data stays Confidential. Do not re-profile for PAPI.
- No new secret, no Secrets Manager entry for PAPI (IAM auth only).

## Checklist

- [ ] Import/mirror the updated drawio into DI (PAPI boundary + flow +
      identity-flow annotation)
- [ ] Re-run DI threat analysis; mark new threats Mitigated (text above)
- [ ] Export HTML, attach to ASR Threat Model task, publish new version
      (supersedes v449)
- [ ] Kale: add the PAPI data-source paragraph to the app description
- [ ] Kale: if the Tax/Accounting financial branch resurfaces, answer
      "no financial data" (false positive, non-blocking)
