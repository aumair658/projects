# 0003. Backend runtime: API Gateway HTTP API + Lambda (Python)
Status: Accepted
Date: 2026-10-23

## Context

The v1 backend is a visitor counter _(assumption, see the overview's open
questions)_: `POST /api/visits` increments and returns the count, and
`GET /api/visits` returns it. Traffic is tiny and bursty. The runtime should
cost nothing while idle, have a sensible abuse ceiling, and be explainable
in an interview. VPC, NAT and always-on compute are non-goals.

## Options considered

### A. API Gateway **HTTP API** → Lambda
- **Pros:** Managed HTTPS front door with **stage-level throttling** (a hard
  rate/burst cap that protects the downstream services and the bill).
  Built-in access logging. Simple Lambda proxy integration. Cheaper and
  simpler than REST APIs. API Gateway + Lambda + DynamoDB is the most widely
  recognised serverless pattern, which is good for interviews.
- **Cons:** One more resource than a Function URL. After the legacy 12-month
  free tier, $1.00 per million requests (negligible at this scale). No
  native WAF attachment (WAF can attach at CloudFront instead). The
  `execute-api` endpoint is publicly reachable even when CloudFront fronts it.
- **Rough cost:** $0 to $0.01 per month at about 5k requests.

### B. Lambda **Function URL** behind CloudFront (OAC for Lambda)
- **Pros:** No API Gateway, and no per-request charge beyond Lambda. With
  CloudFront OAC and `AWS_IAM` auth, the function can **only** be called
  through CloudFront, which closes the direct-access gap that Option A has.
  `tf_pr_bot` already uses Function URLs, so the pattern is familiar.
- **Cons:** No built-in throttling. You'd rely on Lambda reserved
  concurrency, and new accounts often can't reserve concurrency because
  their account limit is low. OAC with Lambda URLs needs the client to send
  an `x-amz-content-sha256` header on POST/PUT bodies, which is a non-obvious
  gotcha. Less standard, so harder to talk about in interviews.
- **Rough cost:** $0.

### C. API Gateway **REST API** → Lambda
- **Pros:** Most features: usage plans/API keys, request validation, native
  WAF, private endpoints, and the default endpoint can be disabled.
- **Cons:** $3.50 per million requests (3.5× HTTP API) and much more
  configuration surface. None of the extra features are needed for a counter.
- **Rough cost:** About $0.02 per month at this scale. The extra complexity
  is the real cost.

### Language sub-decision
- **Python** (latest Lambda-supported 3.x, arm64/Graviton): matches
  `tf_pr_bot`, has a tiny cold start for a boto3 one-liner, and pytest plus
  `moto` make unit testing easy. **Default.**
- **Node.js/TypeScript:** matches a JS frontend. Adds a bundling step.

## Decision

**Option A: API Gateway HTTP API → Lambda (Python, arm64)**, fronted by the
CloudFront `/api/*` behaviour (ADR-0001) so the browser stays same-origin.

- `$default` stage with throttling of **10 rps steady / 20 burst** (adjust
  once real traffic is known). Access logs in JSON to CloudWatch, 14-day
  retention.
- Routes `GET /api/visits` and `POST /api/visits` only. Everything else
  returns 404.
- Lambda: 128 MB, 3-second timeout, `live` alias. API Gateway invokes the
  alias, not `$LATEST`. Environment variable `TABLE_NAME` only. X-Ray off
  in v1.
- Terraform creates the function from a placeholder zip with
  `ignore_changes = [filename, source_code_hash, publish]`. The backend
  pipeline owns the code.
- **Accepted gap:** the `execute-api` URL is reachable directly, bypassing
  CloudFront. Mitigations are stage throttling and the DynamoDB capacity cap
  (ADR-0004). If this matters later, either (1) switch to Option B, or
  (2) have CloudFront inject a secret origin header that Lambda checks,
  stored in SSM Parameter Store. Option 2 introduces the project's first
  secret, so don't do it unless needed.

## Consequences

- **Security:** The Lambda execution role is limited to `UpdateItem`/`GetItem`
  on one table plus its log group. The Lambda resource policy allows invoke
  only from this API's ARN. Input surface is trivial (no body parsing
  needed), which keeps Semgrep findings meaningful. The counter is
  intentionally unauthenticated and can be inflated by a script. That's
  acceptable for a vanity metric and documented.
- **Infra pipeline:** owns the API, stage, routes, integration, Lambda
  function and alias, execution role, log groups and alarms
  (`Errors`, `Throttles`, `5xx`).
- **Backend pipeline:** lint → pytest (with moto) → Semgrep → zip →
  `lambda update-function-code` → `publish-version` → `update-alias live`.
  Its role is limited to those actions on one function ARN. Rollback means
  pointing the alias at the previous version.
- **Frontend pipeline:** unaffected, apart from the JS calling the relative
  path `/api/visits`.

Sources: [API Gateway pricing](https://aws.amazon.com/api-gateway/pricing/) (HTTP API $1.00/M, REST $3.50/M in us-east-1; 1M HTTP API calls/month free for 12 months).
