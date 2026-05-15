# Stonegate-PE Asana API Token Request — NPS Survey Tool

> **Ticket template:** https://t.corp.amazon.com/create/templates/422a5e74-b218-4099-81eb-d3ebd6ae0955
>
> **Why this ticket:** Per SCC's response on P422616163, this stonegate-pe review is the prerequisite for obtaining any Asana API token. The Token Vault onboarding (P422616163) is on hold pending this review's outcome and SCC's internal check on whether Token Vault supports Asana (it was built for M365/Graph).
>
> **Related tickets:**
> - P422616163 — SCC Token Vault onboarding (on hold)
>
> **Submit status:** Ready to paste once the CTI dropdowns are set.

---

## Ticket CTI (top of form — should be pre-filled by template)

- Category: *(template default — don't change)*
- Type: *(template default)*
- Item: *(template default)*
- Severity: Sev-3

---

## Title (paste into Title field)

```
[Asana API Token Request] NPS Survey Tool — WHS CPT IN
```

---

## Description (paste into Description field)

```
Please fill out the finalized template for reviewing your API token request.

Classification: Confidential.
Use case: Internal automation, single Flask application, < 500 API calls/day.
No re-distribution of Asana data to third-party products.
```

---

## Custom Fields (one-by-one — match each to the form field)

### Is this request for Kiro or MCP or QuickSuite?

```
None of the above — custom internal Flask application (NPS Survey Automation Tool)
```

*(If the dropdown doesn't allow "None", pick the closest option and explain in the business use case field.)*

---

### Business use case

```
Automate NPS (Net Promoter Score) survey cycles for WHS CPT IN org leadership. Flask app creates Asana tasks, sends reminders, ingests responses via webhook for an internal dashboard. Asana stores: employee names, emails, NPS scores (1-10), comments.
```

*(250 chars — within the 255 limit.)*

---

### Where will Amazon data be shared (internal / external / third party / vendor software)

```
Asana (external SaaS, approved for Confidential). No other third-party destinations. Data stays inside Amazon AWS account 399016860083 (ap-south-1) and Asana. Not exported to Tableau, QuickSight, or any reporting tool.
```

---

### Business impact

```
Breach exposes internal employee names, amazon.com emails, NPS scores, and free-text feedback on WHS CPT IN leadership. Scope: ~100 nominees, ~15 leaders, one org. No customer data, no financial data, no regulated PII.
```

---

### Email address of the user who needs the API token

```
kumruxl@amazon.com
```

---

### Number of users and customers impacted

```
5-15 internal Amazon employees (WHS CPT IN admins + leaders). Zero customers.
```

---

### Types of requests it will be used for

```
GET /tasks/{gid} (read response), GET /projects/{gid}/custom_field_settings (setup), POST /tasks (create), PUT /tasks/{gid} (update custom fields), POST /webhooks (register), plus webhook receipt on response submission. All over HTTPS.
```

---

### Business justification and acceptance

```
Replaces manual spreadsheet+email process, cuts 2-3 day cycle delays, removes human data-entry as a leak vector. Approved by manager joshnadr. Risks mitigated: Confidential-scope data, token encrypted in DynamoDB+KMS, HTTPS, role-based access.
```

---

### Data classification you will be working with

```
Confidential
```

---

### Data classification above confidential

```
N/A - request is scoped to Confidential data only.
```

---

### What is the requesting user's level of access

```
Service-identity access. Token held by the Flask app, not individuals. Single admin (kumruxl) authorizes on behalf of the tool. Writes gated to 'admin' role in the app. Reads available to 'editor'/'viewer'. Default for all others: no access.
```

---

### Please provide data flow or design diagram to the ticket

Text-field entry (if the form accepts text only):
```
Amazon users (HTTPS) -> EC2 nginx -> Flask/gunicorn (localhost) -> Asana REST API (HTTPS, OAuth2). Flask also writes to DynamoDB (KMS), SES, Slack. Asana posts webhooks back to /webhook/asana. All transport TLS 1.2+. Diagram available on request.
```

If the form requires a file attachment instead, use this full ASCII diagram — paste into a Word doc, export as PDF, attach:

```
┌──────────────────────────────────────────────────────────────┐
│  Amazon Corp Network                                         │
│                                                              │
│  WHS CPT IN Admin (kumruxl) ──► HTTPS ──►                    │
│  Internal User (browser)                                     │
│                                    │                         │
└────────────────────────────────────┼─────────────────────────┘
                                     │
                          TLS 1.2+ (Let's Encrypt)
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────┐
│  AWS Account 399016860083 (ap-south-1)                     │
│                                                            │
│  EC2 i-06ccd83e4b55fa98f (nps-survey-app)                  │
│  ├─ nginx (:443, TLS termination)                          │
│  └─ Flask/gunicorn (:5000, localhost only)                 │
│       │                                                    │
│       ├──► DynamoDB (NpsOrgConfig, KMS-encrypted)          │
│       │    • User accounts, session data                   │
│       │    • OAuth tokens (current) or AppLink/GRASP       │
│       │      token reference (post-approval)               │
│       │                                                    │
│       ├──► SES (outbound reminder emails)                  │
│       │                                                    │
│       ├──► Slack API (outbound DM reminders, optional)     │
│       │                                                    │
│       └──► Asana REST API ◄── HTTPS ──                     │
│            (app.asana.com)                                 │
│                                                            │
└────────────────────────────────────────────────────────────┘
                                     ▲
                                     │
                          Webhooks (inbound HTTPS)
                                     │
┌────────────────────────────────────┼───────────────────────┐
│  Asana SaaS (external)             │                       │
│                                    │                       │
│  • Stores tasks, form responses, projects                  │
│  • Posts webhook to /webhook/asana when responses submitted│
│  • No Amazon data beyond: internal employee names/emails,  │
│    NPS scores (1-10), optional free-text comments          │
│                                                            │
└────────────────────────────────────────────────────────────┘

Data classification: Confidential (internal employee feedback).
Directionality: Bidirectional — reads from Asana, writes to Asana,
                receives webhooks from Asana.
```

---

### How is the implementation done (Local deployment / Org-wide use)

```
Single-tenant EC2 deployment in AWS account 399016860083 (ap-south-1). One t3.micro (i-06ccd83e4b55fa98f) running Flask+gunicorn behind nginx with Let's Encrypt HTTPS. Custom internal Flask app (not COTS). One org (WHS CPT IN) now; maybe RISC later.
```

---

### How will the API token be stored

Dropdown — pick "DynamoDB" / "Other" / whatever is closest. If there's a notes field:
```
Encrypted at rest in DynamoDB (NpsOrgConfig, KMS-encrypted). IAM-scoped via nps-survey-ec2-role with least-privilege policy. Never logged. Will migrate to SCC Token Vault if SCC confirms Asana support (pending P422616163).
```

---

### Is the data being exported out with the API token?

```
No. Data stays within Amazon. Asana is the survey backing store; Flask reads it back for the internal dashboard. No export to Tableau, QuickSight, Excel, email attachments, or any third-party reporting tool. Per-respondent comments visible only to 'admin'.
```

---

### What is your access level — are you a sysadmin?

Pick "No" from the dropdown. If notes field:
```
Software developer building an internal Flask app. Not a sysadmin. Not incorporating Asana data into any third-party product.
```

---

### If you are a sysadmin

```
N/A - not a sysadmin, not incorporating Asana data into any third-party product (no Tableau, no external BI). No Talos or ASR review required per the stated criteria.
```

---

### Are these systems to which the data is being shared external or internal?

Pick "Both" or equivalent from the dropdown. If notes field:
```
Both. Asana external (SaaS, approved for Confidential). NPS Flask app internal (Amazon AWS 399016860083). Data flows only between these two.
```

---

### Security review link (optional)

```
N/A - data classification is Confidential (not above Confidential); no separate Talos/ASR review required per form criteria.
```

---

### Do you agree with follow data access and usage policy?

Pick "Yes" from the dropdown.

---

## Contacts (if the form has these fields)

| Field | Value |
|---|---|
| Requester | kumruxl |
| Manager | joshnadr |
| Backup | kuvinu |
| Team | WHS CPT IN AIFA |
| Team wiki | https://w.amazon.com/bin/view/Whs/centralprograms/Central-Programs |

---

## Post-submission steps

1. [ ] Capture the SIM URL here: `<paste after submission>`
2. [ ] Reply on P422616163 with the new ticket ID so SCC can keep both linked
3. [ ] Wait for stonegate-pe review outcome (SLA varies; typically 1–3 weeks)
4. [ ] Once approved: confirm with SCC whether Token Vault supports Asana — if yes, resume P422616163; if no, proceed with our in-app DynamoDB+KMS storage (already implemented)

---

## Reply to post on P422616163 (after filing the new ticket)

```
Thanks for flagging — understood. Filing the stonegate-pe Asana API token
request now (template 422a5e74-...). Will update this ticket with the
SIM ID once submitted.

Please hold this ticket pending:
1. Outcome of the stonegate-pe review
2. Your confirmation on whether Token Vault supports Asana (built for
   M365/Graph per your message)

Happy to proceed either via Token Vault (if supported) or with our own
DynamoDB+KMS storage (already implemented in the NPS tool) once the
upstream approval lands. We'll pick the path based on your guidance.

Will monitor #scc-tokenvault-grasp-onboarding-support for updates.

— kumruxl
```
