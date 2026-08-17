# Remote state backend.
#
# Fill these in with the outputs from `bootstrap/` after you run it once
# (see bootstrap/README.md). Terraform CANNOT interpolate variables into a
# backend block, so these values must be hardcoded here.

terraform {
  backend "s3" {
    bucket         = "tf-pr-reviewer-test-tfstate-369634474910"
    key            = "tf-pr-reviewer-test/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "tf-pr-reviewer-test-tfstate-lock"
    encrypt        = true
  }
}
