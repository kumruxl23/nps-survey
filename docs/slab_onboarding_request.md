# SLAB Onboarding Request — replace Slack `users:read` to exit Red ASR

Purpose: onboard to SLAB's **`OpusUsersGetSlackIDFromAlias`** API so the
NPS Survey app can resolve a Slack user ID from an Amazon alias WITHOUT
the high-risk `users:read` scope. Per AmazonUC-SIGNAL/OPUS guidance
(Farzin Nickman), dropping `users:read` in favour of SLAB avoids the Red
ASR entirely. Onboarding SLA ~7 days.

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

## Code swap (once onboarded)

In `app/services/nps_distribution_service.py`, both Slack lookup sites
change from email→Slack to alias→SLAB:

```python
# before
lookup_email = base_email(nomination.email)
slack_user_id = slack_client.lookup_user_by_email(lookup_email, bot_token)

# after
alias = slab_client.alias_from_email(nomination.email)
slack_user_id = slab_client.lookup_slack_id_by_alias(alias)
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
