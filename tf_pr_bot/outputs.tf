output "webhook_url" {
  description = "Set this as the GitHub App's Webhook URL"
  value       = aws_lambda_function_url.bot.function_url
}

output "lambda_function_name" {
  value = aws_lambda_function.bot.function_name
}

output "private_key_parameter_name" {
  description = "SSM parameter to populate with the GitHub App's private key PEM"
  value       = aws_ssm_parameter.github_app_private_key.name
}

output "webhook_secret_parameter_name" {
  description = "SSM parameter to populate with the webhook secret you choose when creating the app"
  value       = aws_ssm_parameter.github_webhook_secret.name
}
