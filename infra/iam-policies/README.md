# IAM policies for nps-survey-ec2-role

Least-privilege replacements for the over-broad AWS-managed policies
that were originally attached. Apply these in place of the managed
policies during the ASR review.

## State to converge to

The role should end up with:

- `AmazonSSMManagedInstanceCore` (AWS-managed) — for SSM Session Manager
- `InfoSecHostMonitoringPolicy-DO-NOT-DELETE` (account-mandated) — leave as-is
- `AllowNpsDynamoDB` (custom, this dir) — read/write only Nps* tables
- `AllowNpsSESSend` (custom, this dir) — send email from the verified domain only
- `AllowReadAsanaPAT` (existing inline) — `secretsmanager:GetSecretValue` on `nps-survey/asana-pat*` only
- `AllowReadStakeholderWorkbook` (existing inline) — `s3:GetObject` on `whs-cpt-nps-survey/*` only
- `AllowInvokeSlab` (custom, this dir) — `execute-api:Invoke` for the SLAB
  API (alias→Slack ID lookup, replaces Slack `users:read`)
- `AllowReadSlabApiKey` (add as inline when onboarded) —
  `secretsmanager:GetSecretValue` on `nps-survey/slab-api-key*` only

> **Scope-down TODO for `AllowInvokeSlab`:** the resource is currently
> `arn:aws:execute-api:*:*:*` because the SLAB API Gateway ARN isn't
> known until onboarding. Once the Gamma/Prod endpoints are provided
> (ticket D490637982), replace the wildcard with the specific
> `arn:aws:execute-api:<region>:<acct>:<api-id>/*` to stay least-privilege.

To remove:

- `AmazonDynamoDBFullAccess` — too broad, replaced by `AllowNpsDynamoDB`
- `AmazonSESFullAccess` — too broad, replaced by `AllowNpsSESSend`

## Apply (run with admin creds, NOT from the EC2)

```bash
ROLE=nps-survey-ec2-role
ACCOUNT=399016860083
REGION=ap-south-1

# 1. Create the two custom managed policies
DDB_ARN=$(aws iam create-policy \
  --policy-name AllowNpsDynamoDB \
  --policy-document file://AllowNpsDynamoDB.json \
  --description "Read/write access to Nps* DynamoDB tables only" \
  --query 'Policy.Arn' --output text)

SES_ARN=$(aws iam create-policy \
  --policy-name AllowNpsSESSend \
  --policy-document file://AllowNpsSESSend.json \
  --description "SendEmail/SendRawEmail from verified NPS sender only" \
  --query 'Policy.Arn' --output text)

# 2. Attach them to the role
aws iam attach-role-policy --role-name $ROLE --policy-arn $DDB_ARN
aws iam attach-role-policy --role-name $ROLE --policy-arn $SES_ARN

# 3. Detach the over-broad managed policies
aws iam detach-role-policy --role-name $ROLE \
  --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess
aws iam detach-role-policy --role-name $ROLE \
  --policy-arn arn:aws:iam::aws:policy/AmazonSESFullAccess

# 4. Verify
aws iam list-attached-role-policies --role-name $ROLE
aws iam list-role-policies --role-name $ROLE
```

## Smoke-test after applying

From the EC2 (Session Manager):

```bash
# DynamoDB read - should still work
aws dynamodb scan --table-name NpsOrgConfig --region ap-south-1 --max-items 1

# SES send - should still work
aws ses get-identity-verification-attributes \
  --identities whs-cpt.amazon.dev --region ap-south-1

# DynamoDB on a non-Nps table - should NOW fail (proves scoping works)
aws dynamodb list-tables --region ap-south-1   # this is allowed
aws dynamodb describe-table --table-name CloudTrailEvents --region ap-south-1
# expected: AccessDeniedException

# Restart the app and verify it still serves requests
sudo systemctl restart nps-survey.service
sudo journalctl -u nps-survey.service --since '1 minute ago'
```

If anything in the app breaks, re-attach the broader policies temporarily
and check which call hit a deny in the journal logs.
