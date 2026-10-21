# PROJECT RESILIENCE-ALPHA : Resilience Pay

> Brouillon du README racine de l'archive `Workshop2026-M2-G<n>-Code.zip`. Les liens sont écrits
> relativement à la **racine de l'archive** : le fichier doit être copié en `README.md` à la racine.

## 1. En bref

Resilience Pay est une plateforme de paiement fictive (Stripe en mode test, PayPal en sandbox)
conçue pour **encaisser une attaque et se rétablir seule, sans intervention humaine**.

Un détecteur d'anomalies (IsolationForest) observe l'API de paiement chaque seconde. Quand il
confirme une anomalie, un moteur de remédiation redémarre le service visé, vérifie la reprise par
une transaction de contrôle, puis consigne « 0 intervention humaine ». En amont, un WAF filtre le
trafic public et bannit automatiquement une source qui attaque.

La plateforme tourne sur un **Docker Swarm de 6 VM**, hébergé par un cluster **Proxmox VE 9 / Ceph
de 3 nœuds** en haute disponibilité. La supervision repose sur VictoriaMetrics, Loki et Grafana ;
les identités sur Keycloak, HashiCorp Vault et Vaultwarden. Tout est décrit en code : Terraform,
Packer, Ansible et des stacks Swarm. Aucun secret n'est dans le dépôt.

Démonstration publique : `https://app.slabreze.fr`.

## 2. Architecture

```text
                                  INTERNET
                                     │ HTTPS 443 (Let's Encrypt, HSTS)
                          ┌──────────▼──────────┐
                          │ NPM (reverse proxy) │  terminaison TLS publique
                          └──────────┬──────────┘
                                     │ HTTPS 8443 (CA interne)
  RA-DMZ (VLAN 302)       ┌──────────▼──────────┐   journaux ──► Loki ──► règles waf-ban
                          │ WAF waf01           │◄── bannissement 15 min (Alertmanager → waf-ban)
                          │ ModSecurity + CRS   │
                          └──────────┬──────────┘
                                     │ HTTP 5173
  RA-APP (VLAN 301)       ┌──────────▼──────────┐
                          │ adresse virtuelle   │  keepalived sur les 3 workers
                          │ 10.30.1.200         │
                          └──────────┬──────────┘
   ┌─────────────────────── Docker Swarm (3 managers drainés + 3 workers) ──────────────────────┐
   │  frontend (nginx, 3 réplicas) ── /auth/ ──► auth ──────────┐                              │
   │        │                      ── /api/  ──► payment-api ───┼──► PostgreSQL (réseau interne)│
   │        │ supervision (opérateurs)            ▲    │        │                              │
   │        │                                     │    └──► Stripe test / PayPal sandbox       │
   │        ▼                       lit /api/status chaque seconde                             │
   │   detector (ML) ── verdict « anomalie » ──► remediation ── SSH (commande forcée) ──┐      │
   │                                                                                    ▼      │
   │                                         passerelle « remediate » des managers :          │
   │                                         restart du service Swarm, limites de débit       │
   └────────────────────────────────────────────────────────────────────────────────────────────┘
                                     │ métriques, journaux
  MANAGEMENT (VLAN 10)    ┌──────────▼───────────────────────────────────────────────┐
                          │ vmagent x2 ─► VictoriaMetrics ─► vmalert ─► Alertmanager │──► Discord
                          │ Alloy (17 machines) ─► Loki ─► Grafana (dashboard Démo)  │
                          │ sonde de transaction : un paiement de test toutes les 30 s│
                          ├──────────────────────────────────────────────────────────┤
                          │ Keycloak (SSO + TOTP) · Vault (secrets) · Vaultwarden    │
                          │ poste de contrôle : Terraform, Packer, Ansible           │
                          └──────────────────────────────────────────────────────────┘
   Socle : Proxmox VE 9 (ceph01-03) + Ceph, HA Proxmox sur toutes les machines,
           sauvegardes Proxmox Backup Server, pg_dump de la base toutes les 15 min.
```

Deux boucles de réaction, indépendantes :

| Boucle | Déclencheur | Action | Délai mesuré |
|---|---|---|---|
| **Disponibilité** | détecteur ML : score ≥ 0,55 pendant 3 s | le moteur redémarre `payment-api` par la passerelle, puis vérifie la reprise | anomalie en 2 à 4 s ; reprise en 10 à 19 s |
| **Contention** | règles Loki sur les journaux du WAF : rafale, force brute, attaques répétées | Alertmanager appelle `waf-ban` : l'IP source reçoit des 403 pendant 15 min | 27 s pour la force brute |

Un **filet de sécurité** s'ajoute à ces deux boucles : les alertes vmalert (`PaiementApiDown`,
`PaiementTransactionProbeFailing`...) partent vers Discord, et Swarm relance un conteneur qui
plante.

## 3. Contenu de l'archive

| Dossier / fichier | Contenu | Équipe |
|---|---|---|
| `README.md` | Ce fichier | — |
| `docker-compose.yml` | Définition de référence de l'application : lancement local, base du template Swarm | dev |
| `frontend/` | Application React (boutique, connexion, paiement, journal, supervision) ; `nginx.conf` = relais unique (seul port publié) | dev |
| `auth/` | Service d'authentification : comptes, rôles, jetons Ed25519, freinage de la force brute ; tests `auth/tests` | dev |
| `backend/` | payment-api : paiements Stripe / PayPal, journal en base, métriques ; tests `backend/tests` | dev |
| `db/` | PostgreSQL : une base et un rôle par service (`db/init/01-roles.sh`) | dev |
| `detector/` | Détecteur d'anomalies (IsolationForest + distance robuste) | IA |
| `remediation/` | Moteur de remédiation (mode `docker` en local, mode `ssh` sur le Swarm) ; tests `remediation/tests` | dev / infra |
| `proxy/` | Proxy du socket Docker à liste blanche (compose local uniquement, absent du Swarm) | dev |
| `scripts/init-secrets.py` | Génère les secrets du lancement **local** (dossier `secrets/`, jamais commité) | dev |
| `docs/` | Dossier d'architecture (PDF, PPTX), vue d'ensemble | tous |
| `evaluation/` *(si présent)* | Évaluation du détecteur : `attaque.py` (scénario d'attaque), `capture.py`, `evaluate.py`, notebook, courbe (précision 0,81, rappel 0,92, F1 0,86, AUC 0,92, détection en 4 s) | IA |
| `rag/` *(si présent)* | Assistant RAG des opérateurs (Ollama + LangChain + Chroma), corpus `rag/docs/` | IA |
| `infra/` | Toute l'infrastructure, voir ci-dessous | infra |

Les dossiers `rag/` et `evaluation/` viennent de la branche `IA` du dépôt. S'ils ne sont pas à la
racine de l'archive, ils sont sur cette branche (`git show origin/IA:evaluation/attaque.py`).

### `infra/`

| Dossier | Contenu |
|---|---|
| `infra/terraform/` | Templates de VM, 6 VM Swarm, LXC de supervision et d'identité, VM `rag01` et `waf01` (importée), vnets SDN des VLAN, HA Proxmox. Wrapper `scripts/tf` |
| `infra/packer/debian13-docker/` | Template Debian 13 + Docker durci (VMID 9100) |
| `infra/ansible/` | Playbooks idempotents : `site.yml` (= `swarm`, `monitoring`, `identity`, `rag`, `db-backup`), `app-build.yml`, `app-deploy.yml`, `probe.yml`, `waf-ban.yml`, `waf-roadmap.yml` ; un rôle par composant |
| `infra/app/` | Template de la stack Swarm `paiement`, génération des secrets de l'application dans Vault (et, si présent, `postgres-ha/` : base répliquée) |
| `infra/monitoring/` | Configurations de supervision : scrape vmagent, règles vmalert, Alertmanager, Loki (dont les règles `waf-ban`), Alloy, dashboards Grafana et leurs générateurs, sonde de transaction (`probe/`) |
| `infra/waf/` | Bannissement automatique au WAF : récepteur `waf-ban.py`, service systemd, extraits nginx |
| `infra/unifi/` | Règles réseau de la passerelle UniFi (`ra-network.yml`) et script d'application `unifi-ra` (plan, puis `--apply`) |
| `infra/remediation/` | Stack de démonstration et test de la passerelle `remediate` |
| `infra/chaos/chaos.sh` | **Tests de résilience** : 13 pannes (application, conteneurs, VM, hyperviseur, restauration) mesurées automatiquement |
| `infra/demo/demo-check.sh` | Vérification d'avant démonstration (lecture seule) : PRÊT / PAS PRÊT |
| `infra/scripts/` | `vault-env` (lance une commande avec les secrets de Vault), `vault-unseal` (descellement) |
| `infra/pki/ca.crt` | Certificat **public** de la CA interne |
| `infra/rag/corpus/` | Corpus d'exploitation de l'infrastructure pour l'assistant RAG |
| `infra/roadmap/` | Feuille de route publiée sur `https://app.slabreze.fr/roadmap/` |
| `infra/docs/` | Documentation de l'infrastructure (voir §8), dont la **documentation d'API** (`infra/docs/api/`) |

## 4. Prérequis

**Pour lire et vérifier le code** : rien d'autre que cette archive.

**Pour lancer l'application seule, en local** (poste de développement) : Docker et Docker Compose
v2, ainsi qu'une clé Stripe de **test** (facultative : sans elle, le paiement par carte est simulé
et une bannière l'indique). La marche à suivre est au §5.1.

**Pour redéployer la plateforme complète** :

| Élément | Version utilisée |
|---|---|
| Cluster Proxmox VE 9 avec Ceph, 3 nœuds | PVE 9 |
| Poste de contrôle Debian (LXC ou VM) avec accès SSH aux hyperviseurs | Debian 13 |
| Terraform (provider `bpg/proxmox`, figé dans `.terraform.lock.hcl`) | 1.16.6 (provider 0.117.0) |
| Packer (plugin `hashicorp/proxmox`) | 1.16.1 |
| Ansible (`community.docker` 4.7.0, `community.general` 11.2.1), Python 3.13 + `passlib` | ansible-core 2.19 |
| Un bucket S3 pour l'état Terraform (`infra/terraform/backend.hcl`, non versionné) | — |
| Une passerelle UniFi pour les VLAN `RA-APP`, `RA-DMZ`, `RA-VPN` (facultatif : les mêmes flux sont filtrés par nftables sur les hôtes) | — |
| Un reverse proxy TLS public (NPM) et un nom DNS, pour l'exposition Internet | — |

Les comptes Proxmox (`terraform@pve`, `svc_monitoring@pve`), les rôles et les tokens à créer sont
décrits dans [`infra/docs/deploiement.md`](infra/docs/deploiement.md#1-prérequis).

## 5. Déploiement pas à pas

### 5.1 Application seule, en local

```bash
python scripts/init-secrets.py          # mots de passe PostgreSQL, clé de signature (dossier secrets/)
cp backend/.env.example backend/.env    # clés Stripe / PayPal de test (facultatives)
cp auth/.env.example auth/.env          # mots de passe des comptes operateur et client
cp detector/.env.example detector/.env  # jeton d'administration du détecteur
docker compose up --build -d            # puis http://localhost:5173
docker compose down
```

Les fichiers `.env` restent sur le poste ; ils sont exclus par `.gitignore`. Le détecteur apprend
la normale pendant 60 s avant de noter le trafic.

### 5.2 Plateforme complète

Toutes les commandes se lancent depuis le **poste de contrôle**, dépôt cloné dans
`/srv/M2-EPSI-Workshop`. Les secrets ne sont jamais tapés ni écrits dans un fichier : ils sont lus
dans Vault à chaque lancement, par `vault-env` (Ansible, Packer) ou par le wrapper `tf`
(Terraform).

```bash
# 0. Outils du poste de contrôle (une fois)
R=/srv/M2-EPSI-Workshop/infra
install -m 0755 $R/terraform/scripts/tf /usr/local/bin/tf
install -m 0755 $R/scripts/vault-env    /usr/local/bin/vault-env
install -m 0755 $R/scripts/vault-unseal /usr/local/bin/vault-unseal
ln -s $R/terraform /terraform

# 1. Vault doit être descellé (après chaque redémarrage du lab)
vault-unseal

# 2. Machines : template cloud (9000), template Docker (9100, Packer), puis tout le reste
tf init -backend-config=backend.hcl
tf apply -target=proxmox_virtual_environment_vm.debian13_cloud
cd $R/packer/debian13-docker && packer init . && vault-env packer build .
tf apply                                  # VM Swarm, LXC, rag01, waf01, HA

# 3. Configuration : Swarm, supervision, identités, RAG, sauvegarde de la base
cd $R/ansible
vault-env ansible-playbook site.yml       # second passage attendu : changed=0

# 4. Application : secrets générés dans Vault (une fois), images, stack
python3 ../app/init-secrets-vault.py      # n'écrase jamais une valeur existante
vault-env ansible-playbook app-build.yml  # registre privé + 5 images, construites depuis GitHub
vault-env ansible-playbook app-deploy.yml # stack Swarm « paiement »

# 5. Sonde de transaction et dashboard Démo, bannissement au WAF
vault-env ansible-playbook probe.yml
vault-env ansible-playbook waf-ban.yml
vault-env ansible-playbook monitoring.yml --limit monitoring_core

# 6. Règles réseau de la passerelle UniFi (plan, puis application avec sauvegarde)
cd $R && vault-env unifi/unifi-ra && vault-env unifi/unifi-ra --apply
```

Points d'attention :

- **Ordre `app-build` puis `app-deploy`** : les images sont taguées par le commit (`<version>-<commit
  court>`) et construites **depuis GitHub**. Le commit courant doit donc avoir été poussé, et
  construit, avant d'être déployé. Sinon le déploiement cherche des images qui n'existent pas.
- **Réinstallation à partir de zéro** : Vault ne peut pas fournir les secrets dont il a besoin
  pour être installé. Il faut alors exporter les variables à la main (`VAULT_ENV_LOADED=1`), puis
  les ranger dans Vault. Procédure : [`infra/docs/deploiement.md`](infra/docs/deploiement.md#réinstallation-à-partir-de-zéro).
- Tous les playbooks sont **idempotents** : un second passage doit afficher `changed=0`.

## 6. Vérifier que le système fonctionne

| Vérification | Commande ou écran | Attendu |
|---|---|---|
| Tout ce qui conditionne la démo | `infra/demo/demo-check.sh` (lecture seule, sur le poste de contrôle) | `PRÊT` : quorum, HA, Ceph, Vault descellé, 6 nœuds Swarm, réplicas, adresse virtuelle, API et base, chaîne NPM → WAF (200, injection SQL en 403), détecteur prêt, moteur en veille, quota de la passerelle, sonde, aucune alerte |
| Application publique | `https://app.slabreze.fr` | Page 200 ; connexion ; paiement par carte de test `4242 4242 4242 4242` à l'état `succeeded` |
| WAF | `curl -s -o /dev/null -w '%{http_code}' "https://app.slabreze.fr/?id=1%27%20OR%201=1--"` | `403` |
| API | `curl -s https://app.slabreze.fr/api/health` | `{"ok":true,...,"db":true}` |
| Dashboard Grafana **Démo / Remédiation** | Grafana, dossier `Démo` (uid `demo-remediation`), connexion SSO Keycloak | Paiements **OK**, score d'anomalie sous 0,55, moteur **EN VEILLE**, dernière transaction de la sonde de moins de 60 s |
| Sonde de transaction | stack Swarm `probe` ; Loki `{stack="probe", service="probe_transactions"}` | une ligne `type=transaction result=succeeded` toutes les 30 s |
| Tests de résilience | `infra/chaos/chaos.sh list`, puis `infra/chaos/chaos.sh <test>` | Résultat dans `/root/chaos/resultats.tsv` ; synthèse dans [`infra/docs/tests-resilience.md`](infra/docs/tests-resilience.md) |
| Tests unitaires | `pytest` dans `auth/`, `backend/`, `remediation/` | tous verts |
| Passerelle de remédiation | `infra/remediation/test-passerelle.sh` | actions autorisées, refus tracés |

**Rejouer la séquence de résilience** : `infra/chaos/chaos.sh api-stop` arrête payment-api
proprement (Swarm ne le relance pas). Le détecteur confirme l'anomalie en 2 à 4 s ; le moteur
redémarre le service par la passerelle ; la transaction de contrôle passe. La reprise prend 10 à
19 s, sans intervention humaine. Procédure de démonstration et clip :
[`infra/docs/demo.md`](infra/docs/demo.md).

## 7. Secrets : où ils sont, et où ils ne sont pas

- **Aucun secret n'est dans cette archive.** Pas de `.env`, pas d'état Terraform (`*.tfstate`),
  pas de `backend.hcl`, pas de clé privée. Le seul certificat présent, `infra/pki/ca.crt`, est
  public. Les `.gitignore` excluent ces fichiers, et chaque push a été précédé d'un scan du diff
  contre les valeurs réelles des secrets.
- **Machines et application** : dans **HashiCorp Vault** (KV v2, `secret/infra/*`), lus par
  l'AppRole `ansible` (restreint au poste de contrôle) via `vault-env`. Ils sont ensuite écrits
  sur les serveurs dans des fichiers dédiés (`0600` / `0640`), ou montés en **secrets Swarm** à
  nom versionné (`/run/secrets/...`). Ils n'apparaissent jamais dans la spec d'un service, ni
  dans une sortie Ansible (`no_log`).
- **Comptes de secours des humains** : dans **Vaultwarden**. `secret/breakglass/*` dans Vault est
  réservé aux humains.
- **Clés Stripe / PayPal** (mode test et sandbox) : rangées dans Vault par l'équipe elle-même, sans
  passer par une IA. Seule la clé **publique** Stripe est intégrée à l'image du frontal, à la
  construction.
- Inventaire complet et rotation : [`infra/docs/comptes-et-rotation.md`](infra/docs/comptes-et-rotation.md).

Les exemples de la documentation utilisent des marqueurs (`<identifiant>`, `$TOKEN`, mot de passe
lu par `read -s`), jamais de valeur réelle.

## 8. Documentation

| Sujet | Document |
|---|---|
| Architecture, choix techniques, limites | [`infra/docs/architecture.md`](infra/docs/architecture.md) |
| Déploiement détaillé, opérations courantes, dépannage | [`infra/docs/deploiement.md`](infra/docs/deploiement.md) |
| Application sur le Swarm : registre, stack, secrets, exposition publique, sonde | [`infra/docs/application.md`](infra/docs/application.md) |
| **Documentation d'API** (OpenAPI des 4 services, routes, codes, exemples) | [`infra/docs/api/README.md`](infra/docs/api/README.md) |
| Réseau : VLAN, règles UniFi et nftables | [`infra/docs/reseau.md`](infra/docs/reseau.md) |
| WAF, bannissement automatique | [`infra/docs/waf.md`](infra/docs/waf.md) |
| Passerelle de remédiation | [`infra/docs/remediation.md`](infra/docs/remediation.md) |
| Supervision : métriques, journaux, alertes, dashboards | [`infra/docs/supervision.md`](infra/docs/supervision.md) |
| Identités et secrets : Keycloak, Vault, Vaultwarden, CA interne | [`infra/docs/identites.md`](infra/docs/identites.md) |
| Comptes et rotation des secrets | [`infra/docs/comptes-et-rotation.md`](infra/docs/comptes-et-rotation.md) |
| Contrat de déploiement des applications | [`infra/docs/contrat-deploiement.md`](infra/docs/contrat-deploiement.md) |
| Tests de résilience : méthode, résultats, RTO / RPO | [`infra/docs/tests-resilience.md`](infra/docs/tests-resilience.md) |
| PCA / PRA, éléments techniques | [`infra/docs/pca-pra-technique.md`](infra/docs/pca-pra-technique.md) |
| Démonstration et clip chrono | [`infra/docs/demo.md`](infra/docs/demo.md) |
| Assistant RAG (hébergement) | [`infra/docs/rag.md`](infra/docs/rag.md) |
| Services applicatifs | `auth/README.md`, `backend/README.md`, `detector/README.md`, `remediation/README.md`, `frontend/README.md`, `db/README.md` |

## 9. Construire l'archive

L'archive est produite **à partir du dépôt Git** (`git archive`), jamais par un zip du dossier de
travail. Sur le poste de contrôle, ce dossier contient en effet des fichiers ignorés par Git
(état Terraform, `backend.hcl`) qui ne doivent pas en sortir.

```bash
cd /srv/M2-EPSI-Workshop
git archive --format=zip --prefix=Workshop2026-M2-G<n>-Code/ -o /tmp/Workshop2026-M2-G<n>-Code.zip INFRA
unzip -l /tmp/Workshop2026-M2-G<n>-Code.zip | grep -Ei '\.env$|tfstate|backend\.hcl$|id_ed25519|\.key$|\.pem$'   # doit être vide
```
