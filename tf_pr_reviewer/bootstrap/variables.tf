variable "aws_region" {
  description = "AWS region for the state bucket / lock table"
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_name" {
  description = "Globally-unique name for the Terraform remote state bucket"
  type        = string
  default     = "tf-pr-reviewer-test-tfstate-369634474910"
}

variable "lock_table_name" {
  description = "Name for the DynamoDB state lock table"
  type        = string
  default     = "tf-pr-reviewer-test-tfstate-lock"
}

variable "github_repo" {
  description = "GitHub repo allowed to assume the deploy role, as \"org/repo\". This is the monorepo root repo (e.g. the \"projects\" repo that contains tf_pr_reviewer/ as a subdirectory), not a per-project repo. REPLACE with your actual repo before applying."
  type        = string
  default     = "aumair658/projects"
}

variable "github_subject_claim_prefix" {
  description = "OIDC subject (sub) claim prefix GitHub sends for this repo, without the trailing \":*\". Repos created/renamed after 2026-07-15 use GitHub's immutable subject claim format (\"repo:ORG@ORG_ID/REPO@REPO_ID\") instead of the classic \"repo:org/repo\" - copy the exact value from Settings > Actions > General > OIDC > \"Default subject claim prefix\" for this repo."
  type        = string
  default     = "repo:aumair658@58346411/projects@1337327941"
}

variable "create_oidc_provider" {
  description = "Whether to create the GitHub Actions OIDC provider. AWS allows only one OIDC provider per URL per account, so set this to false if your account already has token.actions.githubusercontent.com registered (check IAM > Identity providers first)."
  type        = bool
  default     = false
}

variable "role_name" {
  description = "Name of the IAM role GitHub Actions will assume"
  type        = string
  default     = "tf-pr-reviewer-test-github-actions"
}
