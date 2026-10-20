# Identités et secrets, en LXC non privilégiés dédiés (hors du Swarm, cible des attaques) :
#   iam01         : Keycloak (SSO des administrateurs, OIDC), base PostgreSQL locale
#   vault01       : HashiCorp Vault (secrets des services, stockage Raft intégré)
#   vaultwarden01 : Vaultwarden (gestionnaire de mots de passe de l'équipe, comptes de secours)
# Un service par hyperviseur : la perte d'un nœud ne coupe qu'un service, que la HA redémarre.
# Les services sont installés et configurés par Ansible (infra/ansible/identity.yml).
# VMID = dernier octet de l'IP.

locals {
  identity_nodes = {
    iam01         = { vm_id = 241, ip = "10.0.1.241", node = "ceph02", cores = 2, memory = 3072, disk = 20, role = "keycloak" }
    vault01       = { vm_id = 242, ip = "10.0.1.242", node = "ceph03", cores = 1, memory = 1024, disk = 10, role = "vault" }
    vaultwarden01 = { vm_id = 243, ip = "10.0.1.243", node = "ceph01", cores = 1, memory = 1024, disk = 10, role = "vaultwarden" }
  }
}

resource "proxmox_virtual_environment_container" "identity" {
  for_each = local.identity_nodes

  description = "Identités et secrets - ${each.value.role} - géré par Terraform"
  tags        = ["identity", each.value.role]
  node_name   = each.value.node
  vm_id       = each.value.vm_id

  unprivileged  = true
  start_on_boot = true
  started       = true

  features {
    nesting = true # requis par systemd (sandboxing des services) sous Debian 13
  }

  operating_system {
    template_file_id = proxmox_download_file.debian13_lxc[each.value.node].id
    type             = "debian"
  }

  cpu {
    cores = each.value.cores
  }

  memory {
    dedicated = each.value.memory
    swap      = 512
  }

  disk {
    datastore_id = "vm-fastec"
    size         = each.value.disk
  }

  network_interface {
    name   = "eth0"
    bridge = "vmbr0"
  }

  initialization {
    hostname = each.key

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
      keys = [trimspace(file("/root/.ssh/id_ed25519_infra.pub"))]
    }
  }

  lifecycle {
    ignore_changes = [operating_system[0].template_file_id, node_name]
  }
}

output "identity_nodes" {
  value = {
    for name, n in local.identity_nodes : name => {
      ip   = n.ip
      node = n.node
    }
  }
}
