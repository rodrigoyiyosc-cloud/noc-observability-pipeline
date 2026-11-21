terraform {
  required_version = "~> 1.17"

  # Estado remoto en MinIO (ADR-008; runbook-minio-estado-terraform.md).
  # Las credenciales NO van aquí: se leen de AWS_ACCESS_KEY_ID y AWS_SECRET_ACCESS_KEY.
  backend "s3" {
    bucket = "tfstate"
    key    = "envs/local/terraform.tfstate"
    region = "us-east-1" # arbitrario; el SDK lo exige

    endpoints = {
      s3 = "http://127.0.0.1:9000"
    }

    use_path_style = true
    use_lockfile   = true

    # MinIO no tiene STS, IAM ni metadata de EC2.
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_s3_checksum            = true
  }

  required_providers {
    kind = {
      source  = "tehcyx/kind"
      version = "~> 0.13.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.3.0"
    }
  }
}