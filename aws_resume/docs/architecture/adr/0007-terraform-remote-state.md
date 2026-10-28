# 0007. Terraform remote state: dedicated S3 bucket with native locking
Status: Accepted
Date: 2026-10-23

## Context

CI runs Terraform, so state must be remote, shared, locked and protected.
The sibling project `tf_pr_reviewer` uses an S3 bucket plus a DynamoDB lock
table created by a hand-run `bootstrap/` config with local state. Since
Terraform 1.10 the S3 backend supports **native S3 locking**
(`use_lockfile = true`, which writes a `.tflock` object next to the state),
and DynamoDB-based locking is **deprecated** and will be removed in a future
release. The project also needs a place for the other things that must exist
before the pipeline does: the CI roles (ADR-0006), the permissions boundary,
and the budget alert.

## Options considered

### A. Dedicated S3 state bucket for aws_resume, S3 native locking (`use_lockfile`)
- **Pros:** No DynamoDB table, so fewer resources and IAM actions. Follows
  current HashiCorp guidance. A per-project bucket keeps the blast radius
  small: aws_resume roles get no access to other projects' state and vice versa.
- **Cons:** Needs Terraform ≥ 1.10. One more bucket (pennies).
- **Rough cost:** About $0.01/month.

### B. Reuse `tf_pr_reviewer`'s state bucket and DynamoDB lock table under a new key
- **Pros:** Nothing new to bootstrap.
- **Cons:** Couples two projects' lifecycles. The sibling bucket has
  `prevent_destroy`, but its roles would need cross-project IAM. Uses the
  deprecated DynamoDB locking.
- **Rough cost:** $0.

### C. HCP Terraform (Terraform Cloud) free tier
- **Pros:** Managed state, locking, UI and run history.
- **Cons:** A third-party SaaS holding state, plus an API token (a secret)
  in GitHub. Runs would execute outside our GitHub Actions gate unless
  configured carefully. Free tier is limited by managed resource count.
  Teaches less about AWS.
- **Rough cost:** $0 within limits.

## Decision

**Option A.** `aws_resume/infra/bootstrap/` (local state, run once by hand
with admin credentials, its state kept out of Git) creates:

1. **State bucket** `aws-resume-tfstate-<account-id>` with versioning,
   SSE-S3, all Block Public Access flags, `BucketOwnerEnforced` object
   ownership, a bucket policy that denies non-TLS access, a lifecycle rule
   that expires non-current versions after 90 days, and Terraform
   `prevent_destroy`.
2. **CI roles + permissions boundary** (ADR-0006), reusing the existing
   GitHub OIDC provider.
3. **AWS Budget** ($5/month, email alerts at 50/80/100% actual and 100%
   forecast). It goes here so the guardrail exists before any spend and
   can't be removed by the CI apply role.

The main stack's backend:

```
backend "s3" {
  bucket       = "aws-resume-tfstate-<account-id>"
  key          = "aws_resume/prod/terraform.tfstate"
  region       = "us-east-1"
  encrypt      = true
  use_lockfile = true
}
```

(Shown for illustration only. The implementation phase writes the real file.)

## Consequences

- **Security:** State holds no secrets by design, but it is still treated
  as confidential (it maps the whole stack). Only the two infra roles can
  read it. Only the apply role can write the state object, and the plan
  role can write only the `.tflock` object. Versioning lets you recover from
  a corrupted or bad state write.
- **Bootstrap state:** the bootstrap's own local state file must be kept
  safe outside Git, the same caveat as `tf_pr_reviewer/bootstrap/README.md`.
  Losing it isn't fatal, because the resources can be imported, but it's
  annoying. Document this in the bootstrap README.
- **Infra pipeline:** pins Terraform ≥ 1.10, and `concurrency` with
  `cancel-in-progress` (the sibling's pattern) as a second line of defence
  against overlapping applies.
- **Backend/frontend pipelines:** no state access at all.
- **Teardown:** destroying the main stack leaves the bootstrap resources in
  place. Fully removing the project means emptying and deleting the state
  bucket by hand after the main stack is gone.

Sources: [Terraform S3 backend docs](https://developer.hashicorp.com/terraform/language/backend/s3) (`use_lockfile`, DynamoDB locking deprecated).
