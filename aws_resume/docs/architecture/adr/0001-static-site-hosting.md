# 0001. Static site hosting: private S3 + CloudFront with OAC
Status: Proposed
Date: 2026-10-23

## Context

The resume is a static site: HTML, CSS, a little JS, maybe a PDF. It needs
HTTPS on a custom domain (ADR-0005), low cost, and a clear security story.
The project's design principles put "private S3 behind CloudFront with OAC"
first, but we still compare it with real alternatives so the trade-off can
be explained.

## Options considered

### A. Private S3 bucket + CloudFront with Origin Access Control (OAC)
- **Pros:** Bucket stays fully private (Block Public Access on, and the bucket
  policy allows only this distribution through `AWS:SourceArn`). HTTPS with
  an ACM cert, HTTP/2 and HTTP/3, edge caching, managed security-headers
  response policy. One distribution can also route `/api/*` to the backend,
  giving same-origin with no CORS. Free AWS Shield Standard. OAC is the
  current AWS-recommended replacement for the legacy OAI, and it supports
  SSE-KMS and all regions.
- **Cons:** More moving parts to learn (distribution, OAC, bucket policy,
  cache and origin-request policies). Invalidations are needed after deploys.
  OAC with the S3 *REST* endpoint does not do "pretty URL" index resolution
  for subdirectories (`/about/` → `/about/index.html`), so you either use
  flat files or a small CloudFront Function. CloudFront Functions have their
  own free allowance and are not needed for a single-page resume.
- **Rough cost:** $0 under the CloudFront always-free tier (1 TB out and 10M
  requests per month) plus about $0.01 of S3.

### B. S3 static website hosting endpoint (public bucket), optionally behind CloudFront
- **Pros:** Simplest possible setup. Native index/error document handling.
- **Cons:** The website endpoint is **HTTP-only** and needs a **public** bucket.
  This is exactly the misconfiguration tfsec flags (and the deliberate finding
  in `tf_pr_reviewer/s3.tf`). Even with CloudFront in front, the bucket stays
  publicly readable and OAC cannot be used with website endpoints.
- **Rough cost:** About $0 as well.

### C. AWS Amplify Hosting
- **Pros:** Git-connected builds, previews per branch, managed TLS and CDN,
  very fast to start.
- **Cons:** Hides CloudFront, S3 and IAM behind a managed abstraction, which
  defeats the learning goal. Its own build pipeline overlaps with, and
  competes with, our GitHub Actions gate. Less control over headers and
  origins. Billed per build minute and per GB served once beyond the free
  allowance.
- **Rough cost:** Low, but not $0 once outside free allowances.

### D. CloudFront flat-rate "Free" pricing plan (variant of A)
AWS now offers flat-rate CloudFront plans: Free at $0 (1M requests, 100 GB),
Pro at $15/month (includes WAF rules) and Business. They bundle DNS, DDoS
protection and WAF with no overage charges.
- **Pros:** No surprise bills, and WAF is included on Pro.
- **Cons:** New. Lower limits on the Free plan than the pay-as-you-go
  always-free tier. Terraform/provider support and interaction with our
  Route 53 setup still need checking.
- **Rough cost:** $0 (Free) or $15/month (Pro).

## Decision

**Option A**: a private S3 bucket (SSE-S3, versioning, all four Block Public
Access flags, TLS-only bucket policy) served only through a CloudFront
distribution using OAC, with:

- `viewer_protocol_policy = redirect-to-https` and minimum protocol `TLSv1.2_2021`
- the managed `SecurityHeadersPolicy` response-headers policy plus a custom
  Content-Security-Policy
- `default_root_object = index.html`, price class `PriceClass_100` (NA/EU edges, cheapest)
- a second ordered behaviour for `/api/*` pointing at the API (ADR-0003) with
  the managed `CachingDisabled` cache policy and `AllViewerExceptHostHeader`
  origin-request policy

Stay on pay-as-you-go pricing with the always-free tier. Re-evaluate Option
D, and WAF, if abuse or cost becomes a concern.

## Consequences

- **Security:** No public bucket anywhere. The only read path is the signed
  CloudFront request. The bucket policy has to reference the distribution
  ARN, which creates a Terraform ordering dependency (distribution → bucket
  policy) that Terraform handles naturally. tfsec/checkov will still flag
  "no WAF" and "no CMK" on CloudFront and S3. Add explicit, commented
  suppressions explaining the cost rationale. CloudFront access logging is
  **on** (owner decision 2026-10-28) and goes to a separate
  `aws-resume-cf-logs-<account-id>` bucket with 30-day expiry, so that check
  passes without a suppression.
- **WAF deferred:** a WAF web ACL costs at least $5/month while idle. The
  trigger to add it is sustained abuse visible in the budget alert or in
  API Gateway metrics.
- **Infra pipeline:** owns bucket, OAC, distribution, policies and alarms.
- **Frontend pipeline:** needs only `s3:PutObject`/`DeleteObject`/`ListBucket`
  on this bucket and `cloudfront:CreateInvalidation` on this distribution.
  It should set `Cache-Control` per file type when syncing (long cache for
  hashed assets, short for `index.html`) to keep invalidations small. 1,000
  invalidation paths per month are free.
- **Backend pipeline:** unaffected.

Sources: [CloudFront pricing](https://aws.amazon.com/cloudfront/pricing/).
