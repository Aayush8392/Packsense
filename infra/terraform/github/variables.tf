variable "github_owner" {
  description = "GitHub account that owns the repository."
  type        = string
  default     = "Aayush8392"
}

variable "github_repository" {
  description = "Repository the rulesets and the deploy key belong to."
  type        = string
  default     = "Packsense"
}

variable "keepalive_deploy_key_id" {
  description = "Numeric id of the existing 'keepalive' deploy key, used only by its import block. The workflow reads it from the API (TF_VAR_keepalive_deploy_key_id)."
  type        = string
}
