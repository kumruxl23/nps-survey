# ASR Re-profiling — post-SLAB (to reclassify out of Red)

Per the certifier: ASR classification is derived from the **profiling
task answers + the DI diagram**. Re-submit both to reflect that the app
no longer uses the high-risk Slack `users:read` scope — the Slack user-ID
lookup now goes through OPUS's **internal Amazon** SLAB API.

App: NPS Survey Automation · ASR WHS_AIFA-1763314908 · Owner kumruxl@ ·
Co-owner kuvinu@.

## The one change that drives the reclassification

| | Before (Red) | After (this resubmission) |
|---|---|---|
| Slack scopes | `chat:write`, `users:read.email`, **`users:read` (HIGH)** | **`chat:write` only** |
| Email→Slack-ID lookup | Slack `users.lookupByEmail` (employee email sent to Slack directory; needs `users:read`) | **OPUS SLAB `OpusUsersGetSlackIDFromAlias`** — internal Amazon service (SigV4a + `x-api-key`), alias in / Slack ID out |
| Employee email egress to 3P | Yes (for directory lookup) | **No** — email/alias resolution stays inside Amazon |
| Slack API calls | `users.lookupByEmail` + `chat.postMessage` | **`chat.postMessage` only** |
| High-risk scope present | Yes | **No** |

Net: the sole Red trigger (`users:read`, granting full Enterprise-Grid
directory access) is removed. Remaining Slack interaction is `chat:write`
(posting a 1:1 DM) — low risk.

## Profiling questionnaire — answer guidance (before → after)

- **High-risk / privileged third-party scopes?**
  Before: Yes — Slack `users:read`. **After: No.** Slack app holds only
  `chat:write`.
- **Non-public Amazon data shared with a third party (SaaS)?**
  Before: Employee email sent to Slack to resolve identity.
  **After: No directory data sent to Slack.** To Slack we send only a
  resolved Slack user ID + the reminder message text (to post a DM).
  Identity resolution is via an **internal Amazon** API (OPUS SLAB).
- **Data classification:** Unchanged — **Confidential** employee data
  (name, email, NPS score, free-form feedback). No customer data, no
  SSN/financial/home address/phone/DOB.
- **New internal dependencies:** OPUS SLAB (`opusslab`), account-to-account
  via API Gateway, SigV4a auth (IAM role `nps-survey-ec2-role`) + API key
  in Secrets Manager (`nps-survey/slab-api-key`).
- **Internet exposure:** Internal only. Currently OUT of production;
  redeploy planned behind Midway/ALB (SSO at the edge).
- **Authentication:** App-local accounts today (bcrypt); Midway/SSO planned.
- **AppSec review for the SLAB method:** Not required
  (`OpusUsersGetSlackIDFromAlias` is exempt per OPUS KB).

## DI diagram updates (Design Inspector)

1. **Trust boundaries:** add **"AmazonUC / OPUS SLAB — internal Amazon
   service"** as an *internal* boundary (NOT a third-party box). This is
   the crux: the identity lookup is now Amazon-internal, not 3P.
2. **Components:** add **SLAB API (`opusslab`, API Gateway, SigV4a)** in
   that internal boundary. Add **Secrets Manager: `nps-survey/slab-api-key`
   (Secret)**.
3. **Flows — replace old flow #6:**
   - **Remove** Flask → Slack `users.lookupByEmail` (email out).
   - **Add** Flask → **SLAB API**: HTTPS, SigV4a (IAM role) + `x-api-key`,
     data = alias out / Slack user ID in. Internal Amazon.
   - **Keep/relabel** Flask → Slack `chat.postMessage`: HTTPS, Bearer bot
     token, data = Slack user ID + DM body only.
4. **Scopes note:** Slack app = `chat:write` only (drop `users:read` +
   `users:read.email`).
5. **Assets:** add SLAB API key (Secret, Secrets Manager). Slack user ID
   stays Confidential (now sourced from SLAB, not Slack).
6. Re-run DI threat analysis, re-mark, export HTML, upload to the ASR
   Threat Model task.

## Threat-model deltas

- **Removed:** "Misuse of `users:read`" — scope no longer requested.
- **Reduced:** "Employee email disclosure to 3P for lookup" — no longer
  sent to Slack.
- **New (all Mitigated):**
  - Spoofing of SLAB endpoint → fixed OPUS API Gateway URL over TLS,
    SigV4a request signing, `x-api-key` header.
  - Tampering in transit (app→SLAB) → HTTPS + SigV4a.
  - API-key leak → stored in Secrets Manager, read-only to
    `nps-survey-ec2-role` (`AllowReadSlabApiKey`); rotate via ticket.
- **Unchanged:** Slack bot-token handling; `chat.postMessage` is
  outbound-only; no Slack callback/event surface.

## Sequencing note

The code swap to SLAB is Option A (via the pipeline/Brazil conversion,
SDO Phase 3). Interim state until then is **email-only** (Slack DMs off),
which is already not-Red on its own. Re-profiling now reflects the target
design so the classification is corrected ahead of the wiring.
