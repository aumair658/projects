output "bucket_name" {
  description = "Name of the S3 bucket"
  value       = aws_s3_bucket.app_data.bucket
}

output "bucket_arn" {
  description = "ARN of the S3 bucket"
  value       = aws_s3_bucket.app_data.arn
}

output "security_group_id" {
  description = "ID of the security group"
  value       = aws_security_group.app_sg.id
}
