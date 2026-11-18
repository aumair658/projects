# -----------------------------------------------------------------------------
# Remote state bucket + lock table
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "tf_state" {
  bucket = var.state_bucket_name

  # Deliberately NOT force_destroy - this bucket holds state, don't let a
  # careless `terraform destroy` wipe it out.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tf_state" {
  bucket                  = aws_s3_bucket.tf_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "tf_lock" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}

# -----------------------------------------------------------------------------
# GitHub Actions OIDC provider + deploy role
# -----------------------------------------------------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

locals {
  app_bucket_arn = "arn:aws:s3:::${var.app_bucket_name}"
}

# Two roles, each trusting exactly one OIDC subject:
#
# - apply: `<prefix>:environment:<apply_environment>`. GitHub only issues that
#   subject to a job that declares the environment, so every apply passes
#   through the environment's required-reviewer gate.
# - plan: `<prefix>:pull_request`, read-only. Any branch can open a PR, so
#   this role must never be able to change anything.
#
# Previously a single role trusted `<prefix>:*` and held iam:PutRolePolicy on
# "*", so a workflow on any branch could grant itself admin (SEC-001 in
# aws_resume/docs/security/design-review-2026-10-28.md). StringEquals, not
# StringLike: no wildcards in either trust policy.
data "aws_iam_policy_document" "apply_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${var.github_subject_claim_prefix}:environment:${var.apply_environment}"]
    }
  }
}

data "aws_iam_policy_document" "plan_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${var.github_subject_claim_prefix}:pull_request"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = var.role_name
  assume_role_policy = data.aws_iam_policy_document.apply_assume_role.json
}

resource "aws_iam_role" "github_actions_plan" {
  name               = var.plan_role_name
  assume_role_policy = data.aws_iam_policy_document.plan_assume_role.json
}

# Apply role: manage the fixture stack (one S3 bucket, one security group)
# and its state. No IAM permissions at all - the stack has no IAM resources.
data "aws_iam_policy_document" "deploy_permissions" {
  statement {
    sid    = "SecurityGroups"
    effect = "Allow"
    actions = [
      "ec2:Describe*",
      "ec2:CreateTags",
      "ec2:CreateSecurityGroup",
      "ec2:DeleteSecurityGroup",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress",
      "ec2:RevokeSecurityGroupEgress",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "S3AppBucket"
    effect = "Allow"
    actions = [
      "s3:CreateBucket",
      "s3:DeleteBucket",
      "s3:PutBucketVersioning",
      "s3:GetBucketVersioning",
      "s3:PutBucketTagging",
      "s3:GetBucketTagging",
      "s3:PutEncryptionConfiguration",
      "s3:GetEncryptionConfiguration",
      "s3:PutBucketPublicAccessBlock",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketPolicy",
      "s3:GetBucketAcl",
      "s3:ListBucket",
      # The AWS provider reads these as part of every aws_s3_bucket
      # refresh (to populate legacy computed attributes), even though
      # this fixture never sets them.
      "s3:GetBucketCORS",
      "s3:GetBucketWebsite",
      "s3:GetBucketLogging",
      "s3:GetLifecycleConfiguration",
      "s3:GetBucketRequestPayment",
      "s3:GetAccelerateConfiguration",
      "s3:GetReplicationConfiguration",
      "s3:GetBucketObjectLockConfiguration",
    ]
    resources = [local.app_bucket_arn]
  }

  statement {
    sid    = "TerraformStateAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.tf_state.arn,
      "${aws_s3_bucket.tf_state.arn}/*",
    ]
  }

  statement {
    sid    = "TerraformLockAccess"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
    ]
    resources = [aws_dynamodb_table.tf_lock.arn]
  }
}

resource "aws_iam_role_policy" "deploy_permissions" {
  name   = "${var.role_name}-permissions"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.deploy_permissions.json
}

# Plan role: only what `terraform plan` needs to refresh the fixture and read
# its state. The lock table is the one write: plan takes and releases the
# state lock.
data "aws_iam_policy_document" "plan_permissions" {
  statement {
    sid       = "DescribeSecurityGroups"
    effect    = "Allow"
    actions   = ["ec2:DescribeSecurityGroups", "ec2:DescribeSecurityGroupRules"]
    resources = ["*"]
  }

  statement {
    sid    = "ReadAppBucket"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketVersioning",
      "s3:GetBucketTagging",
      "s3:GetEncryptionConfiguration",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketPolicy",
      "s3:GetBucketAcl",
      "s3:GetBucketCORS",
      "s3:GetBucketWebsite",
      "s3:GetBucketLogging",
      "s3:GetLifecycleConfiguration",
      "s3:GetBucketRequestPayment",
      "s3:GetAccelerateConfiguration",
      "s3:GetReplicationConfiguration",
      "s3:GetBucketObjectLockConfiguration",
    ]
    resources = [local.app_bucket_arn]
  }

  statement {
    sid       = "ReadState"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.tf_state.arn, "${aws_s3_bucket.tf_state.arn}/*"]
  }

  statement {
    sid    = "TerraformLockAccess"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
    ]
    resources = [aws_dynamodb_table.tf_lock.arn]
  }
}

resource "aws_iam_role_policy" "plan_permissions" {
  name   = "${var.plan_role_name}-permissions"
  role   = aws_iam_role.github_actions_plan.id
  policy = data.aws_iam_policy_document.plan_permissions.json
}
