# Commentaires HA en ASCII uniquement : Proxmox rejette les accents (Wide character).
#
# Haute disponibilité Proxmox pour toutes les VM et tous les LXC gérés par Terraform.
# Si un hyperviseur tombe, ses invités redémarrent sur un autre nœud (stockage Ceph partagé).
#
# Placement :
#   - chaque invité préfère son nœud d'origine (règle node-affinity non stricte) et y revient
#     automatiquement au retour du nœud (failback) : la répartition 1 manager + 1 worker par
#     hyperviseur se rétablit seule ;
#   - les 2 vmagents ne sont jamais sur le même hyperviseur (anti-affinité stricte : toujours
#     satisfiable avec 3 nœuds, même après la perte d'un nœud). Proxmox interdit de combiner
#     anti-affinité et nœud préféré à priorités : les vmagents n'ont donc pas de failback.
#   - rag01 (assistant IA, hors chemin critique du paiement) a sa propre règle de nœud préféré,
#     même principe : l'ajouter ou la retirer ne touche pas aux règles du socle.
#   Pas d'anti-affinité stricte sur les managers / workers : avec 3 nœuds, elle empêcherait de
#   redémarrer un invité après la perte d'un nœud. Mieux vaut 2 managers sur un même hôte
#   pendant une panne qu'un manager arrêté.

locals {
  ha_guests = merge(
    { for name, n in local.swarm_nodes : name => { sid = "vm:${n.vm_id}", node = n.node } },
    { for name, n in local.monitoring_nodes : name => { sid = "ct:${n.vm_id}", node = n.node } },
    { for name, n in local.identity_nodes : name => { sid = "ct:${n.vm_id}", node = n.node } },
    { for name, n in local.rag_nodes : name => { sid = "vm:${n.vm_id}", node = n.node } },
  )

  vmagent_sids = [for name, n in local.monitoring_nodes : local.ha_guests[name].sid if n.role == "vmagent"]
  rag_sids     = [for name, n in local.rag_nodes : local.ha_guests[name].sid]
}

resource "proxmox_haresource" "guests" {
  for_each = local.ha_guests

  resource_id  = each.value.sid
  state        = "started"
  max_restart  = 2
  max_relocate = 1
  failback     = true
  comment      = "${each.key} - gere par Terraform"

  depends_on = [
    proxmox_virtual_environment_vm.swarm,
    proxmox_virtual_environment_container.monitoring,
    proxmox_virtual_environment_container.identity,
    proxmox_virtual_environment_vm.rag,
  ]
}

resource "proxmox_harule" "home_node" {
  for_each = toset(local.pve_nodes)

  rule      = "home-${each.key}"
  type      = "node-affinity"
  strict    = false
  nodes     = { for n in local.pve_nodes : n => n == each.key ? 2 : 1 }
  resources = [for name, g in local.ha_guests : g.sid if g.node == each.key && !contains(concat(local.vmagent_sids, local.rag_sids), g.sid)]
  comment   = "Invites dont le noeud d'origine est ${each.key}"

  depends_on = [proxmox_haresource.guests]
}

resource "proxmox_harule" "vmagents_apart" {
  rule      = "vmagents-apart"
  type      = "resource-affinity"
  affinity  = "negative"
  resources = local.vmagent_sids
  comment   = "Les 2 vmagents toujours sur des hyperviseurs differents"

  # Les vmagents doivent d'abord être retirés des règles de nœud préféré
  depends_on = [proxmox_haresource.guests, proxmox_harule.home_node]
}

resource "proxmox_harule" "rag_home" {
  for_each = local.rag_nodes

  rule      = "home-${each.key}"
  type      = "node-affinity"
  strict    = false
  nodes     = { for n in local.pve_nodes : n => n == each.value.node ? 2 : 1 }
  resources = [local.ha_guests[each.key].sid]
  comment   = "${each.key} (assistant IA) - noeud d'origine ${each.value.node}"

  depends_on = [proxmox_haresource.guests]
}
