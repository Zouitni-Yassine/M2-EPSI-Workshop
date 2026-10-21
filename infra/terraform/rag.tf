# Assistant RAG de l'équipe IA (Ollama + ChromaDB + Streamlit) : VM rag01, en lecture seule
# sur les procédures, sans aucun accès privilégié. Configurée par infra/ansible/rag.yml.
# Réseau : VLAN 301 RA-APP (10.30.1.0/24, network.tf), comme le Swarm. VMID = dernier octet de l'IP.
#
# Clonée depuis le template debian13-docker (9100) : seul template avec l'agent QEMU et le
# durcissement de base. Docker y est désactivé par Ansible (rôle rag).
# CPU x86-64-v3 (AVX2, FMA) : l'inférence d'Ollama sur CPU en dépend ; tous les hyperviseurs
# l'offrent, la VM reste donc migrable par la HA.

locals {
  rag_nodes = {
    rag01 = { vm_id = 230, ip = "10.30.1.230", node = "ceph02", cores = 8, memory = 16384, disk = 60 }
  }
}

resource "proxmox_virtual_environment_vm" "rag" {
  for_each = local.rag_nodes

  depends_on = [proxmox_sdn_applier.ra] # vnet appliqué sur les nœuds

  name        = each.key
  description = "Assistant RAG (IA) - géré par Terraform"
  tags        = ["ia", "rag"]
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
    cores = each.value.cores
    type  = "x86-64-v3"
  }

  memory {
    dedicated = each.value.memory
  }

  agent {
    enabled = true
  }

  disk {
    datastore_id = "vm-fastec"
    interface    = "scsi0"
    size         = each.value.disk
    discard      = "on"
    iothread     = true
    ssd          = true
  }

  network_device {
    bridge = proxmox_sdn_vnet.ra["raapp"].id
    model  = "virtio"
  }

  initialization {
    datastore_id = "vm-fastec"
    interface    = "ide0" # lecteur cloud-init du template

    dns {
      domain  = "epsi.lsn"
      servers = ["10.30.1.254"]
    }

    ip_config {
      ipv4 {
        address = "${each.value.ip}/24"
        gateway = "10.30.1.254"
      }
    }

    user_account {
      username = "debian"
      keys     = [trimspace(file("/root/.ssh/id_ed25519_infra.pub"))]
    }
  }

  lifecycle {
    # Un rebuild du template ne doit pas recréer la VM
    # node_name : la HA Proxmox peut déplacer la VM (placement porté par ha.tf)
    ignore_changes = [clone, node_name]
  }
}

output "rag_nodes" {
  value = { for name, n in local.rag_nodes : name => { ip = n.ip, node = n.node } }
}
