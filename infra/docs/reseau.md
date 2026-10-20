# Réseau : segmentation en VLAN

Le lab tournait sur un seul réseau plat (`MANAGEMENT`, 10.0.1.0/24) : une application compromise
voyait les hyperviseurs, la supervision et les secrets. Depuis le 20/10/2026, l'application (Swarm)
et les futurs points d'entrée exposés ont leurs propres VLAN, filtrés par la passerelle UniFi et,
en défense en profondeur, par le firewall nftables des machines de destination.

## 1. Segments

| VLAN | Réseau / zone UniFi | Sous-réseau (passerelle .254) | Vnet Proxmox | Machines |
|---|---|---|---|---|
| 10 (existant) | `MANAGEMENT` / `Internal` | 10.0.1.0/24 | `vmbr0` (sans tag) | Hyperviseurs, poste de contrôle, supervision, identité, `waf01` (provisoire) |
| 301 | `RA-APP` / `RA-APP` | 10.30.1.0/24 | `raapp` | Swarm : `dockermgr01-03` (.211-.213), `dockerwrk01-03` (.221-.223) |
| 302 | `RA-DMZ` / `RA-DMZ` | 10.30.2.0/24 | `radmz` | Exposé à Internet : serveur NetBird (à venir), WAF (quand l'équipe cyber le déplacera, .251) |
| 303 | `RA-VPN` / `RA-VPN` | 10.30.3.0/24 | `ravpn` | Passerelle NetBird vers le lab (à venir) |

- **Pas de DHCP** : adresses fixes posées par cloud-init (Terraform), dernier octet = VMID.
- **Côté Proxmox** : les vnets sont dans la zone SDN `EPSI` (zone VLAN sur `vmbr0`, existante, non
  gérée ici). Les nœuds Proxmox sont eux-mêmes des VM : le trunk de l'hôte parent laisse passer
  tous les VLAN. Code : [`terraform/network.tf`](../terraform/network.tf).
- **Côté passerelle** (UCG Ultra, UniFi Network 10.6) : réseaux, zones et règles décrits dans
  [`unifi/ra-network.yml`](../unifi/ra-network.yml), appliqués par [`unifi/unifi-ra`](../unifi/unifi-ra).

## 2. Flux autorisés

Les zones personnalisées UniFi refusent tout par défaut (sauf Internet, la passerelle et le trafic
de retour). Seules ces règles `ra-*` ouvrent des flux. `MANAGEMENT` désigne toujours le **réseau**
10.0.1.0/24, jamais toute la zone `Internal`, qui contient d'autres réseaux hors projet.

| Règle | De → vers | Ports | Pourquoi |
|---|---|---|---|
| `ra-mgmt-to-app`, `-dmz`, `-vpn` | `MANAGEMENT` → `RA-*` | tous | Administration (Ansible, SSH), collecte des métriques |
| `ra-app-to-monitoring` | `RA-APP` → 10.0.1.233 | 3100, 8428, 9093 | Logs (Loki), métriques (remote write), lecture des alertes par le moteur |
| `ra-app-to-vault` | `RA-APP` → 10.0.1.242 | 8200 | Secrets de l'application |
| `ra-app-to-keycloak` | `RA-APP` → 10.0.1.241 | 443 | SSO |
| `ra-dmz-to-loki` | `RA-DMZ` → 10.0.1.233 | 3100 | Logs |
| `ra-dmz-to-keycloak` | `RA-DMZ` → 10.0.1.241 | 443 | SSO (NetBird) |
| `ra-vpn-to-mgmt`, `-dmz`, `-app` | `RA-VPN` → `MANAGEMENT`, `RA-DMZ`, `RA-APP` | tous | VPN admin : le filtrage par utilisateur et par groupe Keycloak est fait par NetBird |

Tout le reste est refusé : en particulier `RA-APP` → `RA-DMZ`, `RA-APP` → SSH ou interfaces web
de `MANAGEMENT`, et `RA-*` → les autres réseaux de la passerelle.

**Défense en profondeur** : les mêmes flux sont ouverts dans le firewall nftables des LXC de
destination (`fw_segment_rules` dans `group_vars/monitoring_core.yml`, `keycloak_servers.yml`,
`vault_servers.yml`, réseaux `ra_*_cidr` dans `group_vars/all.yml`). Sur les nœuds Swarm, les
ensembles d'adresses sont construits depuis l'inventaire ; les managers acceptent le SSH des workers
(passerelle de remédiation, voir [remediation.md](remediation.md)).

## 3. Appliquer, vérifier

```sh
cd /srv/M2-EPSI-Workshop/infra
vault-env unifi/unifi-ra            # plan : ne modifie rien
vault-env unifi/unifi-ra --apply    # sauvegarde de la console (/root/.unifi-backups, 0600), puis applique
tf plan && tf apply                 # vnets SDN et VM
cd ansible && vault-env ansible-playbook site.yml
```

Le script ne crée, modifie ou supprime que les objets `RA-*` (réseaux, zones) et `ra-*` (règles) ;
un second passage doit répondre « aucun changement ». Compte : `svc_claude`, administrateur de
l'application Network seulement (pas de UniFi OS), identifiants dans Vault (`secret/infra/unifi`).

Tests faits le 20/10 depuis `dockerwrk01` (RA-APP) :

| Destination | Attendu | Obtenu |
|---|---|---|
| Loki 3100, VictoriaMetrics 8428, Alertmanager 9093, Vault 8200, Keycloak 443 | ouvert | ouvert |
| Grafana 3000, SSH de monitoring01, de vault01, de .110 et des hyperviseurs, Proxmox 8006 | fermé | fermé |
| Autres réseaux de la passerelle (10.0.2.0/24, NPM 172.16.1.10) | fermé | fermé |
| Internet (apt, registre Docker), DNS de la passerelle | ouvert | ouvert |

Supervision après migration : 38 cibles à `up`, les 15 cibles Swarm en 10.30.1.x, logs des 6 nœuds
dans Loki, passerelle de remédiation testée de bout en bout (`remediation/test-passerelle.sh`).

## 4. Constats de la migration (20/10/2026)

| Constat | Cause | Correction |
|---|---|---|
| Création des vnets refusée (403 `SDN.Allocate`) après la destruction des VM | `TerraformRole` n'avait que `SDN.Use` ; les droits ne sont vérifiés qu'à l'application, pas au `plan` | `SDN.Allocate` et `SDN.Audit` ajoutés au rôle. Leçon : créer les vnets dans un premier `apply` ciblé avant de remplacer des VM |
| Le moteur de remédiation ne joignait plus la passerelle | Le SSH des managers n'était ouvert qu'au LAN d'administration : les workers y étaient par hasard | Règle explicite « workers → managers, 22 » dans le firewall des managers |
| Stack `demo` absente après reconstruction | Déployée à la main, pas par `site.yml` | Redéployée par `remediation/test-passerelle.sh` |
| Une règle signalée « modifiée » à chaque passage | La console ne garde pas `match_mac` côté destination | Champ retiré côté destination |
| Interface de la passerelle joignable depuis `RA-*` | Comportement par défaut UniFi (tout réseau joint sa passerelle) | Accepté pour le lab. Un blocage par liste de ports n'était pas appliqué vers la zone `Gateway` (une règle par port nécessaire) |

## 5. Limites

| Limite | En production |
|---|---|
| `RA-VPN` → `MANAGEMENT` tous ports : la passerelle NetBird masque les utilisateurs, la UCG ne voit qu'une adresse | Une passerelle par profil (admins, red team) ou filtrage par identité jusqu'au firewall |
| Supervision et identité restent sur `MANAGEMENT` avec les hyperviseurs | VLAN dédiés (supervision, identité, stockage), d'où un changement d'IP, de certificats et d'URL OIDC évité ici à deux jours du rendu |
| Compte UniFi d'automatisation avec droits sur tous les réseaux de la console | Console dédiée au projet ou droits restreints par site |
