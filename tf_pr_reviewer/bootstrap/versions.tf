terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Intentionally local state for the bootstrap module itself - this is the
  # one piece of infra that has to exist before remote state can be used.
  # Run it once by hand, keep the resulting terraform.tfstate somewhere safe
  # (or migrate it into the bucket it creates), and don't run it from CI.
}

provider "aws" {
  region = var.aws_region
}
