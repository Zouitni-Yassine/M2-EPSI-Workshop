# WAF de l'équipe cyber (ModSecurity + OWASP CRS, conteneur resilience-waf) : VM waf01.
# Créée à la main le 20/10 (clone du template, snapshot waf-validated-20261020), puis intégrée
# à Terraform par import (bloc import ci-dessous) SANS recréation : la configuration du WAF
# (/opt/resilience-waf) reste à l'équipe cyber ; seul le rôle alloy d'Ansible y est appliqué.
#
# Réseau : VLAN 302 RA-DMZ (10.30.2.0/24, network.tf), seule zone joignable depuis NPM
# (172.16.1.10 -> 10.30.2.251:8443) ; le WAF relaie vers l'adresse virtuelle de l'application
# (RA-DMZ -> RA-APP 10.30.1.200:5173). VMID = dernier octet de l'IP, comme les autres VM.
#
# Ce qui ne peut pas être décrit fidèlement est ignoré (lifecycle) : une modification de ces
# attributs forcerait sinon une recréation de la VM, interdite ici (prevent_destroy).

locals {
  waf_node = { name = "waf01", vm_id = 251, ip = "10.30.2.251", node = "ceph01" }
}

import {
  to = proxmox_virtual_environment_vm.waf
  id = "${local.waf_node.node}/${local.waf_node.vm_id}"
}

resource "proxmox_virtual_environment_vm" "waf" {
  depends_on = [proxmox_sdn_applier.ra] # vnet appliqué sur les nœuds

  name        = local.waf_node.name
  description = "WAF ModSecurity + CRS (equipe cyber) - importe dans Terraform"
  tags        = ["cyber", "waf", "workshop-2026"]
  node_name   = local.waf_node.node
  vm_id       = local.waf_node.vm_id

  on_boot         = true
  started         = true
  stop_on_destroy = true

  machine       = "q35"
  bios          = "seabios"
  scsi_hardware = "virtio-scsi-single"

  cpu {
    cores = 2
    type  = "x86-64-v2-AES"
  }

  memory {
    dedicated = 2048
    floating  = 0
  }

  agent {
    enabled = true
  }

  operating_system {
    type = "l26"
  }

  serial_device {}

  vga {
    type   = "serial0"
    memory = 16
  }

  disk {
    datastore_id = "vm-fastec"
    interface    = "scsi0"
    size         = 20
    discard      = "on"
    iothread     = true
    ssd          = true
  }

  network_device {
    bridge      = proxmox_sdn_vnet.ra["radmz"].id
    model       = "virtio"
    mac_address = "BC:24:11:8C:9C:21" # MAC d'origine conservée (netplan : match macaddress)
  }

  initialization {
    datastore_id = "vm-fastec"
    interface    = "ide0"
    # Pas de mise à jour des paquets par cloud-init : changer le réseau change l'instance-id
    # cloud-init (premier démarrage rejoué), qui lancerait sinon un apt upgrade (Docker compris)
    upgrade = false

    dns {
      domain  = "epsi.lsn"
      servers = ["10.30.2.254"]
    }

    ip_config {
      ipv4 {
        address = "${local.waf_node.ip}/24"
        gateway = "10.30.2.254"
      }
    }

    user_account {
      username = "debian"
      keys     = [trimspace(file("/root/.ssh/id_ed25519_infra.pub"))]
    }
  }

  lifecycle {
    prevent_destroy = true
    # VM importée : pas de clone à rejouer ; disque créé hors Terraform ; compte cloud-init
    # (clé SSH) déjà en place ; node_name : la HA Proxmox peut déplacer la VM
    ignore_changes = [clone, disk, node_name, description, initialization[0].user_account]
  }
}

# HA Proxmox : la VM n'en avait pas (créée à la main). Ressource HA propre au WAF, sans règle
# de nœud préféré : l'ajouter aux règles home-* de ha.tf modifierait les règles du socle.
resource "proxmox_haresource" "waf" {
  resource_id  = "vm:${local.waf_node.vm_id}"
  state        = "started"
  max_restart  = 2
  max_relocate = 1
  comment      = "${local.waf_node.name} (WAF equipe cyber) - gere par Terraform"

  depends_on = [proxmox_virtual_environment_vm.waf]
}
