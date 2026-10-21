# Branch protection for main: no deletion, no force-push, linear history. Created by hand on
# 2026-10-13, brought under Terraform in the old single root and moved to this root on the split
# (state key packsense/github.tfstate). The import blocks adopt the live objects; an import block for
# a resource already in state does nothing.
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

# The deploy key's id is not shown anywhere in the GitHub web interface; the workflow reads it from the API and passes it in.
import {
  to = github_repository_deploy_key.keepalive
  id = "${var.github_repository}:${var.keepalive_deploy_key_id}"
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
      required_check {
        context        = "engines" # the gold models give the same rows on DuckDB as on Databricks (golden file); required since 2026-10-21, after 30 of 30 pushes to main passed
        integration_id = 15368
      }
    }
  }
}

import {
  to = github_repository_ruleset.require_ci
  id = "${var.github_repository}:25239089"
}
