output "state_bucket_name" {
  description = "Paste into backend.tf's `bucket`"
  value       = aws_s3_bucket.tf_state.bucket
}

output "lock_table_name" {
  description = "Paste into backend.tf's `dynamodb_table`"
  value       = aws_dynamodb_table.tf_lock.name
}

output "github_actions_role_arn" {
  description = "Paste into the TF_PR_REVIEWER_AWS_ROLE_ARN GitHub Actions repo variable (set at the monorepo root, since that's where the repo/OIDC trust lives)"
  value       = aws_iam_role.github_actions.arn
}
