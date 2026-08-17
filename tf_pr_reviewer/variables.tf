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

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.micro"
}

variable "ami_id" {
  description = "AMI ID for the EC2 instance (defaults to a placeholder - override per region)"
  type        = string
  default     = "ami-0c101f26f147fa7fd"
}

variable "vpc_id" {
  description = "VPC ID to launch the security group and instance into"
  type        = string
  default     = "vpc-07a8ae898e0badacd"
}

variable "subnet_id" {
  description = "Subnet ID to launch the EC2 instance into"
  type        = string
  default     = "subnet-0314bcd1a4f9797cf"
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
