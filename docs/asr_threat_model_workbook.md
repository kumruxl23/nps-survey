# ASR Threat Model — Design Inspector Workbook

Concrete reference for building the Design Inspector (DI) diagram and
filling in the auto-generated STRIDE threat list for the NPS Survey
Reminder application's ASR review.

> **Why this exists:** ASR's Threat Model task gates the rest of the
> Red review. DI auto-derives threats from the components and data
> flows you draw. This doc lists every actor, asset, component, flow,
> trust boundary, and the expected threats so the build is mechanical.

## Trust boundaries (draw these first)

| Boundary | What's inside |
|---|---|
| Amazon Corp Network | Internal admin (browser), internal stakeholder (browser/email/Slack client) |
| AWS Account 399016860083 (ap-south-1) | EC2, DynamoDB, SES, Secrets Manager, IAM |
| Slack (3rd party) | Slack workspace, Slack API |
| Asana (3rd party) | Asana workspace, Asana API |

## Actors

| Actor | Trust zone | Role |
|---|---|---|
| Internal Admin (kumruxl@, kuvinu@) | Amazon Corp | Edits org config, triggers reminders, reads dashboards |
| Internal Editor (POC leads) | Amazon Corp | Sends reminders, reads dashboards |
| Internal Viewer | Amazon Corp | Reads dashboards only |
| Internal Stakeholder | Amazon Corp | Receives email/Slack DM with form link, clicks through to Asana |

## Components

| Component | Inside | Notes |
|---|---|---|
| nginx :443 | EC2 | TLS terminator, Let's Encrypt cert, SG allows 443 only |
| Flask + gunicorn :5000 | EC2 (localhost-bound) | App tier, auth via local user store |
| systemd service unit | EC2 | nps-survey.service running as ssm-user |
| DynamoDB table NpsOrgConfig | AWS | Per-org config including slack_bot_token |
| DynamoDB table NpsSurveyCycles | AWS | Cycle metadata |
| DynamoDB table NpsNominations | AWS | Stakeholder list incl. cached slack_user_id |
| DynamoDB table NpsResponses | AWS | Survey responses incl. feedback text |
| DynamoDB table NpsReminderLogs | AWS | Reminder send audit log |
| DynamoDB table NpsDeliveryFailures | AWS | Failure log |
| DynamoDB table NpsUsers | AWS | Local app users + role |
| AWS SES | AWS | Verified domain whs-cpt.amazon.dev |
| AWS Secrets Manager | AWS | Asana PAT (nps-survey/asana-pat) |
| IAM role nps-survey-ec2-role | AWS | Instance profile for EC2 |
| Slack API | 3rd party | users.lookupByEmail + chat.postMessage |
| Asana API | 3rd party | Custom field reads, section list, task list |

## Assets (data items + classification)

| Asset | Classification | Where stored |
|---|---|---|
| Stakeholder name | Confidential | NpsNominations, NpsResponses |
| Stakeholder email | Confidential | NpsNominations, log lines |
| NPS score | Confidential | NpsResponses |
| Free-form survey feedback | Confidential | NpsResponses.feedback_text + what_missing_text |
| Slack user ID | Confidential | NpsNominations.slack_user_id |
| App user password (hashed) | Confidential | NpsUsers (bcrypt hashed) |
| Asana PAT | Secret | Secrets Manager |
| Slack bot token | Secret | NpsOrgConfig.slack_bot_token (DynamoDB at-rest encryption) |
| Flask session secret | Secret | systemd env var |

## Data flows (label every arrow)

| # | From | To | Protocol | Auth | Data |
|---|---|---|---|---|---|
| 1 | Admin browser | nginx :443 | HTTPS | Session cookie | Confidential (form input incl. tokens during edit) |
| 2 | nginx | Flask | HTTP localhost | None (loopback) | Confidential |
| 3 | Flask | DynamoDB | HTTPS (boto3) | IAM role | Confidential / Secret |
| 4 | Flask | SES | HTTPS (boto3) | IAM role | Confidential (recipient email + body) |
| 5 | Flask | Secrets Manager | HTTPS (boto3) | IAM role | Secret (Asana PAT) |
| 6 | Flask | Slack API | HTTPS | Bearer (bot token) | Confidential (Slack user ID + DM body) |
| 7 | Flask | Asana API | HTTPS | Bearer (PAT) | Confidential (custom-field reads) |
| 8 | Stakeholder mail/Slack client | nginx (form click) | HTTPS | None (link click) | URL only |
| 9 | Stakeholder browser | Asana form | HTTPS | Asana SSO | Confidential (response submission, OUT of our trust boundary) |

## Entry points

| Entry point | Auth | Notes |
|---|---|---|
| `/nps/login` (POST) | Bcrypt password | Rate-limited via Flask-Login session |
| `/nps/orgs/update` (POST) | Session + admin role | Token rotation, validates field allow-list |
| `/nps/remind` (POST) | Session + admin/editor | Outbound email + Slack |
| `/nps/webhook/asana` (POST) | None (external) | Handshake echoes X-Hook-Secret; payload validated |
| All other `/nps/*` routes | Session + role | Standard auth |

---

## STRIDE threat-by-threat playbook

Use the table below to mark each DI-generated threat. Mark each as
**Mitigated** / **Unmitigated** / **False Positive** with the rationale.

### Spoofing

| DI threat (typical wording) | Verdict | Rationale / mitigation |
|---|---|---|
| Spoofing of the user identity at the web entry point | Mitigated | Bcrypt password + Flask session cookie. Migration to Midway/SSO planned (sprint 4) — note as residual risk. |
| Spoofing of the Asana webhook caller | Mitigated | `X-Hook-Secret` handshake on registration; only Asana knows the secret. Payload also validated structurally before being processed. |
| Spoofing of the Slack API endpoint | Mitigated | All Slack calls go to fixed `https://slack.com/api/...` URLs over TLS; cert validated by `requests` default trust store. |
| Spoofing of the EC2 instance to AWS | Mitigated | EC2 instance profile + IAM role binding. No long-lived AWS keys. |

### Tampering

| DI threat | Verdict | Rationale / mitigation |
|---|---|---|
| Tampering with data in transit (admin -> app) | Mitigated | TLS 1.2+ via Let's Encrypt. HSTS not yet enabled — note as follow-up. |
| Tampering with data in transit (app -> AWS APIs) | Mitigated | boto3 uses HTTPS by default; cert validation on. |
| Tampering with data in transit (app -> Slack/Asana) | Mitigated | HTTPS only; tokens scoped to specific operations. |
| Tampering with DynamoDB items by other AWS principals | Mitigated | IAM role allows write only to nps-prefixed tables; no other principals share role. |
| Tampering with the Asana PAT in Secrets Manager | Mitigated | Secret resource policy limits read to nps-survey-ec2-role; rotation possible via console. |
| Tampering with the Slack bot token (DynamoDB) | Mitigated | Same IAM scope; admin UI redacts on read; rotation via overwrite. |

### Repudiation

| DI threat | Verdict | Rationale / mitigation |
|---|---|---|
| User denies sending a reminder | Mitigated | NpsReminderLogs records (sent_at, trigger_type, recipient_count, channels) per send. Trigger source is "automated" or "manual"; route requires authenticated session. |
| User denies updating an org config | Partially Mitigated | Update goes through admin role; no per-update audit log today. **Follow-up:** add audit trail for config changes. |
| Failure repudiation | Mitigated | NpsDeliveryFailures table captures every send-time error with email + reason. |

### Information Disclosure

| DI threat | Verdict | Rationale / mitigation |
|---|---|---|
| Information disclosure of secrets in logs | Mitigated | slack_client never logs auth headers, only error message strings. Reviewed via grep: no `logger.*token` or `logger.*pat` matches. |
| Information disclosure of the Slack bot token via API | Mitigated | `/nps/orgs` GET handler explicitly pops `slack_bot_token` and returns `slack_bot_token_set: bool` instead. |
| Information disclosure of stakeholder emails to other stakeholders | Mitigated | Bulk email uses BCC. Per-stakeholder reminders go individually. |
| Information disclosure of one org's data to another's user | Mitigated | All routes scope reads/writes by `org_id` from request payload; no cross-org list endpoints today. |
| Information disclosure via verbose error messages | Mitigated | Flask runs with `DEBUG=False` in prod; SES/Slack errors are logged server-side, not echoed to UI. |
| Information disclosure of survey responses without auth | Mitigated | All response routes require login + role. |

### Denial of Service

| DI threat | Verdict | Rationale / mitigation |
|---|---|---|
| DoS via repeated reminder sends | Partially Mitigated | No explicit rate limit today; admins are trusted. Slack's own rate limits enforce ceiling at API layer. **Follow-up:** add app-level cooldown between bulk sends. |
| DoS via Asana webhook flood | Mitigated | Endpoint validates payload structure; failures don't propagate. Webhook can be revoked in Asana if abused. |
| DoS via large file uploads | Mitigated | `/nps/nominations/upload` checks file extension and parses with openpyxl streaming; no unlimited concurrent uploads (single gunicorn worker pool of 2). |
| DoS via DynamoDB hot-key | Mitigated | Pay-per-request billing absorbs spikes; partition keys are org_id#cycle_id which spreads load. |

### Elevation of Privilege

| DI threat | Verdict | Rationale / mitigation |
|---|---|---|
| Viewer escalates to admin via UI tampering | Mitigated | Role check is server-side via `@role_required`. Client-side hiding is cosmetic only. |
| Editor uses admin-only routes | Mitigated | `@role_required("admin")` decorator on `/nps/orgs/*` routes. |
| EoP via SQL injection | False Positive | DynamoDB; no SQL. boto3 parameterizes all calls. |
| EoP via path traversal in workbook upload | Mitigated | filename only used for extension check; bytes parsed in-memory by openpyxl. |
| EoP via deserialization | Mitigated | No pickle/yaml.unsafe_load anywhere; only `json.loads` for trusted payloads. |
| EoP via outdated dependencies | Partially Mitigated | requirements.txt pins major versions; **follow-up:** wire in dependabot or pip-audit. |
| EoP via Slack callback impersonation | False Positive | We expose no Slack callback endpoint. Bot is outbound-only. |

---

## DI build steps (clickthrough)

1. Open Design Inspector (link from ASR's Threat Model task)
2. New diagram, name `NPSSurveyReminders`
3. Drop **Trust Boundaries** in this order: Amazon Corp Network, AWS Account, Slack, Asana
4. Drop **Actors** inside Amazon Corp Network: Admin, Editor, Viewer, Stakeholder
5. Drop **Components** inside AWS Account: EC2 (containing nginx and Flask), each DynamoDB table, SES, Secrets Manager, IAM role
6. Drop **Components** inside Slack box: Slack API
7. Drop **Components** inside Asana box: Asana API
8. Draw flows from the table above. For each flow, click the arrow and set:
   - Protocol (HTTPS / HTTP)
   - Authentication (Session, IAM, Bearer)
   - Data classification (Confidential / Secret)
9. DI auto-runs threat analysis → review the threat list
10. For each threat, mark using the playbook above
11. Click **Export** → HTML
12. Upload the HTML back to ASR's Threat Model task

## Known follow-ups (mention in DI Notes)

- HSTS header on nginx (low priority)
- Audit log on org config changes (medium priority)
- App-level cooldown on bulk reminder sends (low priority)
- Midway/SSO migration replacing local password auth (in flight, sprint 4)
- pip-audit / dependabot integration (low priority)
- GitFarm migration for SAST tooling (in flight)
