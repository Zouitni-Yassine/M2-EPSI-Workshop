# Infrastructure Resilience Pay : vue d'ensemble (état du 21/10/2026)

Ce document remplace les anciennes adresses en 10.0.1.21x et 10.0.1.22x : les nœuds Swarm sont
désormais dans le VLAN RA-APP, en 10.30.1.x.

## Machines et adresses

| Machine | Adresse | Rôle |
|---|---|---|
| ceph01, ceph02, ceph03 | 10.0.1.100 à 10.0.1.102 | Hyperviseurs Proxmox VE 9 avec stockage Ceph partagé |
| control01 | 10.0.1.110 | Poste de contrôle : Terraform, Ansible, vault-env, vault-unseal, chaos.sh |
| dockermgr01 à 03 | 10.30.1.211 à 10.30.1.213 | Managers Docker Swarm (pilotage, aucun conteneur applicatif) |
| dockerwrk01 à 03 | 10.30.1.221 à 10.30.1.223 | Workers Docker Swarm : conteneurs de l'application |
| adresse virtuelle | 10.30.1.200 | Entrée de l'application (port 5173), portée par un worker |
| monitoring01 | 10.0.1.233 | VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana |
| iam01, vault01, vaultwarden01 | 10.0.1.241 à 10.0.1.243 | Keycloak (SSO), HashiCorp Vault (secrets), Vaultwarden (comptes de secours) |
| rag01 | 10.30.1.230 | Assistant opérateur (ce RAG), sans aucun accès privilégié |

## Accès utiles

- Application publique : https://app.slabreze.fr (reverse proxy NPM, puis adresse virtuelle 10.30.1.200:5173).
- Grafana : http://10.0.1.233:3000, connexion par Keycloak (double authentification).
- Dashboard de la démonstration : dossier « Démo », dashboard « Démo / Remédiation ».
- Les alertes arrivent sur Discord (Alertmanager).

## Services de l'application (stack Swarm « paiement »)

db (PostgreSQL), auth (authentification), payment-api (API de paiement), detector (détecteur ML),
remediation (moteur de remédiation), frontend (nginx, seul port publié : 5173), mailpit.
Une sonde (stack « probe ») joue le rôle d'un client et fait une transaction de test toutes les 30 s.
