# 0006. CI authentication: GitHub OIDC, environment-pinned roles per pipeline
Status: Proposed
Date: 2026-10-23

## Context

PLAN.md already fixes *that* CI uses GitHub OIDC → IAM roles with one
least-privilege role per pipeline. This ADR decides *how*: which `sub`
claims each role trusts, how plan and apply are separated, and how to stop
the infra role from escalating its own privileges.

What the repo already has:
- The account already has a `token.actions.githubusercontent.com` OIDC
  provider, created by `tf_pr_reviewer/bootstrap`. AWS allows only one per
  URL per account.
- `tf_pr_reviewer`'s role trusts `repo:<repo>:*`. This means **any**
  workflow on **any** branch or PR in the monorepo can assume a role that
  applies infrastructure, including the other projects' workflows. That's
  acceptable for a throwaway fixture, but it's the main thing to improve here.
- The repo uses GitHub's **immutable subject claim format**
  (`repo:aumair658@58346411/projects@1337327941:...`), not the classic
  `repo:aumair658/projects:...`. Trust policies must use the immutable form
  or every role assumption fails. Copy the exact prefix from Settings >
  Actions > General > OIDC (see `tf_pr_reviewer/bootstrap/variables.tf`).

## Options considered

### A. One role per pipeline, trusting `repo:aumair658@58346411/projects@1337327941:*`
- **Pros:** Simple, and matches the sibling project.
- **Cons:** Any workflow file in the monorepo, including one added in a
  malicious or careless PR, can assume any of the roles. PR runs get
  apply-level permissions. "Per pipeline" ends up meaning only "per policy",
  not "per caller".
- **Rough cost:** $0.

### B. Roles pinned by **GitHub Environment** (`sub = repo:aumair658@58346411/projects@1337327941:environment:<env>`), with a separate read-only plan role for PRs
- **Pros:** A token for `environment:aws-resume-prod-backend` only exists
  for a job that declares that environment. Environments can be limited to
  the `main` branch through deployment branch rules and can require
  reviewers. So each role is bound to a specific pipeline job **and** to
  `main`. PR plans use a separate read-only role trusting
  `repo:aumair658@58346411/projects@1337327941:pull_request`. GitHub does not give OIDC tokens
  to fork PRs by default, so outsiders can't use it.
- **Cons:** Needs three GitHub Environments configured (manual, in repo
  settings). The plan role can still be assumed by any same-repo PR
  workflow, which is acceptable because it is read-only plus lockfile writes.
- **Rough cost:** $0.

### C. Custom OIDC `sub` claim template including `job_workflow_ref`
- **Pros:** Pins a role to a specific workflow *file*, the strongest binding.
- **Cons:** Changing the repo's OIDC subject template affects **every**
  workflow in the monorepo, including `tf_pr_reviewer`'s role trust. That's
  a cross-project change, and the claim format is harder to explain.
  Overkill for now.
- **Rough cost:** $0.

## Decision

**Option B.** The four CI roles are created in `aws_resume/infra/bootstrap/`
(local state, run by hand) and **reuse the existing OIDC provider through a
data source**:

| Role | Trust `sub` | Permission scope |
|---|---|---|
| `aws-resume-infra-plan` | `repo:aumair658@58346411/projects@1337327941:pull_request` | Read-only on the stack's services. `s3:GetObject` on the state key. Get/Put/Delete on the `.tflock` key only |
| `aws-resume-infra-apply` | `repo:aumair658@58346411/projects@1337327941:environment:aws-resume-prod-infra` | CRUD on stack resources scoped to `aws-resume-*` names, zone ID and ARNs where the services support it. State read/write |
| `aws-resume-backend-deploy` | `repo:aumair658@58346411/projects@1337327941:environment:aws-resume-prod-backend` | `lambda:UpdateFunctionCode`, `PublishVersion`, `UpdateAlias`, `GetFunction`, `GetAlias` on one function ARN |
| `aws-resume-frontend-deploy` | `repo:aumair658@58346411/projects@1337327941:environment:aws-resume-prod-frontend` | `s3:ListBucket` on site bucket. `s3:PutObject`/`DeleteObject` on `site-bucket/*`. `cloudfront:CreateInvalidation` on one distribution |

All trust policies also require `aud = sts.amazonaws.com` (`StringEquals`,
not `StringLike`, for the `sub` claim). Maximum session duration is 1 hour.

**Privilege-escalation guard for the apply role:** a managed policy
`aws-resume-boundary` is created in bootstrap. The apply role may
`iam:CreateRole`/`PutRolePolicy`/`AttachRolePolicy` **only** when
`iam:PermissionsBoundary` equals that boundary's ARN, and only for roles
named `aws-resume-*`. It may not modify its own role, the boundary policy
or the other CI roles. `iam:PassRole` is limited to `aws-resume-*` roles,
with `iam:PassedToService = lambda.amazonaws.com`.

**GitHub side:** three Environments (`aws-resume-prod-infra`, `-backend` and
`-frontend`), each limited to the `main` branch and each with the owner as
a **required reviewer** (owner decision 2026-10-28: approval on all three
pipelines). The repo is public, so environment protection rules are free. Role ARNs are stored as **repository variables**
(`AWS_RESUME_INFRA_PLAN_ROLE_ARN`, and so on), namespaced like
`TF_PR_REVIEWER_AWS_ROLE_ARN`. Workflows set `permissions: id-token: write`
only on the jobs that need it.

## Consequences

- **Security:** No long-lived keys. A compromised backend or frontend
  workflow can only ship code or content, never change IAM, DNS or data.
  PR-triggered code can never get write access. The infra apply role is
  powerful, but it is gated by human approval, branch rules and the
  permissions boundary. CloudTrail (free management-event trail) records
  every role assumption with the GitHub `sub` in the session context.
- **Bootstrap:** the roles are created by hand once with admin
  credentials. Later changes to them are also manual bootstrap re-runs,
  intentionally outside the apply role's reach.
- **Infra pipeline:** two jobs. `plan` on `pull_request` uses the plan role.
  `apply` on push to `main` uses `environment: aws-resume-prod-infra`.
  Finding the exact read and write action list will take a few iterations
  (the sibling project's comments show the AWS provider needs extra `Get*`
  permissions on refresh). Start from AWS-managed `ReadOnlyAccess` for the
  plan role and tighten later.
- **Backend/frontend pipelines:** each deploy job declares its environment.
  Test, lint and scan jobs run without AWS credentials at all.
- **Cross-project:** `tf_pr_reviewer`'s wildcard trust remains. Tightening
  it is a recommended follow-up, tracked in PLAN.md.
