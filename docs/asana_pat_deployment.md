# Asana PAT Deployment Runbook

> **Status:** stonegate-pe approved on P426628259 — kumruxl@amazon.com may generate an Asana PAT for the NPS Survey Tool.
>
> **What this runbook covers:** end-to-end steps to get the live tool on EC2 (`15.206.208.196`) using a PAT stored in AWS Secrets Manager.

---

## Prerequisites (already done)

- ✅ Stonegate-PE approval on P426628259
- ✅ EC2 instance `i-06ccd83e4b55fa98f` (ap-south-1, AWS account `399016860083`)
- ✅ HTTPS live at `https://15-206-208-196.nip.io`
- ✅ NPS app running as systemd service (`nps-survey.service`)
- ✅ Code in `app/services/asana_client.py` supports PAT mode (this commit)

---

## Phase 1 — Generate the PAT in Asana (2 min)

1. Browser → https://app.asana.com/0/my-apps
2. Personal Access Tokens section → **Create new token**
3. Name: `NPS Survey Tool - Prod`
4. Click **Create token**
5. **Copy the token immediately** — Asana shows it only once
6. **Don't paste it anywhere yet** — go straight to Phase 2 (browser tab open with the token visible is fine)

If you accidentally close the page before copying, just delete and create a new one.

---

## Phase 2 — Store the PAT in AWS Secrets Manager (5 min)

### Option A — AWS Console (recommended — visual confirmation)

1. AWS Console → switch to region **ap-south-1 (Mumbai)**
2. Search for **Secrets Manager** → open
3. Click **Store a new secret**
4. **Secret type:** Other type of secret
5. **Key/value pairs:**
   - Key: `ASANA_PAT`
   - Value: paste the PAT from Phase 1
6. **Encryption key:** `aws/secretsmanager` (default AWS-managed KMS key)
7. **Next**
8. **Secret name:** `nps-survey/asana-pat`
9. **Description:** `Asana Personal Access Token for NPS Survey Tool. Approved on P426628259.`
10. **Tags (optional but recommended):**
    - `tool` = `nps-survey`
    - `owner` = `kumruxl`
    - `approval-ticket` = `P426628259`
11. **Next** → leave automatic rotation **disabled** (PATs aren't rotated by Secrets Manager)
12. **Next** → **Store**

Copy the secret ARN from the secret's detail page — you'll need it for the IAM policy in Phase 3.

### Option B — AWS CLI (if you prefer terminal)

From CloudShell or a machine with credentials in account `399016860083`:

```bash
aws secretsmanager create-secret \
  --region ap-south-1 \
  --name nps-survey/asana-pat \
  --description "Asana PAT for NPS Survey Tool (approved on P426628259)" \
  --secret-string '{"ASANA_PAT":"PASTE_PAT_HERE"}' \
  --tags Key=tool,Value=nps-survey Key=owner,Value=kumruxl Key=approval-ticket,Value=P426628259
```

The output includes the ARN. Save it.

---

## Phase 3 — Grant the EC2 IAM role permission to read the secret (5 min)

The EC2 uses IAM role `nps-survey-ec2-role`. Add an inline policy that allows reading **only** this one secret.

### Option A — AWS Console

1. AWS Console → IAM → Roles → `nps-survey-ec2-role`
2. **Permissions** tab → **Add permissions** → **Create inline policy**
3. Switch to JSON view, paste:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowReadAsanaPAT",
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue",
                "secretsmanager:DescribeSecret"
            ],
            "Resource": "arn:aws:secretsmanager:ap-south-1:399016860083:secret:nps-survey/asana-pat-*"
        }
    ]
}
```

(The trailing `-*` matches AWS's auto-suffix on secret ARNs.)

4. **Next** → policy name: `AllowReadAsanaPAT` → **Create policy**

### Option B — AWS CLI

```bash
aws iam put-role-policy \
  --role-name nps-survey-ec2-role \
  --policy-name AllowReadAsanaPAT \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["secretsmanager:GetSecretValue","secretsmanager:DescribeSecret"],"Resource":"arn:aws:secretsmanager:ap-south-1:399016860083:secret:nps-survey/asana-pat-*"}]}'
```

---

## Phase 4 — Deploy the new code to EC2 (5 min)

1. **Push the latest code from your local workspace** (Kiro/Windows):
   ```cmd
   git status
   git add app/services/asana_client.py app/services/test_asana_client.py app/nps/routes.py app/templates/nps_dashboard.html app/services/auth_service.py docs/
   git commit -m "feat(asana): support PAT auth via Secrets Manager"
   git push origin main
   ```

2. **SSH/SSM to the EC2** (via EC2 Instance Connect from the AWS console)

3. **Pull and restart**:
   ```bash
   cd /opt/nps-survey
   sudo git pull origin main
   sudo systemctl restart nps-survey.service
   ```

4. **Verify the service came up**:
   ```bash
   sudo systemctl status nps-survey.service | head -10
   ```
   Look for `Active: active (running)`.

5. **Check logs for any startup errors**:
   ```bash
   sudo journalctl -u nps-survey.service --since "2 min ago" | tail -30
   ```

---

## Phase 5 — Verify the auth chain end-to-end (5 min)

### Test 1 — Auth status endpoint

From your laptop:

```cmd
curl.exe https://15-206-208-196.nip.io/nps/auth/status -b "cookies.txt"
```

This requires being logged in. Easier: log into the dashboard in a browser, then visit:
```
https://15-206-208-196.nip.io/nps/auth/status
```

Expected response:
```json
{"authorized": true, "mode": "pat"}
```

If you see `"mode": "none"` → the PAT isn't being read. See Troubleshooting.

### Test 2 — Dashboard banner

Open `https://15-206-208-196.nip.io/nps/dashboard` in a browser (logged in as admin).

The yellow "ASANA not connected" banner should **not** appear. If it does, the auth status check is failing.

### Test 3 — Real Asana API call

SSH to EC2 and run a one-off Python check:

```bash
sudo -u ssm-user -H bash -lc 'export PYTHONPATH=/home/ssm-user/.local/lib/python3.11/site-packages && cd /opt/nps-survey && /usr/bin/python3.11 << "PYEOF"
from app.services import asana_client
print("Authorized:", asana_client.is_authorized())
print("Mode:", asana_client.auth_mode())
# Try a real API call (replace with your actual project GID)
fields = asana_client.get_project_custom_fields("1213555970616516")
print(f"Fetched {len(fields)} custom field settings.")
for f in fields[:3]:
    print(" -", f.get("custom_field", {}).get("name", "?"))
PYEOF
'
```

Expected: `Mode: pat`, then a list of custom fields.

If you get `RuntimeError: ASANA not authorized` → see Troubleshooting.

---

## Troubleshooting

### `Mode: none` — PAT isn't being found

Most likely the EC2 IAM role can't read the secret yet, or the region is wrong.

**Check 1 — IAM:**
```bash
aws sts get-caller-identity
aws secretsmanager describe-secret --secret-id nps-survey/asana-pat --region ap-south-1
```
If `describe-secret` errors with AccessDenied, the inline policy didn't apply. Re-check Phase 3.

**Check 2 — Region:**
The Secrets Manager call defaults to `ap-south-1`. Confirm the secret is in that region (Phase 2).

**Check 3 — Restart didn't take:**
```bash
sudo systemctl restart nps-survey.service
sudo journalctl -u nps-survey.service --since "1 min ago" | grep -i pat
```

### `401 Unauthorized` from Asana

The PAT itself is invalid or revoked. Either:
- Wrong PAT pasted into Secrets Manager (regenerate, update the secret)
- Asana revoked it (check https://app.asana.com/0/my-apps → see if the token is still listed)

To update the secret value:
```bash
aws secretsmanager put-secret-value \
  --region ap-south-1 \
  --secret-id nps-survey/asana-pat \
  --secret-string '{"ASANA_PAT":"NEW_PAT_VALUE"}'
sudo systemctl restart nps-survey.service
```

### Service won't start after `git pull`

Most likely a syntax error or missing dependency. Check:
```bash
sudo journalctl -u nps-survey.service --since "2 min ago" | tail -50
```

If the import fails, run a syntax check as ssm-user:
```bash
sudo -u ssm-user -H bash -lc 'cd /opt/nps-survey && /usr/bin/python3.11 -c "from app.services import asana_client"'
```

### Tokens not picked up despite the secret existing

Clear the in-memory cache (the app caches the PAT after first read). A `systemctl restart` does this. If the service was running across the deploy, it may still hold the old `none` resolution — restart it.

---

## Rotation (when the PAT needs to change)

PATs don't auto-expire on Asana, but rotate on schedule (suggest every 90 days) or immediately if compromised.

1. Asana → My Apps → revoke the old token
2. Generate a new token
3. Update Secrets Manager:
   ```bash
   aws secretsmanager put-secret-value \
     --region ap-south-1 \
     --secret-id nps-survey/asana-pat \
     --secret-string '{"ASANA_PAT":"NEW_PAT_VALUE"}'
   ```
4. Restart the service:
   ```bash
   sudo systemctl restart nps-survey.service
   ```
5. Confirm `auth/status` returns `{"authorized": true, "mode": "pat"}`

---

## Future migration paths

This implementation keeps OAuth code intact, so future migrations are clean:

- **Add backup PAT holder (kuvinu@):** file follow-up on P426628259, kuvinu generates their own PAT, swap in via `put-secret-value`. No code change.
- **Move to OAuth (Token Vault or self-managed):** unset `ASANA_PAT_SECRET_ID`, complete OAuth at `/nps/auth/asana`. Auth chain auto-falls-back to OAuth tokens.
- **Service-account PAT:** create the service account, generate its PAT, swap into Secrets Manager. No code change.

---

## Tracking

Reflected in:
- `SETUP_CHECKLIST.md` — top-level approval status
- `docs/stonegate_pe_asana_token_request.md` — original ticket draft
- `docs/applink_onboarding_request.md` — AppLink/SCC ticket (separate, on hold)
