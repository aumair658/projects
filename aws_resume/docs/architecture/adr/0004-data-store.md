# 0004. Data store: DynamoDB with minimal provisioned capacity
Status: Accepted
Date: 2026-10-23

## Context

The backend stores one number, the visit count, and must increment it
atomically under concurrent requests. Future small features might add a few
more keys. There is no relational data and no PII (unique-visitor
deduplication is a non-goal).

## Options considered

### A. DynamoDB, **provisioned** capacity (1 RCU / 1 WCU, no autoscaling)
- **Pros:** Serverless and IAM-authenticated, so there are no passwords.
  Atomic `UpdateItem ... ADD #count :one` with `ReturnValues=UPDATED_NEW`
  removes race conditions. The **always-free tier covers 25 RCU / 25 WCU
  and 25 GB**, so this costs $0 indefinitely. The fixed capacity is a
  **cost ceiling**: a flood of writes gets throttled instead of billed.
- **Cons:** Throttling during a genuine spike (1 WCU is about 1 write per
  second sustained, with burst credit). For a resume site that's fine, and
  it shows up as an alarm, not an outage of the static site.
- **Rough cost:** $0.

### B. DynamoDB, **on-demand** capacity
- **Pros:** No capacity planning. Absorbs spikes.
- **Cons:** Request charges aren't covered by the always-free tier. More
  importantly, there's **no ceiling**: abuse scales the bill linearly.
  Cheap per request, but it's the wrong failure mode for a personal project.
- **Rough cost:** Fractions of a cent at expected traffic. Unbounded under abuse.

### C. Aurora Serverless v2 / RDS
- **Cons:** Needs a VPC. Aurora Serverless v2 has a minimum capacity that
  bills while idle (tens of dollars a month), and RDS bills per hour.
  Massive overkill for one integer.
- **Rough cost:** ≥ $40/month while idle. Rejected.

### D. S3 object or SSM parameter as a counter
- **Pros:** Zero new services.
- **Cons:** No atomic increment, so read-modify-write races lose counts.
  Using a "database" that isn't one is a poor pattern to explain in an interview.
- **Rough cost:** $0.

## Decision

**Option A: DynamoDB with provisioned 1 RCU / 1 WCU, autoscaling off.**

- Table `aws-resume-visitor-count`, partition key `pk` (string). There is
  one item, `pk = "site"`, with numeric attribute `count`.
- Encryption with the **AWS-owned key** (default, free). Point-in-time
  recovery **on** (cost is per GB stored, so effectively $0 for KBs).
  `deletion_protection_enabled = true`.
- Alarm on `ThrottledRequests > 0` to tell us when to raise capacity, which
  is still free up to 25.

## Consequences

- **Security:** Access is IAM-only. The Lambda role gets `UpdateItem` and
  `GetItem` on this one table ARN. Data is public-classified, so the
  AWS-owned key is appropriate. tfsec/checkov "no CMK" findings get a
  documented suppression. Deletion protection plus PITR guard against an
  accidental `terraform destroy`. Turning deletion protection off becomes
  an explicit, reviewable PR.
- **Cost:** $0, with throttling as the abuse ceiling, working together with
  the API stage throttle (ADR-0003).
- **Infra pipeline:** owns the table, PITR and the alarm. The apply role
  needs `dynamodb:CreateTable/UpdateTable/DeleteTable/Describe*/Tag*` and
  the PITR actions on `aws-resume-*` tables.
- **Backend pipeline:** no table permissions. Only the runtime role touches data.
- **Frontend pipeline:** unaffected.
