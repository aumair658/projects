variable "aws_region" {
  description = "AWS region for the state bucket / lock table"
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_name" {
  description = "Globally-unique name for the Terraform remote state bucket"
  type        = string
  default     = "tf-pr-reviewer-test-tfstate-change-me"
}

variable "lock_table_name" {
  description = "Name for the DynamoDB state lock table"
  type        = string
  default     = "tf-pr-reviewer-test-tfstate-lock"
}

variable "github_repo" {
  description = "GitHub repo allowed to assume the deploy role, as \"org/repo\". This is the monorepo root repo (e.g. the \"projects\" repo that contains tf_pr_reviewer/ as a subdirectory), not a per-project repo. REPLACE with your actual repo before applying."
  type        = string
  default     = "YOUR_GH_ORG/YOUR_REPO"
}

variable "create_oidc_provider" {
  description = "Whether to create the GitHub Actions OIDC provider. AWS allows only one OIDC provider per URL per account, so set this to false if your account already has token.actions.githubusercontent.com registered (check IAM > Identity providers first)."
  type        = bool
  default     = true
}

variable "role_name" {
  description = "Name of the IAM role GitHub Actions will assume"
  type        = string
  default     = "tf-pr-reviewer-test-github-actions"
}
