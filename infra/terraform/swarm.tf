# Cluster Docker Swarm : 3 managers (DOCKERMGR) + 3 workers (DOCKERWRK),
# clonés depuis le template Packer debian13-docker (9100).
# Un manager et un worker par nœud Proxmox : la perte d'un hôte ne coûte qu'un de chaque.
# VMID = dernier octet de l'IP.

locals {
  swarm_template_id   = 9100
  swarm_template_node = "ceph01"

  swarm_roles = {
    manager = { cores = 2, memory = 4096, disk = 30 }
    worker  = { cores = 4, memory = 12288, disk = 80 }
  }

  swarm_nodes = {
    dockermgr01 = { role = "manager", vm_id = 211, ip = "10.0.1.211", node = "ceph01" }
    dockermgr02 = { role = "manager", vm_id = 212, ip = "10.0.1.212", node = "ceph02" }
    dockermgr03 = { role = "manager", vm_id = 213, ip = "10.0.1.213", node = "ceph03" }
    dockerwrk01 = { role = "worker", vm_id = 221, ip = "10.0.1.221", node = "ceph01" }
    dockerwrk02 = { role = "worker", vm_id = 222, ip = "10.0.1.222", node = "ceph02" }
    dockerwrk03 = { role = "worker", vm_id = 223, ip = "10.0.1.223", node = "ceph03" }
  }
}

resource "proxmox_virtual_environment_vm" "swarm" {
  for_each = local.swarm_nodes

  name        = each.key
  description = "Docker Swarm ${each.value.role} - géré par Terraform"
  tags        = ["docker", "swarm", each.value.role]
  node_name   = each.value.node
  vm_id       = each.value.vm_id

  on_boot         = true
  started         = true
  stop_on_destroy = true

  clone {
    vm_id     = local.swarm_template_id
    node_name = local.swarm_template_node
    full      = true
  }

  cpu {
    cores = local.swarm_roles[each.value.role].cores
    type  = "x86-64-v2-AES"
  }

  memory {
    dedicated = local.swarm_roles[each.value.role].memory
  }

  agent {
    enabled = true
  }

  disk {
    datastore_id = "vm-fastec"
    interface    = "scsi0"
    size         = local.swarm_roles[each.value.role].disk
    discard      = "on"
    iothread     = true
    ssd          = true
  }

  network_device {
    bridge = "vmbr0"
    model  = "virtio"
  }

  initialization {
    datastore_id = "vm-fastec"
    interface    = "ide0" # lecteur cloud-init du template

    dns {
      domain  = "epsi.lsn"
      servers = ["10.0.1.254"]
    }

    ip_config {
      ipv4 {
        address = "${each.value.ip}/24"
        gateway = "10.0.1.254"
      }
    }

    user_account {
      username = "debian"
      keys     = [trimspace(file("/root/.ssh/id_ed25519_infra.pub"))]
    }
  }

  lifecycle {
    # Un rebuild du template ne doit pas recréer les VM existantes
    # node_name : la HA Proxmox peut déplacer la VM (placement porté par ha.tf)
    ignore_changes = [clone, node_name]
  }
}

output "swarm_nodes" {
  value = {
    for name, n in local.swarm_nodes : name => {
      role = n.role
      ip   = n.ip
      node = n.node
    }
  }
}
