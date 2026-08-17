# tf_pr_reviewer test fixture

This is a small, self-contained Terraform stack used as a test fixture for a
Terraform PR-review bot. It provisions:

- An S3 bucket (`s3.tf`)
- A security group (`security_group.tf`)
- An IAM role + instance profile for EC2 (`iam.tf`)
- An EC2 instance (`ec2.tf`)

## Intentional issues

Two issues are deliberately left in place so a review bot has something
concrete to catch:

1. **Unencrypted S3 bucket** (`s3.tf`) — no
   `aws_s3_bucket_server_side_encryption_configuration` resource and no
   `aws_s3_bucket_public_access_block` resource are attached to
   `aws_s3_bucket.app_data`.
2. **Wide-open security group rule** (`security_group.tf`) — the ingress rule
   on `aws_security_group.app_sg` opens SSH (port 22) to `0.0.0.0/0`.

Both are marked inline with `INTENTIONAL FINDING` comments. Everything else
in the stack (versioning, least-privilege IAM policy scoped to the bucket,
egress rule, instance profile) is written to be reasonably clean so the
review bot's signal isn't drowned out by unrelated noise.

## Repo layout: this project lives inside a monorepo

This directory (`tf_pr_reviewer/`) is one project inside the `projects`
monorepo — see `../README.md` at the repo root for the full layout and
conventions for adding other projects alongside it.

## Deploying: GitHub Actions, not local `terraform apply`

This project deploys through a CI/CD pipeline rather than by running
`terraform apply` from a laptop. The workflow lives at the **monorepo
root** (GitHub only reads `.github/workflows/` from the repo root, not
per-subdirectory): `../.github/workflows/tf_pr_reviewer-terraform.yml`.
It's scoped with a `paths:` filter so it only triggers on changes under
`tf_pr_reviewer/`, and it runs its steps with
`working-directory: tf_pr_reviewer`.

- **Pull requests** (that touch this directory) run `fmt -check`,
  `validate`, and `plan`, and post the plan output as a PR comment.
- **Merges to `main`** (that touch this directory) run `terraform apply`
  automatically.
- AWS auth is via **OIDC role assumption** — no long-lived AWS keys are
  stored in GitHub. The workflow assumes an IAM role using the
  `TF_PR_REVIEWER_AWS_ROLE_ARN` repo variable (namespaced by project name,
  since other projects in the monorepo will get their own roles/variables).

### One-time setup (do this before the pipeline can run)

1. `bootstrap/` is a separate, small Terraform config that creates the
   things the pipeline itself depends on: the S3 state bucket, the
   DynamoDB lock table, the GitHub OIDC provider, and the IAM role GitHub
   Actions assumes. Run it once, locally, by hand — see
   `bootstrap/README.md` for the full steps.
2. Take the `bootstrap` outputs and:
   - Fill `bucket` / `dynamodb_table` into `backend.tf` here.
   - Set the `TF_PR_REVIEWER_AWS_ROLE_ARN` GitHub Actions repo variable at
     the monorepo root (Settings → Secrets and variables → Actions →
     Variables) to the `github_actions_role_arn` output.
3. Run `terraform init` in this directory once to migrate to the S3
   backend, commit `backend.tf`, and push. From then on, PRs plan and
   merges to `main` apply — no one needs to run `terraform apply` locally.

You'll also need to supply `vpc_id` and `subnet_id` (e.g. as GitHub Actions
`vars`/`tfvars`, or hardcode test values) for `plan`/`apply` to succeed
against a real AWS account.

### Local development

For iterating on the Terraform itself without touching the pipeline:

```
terraform init
terraform validate
terraform plan
```

`init`/`validate` work without a configured backend or AWS credentials;
`plan`/`apply` need both.
