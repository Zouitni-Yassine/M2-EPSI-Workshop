# Partie infrastructure

L'infrastructure héberge Resilience Pay, l'observe et lui donne les moyens de se réparer. Tout
est décrit en code (Packer, Terraform, Ansible) dans le dossier `infra/` de la branche `INFRA`.
Les playbooks sont idempotents : un second passage ne change rien. Les chiffres cités viennent
des tests des 20 et 21/10/2026, mesurés par une sonde qui paie comme un vrai client.

> **Contribution infra**
>
> *(à compléter par l'équipe)*
>
>
>

## 1. Architecture et flux

```text
 Internet ─443─> NPM (TLS public) ─8443─> WAF waf01  [RA-DMZ, VLAN 302]
                                           ModSecurity + CRS, liste de bannissement
                                     ─5173─> adresse virtuelle 10.30.1.200 (keepalived)
 ┌─ Swarm [RA-APP, VLAN 301] ───────────────────────────────────────────────┐
 │ 3 managers drainés (Raft) + passerelle remediate                         │
 │ 3 workers : frontal x3 ─> auth ─> payment-api ─> PostgreSQL (Patroni x3)  │
 │             détecteur ML, moteur de remédiation, sonde de transaction     │
 └──────────────────────────────────────────────────────────────────────────┘
 ┌─ MANAGEMENT [VLAN 10] ───────────────────────────────────────────────────┐
 │ Proxmox VE 9 + Ceph (3 nœuds, HA) · poste de contrôle (IaC)               │
 │ vmagent x2 ─> VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana       │
 │ Keycloak (SSO, TOTP) · Vault (secrets) · Vaultwarden (comptes de secours)  │
 └──────────────────────────────────────────────────────────────────────────┘
 Détection : détecteur ML + vmalert/Loki ─> Alertmanager ─> moteur ─> passerelle ─> Swarm
                                                         └─> récepteur waf-ban ─> WAF
                                                         └─> Discord (humains)
 Hors du lab : PBS (sauvegardes), S3 (état Terraform), healthchecks.io (Watchdog), GitHub
```

| Composant | Rôle | Technologie | Redondance |
|---|---|---|---|
| Socle | Hébergement, stockage partagé | Proxmox VE 9, Ceph | 3 nœuds, HA sur toutes les machines |
| Orchestrateur | Exécute et relance les conteneurs | Docker Swarm | 3 managers Raft, 3 workers (un par nœud) |
| Point d'entrée | TLS public, filtrage, bannissement | NPM, ModSecurity + OWASP CRS | 1 VM WAF, relancée par la HA |
| Adresse virtuelle | Cible unique du WAF | keepalived (VRRP unicast) | Portée par 1 des 3 workers |
| Frontal | Page web, relais `/api` et `/auth` | Swarm | 3 réplicas, une par worker |
| Base | Paiements et comptes | PostgreSQL 16, Patroni 4.1.5, etcd 3.6.15 | 3 membres, réplication synchrone par quorum (migration en cours) |
| Supervision | Métriques, logs, alertes | VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana, Alloy | 2 collecteurs avec tampon disque ; stockage sur 1 LXC |
| Remédiation | Exécute les réparations décidées par le moteur | Passerelle SSH `remediate` | Sur les 3 managers |
| Identité, secrets | SSO admin, secrets machines | Keycloak, Vault, Vaultwarden, CA interne | 1 LXC chacun, sur 3 nœuds différents |
| Sauvegardes | Machines et base | PBS externe, `pg_dump` | Hors du lab |

## 2. Choix structurants et arbitrages

**Proxmox, Ceph et HA plutôt qu'un PC hôte.** Un poste unique est un point de défaillance : on
ne peut pas y démontrer de résilience. Trois nœuds avec stockage partagé tolèrent la perte d'un
hyperviseur. Le coût est l'exploitation, d'où l'automatisation complète. Choix validé par le jury.

**Swarm plutôt que Compose seul.** Les applications restent décrites en fichiers Compose
(consigne respectée), déployées par `docker stack deploy`. Swarm apporte la relance des tâches,
la replanification sur un autre nœud, les secrets et les mises à jour avec retour arrière.
Kubernetes a été écarté : courbe d'apprentissage trop longue pour quatre jours. Les managers
sont drainés pour qu'une application qui sature ne touche pas le plan de contrôle.

**VictoriaMetrics plutôt que Prometheus.** La chaîne reste compatible Prometheus (exposition,
PromQL, Alertmanager officiel). Deux collecteurs identiques sont dédoublonnés nativement, et le
tampon disque a absorbé 90 s de coupure du stockage sans trou. Alerting de Grafana écarté : il
aurait fait de Grafana un point de panne de la chaîne d'alerte.

**Segmentation en VLAN.** Le lab était un réseau plat : une application compromise voyait les
hyperviseurs et les secrets. L'application (RA-APP), l'exposition (RA-DMZ) et le VPN (RA-VPN)
ont leurs propres VLAN, filtrés par la passerelle UniFi puis par nftables sur chaque machine
(politique `drop`). Les règles sont en code.

**Vault, Keycloak, Vaultwarden hors du Swarm.** Trois besoins, trois outils : secrets des
machines avec audit des lectures (Vault, exigé par le sujet), SSO avec double authentification
(Keycloak), comptes de secours (Vaultwarden). Ils ne partagent ni noyau ni réseau avec la
plateforme attaquée.

**Passerelle de remédiation à liste fermée.** Le moteur décide, la passerelle exécute. Elle
n'accepte que `list`, `status`, `restart`, `rollback` et `scale`, sur les stacks autorisées.

**WAF en DMZ, seul point d'entrée.** Depuis le 21/10, aucun accès public ne contourne le WAF.

**Ce qu'on a refusé :**

- **Donner au moteur le socket Docker** : c'est root sur tout le cluster. Remplacé par la
  passerelle.
- **Terraform ou Ansible dans la boucle de remédiation** : trop lents (minutes), trop larges
  (ils peuvent détruire une VM) et dépendants de Vault. La boucle automatique ne fait que des
  actions courtes et réversibles ; Terraform et Ansible restent des outils humains.
- **Un webhook entrant vers le moteur** : le moteur lit les alertes. Il n'a aucun port ouvert.
- **Anti-affinité stricte des managers** : avec un nœud perdu, elle empêcherait de relancer le
  troisième manager.
- **VLAN dédiés à la supervision et à l'identité** : changement d'adresses, de certificats et
  d'URL OIDC trop risqué à deux jours du rendu. Limite assumée (§ 6).

## 3. Chaîne de détection et de reprise

Le sujet impose une reprise sans humain. La chaîne, de la panne au paiement vérifié :

| Étape | Mécanisme | Temps mesuré |
|---|---|---|
| 1. Détection | Détecteur ML (IsolationForest, F1 0,86, rappel 0,92) ; règles vmalert et Loki | 2 à 4 s |
| 2. Décision | Le moteur lit Alertmanager et le verdict ML, choisit l'action | Lecture toutes les 5 s |
| 3. Action | SSH vers la passerelle d'un manager : `restart paiement_payment-api` | 12,6 à 13,8 s (convergence comprise) |
| 4. Vérification | `status` de la passerelle, retrait du verdict ML, transaction de la sonde | État nominal à 17,9 s |
| **Résultat, API arrêtée** | Panne vue par un client | **10 à 16 s**, 0 intervention |

Les couches se complètent : Swarm relance un conteneur planté (7 à 22 s), keepalived déplace
l'adresse virtuelle (3 s), Raft élit un nouveau leader (invisible), la HA Proxmox relance une
machine perdue (24 à 31 s). Le moteur couvre ce que Swarm ne voit pas : un service arrêté
proprement, une anomalie de trafic.

**Réponse à l'attaque.** Redémarrer rétablit le service mais ne bloque pas la source. Le
bannissement automatique la contient : journaux du WAF → Loki (règles évaluées toutes les
15 s) → Alertmanager → récepteur `waf-ban` sur le WAF → liste nginx → 403 pour cette IP pendant
15 min. Force brute sur la connexion : **IP bannie en 27 s**. Garde-fous : jeton, liste blanche
(réseaux internes, supervision), 20 IP au plus, 5 nouveaux bannissements par minute.

**Scénario red team.** L'attaquant est un PC « admin compromis » sur le VPN EPSI-WG. Ce VPN
n'est volontairement pas en liste blanche du bannissement. La segmentation l'oblige à passer
par le WAF et donc par la détection.

**Disponibilité et compromission ne se traitent pas pareil.** `restart` et `rollback`
rétablissent la disponibilité, pas l'intégrité. Une compromission demande d'autres réponses :
bannir la source (automatique), restaurer la base depuis un dump (15 min de données au plus,
décision humaine), faire tourner les secrets (procédure documentée), reconstruire depuis Git.
L'isolement d'un service compromis n'est pas implémenté.

## 4. Sécurité

- **Secrets** : tous dans Vault, lus à chaque exécution par `vault-env` (AppRole limité au poste
  de contrôle). Plus aucun fichier `.env`. Sur les serveurs, fichiers dédiés 0640 lisibles par
  le seul service ; secrets Swarm versionnés par empreinte. Diff scanné avant chaque push.
  Clés des prestataires de paiement rangées dans Vault par un humain.
- **Identités** : SSO Keycloak avec TOTP pour Grafana et Proxmox ; comptes de secours dans
  Vaultwarden ; tous les secrets renouvelés le 20/10. Tokens Proxmox séparés, supervision en
  lecture seule (`PVEAuditor`).
- **Segmentation** : RA-APP ne joint de MANAGEMENT que Loki, VictoriaMetrics, Alertmanager,
  Vault et Keycloak. SSH et interfaces web refusés, testés depuis un worker.
- **Moteur de remédiation durci** : clé SSH dédiée, utilisable seulement depuis les workers ;
  commande forcée sans shell ; 60 s entre deux actions sur un service, 10 actions par 10 min ;
  interrupteur d'arrêt ; empreintes des managers vérifiées. Conteneur en lecture seule, sans
  capacité. Testé : 11 cas sur 11 conformes, injections refusées.
- **WAF et SIEM** : ModSecurity (OWASP CRS) bloque injection SQL et XSS (403). Règles d'alerte
  Loki de l'équipe cyber, dashboard dédié.
- **Journaux** : Alloy sur toutes les machines, hyperviseurs et WAF compris, vers Loki. Chaque
  appel à la passerelle et chaque bannissement est tracé. Vault journalise chaque lecture.
- **Surveillance de la surveillance** : un Watchdog part chaque minute vers healthchecks.io,
  hors du lab. S'il cesse, la chaîne d'alerte est morte et un humain est prévenu.

### Consigne additionnelle : reconnaissance faciale des opérateurs

Consigne ajoutée par l'école le 21/10. Les opérateurs du back-office se connectent en trois
temps : identifiant, visage devant la caméra du navigateur, mot de passe. Les clients de la
boutique ne sont pas concernés. Le code est celui de l'équipe applicative (service auth :
YuNet pour trouver le visage, SFace pour en tirer un gabarit de 128 nombres, modèles ONNX sur
CPU). L'infrastructure l'a intégré ainsi :

| Sujet | Choix | Raison |
|---|---|---|
| Caméra | Celle du navigateur du poste de démo | Aucune webcam sur un serveur, pas de passthrough USB vers une VM : auth peut tourner sur n'importe quel worker. La stack « PC hôte » du sujet aurait lié la connexion à une machine physique |
| Exposition | Même chemin que le reste : NPM, WAF, VIP, frontal, auth | La caméra exige HTTPS : le certificat public existant suffit |
| Taille des requêtes | 4 Mo sur les seules routes caméra, au frontal et au WAF ; 1 Mo ailleurs | Les images passent, le reste du site garde une limite basse |
| WAF | Règles ModSecurity vérifiées sur les routes caméra le 22/10 : aucune exclusion, aucun 403 sur 2,8 Mo d'images ni sur une rafale de 40 guidages | Un faux positif (403) serait compté par le bannissement automatique et bannirait le présentateur |
| Ressources | auth à 1 CPU et 768 Mo (0,5 et 256 Mo avant) ; image plus lourde (OpenCV, ≈ 37 Mo de modèles) | Inférence sur CPU ; image pré-téléchargée sur les workers |
| Intégrité des modèles | Téléchargés au build, empreinte SHA-256 figée, build arrêté si elle diffère | Rien n'est téléchargé au démarrage (conteneur en lecture seule, réseau de la base sans sortie) |
| Réplicas | auth reste à 1 réplica | Identifications en cours et blocages en mémoire : deux réplicas casseraient le parcours et permettraient de contourner les blocages |
| Compte de service | `operateur` (sonde) dispensé de caméra depuis les réseaux internes seulement (`FACE_SERVICE_NETS` restreint) | Le défaut du code (toutes les plages privées) dispensait aussi le VPN de la red team et NPM, donc Internet |
| Supervision | Alertes `AuthFaceUnavailable` et `AuthFaceRejectBurst`, panneaux Démo et Cyber | Voir un moteur hors service ou une rafale d'usurpation |
| Premier enrôlement | Tunnel SSH vers le poste de contrôle, page en `localhost` | La caméra accepte `localhost` ; la source est interne, `operateur` enrôle les comptes nominatifs |

**Données biométriques (RGPD, art. 9).** Un gabarit facial est une donnée sensible. Seuls les
membres de l'équipe sont enrôlés, avec leur consentement explicite, pour la durée du workshop.
Aucune image n'est conservée. Les gabarits sont dans la base `auth`, donc répliqués sur les
trois membres Patroni, copiés dans les `pg_dump` toutes les 15 min sur le poste de contrôle
(24 h glissantes) et dans les sauvegardes PBS des workers et du poste de contrôle. La
disponibilité qui protège les paiements multiplie aussi les copies des gabarits : après la
démo, ils sont supprimés de la base, puis les dumps et sauvegardes qui les contiennent sont
purgés (procédure dans `docs/application.md`). Accès : par auth seulement (aucune route ne
renvoie un gabarit), dumps lisibles par root sur le poste de contrôle.

**Limites.** Pas de détection du vivant : une photo peut tromper la caméra, le mot de passe
reste exigé. auth à une réplica est un point de défaillance de la connexion au back-office :
Swarm le relance en ≈ 20 s, l'identification en cours est à recommencer, les sessions ouvertes
continuent. Gabarits non chiffrés dans la base. Tests de panne prévus, résultats à mesurer
([`tests-resilience.md`](../tests-resilience.md), § 3.5).

## 5. Résultats des essais

Outil `infra/chaos/chaos.sh` : vérifie l'état de départ, injecte la panne, mesure côté client,
attend le retour à l'état nominal. Référence : la panne vue par la sonde (paiement complet toutes
les 30 s, vérification toutes les 5 s), car `/api/health` reste à 200 base arrêtée.

| Couche | Panne | Qui répare | Panne vue par un client |
|---|---|---|---|
| Appli | API arrêtée proprement | Détecteur ML, moteur, passerelle | 10 s |
| Appli | Même panne 50 s après | Idem, retardé par la limite de 60 s | 72,5 s (bug du moteur corrigé depuis) |
| Appli | Rafale, 40 requêtes en parallèle | Détecteur, moteur ; bannissement | 0 s |
| Appli | Force brute | Bannissement au WAF | Attaquant bloqué en 27 s |
| Conteneur | SIGKILL de payment-api / auth | Swarm | 17,4 s / 21,9 s |
| Conteneur | SIGKILL du frontal, 1 puis 3 réplicas | Swarm, maillage de routage | 11,1 s → **0 s** |
| Conteneur | SIGKILL du détecteur, du moteur | Swarm | 0 s |
| Conteneur | VM du worker porteur de l'adresse virtuelle | keepalived, HA | 3 s (1 requête) |
| Conteneur | VM du manager leader | Raft, HA | 0 s |
| Base | PostgreSQL tué, base unique | Swarm | 7,5 s, 0 paiement perdu |
| Base | VM du worker de la base, base unique | HA | 91,9 s |
| Base | VM du primaire, prototype Patroni | Patroni, etcd | 18,3 s, 0 écriture perdue sur 2 979 |
| Base | Conteneur primaire, prototype Patroni | Patroni | 11,8 s |
| Virtualisation | Supervision tuée | HA | 0 s (Grafana revenu à +28 s) |
| Virtualisation | Hyperviseur ceph03 coupé brutalement | Quorum 2/3, Ceph, Swarm, base répliquée | Aucun échec sur les relevés (toutes les 20 s) ; un 502 isolé au retour du nœud |
| Virtualisation | Restauration PBS d'une machine | Humain | 40 s de restauration, RTO ≈ 1 min |
| Lab complet | Démarrage à froid | HA, Swarm | ≈ 5 min, seul `vault-unseal` manuel |

Bilan : toutes les pannes injectées ont été réparées sans intervention humaine, hors
restauration (manuelle par nature) et descellement de Vault. Les composants de pilotage
(détecteur, moteur, supervision, leader) peuvent tomber sans couper le paiement.

Base répliquée : chiffres du prototype. Les valeurs sur la stack de production sont **à
confirmer** (migration en cours). La bascule manuelle prend 3,7 s ; l'ancien primaire revient
en standby (pg_rewind), sans double primaire.

Perte d'hyperviseur : le nœud a été rallumé au bout de 4 min environ, avant la fin du fencing.
Le déplacement des machines par la HA **reste à mesurer** (nouveau test prévu). Vault est
revenu scellé et a été descellé par `vault-unseal`.

Détail, méthode et données brutes : [`tests-resilience.md`](../tests-resilience.md).

**Sauvegardes.** PBS sur un serveur externe au lab : job de 13h00 (Swarm, rag01, identité,
WAF) et de 21h00 (contrôle, collecteurs, supervision). `pg_dump` toutes les 15 min, restauration
testée (423 paiements en 0,7 s). RPO : 0 en cas de panne, 15 min pour la base restaurée, 24 h
pour une machine restaurée.

## 6. Limites assumées

| Limite | En contexte industriel |
|---|---|
| Un seul site, trois hyperviseurs sur un même hôte parent | Second site ou cloud, PRA testé de bout en bout |
| Supervision et identité sur le VLAN des hyperviseurs | VLAN dédiés (supervision, identité, stockage) |
| Vault à nœud unique, descellé à la main | Vault Raft à 3 nœuds, auto-unseal (KMS, HSM) |
| Supervision et WAF en instance unique ; le moteur dépend d'Alertmanager | Clusters VictoriaMetrics et Loki, second WAF |
| payment-api et auth à une réplica | Plusieurs réplicas, état anti force brute partagé |
| Reconnaissance faciale : pas de détection du vivant, état des identifications en mémoire, gabarits non chiffrés et copiés dans les sauvegardes | Détection du vivant, état partagé, gabarits chiffrés (clé dans Vault), sauvegardes à rétention courte pour la base `auth` |
| `/api/health` ne teste pas ses dépendances | Point de santé qui échoue si la base manque |
| Un seul serveur de sauvegarde, dumps copiés hors du lab une fois par jour | Seconde copie hors site, dumps vers S3 à chaque exécution |
| Limites de la passerelle comptées par manager | État partagé |
| Bannissement par IP : NAT partagé banni pour tous, attaque distribuée sous les seuils non arrêtée | Limitation de débit, réputation d'IP |
| Clé de la CA et token root de Vault sur le poste de contrôle | CA racine hors ligne ; token révoqué après la démo (prévu) |
| Verrou Terraform local | Backend avec verrou partagé, exécution en CI |

## 7. Renvois vers le dépôt (`infra/`)

| Document | Contenu |
|---|---|
| `README.md` | Vue d'ensemble, déploiement rapide, accès |
| `docs/architecture.md` | Décisions D1 à D10 avec alternatives écartées, limites |
| `docs/reseau.md` | VLAN, flux autorisés, adresse virtuelle, tests de filtrage |
| `docs/application.md` | Stack Swarm, build, exposition publique, reconnaissance faciale (infra, RGPD), sonde de transaction |
| `docs/supervision.md` | Métriques, logs, règles d'alerte, routage, dashboards |
| `docs/waf.md` | WAF en DMZ, bannissement automatique, routes de la caméra, exploitation |
| `docs/remediation.md` | Passerelle : actions, garde-fous, tests |
| `docs/identites.md` | Keycloak, Vault, Vaultwarden, CA interne |
| `docs/comptes-et-rotation.md` | Inventaire des comptes et secrets, rotation |
| `docs/deploiement.md` | Déploiement pas à pas, démarrage du lab, dépannage |
| `docs/contrat-deploiement.md` | Règles de déploiement pour les développeurs |
| `docs/tests-resilience.md` | Méthode, résultats et données brutes des tests de panne |
| `docs/pca-pra-technique.md` | Services critiques, scénarios, RTO/RPO, sauvegardes, décisions humaines |
| `docs/rag.md` | Hébergement isolé de l'assistant des opérateurs |
| `docs/demo.md` | Scénario de démonstration, check-list, plan B |
| `docs/api/README.md` | Documentation de l'API |
| `roadmap/index.html` | Feuille de route : exigé par le sujet et ajouts |
