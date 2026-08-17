variable "aws_region" {
  description = "AWS region to deploy resources into"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name prefix used for tagging and naming resources"
  type        = string
  default     = "tf-pr-reviewer-test"
}

variable "bucket_name" {
  description = "Name of the S3 bucket (must be globally unique)"
  type        = string
  default     = "tf-pr-reviewer-test-bucket-change-me"
}

variable "vpc_id" {
  description = "VPC ID to launch the security group into"
  type        = string
  default     = "vpc-07a8ae898e0badacd"
}

variable "tags" {
  description = "Common tags applied to all resources"
  type        = map(string)
  default = {
    Project     = "tf-pr-reviewer-test"
    Environment = "test"
    ManagedBy   = "terraform"
  }
}
