# bootstrap

One-time setup, run **locally by hand** (not from CI, and not automatically —
this is the chicken-and-egg piece: the pipeline can't create its own state
bucket and IAM role before it exists).

## Before you run this

1. Edit `variables.tf`:
   - `state_bucket_name` - must be globally unique.
   - `github_repo` - replace `YOUR_GH_ORG/YOUR_REPO` with your actual repo,
     e.g. `aumair658/projects`. This is the **monorepo root repo**
     (the one containing `tf_pr_reviewer/` as a subdirectory), not a
     `tf_pr_reviewer`-only repo - that's what scopes the IAM role so only
     Actions runs from that repo can assume it.
   - `create_oidc_provider` - leave `true` unless your AWS account already
     has a `token.actions.githubusercontent.com` OIDC provider registered
     (check IAM > Identity providers in the console first - AWS only allows
     one per URL per account).

2. Make sure you have local AWS credentials with enough privilege to create
   S3 buckets, a DynamoDB table, an IAM OIDC provider, and an IAM role
   (e.g. `aws configure` with an admin-ish profile, just for this one-time
   run).

## Run it

```bash
cd bootstrap
terraform init
terraform apply
```

This state file stays local (or wherever you choose to keep it) - it is
*not* moved into the bucket it creates. That's intentional: it avoids a
circular dependency, and this module changes rarely enough that local state
is fine. Keep `bootstrap/terraform.tfstate` somewhere safe (e.g. commit it
to a private state-only location, or just keep the local file and note down
the outputs below).

## After it applies

Take the three outputs and wire them in:

- `state_bucket_name` → `../backend.tf`, the `bucket` field.
- `lock_table_name` → `../backend.tf`, the `dynamodb_table` field.
- `github_actions_role_arn` → a GitHub Actions repo variable named
  `TF_PR_REVIEWER_AWS_ROLE_ARN`, set at the **monorepo root repo**
  (Settings → Secrets and variables → Actions → Variables). Namespaced by
  project name since other projects in the monorepo will get their own
  roles/variables later. It doesn't need to be a secret since a role ARN
  isn't sensitive on its own, but a secret works too if you'd rather keep
  it out of logs.

Then run `terraform init` again in `tf_pr_reviewer/` (not the monorepo
root - Terraform only operates on the directory you run it from) to
migrate to the S3 backend, commit `backend.tf`, and the
`tf_pr_reviewer-terraform.yml` workflow at the repo root will be able to
plan/apply against real remote state.
