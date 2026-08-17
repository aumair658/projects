# -----------------------------------------------------------------------------
# Secrets - created as placeholders. Terraform should not own the real
# values (they'd land in state); populate them for real after apply with:
#   aws ssm put-parameter --name <name> --type SecureString --overwrite --value <value>
# lifecycle.ignore_changes keeps subsequent applies from stomping on that.
# -----------------------------------------------------------------------------

resource "aws_ssm_parameter" "github_app_private_key" {
  name  = "/${var.function_name}/github-app-private-key"
  type  = "SecureString"
  value = "REPLACE_ME_AFTER_APPLY"
  tags  = var.tags

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "github_webhook_secret" {
  name  = "/${var.function_name}/github-webhook-secret"
  type  = "SecureString"
  value = "REPLACE_ME_AFTER_APPLY"
  tags  = var.tags

  lifecycle {
    ignore_changes = [value]
  }
}

# -----------------------------------------------------------------------------
# Lambda execution role
# -----------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "${var.function_name}-exec"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = var.tags
}

data "aws_iam_policy_document" "lambda_permissions" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.function_name}*"]
  }

  statement {
    sid    = "ReadSecrets"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
    ]
    resources = [
      aws_ssm_parameter.github_app_private_key.arn,
      aws_ssm_parameter.github_webhook_secret.arn,
    ]
  }
}

resource "aws_iam_role_policy" "lambda_permissions" {
  name   = "${var.function_name}-permissions"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_permissions.json
}

# -----------------------------------------------------------------------------
# tfsec binary, packaged as a Lambda layer (see scripts/build_layer.sh)
# -----------------------------------------------------------------------------

resource "aws_lambda_layer_version" "tfsec" {
  layer_name          = "${var.function_name}-tfsec"
  filename            = "${path.module}/build/layer/tfsec-layer.zip"
  source_code_hash    = filebase64sha256("${path.module}/build/layer/tfsec-layer.zip")
  compatible_runtimes = ["python3.12"]
  compatible_architectures = ["x86_64"]
}

# -----------------------------------------------------------------------------
# Lambda function + public Function URL (webhook endpoint)
#
# authorization_type = NONE because GitHub can't sign requests with AWS
# SigV4 - the handler verifies the X-Hub-Signature-256 HMAC instead, using
# the webhook secret above. This is the standard pattern for GitHub App
# webhooks on Lambda.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_function" "bot" {
  function_name = var.function_name
  role          = aws_iam_role.lambda_exec.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]
  timeout       = 30
  memory_size   = 512

  filename         = "${path.module}/build/lambda.zip"
  source_code_hash = filebase64sha256("${path.module}/build/lambda.zip")

  layers = [aws_lambda_layer_version.tfsec.arn]

  environment {
    variables = {
      GITHUB_APP_ID              = var.github_app_id
      GITHUB_APP_PRIVATE_KEY_SSM = aws_ssm_parameter.github_app_private_key.name
      GITHUB_WEBHOOK_SECRET_SSM  = aws_ssm_parameter.github_webhook_secret.name
      TFSEC_PATH                 = "/opt/bin/tfsec"
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
  tags       = var.tags
}

resource "aws_lambda_function_url" "bot" {
  function_name      = aws_lambda_function.bot.function_name
  authorization_type = "NONE"
}
