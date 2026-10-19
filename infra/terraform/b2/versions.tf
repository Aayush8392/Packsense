terraform {
  required_version = ">= 1.13"

  required_providers {
    b2 = {
      source  = "Backblaze/b2"
      version = "~> 0.14"
    }
    github = {
      source  = "integrations/github"
      version = "~> 6.13"
    }
  }

  # State lives in a private, versioned Backblaze B2 bucket through its S3-compatible API.
  # The bucket name and the keys are supplied at init time (never committed).
  backend "s3" {
    key                         = "packsense/terraform.tfstate"
    region                      = "eu-central-003"
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
  }
}

# Credentials come from the environment: B2_APPLICATION_KEY_ID / B2_APPLICATION_KEY for b2,
# GITHUB_TOKEN for github.
provider "b2" {}

provider "github" {
  owner = var.github_owner
}
