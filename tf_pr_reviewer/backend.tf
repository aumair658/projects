# Remote state backend.
#
# Fill these in with the outputs from `bootstrap/` after you run it once
# (see bootstrap/README.md). Terraform CANNOT interpolate variables into a
# backend block, so these values must be hardcoded here.

terraform {
  backend "s3" {
    bucket         = "REPLACE_WITH_STATE_BUCKET_NAME"
    key            = "tf-pr-reviewer-test/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "REPLACE_WITH_LOCK_TABLE_NAME"
    encrypt        = true
  }
}
