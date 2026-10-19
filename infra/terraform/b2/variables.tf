variable "github_owner" {
  description = "GitHub account that owns the repository."
  type        = string
  default     = "Aayush8392"
}

variable "github_repository" {
  description = "Repository that receives the capture secrets and variables."
  type        = string
  default     = "Packsense"
}

variable "bucket_name" {
  description = "Globally unique name of the raw-capture bucket."
  type        = string
  default     = "packsense-raw-aayush-8392"
}

variable "b2_s3_endpoint" {
  description = "S3-compatible endpoint of the bucket's region."
  type        = string
  default     = "https://s3.eu-central-003.backblazeb2.com"
}

variable "hidden_file_retention_days" {
  description = "Days a hidden (delete-marked) object is kept before B2 removes it. An upload-only key can hide objects, so this is the recovery window."
  type        = number
  default     = 30

  validation {
    condition     = var.hidden_file_retention_days >= 30
    error_message = "Keep hidden files at least 30 days: an upload-only key can hide objects (verified in test B1)."
  }
}
