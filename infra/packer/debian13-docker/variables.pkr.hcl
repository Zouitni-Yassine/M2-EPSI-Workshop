# Secrets : fournis par l'environnement (source /root/.proxmox-env)
#   PKR_VAR_proxmox_token_id / PKR_VAR_proxmox_token_secret

variable "proxmox_token_id" {
  type = string
}

variable "proxmox_token_secret" {
  type      = string
  sensitive = true
}

variable "proxmox_url" {
  type    = string
  default = "https://10.0.1.100:8006/api2/json"
}

variable "node" {
  type    = string
  default = "ceph01"
}

variable "base_vm_id" {
  type        = number
  default     = 9000
  description = "Template debian13-cloud créé par Terraform"
}

variable "vm_id" {
  type    = number
  default = 9100
}

variable "template_name" {
  type    = string
  default = "debian13-docker"
}

variable "bridge" {
  type    = string
  default = "vmbr0"
}

# IP temporaire de la VM pendant le build
variable "build_ip" {
  type    = string
  default = "10.0.1.200"
}

variable "gateway" {
  type    = string
  default = "10.0.1.254"
}

variable "nameserver" {
  type    = string
  default = "10.0.1.254"
}

variable "searchdomain" {
  type    = string
  default = "epsi.lsn"
}

variable "ssh_private_key_file" {
  type    = string
  default = "/root/.ssh/id_ed25519_infra"
}
