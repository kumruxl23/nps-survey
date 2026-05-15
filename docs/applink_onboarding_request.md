# SCC Token Vault (GRASP) Onboarding — NPS Survey Tool

> **Ticket template:** https://t.corp.amazon.com/create/templates/682733e6-30c5-4161-904b-c78799bce43b
> **Runbook:** Wiki → EnterpriseEngineering → EE-SWAT → AppLink → ServiceRunbook → TokenFlow → OAuth Agent Onboarding
> **Support Slack:** `#scc-tokenvault-grasp-onboarding-support`
>
> **Status:** Ready to submit. Verify the two items flagged with ⚠️ below, then paste into the ticket.

---

## ⚠️ Verify before submitting

1. **AWS Account ID** — I've put `399016860083` (pulled from your permissions.amazon.com team URL). Confirm by running in CMD:
   ```cmd
   aws sts get-caller-identity
   ```
   If the `"Account"` field is different, swap it in the Description below.

2. **Posix group** — I've put `WHS CPT IN AIFA` (the display name from your permissions link). If SCC asks for the exact posix group string (lowercase / hyphens / underscores), ask them in the ticket comments or on `#scc-tokenvault-grasp-onboarding-support`.

---

## Ticket fields

**CTI (dropdowns at the top of the form):**
- Category: `Enterprise Engineering`
- Type: `SoftWare Automation and Tooling`
- Item: `AppLink`
- Severity: `Sev-3`
- Assigned Group: `SoftWare Automation Tooling` (auto-fills)

*(These are the EE-SWAT intake CTI — same as the screenshot you shared earlier. They route the ticket to SCC; they're not your team's CTI.)*

---

## Title (paste into Title field)

```
[GRASP customer] [Onboarding request to SCC's Token Vault Service] - WHS CPT India
```

---

## Description (paste everything below into the Description field)

```
NON-TECHNICAL INFORMATION:
==========================

Use Case:
The NPS Survey Automation tool is an internal Flask application that
automates the Net Promoter Score (NPS) survey lifecycle for WHS CPT IN
(and planned RISC) org leadership. It creates Asana tasks for nominated
respondents using a pre-configured Asana form, sends scheduled reminder
emails (SES) and Slack DMs, receives Asana webhooks when responses are
submitted, and surfaces results on an internal dashboard (NPS score,
promoters/passives/detractors, per-leader breakdowns). The tool needs to
call the Asana REST API on behalf of a single shared service identity;
SCC's Token Vault will hold the Asana OAuth tokens and vend short-lived
access tokens to the tool via GetAccessToken.

User Scale:
5–15 internal Amazon employees (team admins + leadership viewers).
Single Asana workspace. Estimated steady-state volume < 500 Asana API
calls per day. No customer-facing surface; no PII beyond internal
employee names, emails, and NPS scores (1–10 integer + optional comment).

Customer Name:
NPS Survey Automation Tool

Customer CTI:
WHS / CPT / NPSSurveyTool

Customer Posix Group:
WHS CPT IN AIFA
(Display name from https://permissions.amazon.com/a/team/WHS%20CPT%20IN%20AIFA.
Please confirm if the exact posix group string is needed in a different format.)

PREREQUISITES:
==============

Have you completed the following prerequisites?

1. OAuth Application created in GRASP: NO
   (Per runbook §2.2/2.3, SCC creates the OAuth application in GRASP as
   part of onboarding. We have the Asana OAuth app created on the vendor
   side — Client ID below. Asana Client Secret will be shared with SCC
   out-of-band via a secure channel.)

2. Set OAuth callback/redirect URI for each environment:
   - Prod:  applink.ee.amazon.dev/oauth/callback        — YES (registered in Asana dev portal)
   - Beta:  beta.applink.ee.amazon.dev/oauth/callback   — YES (registered as precaution)
   - Gamma: gamma.applink.ee.amazon.dev/oauth/callback  — YES (registered as precaution)

TECHNICAL INFORMATION:
======================

GRASP Client ID:
1214119402148845
(Asana OAuth application Client ID, from https://app.asana.com/0/my-apps.
Per runbook §2.3.2.5, this is the Client ID from the vendor OAuth
application. Client Secret will be shared with SCC out-of-band.)

OAuth Scopes:
default offline_access
(default = Asana's standard read/write scope on the authorizing user's
workspaces. offline_access included per runbook §4.1.8 requirement for
refresh token retrieval. Note: Asana's documented scope list does not
include offline_access as a literal string — Asana issues refresh tokens
by default. Please advise if we should adjust the scope string.)

Customer redirect URI (Optional):
http://localhost:5000/nps/auth/callback
(Dev environment only. Prod hostname is TBD and will be provided once
infrastructure is provisioned. Default https://beta.applink.ee.amazon.dev/close-window
from runbook §4.1.4 is acceptable if a single redirect is required.)

Access token Expiry:
1 hour (Asana default — not configurable on vendor side)

Refresh token Expiry:
Non-expiring (Asana does not expire refresh tokens unless revoked)

Do you want to Onboard to SNS subscriptions for getting token expiry
notifications?
No
(Given our scale and the non-expiring nature of Asana refresh tokens,
we'll use the ListAuthorizedServicesByAgentUser API to check token
metadata on demand. We can re-evaluate SNS later if needed.)

AWS ACCOUNT INFORMATION:
========================

Customer AWS Account (Beta):
N/A — single-environment tool

Customer AWS Account (Gamma):
N/A — single-environment tool

Customer AWS Account (Prod):
399016860083
(WHS CPT India AWS account where the NPS Flask application will run.
Requesting allowlist for applink:GetAccessToken,
applink:ListAuthorizedServicesByAgentUser, and
applink:BulkRevokeAuthorizationByAgentUser actions per runbook §3.2.1.)

Customer Queue ARNs (Beta):
N/A

Customer Queue ARNs (Gamma):
N/A

Customer Queue ARNs (Prod):
N/A (not onboarding to SNS notifications)

CONTACTS:
=========

Customer Primary Contact:
kumruxl

Customer Secondary Contact:
kuvinu

Manager:
joshnadr

ADDITIONAL CONTEXT:
===================

Team Wiki:
https://w.amazon.com/bin/view/Whs/centralprograms/Central-Programs

Code Repo:
Local workspace only at this time. Will be published to code.amazon.com
before production deployment.

Prod Hostname:
TBD — infrastructure (EC2 + HTTPS endpoint) being provisioned in parallel
with this onboarding. Will update the ticket with the final hostname when
available so it can be allowlisted.

Open Questions for SCC:
1. Does Asana's `default` scope satisfy the offline_access requirement,
   or must offline_access be included as a literal scope string?
2. What is the exact AWS SDK operation name / service endpoint for
   GetAccessToken (for our Python client)?
3. Typical approval SLA for a single-environment customer?
4. Can SCC share sample Python code or a reference implementation for
   calling GetAccessToken from a Flask application?
```

---

## Post-submission checklist

- [x] Ticket submitted; record SIM URL below:

  **P422616163** — https://t.corp.amazon.com/P422616163

- [x] Joined `#scc-tokenvault-grasp-onboarding-support` on Slack  ← (confirm if done)
- [ ] Shared Asana Client Secret with SCC via their requested secure channel (do NOT paste into the ticket itself)
- [x] Added AppLink redirect URIs to Asana dev portal (https://app.asana.com/0/my-apps → OAuth tab):
   - `https://applink.ee.amazon.dev/oauth/callback`
   - `https://beta.applink.ee.amazon.dev/oauth/callback`
   - `https://gamma.applink.ee.amazon.dev/oauth/callback`

## What SCC will return to you after approval

1. **Agent ID** (unique for WHS CPT IN in Prod SCC)
2. **KMS key certificate** (for authentication)
3. **3LO URL** in the form:
   `https://applink.ee.amazon.dev/services/Asana/StonegateMCP/redirecting-to-3p?agentId={YOUR_AGENT_ID}&scopes=default%20offline_access&redirectUri={YOUR_CALLBACK}`

Once those arrive, we swap `asana_client.py` to call AppLink's `GetAccessToken` instead of Asana's `/oauth_token` directly. I'll handle that code change in a follow-up CR.
