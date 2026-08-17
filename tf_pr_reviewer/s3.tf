# -----------------------------------------------------------------------------
# S3 bucket
#
# INTENTIONAL FINDING (for review-bot testing): this bucket has no public
# access block, so a review bot should flag it as "potentially public"
# storage.
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "app_data" {
  bucket = var.bucket_name

  tags = merge(var.tags, {
    Name = "${var.project_name}-bucket"
  })
}

resource "aws_s3_bucket_versioning" "app_data" {
  bucket = aws_s3_bucket.app_data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "app_data" {
  bucket = aws_s3_bucket.app_data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# NOTE: No aws_s3_bucket_public_access_block resource here.
# Left intentionally so tf_pr_bot's full-scan-diff has something to
# report as "still open" alongside the encryption fix above.
