# State distant : bucket S3 (DataCore Swarm). Bucket et endpoint dans backend.hcl (non versionné) :
#   terraform init -backend-config=backend.hcl
# Identifiants : AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (source /root/.proxmox-env)
#
# Pas de use_lockfile : ce stockage ne gère pas les écritures conditionnelles
# (If-None-Match -> 501, testé). Le verrou est pris localement par le wrapper /usr/local/bin/tf.
terraform {
  backend "s3" {
    key            = "infra/terraform.tfstate"
    region         = "us-east-1" # ignoré par le stockage, requis par le provider S3
    use_path_style = true

    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
  }
}
