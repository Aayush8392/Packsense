terraform {
  required_version = ">= 1.13"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.13"
    }
  }

  # State lives in the same private, versioned Backblaze B2 bucket as the b2 root, under its own key.
  # The bucket name and the keys are supplied at init time (never committed).
  backend "s3" {
    key                         = "packsense/github.tfstate"
    region                      = "eu-central-003"
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
  }
}

# The token comes from the environment: GITHUB_TOKEN. This root needs no Backblaze admin key.
provider "github" {
  owner = var.github_owner
}
