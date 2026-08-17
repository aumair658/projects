# Reuses the same state bucket + lock table tf_pr_reviewer/bootstrap created
# (see ../tf_pr_reviewer/bootstrap/README.md) - just a different state key,
# so this project doesn't need its own bootstrap stack.

terraform {
  backend "s3" {
    bucket         = "tf-pr-reviewer-test-tfstate-369634474910"
    key            = "tf-pr-bot/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "tf-pr-reviewer-test-tfstate-lock"
    encrypt        = true
  }
}
