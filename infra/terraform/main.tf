# Capital Cortex — infrastructure as code (HLD: Compose-first; managed services when volume justifies it, G4).
#
# Phase 0 fixes the interface, not the cloud: the target provider is an open decision (DECISIONS D-011).
# When it is chosen, add a `compose_host` module (one VM running infra/docker-compose.yml behind TLS),
# managed Postgres with AGE and pgvector (or the custom image on a disk-backed VM), object storage, KMS, and
# DNS. CI's deploy job runs only when the repository variable TF_DEPLOY_ENABLED is "true".

terraform {
  required_version = ">= 1.6"
}

locals {
  name = "capital-cortex-${var.environment}"
  tags = {
    product     = "capital-cortex"
    environment = var.environment
    owner       = var.owner
  }
}

output "stack_name" {
  value       = local.name
  description = "Resource name prefix for the environment."
}

output "tags" {
  value = local.tags
}
