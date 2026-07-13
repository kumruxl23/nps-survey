# Midway-gated ALB in front of the NPS app

Put an internet-facing ALB with an `authenticate-oidc` (Amazon Federate /
Midway) listener rule in front of the app. Midway gates the network edge;
the app needs zero auth code for that gate. The app's own admin/editor/
viewer roles still control *what* an authenticated user can do.

**You run these** (admin/write creds for account 399016860083; the
read-only Conduit access can't create infra). Non-destructive except where
noted. Store the OIDC client secret in Secrets Manager, never in the ALB
config in plaintext beyond the listener requirement.

> Prerequisite decision: this makes the app internet-facing. See
> `docs/asr_engagement_status.md` — confirm the ASR reclassification /
> interim acceptance BEFORE pointing real traffic at prod.

## App-side prep (already done in code)

Set these on the EC2 service environment so Flask behaves behind the proxy:

```
NPS_BEHIND_PROXY=1
NPS_ALLOWED_HOSTS=nps.aifa.amazon.dev     # your real domain
```

`create_app()` then enables ProxyFix (trusts `X-Forwarded-*`, emits
`https://`), Secure/HttpOnly/SameSite cookies, and rejects spoofed Host
headers.

## 0. Variables

```bash
REGION=ap-south-1
ACCOUNT=399016860083
VPC_ID=vpc-xxxxxxxx
SUBNETS="subnet-aaaa subnet-bbbb"        # 2+ public subnets for the ALB
INSTANCE_ID=i-06ccd83e4b55fa98f
APP_PORT=5000                            # gunicorn port
DOMAIN=nps.aifa.amazon.dev
CERT_ARN=arn:aws:acm:$REGION:$ACCOUNT:certificate/xxxx   # ISSUED
# Federate OIDC (from the Federate client you register in step 1)
OIDC_CLIENT_ID=xxxx
OIDC_SECRET_ARN=arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:nps/federate-oidc
```

## 1. Register a Federate OIDC client (Midway login)

- In Amazon Federate, create an OIDC application/client for the app URL.
- Redirect/callback URL (fixed ALB path): `https://$DOMAIN/oauth2/idpresponse`
- Standard endpoints:
  - issuer `https://idp.federate.amazon.com`
  - authorize `/api/oauth2/v1/authorize`
  - token `/api/oauth2/v2/token`
  - userinfo `/api/oauth2/v1/userinfo`
  - scope `openid`
- Save the client secret to Secrets Manager (`$OIDC_SECRET_ARN`).

## 2. Domain + ACM cert

- Route 53 hosted zone for `$DOMAIN` (we use SuperNova `*.aifa.amazon.dev`).
- Request an ACM cert in `$REGION`; wait for status `ISSUED`.

## 3. Security groups

```bash
# ALB SG: 443 from anywhere (Midway gates it)
ALB_SG=$(aws ec2 create-security-group --group-name nps-alb-sg \
  --description "NPS ALB" --vpc-id $VPC_ID --region $REGION \
  --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id $ALB_SG \
  --protocol tcp --port 443 --cidr 0.0.0.0/0 --region $REGION

# Instance SG: app port ONLY from the ALB SG
INSTANCE_SG=$(aws ec2 create-security-group --group-name nps-instance-sg \
  --description "NPS app from ALB only" --vpc-id $VPC_ID --region $REGION \
  --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id $INSTANCE_SG \
  --protocol tcp --port $APP_PORT --source-group $ALB_SG --region $REGION
# then attach INSTANCE_SG to the instance and remove any public :443/:5000 ingress
```

## 4. Target group + register the instance

```bash
TG_ARN=$(aws elbv2 create-target-group --name nps-tg \
  --protocol HTTP --port $APP_PORT --vpc-id $VPC_ID \
  --health-check-path /nps/dashboard --matcher HttpCode=200-404 \
  --region $REGION --query 'TargetGroups[0].TargetGroupArn' --output text)
aws elbv2 register-targets --target-group-arn $TG_ARN \
  --targets Id=$INSTANCE_ID --region $REGION
```

## 5. Create the ALB

```bash
ALB_ARN=$(aws elbv2 create-load-balancer --name nps-alb \
  --type application --scheme internet-facing \
  --subnets $SUBNETS --security-groups $ALB_SG \
  --region $REGION --query 'LoadBalancers[0].LoadBalancerArn' --output text)
```

## 6. HTTPS listener with OIDC auth (the core step)

```bash
aws elbv2 create-listener --load-balancer-arn $ALB_ARN \
  --protocol HTTPS --port 443 --certificates CertificateArn=$CERT_ARN \
  --region $REGION \
  --default-actions '[
    {
      "Type": "authenticate-oidc",
      "Order": 1,
      "AuthenticateOidcConfig": {
        "Issuer": "https://idp.federate.amazon.com",
        "AuthorizationEndpoint": "https://idp.federate.amazon.com/api/oauth2/v1/authorize",
        "TokenEndpoint": "https://idp.federate.amazon.com/api/oauth2/v2/token",
        "UserInfoEndpoint": "https://idp.federate.amazon.com/api/oauth2/v1/userinfo",
        "ClientId": "'"$OIDC_CLIENT_ID"'",
        "ClientSecret": "<inject from '"$OIDC_SECRET_ARN"'>",
        "Scope": "openid",
        "OnUnauthenticatedRequest": "authenticate"
      }
    },
    {"Type": "forward", "Order": 2, "TargetGroupArn": "'"$TG_ARN"'"}
  ]'
```

## 7. Route 53 alias

Create an A/ALIAS record `$DOMAIN` -> the ALB DNS name.

## 8. Verify

- Hit `https://$DOMAIN/nps/dashboard` in a browser -> Midway login -> app.
- `curl` without Midway cookies -> redirected to Midway (blocked).
- Confirm the instance has no public :443/:5000 ingress anymore.

## Gotchas (these bite)

- Redirect URI must match EXACTLY between the Federate client and the ALB
  (`/oauth2/idpresponse`) — the #1 setup failure.
- Set `NPS_BEHIND_PROXY=1` (done in code) or you'll get http:// links and
  mixed-content.
- Add `$DOMAIN` to `NPS_ALLOWED_HOSTS`.
- Midway only gates the network. App-level authorization (admin/editor/
  viewer) is still yours to enforce.
