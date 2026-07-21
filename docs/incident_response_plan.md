# NPS Survey Automation — Incident Response Plan

Document version: 1.0
Last updated: 2026-06-01
Owner: kumruxl@ (Rohit Kumar)
Backup: kuvinu@ (planned)
Escalation: Sandeep@ (manager)

## Service tier and impact assessment

**Tier:** Non-tier-1 (internal employee feedback tool, no customer-facing
dependency).

**Maximum tolerable downtime:** 24 hours. Surveys are collected directly
in Asana (independent of this app). Reminder dispatch and dashboard
analytics are the affected functions if the app is unavailable.

**Affected populations:** ~10 admin/editor/viewer users, ~250 nominated
stakeholders across WHS CPT IN, WHS CPT NA, FEC.

## Detection signals

| Signal | Source | Threshold |
|---|---|---|
| Failed reminder send | NpsDeliveryFailures table; dashboard "View Failures" tile | Any non-zero in a send window |
| Auth failures | CloudWatch Logs `/aws/ec2/nps-survey-app` | 5+ failed logins from one IP within 1 minute |
| Token-access anomaly | CloudTrail events on `nps-survey/asana-pat` Secrets Manager secret | Any access from a principal that is not `nps-survey-ec2-role` |
| Database tamper | CloudTrail PutItem/DeleteItem on Nps* tables | Any write from a non-EC2 principal |
| Service down | nginx 5xx, gunicorn worker exits, dashboard 502 | Sustained > 5 minutes |

## Response runbook

### Step 1 — Triage

1. Open the dashboard at `https://15-206-208-196.nip.io/nps/dashboard`
2. Check `NpsDeliveryFailures` for recent failures + reasons
3. Pull CloudWatch logs in the affected window:
   ```bash
   aws logs filter-log-events \
     --log-group-name /aws/ec2/nps-survey-app \
     --start-time $(date -d '1 hour ago' +%s)000 \
     --region ap-south-1
   ```
4. SSM into the EC2 if needed:
   ```bash
   aws ssm start-session --target i-06ccd83e4b55fa98f --region ap-south-1
   ```

### Step 2 — Containment by failure mode

#### 2a. Slack bot token compromise

1. Open `/nps/orgs/view` as admin
2. Click Edit on each affected org → paste a fresh `xoxb-…` bot token from
   Slack admin → Save
3. Old token immediately invalidates server-side at Slack
4. Verify by sending a test reminder to yourself only

#### 2b. Asana PAT compromise

1. Regenerate the PAT in Asana web UI (Settings → Apps → Personal access
   tokens → Revoke + Create new)
2. Update Secrets Manager:
   ```bash
   aws secretsmanager update-secret \
     --secret-id nps-survey/asana-pat \
     --secret-string "$NEW_PAT" \
     --region ap-south-1
   ```
3. Restart the app to pick up the new value:
   ```bash
   sudo systemctl restart nps-survey.service
   ```
4. Verify with `curl https://localhost/nps/dashboard -k -o /dev/null -w "%{http_code}\n"`

#### 2c. App user account compromise

1. Deactivate the user row in NpsUsers via the admin UI (or directly via
   DynamoDB UpdateItem if UI unavailable)
2. Rotate `FLASK_SECRET_KEY` env var in
   `/etc/systemd/system/nps-survey.service.d/override.conf` to invalidate
   all sessions
3. `sudo systemctl daemon-reload && sudo systemctl restart nps-survey.service`

#### 2d. DynamoDB tampering

1. Confirm scope via CloudTrail
2. Restore tables from PITR (if enabled — current state: planned, not yet on)
3. Fallback: re-import stakeholder workbooks from the admin-held source
   files (app is stateless on EC2) + re-run backfill_from_asana for
   missing responses (Asana is the secondary system of record)
4. RPO 5 min for PITR; RTO < 4 hours for full re-import

#### 2e. Service degradation

1. Check `sudo systemctl status nps-survey.service`
2. Check disk space, memory, network on the EC2
3. Restart: `sudo systemctl restart nps-survey.service`
4. If still failing, check nginx config: `sudo nginx -t`
5. As a last resort, redeploy from `infra/deploy.sh` on a fresh instance

### Step 3 — Communication

| Severity | Notify | Within |
|---|---|---|
| Sev-1 | Sandeep@ + AppSec via #appsec-help + affected stakeholders | 4 hours |
| Sev-2 | Sandeep@ | 1 business day |
| Sev-3 | Best-effort summary in next standup | as convenient |

For credential leaks at any severity, file an AppSec ticket immediately.

### Step 4 — Post-incident review

After Sev-1 or Sev-2 incidents:
1. Write a brief Correction-of-Errors (COE) within 5 business days
2. Review in next team standup
3. File any follow-up engineering tickets
4. Update this runbook if a step was unclear

## Severity ladder

| Sev | Definition | Examples |
|---|---|---|
| Sev-3 (low) | Cosmetic glitch, single failure | Dashboard tile rendering wrong, one email failed |
| Sev-2 (medium) | Repeated failure, suspected misconfiguration, individual unauthorized access attempt | Send queue stuck > 1 hour, brute-force login attempts |
| Sev-1 (high) | Credential leak, unauthorized data access at scale, PII exposure | Slack bot token in commit history, DynamoDB items copied externally |

## SLAs

| Severity | Acknowledge | Mitigate |
|---|---|---|
| Sev-1 | < 4 hours | < 24 hours |
| Sev-2 | < 1 business day | best-effort |
| Sev-3 | best-effort | best-effort |

## Service degradation impact details

| Component down | Effect | Workaround |
|---|---|---|
| App (EC2) | Reminders pause; dashboard inaccessible | Asana form keeps collecting; restart EC2 |
| DynamoDB | Read/write fails | PITR restore or re-import from admin-held workbooks |
| SES | Email reminders fail | Slack channel still works (if enabled per org) |
| Slack API | Slack DMs fail | Email reminders still work |
| Asana API | Backfill stalls; existing responses unaffected | Manual admin entry via /nps/responses/record |
| Secrets Manager | Asana PAT unreadable; backfill fails | Reminders unaffected (don't need PAT) |

## Backup and recovery

- **Application code:** ssh://git.amazon.com/pkg/NPSSurveyAutomation
  (mainline)
- **Data:** DynamoDB tables in ap-south-1; PITR enablement planned. Manual
  daily JSON backup via `scripts/backup_and_wipe_test_data.py` on demand.
- **Configuration:** `/etc/systemd/system/nps-survey.service.d/override.conf`
  on EC2 (env vars). NOT backed up automatically — re-document in a Quip
  page if changed.
- **Secrets:** Asana PAT in Secrets Manager (versioned, 90-day rotation
  reminder). Slack bot tokens in NpsOrgConfig (rotate via admin UI).

## References

- ASR engagement: https://asr.security.amazon.dev/applications/33d9f777-6675-4612-bf3e-640960c021ad
- Threat model: ASR Threat Model task (DI export uploaded)
- IAM policies: `infra/iam-policies/` in this package
- Code repo: ssh://git.amazon.com/pkg/NPSSurveyAutomation
