# OPUS request — org-wide (Enterprise Grid) install for NPS Survey Reminders

Paste-ready request for the AmazonUC-SIGNAL / OPUS AppsApp flow (ticket or
#help channel). Goal: promote the existing per-workspace install to an
**org-level (Enterprise Grid) install** so the bot can DM survey stakeholders
regardless of which workspace they belong to.

## One-paragraph ask

> Requesting an **org-wide (Enterprise Grid) install** for our approved Slack
> app **NPS Survey Reminders** (App ID **A0B5WB9GC68**). It is currently
> installed on the Operations, World Wide Consumer, and Amazon workspaces, but
> our recipients (survey stakeholders across WHS CPT IN/NA and FEC) are spread
> across many workspaces, so per-workspace installs can't reach them reliably.
> The app is **`chat:write`-only** (bot token; no `users:read`, no user-token
> scopes, no events/slash/interactivity) and sends outbound 1:1 DMs only, so an
> org-level install does not broaden data access — it only lets the bot deliver
> DMs grid-wide. Please advise on approving/installing at the org level.

## App facts (for the reviewer)

- **App:** NPS Survey Reminders — **App ID A0B5WB9GC68**, Amazon Enterprise Grid.
- **Owner:** kumruxl@ (Rohit Kumar), WHS CPT IN. **Backup:** kuvinu@.
- **Bot Token Scopes (only):** `chat:write`, `chat:write.customize`, `im:write`.
  No User Token Scopes. Specifically **no `users:read` / `users:read.email`**
  (alias→Slack-ID is resolved out-of-band via OPUS **SLAB**
  `OpusUsersGetSlackIDFromAlias`, onboarding D490668297).
- **Endpoints called:** `chat.postMessage` (+ `conversations.open` implied by
  `im:write`) only. No events API, no slash commands, no interactivity, no
  webhooks, no channel reads.
- **Approval status:** already OPUS-approved and auto-installed (no Talos, no
  high-risk scope) on Operations / World Wide Consumer / Amazon workspaces.
- **Collaborator:** `opus-amazon-prod` is added.

## Why org-wide (not more per-workspace installs)

- Recipients are Amazonians across many home workspaces; we cannot enumerate
  each leader's workspace in advance, and SLAB returns a grid-wide user ID with
  no workspace hint.
- A single org-level install lets `chat.postMessage` DM any grid user, removing
  per-workspace guesswork and avoids repeatedly re-requesting individual
  workspaces as the roster changes.

## Data / risk (unchanged by org-wide)

- **Outbound-only.** Bot sends a survey-link DM; it does not read, archive, or
  process replies, and subscribes to no events.
- **Data handled:** Amazon employee alias → Slack user ID (from SLAB) + the
  survey link. No customer data, no message-content storage, no directory reads.
- **Scope stays `chat:write`.** Org-wide changes *reach*, not *access*.
- **Volume:** ~80 stakeholders across 3 orgs, ~5 sends/cycle, 4 cycles/yr
  (~1,600 DMs/yr) — well under Slack rate limits.

## Ask summary

1. Approve/enable **org-level install** for App ID A0B5WB9GC68 on the Amazon
   Enterprise Grid.
2. Confirm whether anything beyond the standard AppsApp questionnaire is needed
   for an org-level (vs per-workspace) install of a `chat:write`-only app.
3. Note any org-install rate/usage guidance we should design for.
