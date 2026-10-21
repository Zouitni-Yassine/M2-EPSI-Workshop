# Procédures : incidents d'infrastructure

## Incident : Vault est scellé (alerte VaultSealed)

Vault redémarre toujours scellé (choix de sécurité : les clés ne sont pas sur la machine).
Impact : l'application continue de fonctionner (ses secrets sont déjà dans Swarm), mais aucun
déploiement Ansible ou Terraform n'est possible.
Procédure : sur le poste de contrôle 10.0.1.110, en root, lancer la commande vault-unseal.
Vérifier ensuite que la tuile Vault du dashboard Démo indique DESCELLÉ.

## Incident : un worker Swarm tombe (dockerwrk01, 02 ou 03)

Reprise automatique :
1. Si le worker portait l'adresse virtuelle 10.30.1.200, keepalived la déplace sur un autre
   worker en quelques secondes (une requête perdue mesurée).
2. Swarm replace les conteneurs du worker perdu sur les autres.
3. La HA Proxmox redémarre la VM.
Vérifier sur le dashboard Démo, section Infrastructure : « Adresse virtuelle » affiche un worker,
« Nœuds Swarm joignables » revient à 6 / 6, conteneurs répartis sur les workers restants.

## Incident : un manager Swarm tombe ou le leader change

Les managers votent (Raft) : avec 3 managers, la perte d'un seul ne bloque rien et un nouveau
leader est élu en quelques secondes. La passerelle de remédiation existe sur les 3 managers : le
moteur essaie le suivant. Alerte SwarmNoLeader : quorum perdu (2 managers sur 3 hors service),
redémarrer les VM des managers depuis Proxmox.

## Incident : perte d'un hyperviseur entier (alerte PveNodeDown)

La HA Proxmox redémarre les machines du nœud perdu sur les deux autres (fencing par watchdog,
quelques minutes). Ceph passe en HEALTH_WARN mais sert les données depuis les copies restantes.
Le cluster garde le quorum à 2 nœuds sur 3. Si vault01 était sur ce nœud, Vault revient scellé :
lancer vault-unseal. À ne pas faire : perdre un deuxième nœud avant le retour du premier.

## Incident : supervision indisponible (monitoring01)

L'application continue de fonctionner : la supervision observe, elle ne participe pas au
paiement. Grafana, Loki et les alertes sont absents pendant le redémarrage par la HA Proxmox.
L'alerte de surveillance externe (healthchecks.io, signal Watchdog) prévient si plus aucune
alerte n'arrive. Les collecteurs vmagent gardent les métriques en tampon et les renvoient.
