# Step 4 — Install the NPS Slack app as `chat:write`-only (auto-approval path)

Goal: get a **Bot User OAuth Token** (`xoxb-…`) for the Amazon prod Slack
workspace and drop it into the org's `slack_bot_token`, so leader reminder /
nomination-open **DMs** actually send.

## Why this is now easy

We moved alias→Slack-ID resolution to **SLAB** (`slab_client.py`), so the app
no longer needs `users:read` / `users:read.email` (the High-risk scopes that
forced a Talos review). With **only `chat:write`**, the OPUS "AppsApp" install
questionnaire is all-"No" + no high-risk scope ⇒ **auto-approval in minutes**,
no AppSec engagement. (`docs/slack_talos_review_request.md` is superseded.)

## App to use

- Existing app: **A0B5WB9GC68** ("NPS Survey Reminders"), Amazon workspace
  T016NEJQWE9, owner kumruxl@. Reuse it — don't create a new one.

## Steps (do these in api.slack.com/apps → your app)

1. **OAuth & Permissions → Scopes → Bot Token Scopes.**
   Remove everything except **`chat:write`**. Specifically delete
   `users:read` and `users:read.email` (SLAB replaces them). Final list =
   exactly `chat:write`.
   - If a *fresh* DM fails to open at send time (rare), add **`im:write`** —
     it's also **Low** risk, so auto-approval still holds. Start with just
     `chat:write`.

2. **Settings → Socket Mode → OFF.** We're outbound-only (no events, no slash
   commands, no interactivity). OPUS submission expects Socket Mode off.

3. **Settings → Collaborators → add `opus-amazon-prod`.** Mandatory — this is
   how OPUS reads your scopes during review. Without it, Request Install stalls.

4. **Have your CTI ready.** The earlier install blocked on a CTI attestation.
   Use your team's real CTI (confirm Category/Type/Item with your manager —
   do NOT use a placeholder). You'll enter it in the questionnaire.

5. **Manage Distribution → Activate Public Distribution** (if prompted), then
   **Request Install** to the Amazon prod workspace.

6. **Answer the 10-question questionnaire.** All "No":
   - No private-channel data, no message reading, no external data sharing,
     no storage of Slack conversation content. We store only a Slack user ID
     (from SLAB) + send outbound DMs. No high-risk scopes.
   - Expected result: **auto-approved in minutes**. (If it routes to Talos,
     something still requests a high-risk scope — recheck step 1.)

7. **After approval: Install to Workspace → copy the Bot User OAuth Token**
   (`xoxb-…`).

## Wire the token into the app

8. In the NPS admin UI, open **`/nps/orgs/view`**, edit the **whs_cpt_in** org,
   paste the `xoxb-…` value into **Slack bot token**, save. (Stored in
   `OrgConfig.slack_bot_token`, DynamoDB, read only by `nps-survey-ec2-role`;
   the GET handler redacts it.)

## Test (you as the dummy leader)

9. The test redirects are already in prod: `nsbhatia → kumruxl`,
   `raabhas → kuvinu`, and `NPS_DEMO_SAFE=1` blocks real leaders. So a Slack
   send for Navjyot actually DMs **you**.
10. First confirm SLAB resolves on the host (no token needed):
    `GET /nps/leaders/slack-check?alias=kumruxl` → expect `{ok:true, slack_id:"U…"}`.
    (Only meaningful after deploy — SLAB accepts only the EC2 role.)
11. Then trigger the DM: the "Remind leaders (test)" button (or
    `POST /nps/leaders/remind {"org_id":"whs_cpt_in","channels":["slack"]}`).
    You should receive the placeholder DM. Repeat with `/leaders/notify-open`
    for the nominations-open announcement.

## Notes / gotchas

- **DMs don't need a channel invite** — `chat.postMessage` with `channel=U…`
  opens the 1:1 IM. If you ever post to a *channel*, the bot must be invited
  first (Enterprise Grid rule) — not our case.
- **Incoming webhooks are blocked** at Amazon; posting must be
  `chat.postMessage` (which is what `slack_client.send_dm` does). Good.
- **Token rotation:** re-run step 8 with a new value; it overwrites in place.
- Code degrades gracefully until the token exists: Slack rows report
  "no bot token configured for this org"; email still sends.
