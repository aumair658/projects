# projects

Monorepo root. Each subdirectory is an independent project with its own
README, dependencies, and (where relevant) its own GitHub Actions workflow
in `.github/workflows/`.

## Projects

- [`tf_pr_reviewer/`](tf_pr_reviewer/README.md) — Terraform test fixture
  (S3 bucket, security group) used to exercise a Terraform PR-review bot.
  Deploys via `.github/workflows/tf_pr_reviewer-terraform.yml`: PRs plan,
  merges to `main` apply.
- [`tf_pr_bot/`](tf_pr_bot/README.md) — the PR-review bot itself: a
  GitHub App + AWS Lambda (Function URL) that runs tfsec against the
  changed `.tf` files on a PR and comments the findings. Deployed by hand
  (see its README), not via a repo-root CI workflow.
- [`aws-tf-mcp/`](aws-tf-mcp/README.md) — a learning project building an
  MCP server in the AWS/Terraform space, staged from a simple local
  file-parsing tool up to live AWS calls and Terraform CLI integration.
  No CI/CD; run locally with the MCP Inspector.

## Security

Every PR into `main` (and every push to `main`) runs
[`.github/workflows/security-scan.yml`](.github/workflows/security-scan.yml),
which is repo-wide by design — it covers every project here automatically,
not just the one being changed:

- **Trivy** scans for known-CVE dependencies, Terraform misconfigurations,
  and committed secrets (`tf_pr_reviewer/` is excluded from this scan — it
  intentionally contains two vulnerable resources as a fixture for
  `tf_pr_bot`, not real infrastructure).
- **Bandit** statically checks Python code for common security issues.

GitHub's native secret scanning, push protection, and Dependabot security
updates are also enabled on the repo itself (Settings → Code security).

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
