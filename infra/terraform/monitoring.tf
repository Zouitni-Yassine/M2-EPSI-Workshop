# Stack d'observabilité en LXC non privilégiés :
#   vmagent01/02 : collecte (scrape) avec buffer disque, sur 2 hyperviseurs différents
#   monitoring01 : VictoriaMetrics single-node, vmalert, Alertmanager, Loki, Grafana
# Les services sont installés et configurés par Ansible (infra/ansible/monitoring.yml).
# VMID = dernier octet de l'IP.

locals {
  pve_nodes = ["ceph01", "ceph02", "ceph03"]

  monitoring_nodes = {
    vmagent01    = { vm_id = 231, ip = "10.0.1.231", node = "ceph02", cores = 1, memory = 1024, disk = 20, role = "vmagent" }
    vmagent02    = { vm_id = 232, ip = "10.0.1.232", node = "ceph03", cores = 1, memory = 1024, disk = 20, role = "vmagent" }
    monitoring01 = { vm_id = 233, ip = "10.0.1.233", node = "ceph01", cores = 4, memory = 8192, disk = 100, role = "core" }
  }
}

# Template LXC officiel Proxmox, présent sur chaque nœud (stockage "local" non partagé)
resource "proxmox_download_file" "debian13_lxc" {
  for_each = toset(local.pve_nodes)

  node_name           = each.key
  datastore_id        = "local"
  content_type        = "vztmpl"
  url                 = "http://download.proxmox.com/images/system/debian-13-standard_13.6-1_amd64.tar.zst"
  checksum            = "4c0c27ca6ceab5ef0b84db57825a00f26157ef1854bafe97297813e1cbe8ecb8cc9c453cab6b3b0efe1ba193a50c47ece1e41d950e411b8730b835b71e9e754b"
  checksum_algorithm  = "sha512"
  overwrite_unmanaged = true
}

resource "proxmox_virtual_environment_container" "monitoring" {
  for_each = local.monitoring_nodes

  description = "Observabilité - ${each.value.role} - géré par Terraform"
  tags        = ["monitoring", each.value.role]
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
    # Une mise à jour du template LXC ne doit pas recréer les conteneurs
    # node_name : la HA Proxmox peut déplacer le conteneur (placement porté par ha.tf)
    ignore_changes = [operating_system[0].template_file_id, node_name]
  }
}

output "monitoring_nodes" {
  value = {
    for name, n in local.monitoring_nodes : name => {
      role = n.role
      ip   = n.ip
      node = n.node
    }
  }
}
