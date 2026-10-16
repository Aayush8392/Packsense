# Raw capture bucket: private, versioned (B2 keeps file versions), with lifecycle rules.
resource "b2_bucket" "raw" {
  bucket_name = var.bucket_name
  bucket_type = "allPrivate"

  # raw/ : delta files and taxonomy snapshots, hot for about nine months, then hidden.
  lifecycle_rules {
    file_name_prefix              = "raw/"
    days_from_uploading_to_hiding = 270
    days_from_hiding_to_deleting  = var.hidden_file_retention_days
  }

  # tmp/ : scratch objects.
  lifecycle_rules {
    file_name_prefix              = "tmp/"
    days_from_uploading_to_hiding = 7
    days_from_hiding_to_deleting  = var.hidden_file_retention_days
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Upload-only key for the capture job, scoped to this one bucket.
# Verified in test B1: it can put objects, cannot list or read them, but CAN hide objects
# (delete markers), which is why hidden files are kept for 30 days.
resource "b2_application_key" "capture_upload" {
  key_name     = "packsense-capture-upload"
  capabilities = ["writeFiles"]
  bucket_ids   = [b2_bucket.raw.bucket_id]
}

# Read-only key for the tripwires and B2 reconciliation, scoped to this one bucket.
# listFiles also covers listing object versions, which is how delete markers are seen.
# It cannot write, hide or delete anything.
resource "b2_application_key" "tripwire_read" {
  key_name     = "packsense-tripwire-read"
  capabilities = ["listFiles", "readFiles"]
  bucket_ids   = [b2_bucket.raw.bucket_id]
}

# The key is written straight into the repository's Actions secrets: nobody copies it by hand.
resource "github_actions_secret" "b2_upload_key_id" {
  repository      = var.github_repository
  secret_name     = "B2_UPLOAD_KEY_ID"
  plaintext_value = b2_application_key.capture_upload.application_key_id
}

resource "github_actions_secret" "b2_upload_application_key" {
  repository      = var.github_repository
  secret_name     = "B2_UPLOAD_APPLICATION_KEY"
  plaintext_value = b2_application_key.capture_upload.application_key
}

resource "github_actions_secret" "b2_read_key_id" {
  repository      = var.github_repository
  secret_name     = "B2_READ_KEY_ID"
  plaintext_value = b2_application_key.tripwire_read.application_key_id
}

resource "github_actions_secret" "b2_read_application_key" {
  repository      = var.github_repository
  secret_name     = "B2_READ_APPLICATION_KEY"
  plaintext_value = b2_application_key.tripwire_read.application_key
}

# Not secrets: the bucket name and endpoint are plain Actions variables.
resource "github_actions_variable" "b2_bucket" {
  repository    = var.github_repository
  variable_name = "B2_BUCKET"
  value         = b2_bucket.raw.bucket_name
}

resource "github_actions_variable" "b2_s3_endpoint" {
  repository    = var.github_repository
  variable_name = "B2_S3_ENDPOINT"
  value         = var.b2_s3_endpoint
}

# Branch protection for main: no deletion, no force-push, linear history. Created by hand on
# 2026-10-13 and brought under Terraform by the import block below.
resource "github_repository_ruleset" "protect_main" {
  name        = "protect-main"
  repository  = var.github_repository
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  rules {
    deletion                = true
    non_fast_forward        = true
    required_linear_history = true
  }
}

import {
  to = github_repository_ruleset.protect_main
  id = "${var.github_repository}:25028655"
}

# Required CI on main, with a bypass for ONE deploy key only. A required status check refuses any commit that has no passing result
# on its own SHA, and the keep-alive workflow's empty commit never has one (a push with the workflow's built-in token starts no other
# workflow, and GitHub Actions cannot be added to a ruleset's bypass list). So the keep-alive pushes over SSH with this deploy key and
# the key is the only bypass. It lives in its own ruleset, apart from protect-main, because a bypass skips the WHOLE ruleset it is
# attached to: the key must not be able to delete main or force-push it. Proven first in a throwaway repo (2026-10-16): the key pushed
# an empty commit, and the same key's force-push was refused by the ruleset that had no bypass.
# The private half is a repository secret (KEEPALIVE_DEPLOY_KEY) set by hand: it never goes through Terraform or its state.
resource "github_repository_deploy_key" "keepalive" {
  title      = "keepalive"
  repository = var.github_repository
  key        = trimspace(file("${path.module}/keepalive_deploy_key.pub"))
  read_only  = false
}

resource "github_repository_ruleset" "require_ci" {
  name        = "require-ci"
  repository  = var.github_repository
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  bypass_actors {
    actor_type  = "DeployKey"
    bypass_mode = "always"
  }

  rules {
    required_status_checks {
      required_check {
        context        = "tests"
        integration_id = 15368 # the GitHub Actions app
      }
      required_check {
        context        = "lint"
        integration_id = 15368
      }
    }
  }
}
