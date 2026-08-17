variable "aws_region" {
  description = "AWS region for the Lambda + supporting resources"
  type        = string
  default     = "us-east-1"
}

variable "function_name" {
  description = "Name for the Lambda function"
  type        = string
  default     = "tf-pr-bot"
}

variable "github_app_id" {
  description = "GitHub App ID (not sensitive - shown on the app's settings page). Set after registering the app."
  type        = string
  default     = "4626886"
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the Lambda's log group"
  type        = number
  default     = 14
}

variable "tags" {
  description = "Common tags applied to all resources"
  type        = map(string)
  default = {
    Project   = "tf-pr-bot"
    ManagedBy = "terraform"
  }
}
