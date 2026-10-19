# Template Debian 13 + Docker CE, commun aux managers (DOCKERMGR) et workers (DOCKERWRK).
# Le rôle Swarm est attribué après clonage (swarm init / join via Ansible).
#
# Usage :
#   source /root/.proxmox-env
#   cd /srv/M2-EPSI-Workshop/infra/packer/debian13-docker
#   packer init . && packer build .

packer {
  required_plugins {
    proxmox = {
      source  = "github.com/hashicorp/proxmox"
      version = "~> 1.2"
    }
  }
}

source "proxmox-clone" "debian13_docker" {
  proxmox_url              = var.proxmox_url
  username                 = var.proxmox_token_id
  token                    = var.proxmox_token_secret
  insecure_skip_tls_verify = true # certificat auto-signé

  node        = var.node
  clone_vm_id = var.base_vm_id
  full_clone  = true

  vm_id                = var.vm_id
  vm_name              = var.template_name
  template_name        = var.template_name
  template_description = "Debian 13 + Docker CE - build Packer du ${formatdate("YYYY-MM-DD hh:mm", timestamp())} UTC"
  tags                 = "debian13;docker;template"

  os              = "l26"
  cores           = 2
  memory          = 2048
  cpu_type        = "x86-64-v2-AES"
  scsi_controller = "virtio-scsi-single"
  qemu_agent      = true

  network_adapters {
    bridge = var.bridge
    model  = "virtio"
  }

  # Lecteur cloud-init ajouté au template final (IP, user, clés fixées par Terraform au clonage)
  cloud_init              = true
  cloud_init_storage_pool = "vm-fastec"

  ipconfig {
    ip      = "${var.build_ip}/24"
    gateway = var.gateway
  }
  nameserver   = var.nameserver
  searchdomain = var.searchdomain

  communicator         = "ssh"
  ssh_host             = var.build_ip
  ssh_username         = "debian"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "10m"
}

build {
  sources = ["source.proxmox-clone.debian13_docker"]

  provisioner "shell" {
    execute_command = "chmod +x {{ .Path }}; sudo -E bash -euxo pipefail {{ .Path }}"
    scripts = [
      "scripts/00-wait-cloud-init.sh",
      "scripts/10-base.sh",
      "scripts/20-docker.sh",
      "scripts/30-hardening.sh",
      "scripts/90-cleanup.sh",
    ]
  }
}
