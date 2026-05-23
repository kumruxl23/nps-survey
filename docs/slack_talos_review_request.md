# Talos AppSec Review — NPS Survey Reminder Slack App

Engagement template for the AmazonUC-SIGNAL Talos review required to install
the **NPS Survey Reminder** Slack app.

> **Why this is needed:** Slack flagged `users:read` as a high-risk scope.
> `users:read.email` requires `users:read` as a parent scope (Slack platform
> rule), so we cannot drop it. AmazonUC-SIGNAL therefore requires a Talos
> AppSec engagement before approving the workspace install.

## App identity

- **App name:** NPS Survey Reminders
- **Slack workspace:** Amazon (T016NEJQWE9)
- **Owner:** kumruxl@ (Rohit Kumar), WHS CPT IN team
- **Backup owner:** kuvinu@ (planned, not yet assigned)
- **Source repo:** https://github.com/kumruxl23/nps-survey
- **Deployed at:** https://15-206-208-196.nip.io/nps/dashboard
- **AWS account:** 399016860083 (region ap-south-1)
- **Hosting:** Single EC2 instance (i-06ccd83e4b55fa98f), nginx + Let's Encrypt
- **CTI:** WHS-India / Computer-Vision / AIFA (verify before submission)

## Purpose

Send per-stakeholder reminder DMs to people who haven't responded to the
internal NPS Survey for WHS CPT IN, WHS CPT NA, and FEC org leadership.
Email is the primary channel today; Slack DMs are an additional opt-in
channel admins can enable per org via the existing admin UI.

## Scopes requested and why

| Scope | Risk per Slack | Endpoint(s) used | Why it is required |
|---|---|---|---|
| `chat:write` | Low | `chat.postMessage` | Send 1:1 DM with the survey link |
| `users:read.email` | Low | `users.lookupByEmail` | Map a stakeholder email -> Slack user id (one-time per stakeholder, cached on the Nomination row) |
| `users:read` | High | (parent of `users:read.email`, no direct call) | Slack requires this as parent scope of `users:read.email`. Our app does NOT call `users.list`, `users.info`, or any other endpoint enabled by it. |

**Endpoints actually called** (verify by reading
`app/services/slack_client.py`):
- `https://slack.com/api/users.lookupByEmail`
- `https://slack.com/api/chat.postMessage`

No other Slack endpoints are touched. No incoming events, slash commands,
interactivity payloads, webhooks, or shortcuts.

## Data handling

- **Inputs from Slack:** Slack user id (`U…`) returned by `users.lookupByEmail`
  for stakeholders whose email is on the targeted list.
- **Stored in DynamoDB (`NpsNominations` table):** `slack_user_id` field on
  each nomination row, used to skip the lookup on subsequent sends. No
  message content, no timestamps beyond `responded_at`.
- **Outbound:** the bot sends the survey link DM. Bot does not read,
  archive, or process any DM responses.
- **Bot token storage:** `OrgConfig.slack_bot_token` in DynamoDB
  (per-org, encrypted at rest, accessible only by the EC2 IAM role
  `nps-survey-ec2-role`). The admin UI redacts the value on read.
- **Rotation:** admins rotate by editing the org in
  `/nps/orgs/view`. Old token is overwritten in place.
- **Logging:** Send attempts logged to `NpsReminderLogs`; failures (incl.
  `users_not_found`, transport errors) logged to `NpsDeliveryFailures`.
  Logs include the deliverable email and a textual error reason. No
  Slack message content is ever logged.

## Data classification

- **Customer data:** None. The app does not handle AWS customer or Amazon
  retail customer data.
- **Employee data:** Yes — Amazon employee email addresses, names, and
  optionally Slack user IDs. No SSN, bank info, home address, phone, or
  birthday.
- **Conversation data:** None. Bot is outbound-only.
- **Special region data:** None. Standard ap-south-1.

## Volume

- ~80 stakeholders across 3 orgs total
- ~5 reminder sends per cycle (4 cycles / year => ~20 sends/year * 80 = 1,600 DMs/year peak)
- Well below Slack tier 3 rate limits

## Authorization model

- App is internal Amazon, gated by local username/password today
  (`/nps/login`). Migration to Midway is on the roadmap.
- Only `admin` role can edit org configs (i.e. paste/rotate the bot token).
- Only `admin` and `editor` can trigger reminder sends.
- `viewer` role has read-only dashboard access, cannot send.

## Threat model summary

| Threat | Mitigation |
|---|---|
| Token leak from DynamoDB | IAM role-scoped read; admin-only redacted UI; rotate by overwrite |
| Token leak in logs | Token never logged; `slack_client` only logs error strings, not auth headers |
| Replay / impersonation against our app | App does NOT expose any Slack callback endpoints (no events, no slash commands), so no Slack signature verification is required |
| Misuse of `users:read` | Code review point: only `slack_client.py` uses Slack APIs; greppable surface is two URLs. Linter or pre-commit hook can pin these. |
| Sending to wrong workspace | Per-org bot token stored in `OrgConfig`; cross-org DMs not possible because bot only acts on the calling org's nominations |

## What this review is NOT

- Not asking for any user-data scopes beyond email
- Not subscribing to Slack events
- Not exposing a Slack callback URL on our backend
- Not using Slack to authenticate users (Midway will handle that)

## Verification steps for reviewer

1. `app/services/slack_client.py` is the only file calling Slack:
   ```bash
   grep -n "slack.com/api" -r app/
   ```
2. Two URLs only: `users.lookupByEmail`, `chat.postMessage`.
3. `slack_bot_token` stored in `NpsOrgConfig` (DynamoDB, ap-south-1),
   redacted in `/nps/orgs` GET handler:
   ```python
   d.pop("slack_bot_token", "")
   d["slack_bot_token_set"] = bool(token)
   ```
4. Send orchestration in `app/services/nps_distribution_service.py`
   (`send_reminder` and `send_targeted_reminder`).

## Talos engagement form fields (suggested values)

| Field | Value |
|---|---|
| Engagement type | Application Security Review (light) |
| Customer impact | Internal only |
| Data classification | Internal / Confidential (employee email + name) |
| External integrations | Slack (this), AWS SES (verified domain), Asana (PAT auth, separate Talos done in P426628259) |
| Authentication mechanism | Slack bot token, scoped to one Amazon Slack workspace per org |
| AppSec consultation needed? | No — please review against this doc |

> Add **AmazonUC-SIGNAL Team** (Team ID `amzn1.abacus.team.2ulq2u5nlk3cyucrn2pa`)
> as **read-only** to the Talos engagement so they can validate approval.
> Add the **Team**, NOT the POSIX group.

## Related approvals

- **P426628259** — Asana PAT integration (Stonegate-PE), already approved
- **P422616163** — AppLink/SCC token vault, parked
