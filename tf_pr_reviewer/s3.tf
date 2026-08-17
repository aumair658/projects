# -----------------------------------------------------------------------------
# S3 bucket
#
# INTENTIONAL FINDING (for review-bot testing): this bucket has no server-side
# encryption configuration and no public access block, so a review bot should
# flag it as "unencrypted" / "potentially public" storage.
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

# NOTE: No aws_s3_bucket_server_side_encryption_configuration resource here.
# NOTE: No aws_s3_bucket_public_access_block resource here either.
# Both omissions are intentional so a review bot has something to catch.
# (touched to trigger tf_pr_bot for a live test)
