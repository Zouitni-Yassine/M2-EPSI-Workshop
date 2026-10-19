# Template de base Debian 13 (image cloud officielle, non modifiée).
# Il sert uniquement de point de départ au build Packer "debian13-docker" (VMID 9100).

resource "proxmox_download_file" "debian13_cloud" {
  node_name          = "ceph01"
  datastore_id       = "local"
  content_type       = "import"
  url                = "https://cloud.debian.org/images/cloud/trixie/20261017-2634/debian-13-genericcloud-amd64-20261017-2634.qcow2"
  file_name          = "debian-13-genericcloud-amd64-20261017-2634.qcow2"
  checksum           = "ec584ccabfef7120b4c4f7482adf0e615894d9292cedec446b64194b951ebe5dd97c336b5dcbae458333764b0edd516334506017f33c4f2020ef8d38b569ffe3"
  checksum_algorithm = "sha512"
}

resource "proxmox_virtual_environment_vm" "debian13_cloud" {
  name        = "debian13-cloud"
  description = "Image cloud Debian 13 brute - base du build Packer debian13-docker"
  tags        = ["debian13", "template"]
  node_name   = "ceph01"
  vm_id       = 9000
  template    = true
  started     = false

  machine       = "q35"
  scsi_hardware = "virtio-scsi-single"

  operating_system {
    type = "l26"
  }

  cpu {
    cores = 2
    type  = "x86-64-v2-AES"
  }

  memory {
    dedicated = 2048
  }

  # L'agent est installé par Packer, pas présent dans l'image cloud
  agent {
    enabled = true
  }

  disk {
    datastore_id = "vm-fastec"
    import_from  = proxmox_download_file.debian13_cloud.id
    interface    = "scsi0"
    size         = 20
    discard      = "on"
    iothread     = true
    ssd          = true
  }

  network_device {
    bridge = "vmbr0"
    model  = "virtio"
  }

  serial_device {}

  vga {
    type = "serial0"
  }

  initialization {
    datastore_id = "vm-fastec"

    user_account {
      username = "debian"
      keys     = [trimspace(file("/root/.ssh/id_ed25519_infra.pub"))]
    }

    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }
  }
}
