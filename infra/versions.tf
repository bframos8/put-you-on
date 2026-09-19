# Terraform for the production box (gameplan 6.0). One root module, one environment.
#
# State lives in S3 so both dev machines see the same record of what exists; without it,
# a machine with a stale checkout could happily create a second instance. The bucket was
# created once by hand (Terraform can't keep its state in a bucket it hasn't made yet):
# private, versioned (roll back a bad state), encrypted. Its name has a random suffix
# instead of the account ID because this file is in a public repo.
#
# use_lockfile: S3-native state locking (Terraform >= 1.10), so two applies can't run at
# once. No DynamoDB table needed.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.65"
    }
  }

  backend "s3" {
    bucket       = "putyouon-tfstate-b43f7b3a"
    key          = "prod/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project   = "putyouon"
      ManagedBy = "terraform"
    }
  }
}
