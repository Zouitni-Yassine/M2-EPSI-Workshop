# Infrastructure : PROJECT RESILIENCE-ALPHA (vue d'ensemble)

Fiche courte pour l'assistant. La documentation détaillée et à jour de l'infrastructure est
indexée à part (dossier `doc-infra/` : architecture, réseau, supervision, WAF, tests de
résilience, PCA/PRA ; dossier `infra/` : fiches de procédures). En cas de doute, ces documents
font foi.

## Serveurs physiques et machines

Les **seuls serveurs physiques** du lab sont les **3 hyperviseurs Proxmox VE 9 + Ceph**
(ceph01, ceph02, ceph03). Toutes les autres machines sont des VM ou des LXC hébergées sur eux.
(Dans le lab, ces trois hyperviseurs tournent eux-mêmes sur un hôte parent.)

| Machine | Type | IP | Réseau | Rôle |
|---|---|---|---|---|
| ceph01-03 | Serveur physique (hyperviseur Proxmox + Ceph) | 10.0.1.100-102 | MANAGEMENT (VLAN 10) | Hébergement, stockage Ceph partagé, HA |
| control01 | VM | 10.0.1.110 | MANAGEMENT | Poste de contrôle : Terraform, Packer, Ansible |
| dockermgr01-03 | VM | 10.30.1.211-213 | RA-APP (VLAN 301) | Managers Swarm (Raft), drainés, passerelle de remédiation |
| dockerwrk01-03 | VM | 10.30.1.221-223 | RA-APP | Workers Swarm : conteneurs applicatifs, base répliquée |
| Adresse virtuelle | VIP keepalived | 10.30.1.200 | RA-APP | Entrée de l'application (port 5173), portée par un worker |
| rag01 | VM | 10.30.1.230 | RA-APP | Assistant des opérateurs (Ollama, API, bot Discord) |
| waf01 | VM | 10.30.2.251 | RA-DMZ (VLAN 302) | WAF ModSecurity, bannissement d'IP |
| vmagent01-02 | LXC | 10.0.1.231-232 | MANAGEMENT | Collecteurs de métriques redondants |
| monitoring01 | LXC | 10.0.1.233 | MANAGEMENT | VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana |
| iam01 / vault01 / vaultwarden01 | LXC | 10.0.1.241-243 | MANAGEMENT | Keycloak (SSO + TOTP), HashiCorp Vault, Vaultwarden |

Chaque hyperviseur porte un manager, un worker et un membre de la base : la perte d'un
hyperviseur ne coûte qu'un nœud de chaque type (testé : application disponible pendant la
coupure de ceph03).

Pour la charge CPU / RAM / disque d'une machine, l'outil de supervision `charge_machines`
donne les valeurs actuelles (`physique` = ceph01-03).

## Chemin d'une requête

Internet → NPM (TLS, `https://app.slabreze.fr`) → WAF waf01 (RA-DMZ) → adresse virtuelle
10.30.1.200:5173 → frontal (3 réplicas) → `auth` / `payment-api` → PostgreSQL répliqué
(Patroni + etcd, 3 membres, réplication synchrone). Aucun accès public ne contourne le WAF.

## Supervision et reprise

- Métriques : vmagent x2 → VictoriaMetrics ; journaux : Alloy sur toutes les machines → Loki ;
  alertes : vmalert et règles Loki → Alertmanager → Discord, moteur de remédiation, WAF.
- Dashboards Grafana : « Démo / Remédiation » (état du service, sonde, anomalie, actions),
  « Cyber » (WAF, bannissements, reconnaissance faciale).
- Sonde de transaction : un vrai paiement de test toutes les 30 s.
- Reprise automatique : détecteur ML (2 à 4 s) → moteur → passerelle des managers (liste
  fermée d'actions) → redémarrage → vérification par une transaction. Reprise mesurée en 10 à
  16 s, sans intervention humaine.
- Bannissement automatique au WAF : rafale, force brute ou attaques bloquées en série → IP
  bannie 15 min (mesuré : 27 s).

## Accès d'administration

- Interfaces web (Grafana, Proxmox) : par le SSO Keycloak avec double authentification (TOTP),
  depuis les VPN d'administration seulement.
- Secrets : tous dans HashiCorp Vault ; aucun mot de passe dans le dépôt ni dans cette fiche.
- Après un redémarrage du lab, Vault est scellé : le desceller avec `vault-unseal` sur le poste
  de contrôle (seul geste manuel du démarrage à froid, ≈ 5 min).
