# SLAB Onboarding Request — replace Slack `users:read` to exit Red ASR

Purpose: onboard to SLAB's **`OpusUsersGetSlackIDFromAlias`** API so the
NPS Survey app can resolve a Slack user ID from an Amazon alias WITHOUT
the high-risk `users:read` scope. Per AmazonUC-SIGNAL/OPUS guidance
(Farzin Nickman), dropping `users:read` in favour of SLAB avoids the Red
ASR entirely. Onboarding SLA ~7 days.

## Status

**Onboarding ticket: D490668297** (Opus-SLAB-Onboarding template, Prod) —
https://t.corp.amazon.com/D490668297/overview — status Assigned. Method:
OpusUsersGetSlackIDFromAlias; security review N/A. Verify Role ARN +
Environment=Prod under the Information tab. Awaiting prod API key comment.

Initial general query ticket (superseded): **D490637982** —
https://t.corp.amazon.com/D490637982

SIGNAL response: technical specs are on the KB page
https://w.amazon.com/bin/view/AmazonUC/SIGNAL/OPUS/KB/SLAB
Confirmed: API key is passed as an `x-api-key` header (matches
`slab_client.py`); one ARN per ticket (ours provided); include ASR ref
WHS_AIFA-1763314908 for production access; API key issued in ticket
correspondence after approval.

**Onboarding CR MERGED: CR-289008613** (OpusSLABCDK, "onboard 2 SLAB
clients Phase B"). Our role `arn:aws:iam::399016860083:role/nps-survey-ec2-role`
added to prod allowlist for `OpusUsersGetSlackIDFromAlias`
(allowAccessToProdEndpoints: true). Config at `lib/config/clientDetails.ts`;
method enum `SlabApiMethod.UsersGetSlackIDFromAlias`. GetSlackID needs NO
AppSec review (confirmed in CR). **Next: pipeline deploy to prod → API key
minted and posted to ticket D490668297.**

## KEY FINDING — supported integration is the OpusSLABPythonSDK (Brazil/Coral)

From the SLAB Python SDK README, the intended integration is NOT a raw
HTTPS call:
- `OpusSLABPythonSDK` is a **Brazil version-set package** (declare it as a
  direct dependency + merge into the version set).
- Endpoint is resolved at runtime from **coral-config**
  (`conf.get("OpusSLAB", "Base.Prod")["httpEndpoint"]["url"]`) — no static
  URL to hardcode; needs a Brazil/Apollo runtime with coral-config.
- Signing is **SigV4a** (`signature_version="v4a"`, `region="global"`),
  requires `Aws-crt-python`. (Our interim `slab_client.py` uses plain v4.)
- Client call: `client.opus_users_get_slack_id_from_alias(userAliases=[...])`
  — request field is **`userAliases`** (confirmed). Response has `ok` and
  `ResponseMetadata.HTTPStatusCode`.
- API key via `x-api-key` header (confirmed, matches our code).

### Decision: SDK-via-pipeline vs hand-rolled interim

- **Option A (recommended):** adopt the SDK as part of the Brazil/Apollo
  pipeline conversion (SDO Phase 3). Clean, supported, and satisfies the
  certifier's pipeline ask in one stroke.
- **Option B (interim):** keep the hand-rolled `slab_client.py`, but then
  we need (1) the raw prod endpoint URL (from OpusSLABClientConfig / ask on
  ticket) and (2) switch signing to SigV4a (`aws-crt-python`). Fragile;
  diverges from supported usage.

Slack DMs are NOT needed for the demo (email-only), so no rush. Prefer
Option A alongside the pipeline work.

Still needed either way:
- Prod API key (store in Secrets Manager nps-survey/slab-api-key) — RECEIVED
  (in ticket D490668297); store securely + rotate later (shared in plaintext).
- Option B only: raw prod endpoint URL + SigV4a signing.
- Confirm response results field name (from the OpenAPI / index.html).

Still needed from the KB / ticket to finalize:
- API endpoint URL for OpusUsersGetSlackIDFromAlias
- Request/response schema (alias-in field, slack-id-out field)
- SigV4 service name + region
- Throttling/usage limits
- API key (store in Secrets Manager `nps-survey/slab-api-key`)

## Contact route (confirmed)

Primary path is a **SIGNAL queue ticket** (~7-day SLA). OPUS Office Hours
are booked out until mid-August, and the technical specs
(endpoint/schema/service name/API-key process) are NOT documented in the
channel — the SIGNAL team provides them via the ticket. Warm contact:
Farzin Nickman (answered in the OPUS channel); tag him with the ticket
link to accelerate.

## Request to send (AmazonUC-SIGNAL / OPUS / SLAB queue)

> Requesting onboarding to SLAB `OpusUsersGetSlackIDFromAlias`.
>
> **App:** NPS Survey Automation (internal NPS surveys for WHS CPT IN/NA,
> FEC leadership). ASR app WHS_AIFA-1763314908 (currently Red due to the
> Slack `users:read` scope).
> **Owner:** kumruxl@ · **Backup:** kuvinu@
> **AWS account:** 399016860083 (ap-south-1) · runs on EC2
> i-06ccd83e4b55fa98f under IAM role `nps-survey-ec2-role`.
>
> Goal: replace the Slack `users.lookupByEmail` call (needs `users:read`)
> with SLAB alias→Slack-ID lookup, so we can drop `users:read` and exit
> the Red ASR. The bot will then only hold `chat:write` for posting
> reminder DMs.
>
> Please advise on:
> 1. Onboarding steps + the API contract (endpoint URL, request/response
>    schema, SigV4 service name).
> 2. How to obtain the API key and the caller identity/allowlisting we
>    need (our EC2 role ARN above).
> 3. Any usage limits/throttling we should design for (we do batched
>    per-cycle reminder lookups, low volume).

## What we need back (to finalize the code)

The code (`app/services/slab_client.py`) is already written and tested;
these values are env-overridable constants so finalizing is a CONFIG
change, not a code change:

| Constant / env | Meaning | Status |
|---|---|---|
| `SLAB_ENDPOINT` | Full `OpusUsersGetSlackIDFromAlias` URL | **Need from onboarding** |
| `SLAB_REGION` | Region for SigV4 signing | Confirm (default us-east-1) |
| `SLAB_SERVICE_NAME` | SigV4 service name | Confirm (default execute-api) |
| `SLAB_API_KEY_SECRET_ID` | Secrets Manager id for the API key | We create: `nps-survey/slab-api-key` |
| `REQUEST_ALIAS_FIELD` | JSON field carrying the alias | Confirm (assumed `alias`) |
| `RESPONSE_SLACK_ID_FIELD` | JSON field with the Slack ID | Confirm (assumed `slackId`) |

## Onboarding flow (from the SLAB KB)

Decision: **onboard straight to Prod, skip Gamma.** For
`OpusUsersGetSlackIDFromAlias`, prod needs **no appsec review**, and Gamma
only resolves users in the Slack sandbox grid (and requires a Sandbox ID /
provisioned sandbox) — useless for resolving real stakeholders. So Gamma
adds setup for no value here.

Onboarding template (private SIM), custom fields:
- **Role arn:** `arn:aws:iam::399016860083:role/nps-survey-ec2-role`
- **Environment:** Prod
- **Nonadminappuserid:** blank (admin-methods only)
- **Sandbox id:** blank (Gamma only)
- Security-review line: N/A (only OpusUsersGetSlackIDFromAlias)

Prereq: the IAM role must already have `execute-api:Invoke`
(`infra/iam-policies/AllowInvokeSlab.json`). Prod returns the API key as a
ticket comment; store in Secrets Manager `nps-survey/slab-api-key`.

## API contract (from KB; confirm field names from Python client docs)

- **Batch**: up to **600 aliases** per call (dupes count toward the limit).
- Aliases are case-insensitive; returned IDs are lowercase-keyed.
- Response: `ok` (bool), `aliasesNotFound` (definitive misses — don't
  retry), `aliasesUnprocessed` (transient — safe to retry). Success-map
  field name still to confirm (code defaults to `slackIds`, configurable).

## Code swap (once onboarded)

`app/services/slab_client.py` is written for the batch contract with a
single-alias convenience wrapper. Two options for
`nps_distribution_service.py`:

Simple (per-nomination, keeps current caching):
```python
# after
alias = slab_client.alias_from_email(nomination.email)
slack_user_id = slab_client.lookup_slack_id_by_alias(alias)
```

Better (batch — one call per ~600 non-respondents):
```python
aliases = [slab_client.alias_from_email(n.email) for n in non_respondents]
id_map = slab_client.lookup_slack_ids_by_aliases(aliases)
# then per nomination: slack_user_id = id_map.get(alias)
```

- Catch `slab_client.SlackUserNotFoundError` (same handling as today).
- `send_dm` (chat.postMessage) is unchanged — still uses the bot token.
- The per-nomination `slack_user_id` caching stays as-is.

## IAM / secrets follow-ups (when onboarded)

- Add `secretsmanager:GetSecretValue` on `nps-survey/slab-api-key*` to
  `nps-survey-ec2-role` (mirror the existing Asana PAT grant).
- If SLAB authorizes by caller identity, share the role ARN above.

## After the swap

- Remove `users:read` (and `users:read.email`) from the Slack app scopes;
  keep only `chat:write`.
- Ask OPUS/ASR to confirm the reclassification out of Red.
- Retire `app/services/slack_client.lookup_user_by_email` (keep `send_dm`).
