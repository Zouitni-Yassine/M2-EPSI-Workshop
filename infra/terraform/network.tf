# VLAN RESILIENCE-ALPHA : vnets de la zone SDN "EPSI" (zone VLAN existante sur vmbr0, non gérée
# ici). Côté passerelle UniFi (réseaux, zones, règles) : infra/unifi/ra-network.yml, mêmes VLAN.
# Les nœuds Proxmox sont eux-mêmes des VM : le trunk de l'hôte parent laisse passer tous les VLAN.

locals {
  ra_vnets = {
    raapp = { tag = 301, alias = "RA-APP Swarm" }           # 10.30.1.0/24
    radmz = { tag = 302, alias = "RA-DMZ expose" }          # 10.30.2.0/24
    ravpn = { tag = 303, alias = "RA-VPN passerelle VPN" }  # 10.30.3.0/24
  }
}

resource "proxmox_sdn_vnet" "ra" {
  for_each = local.ra_vnets

  id    = each.key
  zone  = "EPSI"
  tag   = each.value.tag
  alias = each.value.alias
}

# Applique la configuration SDN en attente sur tous les nœuds (bouton "Apply" de l'interface)
resource "proxmox_sdn_applier" "ra" {
  depends_on = [proxmox_sdn_vnet.ra]

  lifecycle {
    replace_triggered_by = [proxmox_sdn_vnet.ra]
  }
}
