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

- **Option A (recommended long-term):** adopt the SDK as part of the
  Brazil/Apollo pipeline conversion (SDO Phase 3). Clean, supported, and
  satisfies the certifier's pipeline ask in one stroke.
- **Option B (interim — NOW IMPLEMENTED):** hand-rolled `slab_client.py`
  calling the raw HTTPS endpoint. Both unknowns are now resolved:
  1. **Endpoint** — confirmed from `OpusSLABClientConfig/coral-config/OpusSLABProd.config`
     (the source of truth): `https://api.prod.slack-admin.enterprise-engineering.aws.dev`.
     The Coral REST/JSON binding maps the method to `/opus.users.getSlackIdFromAlias`,
     so the full URL is baked in as `DEFAULT_SLAB_ENDPOINT`.
  2. **Signing** — switched to **SigV4a** via botocore's CRT signer
     (`botocore.crt.auth.CrtSigV4AsymAuth`, service `execute-api`,
     region-set `*`). Region `*` makes the signature valid at whichever
     regional gateway latency-based DNS routes us to — important because
     our EC2 is in ap-south-1, which may have no local SLAB deployment.
     Added `awscrt` to `requirements.txt`. Response parsing uses the real
     `aliasToSlackIdMap` contract (`{alias, slackId, isActive}`;
     `isActive:false` treated as not-found).

This matches the raw-HTTPS pattern used by production SLAB consumers
(EMRClusterTerminationLambda, CIASHIFTApi) but with SigV4a instead of
plain v4 for cross-region robustness.

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
| `SLAB_ENDPOINT` | Full method URL | **CONFIRMED** `https://api.prod.slack-admin.enterprise-engineering.aws.dev/opus.users.getSlackIdFromAlias` |
| `SLAB_REGION` | SigV4a region-set | **CONFIRMED** `*` (multi-region active-active) |
| `SLAB_SERVICE_NAME` | SigV4 signing service | **CONFIRMED** `execute-api` |
| `SLAB_API_KEY_SECRET_ID` | Secrets Manager id for the API key | `nps-survey/slab-api-key` (create + populate — see below) |
| `REQUEST_ALIASES_FIELD` | JSON field carrying aliases | **CONFIRMED** `userAliases` |
| `RESPONSE_RESULTS_FIELD` | JSON field with results | **CONFIRMED** `aliasToSlackIdMap` (list of `{alias, slackId, isActive}`) |

**API key:** issued and posted to onboarding ticket **D490668297** (now
Closed, resolution "API Key Created"). Do NOT paste the raw key into the
repo — pull it from the ticket and store it in Secrets Manager (below).
For local testing only, export it as `SLAB_API_KEY`.

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
