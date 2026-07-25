## Summary

Consolidated H2 feature work that has been running in prod (deployed from
`main` via SSM) and is now being brought back to `mainline` for review. Four
themes:

### 1. Midway auto-login + `/health`
- App reads `X-Amzn-Oidc-Identity` from the Midway-gated ALB and maps
  alias → role from the user store (`NPS_MIDWAY_AUTH=1`).
- Password form disabled in prod, retained for local dev.
- Unknown aliases get an access-request page.
- New unauthenticated `/health` endpoint, exempt from the Host-header guard,
  used by the ALB target group health check.

### 2. Org-scoped share links + alias prefill
- Per-org share tokens (`__share__nominate_form#<org>`); the old global token
  is retired. Token access is locked server-side to its org (403 on cross-org
  context/list/submit/remove/prefill).
- Leader roster is org-scoped (`leader_org` attribute; unscoped = all orgs).
- `/nps/nominate/prefill`: alias → {name, designation, leader} from roster +
  nomination history.

### 3. PAPI directory client (supervisor-chain)
- New PAPI client resolves alias → name/title/leader via a single
  `expand=supervisor-chain` call (IAM-auth regional endpoint, SigV4).
- Op allowlisted: `employeeV2ByLogin` only. TPS 10.
- Drives leader auto-resolution on the nomination form.

### 4. Identity-driven form + privileged-only visibility
- Nominator and leader are resolved server-side (Midway → roster → PAPI chain →
  history). Leader is NEVER user-selectable (dropdown is view-only).
- Nomination lists are visible only to admins/editors/roster leaders.
- Duplicates surface only via 409 conflict.

## Testing
- Full suite green (379 tests, CPython 3.10 + 3.12) locally.
- `brazil-build release` gate must pass before this CR is published.
- Smoke-tested in prod via SSM: prefill returns 200, per-org tokens resolve in
  context, Midway auto-login confirmed, `/health` target HEALTHY.

## Deploy / rollout note
- This code is already live in prod (SSM deploy from `main`); this CR
  reconciles mainline with what is running. No behavior change on merge.
- Follow-up: Phase 3 Apollo deploy stages, then retire `infra/ssm_deploy.py`.

sim: https://taskei.amazon.dev/tasks/WHS_AIFA-1763314908
