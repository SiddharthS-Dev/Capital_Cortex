variable "environment" {
  type        = string
  description = "dev | staging | prod"
  default     = "staging"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "owner" {
  type    = string
  default = "inspironics"
}

variable "backup_rpo_minutes" {
  type        = number
  description = "Point-in-time recovery objective (§10: RPO <= 15 min)."
  default     = 15
}

variable "restore_rto_minutes" {
  type        = number
  description = "Recovery time objective (§10: RTO <= 1 h)."
  default     = 60
}
