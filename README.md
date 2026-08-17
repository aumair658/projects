# projects

Monorepo root. Each subdirectory is an independent project with its own
README, dependencies, and (where relevant) its own GitHub Actions workflow
in `.github/workflows/`.

## Projects

- [`tf_pr_reviewer/`](tf_pr_reviewer/README.md) — Terraform test fixture
  (S3 bucket, security group, IAM role, EC2 instance) used to exercise a
  Terraform PR-review bot. Deploys via
  `.github/workflows/tf_pr_reviewer-terraform.yml`: PRs plan, merges to
  `main` apply.

## Conventions for adding a new project

1. Create `projects/<name>/` with the project's own code and README.
2. If it needs CI/CD, add `.github/workflows/<name>-terraform.yml` (or
   `<name>-<tool>.yml`) here at the repo root — GitHub only reads workflows
   from the root `.github/workflows/`, not per-subdirectory. Scope it with
   a `paths: ["<name>/**"]` filter and `working-directory: <name>` so it
   only runs on changes to that project and only touches that directory.
2b. Namespace any GitHub Actions repo variables/secrets the workflow needs
   (e.g. `<NAME>_AWS_ROLE_ARN`) so multiple projects' pipelines don't
   collide.
3. Update this file's project list.
