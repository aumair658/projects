# 0002. IaC tool: Terraform
Status: Accepted
Date: 2026-10-23

## Context

PLAN.md fixes "infrastructure as code" and "nothing created by hand except
documented bootstrap". It does not formally record *which* tool. The owner
already uses Terraform in this monorepo (`tf_pr_reviewer`, `tf_pr_bot`,
`aws-tf-mcp`) and wants to deepen Terraform skills for career growth. The
infra pipeline design (fmt → validate → tfsec/checkov → plan comment →
gated apply) already assumes Terraform.

## Options considered

### A. Terraform (HashiCorp AWS provider)
- **Pros:** Matches the owner's existing skills, CI patterns and security
  tooling (tfsec, checkov, the `tf_pr_bot` reviewer). Readable `plan` output
  works well as a PR comment. Multi-cloud, so the skill transfers. Very
  strong market demand. Large ecosystem of modules and examples.
- **Cons:** You manage state yourself (ADR-0007). BSL licence since 2023
  (OpenTofu is the open-source fork. Configs are near-compatible, so this
  isn't a lock-in risk for a personal project). Lambda code packaging sits
  awkwardly in Terraform, which we avoid by giving code to the backend
  pipeline (see overview §2.2).
- **Rough cost:** $0 (CLI). State costs fractions of a cent in S3.

### B. AWS CDK (TypeScript/Python) → CloudFormation
- **Pros:** Real programming language. High-level constructs (for example
  one construct for an S3 static site with CloudFront). State is managed by
  CloudFormation, so no state bucket. Native Lambda asset bundling.
- **Cons:** New tool for the owner, so it competes with the Terraform
  learning goal. Synthesised CloudFormation diffs are harder to review in a
  PR than `terraform plan`. Needs a CDK bootstrap stack anyway. The existing
  tfsec-based tooling would need replacing (cfn-nag/checkov on synthesised
  templates).
- **Rough cost:** $0 (CloudFormation is free for AWS resource types).

### C. AWS SAM / raw CloudFormation
- **Pros:** First-party, no state to manage. SAM is very convenient for
  Lambda + API.
- **Cons:** Verbose YAML. Weaker than Terraform for non-serverless pieces
  (Route 53/ACM cross-region needs StackSets or a separate stack). Doesn't
  build the skill the owner is targeting.
- **Rough cost:** $0.

## Decision

**Terraform**, with:
- Terraform CLI **≥ 1.10** (needed for S3 native state locking, ADR-0007),
  pinned in CI through `hashicorp/setup-terraform` and in `required_version`.
- AWS provider pinned to a major version (`~> 6.x` or whatever major is
  current at implementation time). Commit `.terraform.lock.hcl`.
- **Naming convention** (owner decision 2026-10-28): every AWS resource
  name starts with `aws-resume-`, e.g. `aws-resume-visitor-count`,
  `aws-resume-infra-apply`. For globally unique names (S3 buckets), append
  the account ID: `aws-resume-site-<account-id>`. IAM policies scope access
  by this prefix.
- **Tagging standard:** `default_tags` on the provider, so every resource
  gets them automatically: `Project = aws-resume`, `Environment = prod`,
  `ManagedBy = terraform`, `Repo = aumair658/projects`. Activate `Project`
  as a **cost allocation tag** once (in the bootstrap) so Cost Explorer and
  the budget can filter on it. Create a Resource Group on `Project = aws-resume`
  to see the whole stack in one place. Tags are for grouping and cost.
  Isolation from the sibling projects in this account comes from the IAM
  name-prefix scoping and the permissions boundary (ADR-0006), not from tags.
- Two root configurations: `aws_resume/infra/bootstrap/` (local state, run
  once by hand) and `aws_resume/infra/` (remote state, CI only). Extract
  modules (`site`, `api`, `dns`) once the root config grows, not before.
- A second provider alias for `us-east-1` is only needed if the owner picks
  a non-us-east-1 region (the ACM cert for CloudFront must be in us-east-1).

## Consequences

- **Security:** tfsec/checkov run on every PR as a merge gate. Every
  suppression needs an inline justification. State must hold no secrets
  (placeholder-then-out-of-band pattern from `tf_pr_bot`).
- **Infra pipeline:** follows the existing `tf_pr_reviewer-terraform.yml`
  structure (plan as PR comment, `concurrency` with `cancel-in-progress`,
  apply behind an environment approval) and adds tfsec/checkov steps, which
  are commented out in the sibling.
- **Backend pipeline:** does **not** run Terraform. It calls the Lambda API
  directly to ship code (ADR-0003). Terraform's `ignore_changes` on code
  attributes prevents the two from fighting.
- **Frontend pipeline:** does not run Terraform. It reads the bucket name
  and distribution ID from GitHub variables, set once from Terraform outputs.
