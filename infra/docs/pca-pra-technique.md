# PCA / PRA : éléments techniques

Faits techniques pour le plan de continuité et de reprise d'activité de Resilience Pay :
services critiques, scénarios couverts avec leurs RTO et RPO mesurés, sauvegardes, rôles et
limites. La gouvernance (analyse de risques, cadre réglementaire, organisation de crise) est
traitée dans le dossier PCA/PRA ; ce document n'en fournit que la matière. Mesures du 20 et
21/10/2026, méthode et détail dans [tests-resilience.md](tests-resilience.md).

Définitions :

- **RTO mesuré** : durée pendant laquelle un client ne peut pas payer, vue par la sonde de
  transaction (paiement de test complet toutes les 30 s, vérification légère toutes les 5 s).
- **RPO** : données perdues, exprimées en durée (âge de la dernière copie utilisable).

## 1. Services critiques et dépendances

Chaîne d'un paiement :

```text
Client ─> NPM (TLS public) ─> WAF waf01 ─> adresse virtuelle 10.30.1.200 (keepalived)
       ─> frontal ─> auth (connexion) ─> payment-api ─> PostgreSQL (primaire Patroni)
                                                    └─> Stripe (mode test, externe)
```

| Service | Rôle | Criticité | Dépend de | Redondance actuelle |
|---|---|---|---|---|
| Frontal (`paiement_frontend`) | Page web, relais `/api` et `/auth` | Critique | Swarm, adresse virtuelle | 3 réplicas, une par worker |
| Authentification (`paiement_auth`) | Connexion, jetons, freinage anti force brute | Critique | PostgreSQL (base `auth`) ; pour les opérateurs, reconnaissance faciale (voir [application.md](application.md#reconnaissance-faciale-du-back-office-consigne-additionnelle)) | 1 réplica, relance par Swarm |
| API de paiement (`paiement_payment-api`) | Création et confirmation des paiements | Critique | PostgreSQL (base `payments`), Stripe | 1 réplica, relance par Swarm et par le moteur |
| Base (`paiement_db1` à `db3`) | PostgreSQL 16, bases `payments` et `auth` | Critique | Patroni 4.1.5 et etcd 3.6.15 (`paiement_etcd1` à `3`) ; volume local sur chaque worker | 3 membres, un par worker (donc par hyperviseur) : 1 primaire, 2 standbys, réplication synchrone par quorum, bascule automatique ; clients multi-hôtes (`target_session_attrs=read-write`) |
| Stripe | Prestataire de paiement | Critique | Internet | Hors de notre périmètre |
| WAF (`waf01`) | Seul point d'entrée public, bannissement d'IP | Critique (accès public) | NPM, adresse virtuelle | 1 VM, relance par la HA Proxmox |
| NPM | Terminaison TLS publique | Critique (accès public) | Réseau de l'utilisateur | Hors périmètre du projet |
| Détecteur ML (`paiement_detector`) | Détection d'anomalies | Secondaire | Trafic de payment-api | 1 réplica |
| Moteur de remédiation (`paiement_remediation`) | Décide et lance les réparations | Secondaire | Alertmanager (monitoring01), passerelle `remediate` (managers) | 1 réplica (un seul décideur) |
| Supervision (monitoring01, vmagent01-02) | Métriques, logs, alertes, Grafana | Secondaire | Ceph, réseau MANAGEMENT | 2 collecteurs ; stockage et alertes sur 1 LXC |
| Identité (Keycloak, Vault, Vaultwarden) | Connexion des admins, secrets, comptes de secours | Secondaire pour le paiement, critique pour l'exploitation | Ceph | 1 LXC chacun ; Vault à desceller à la main |
| Socle (Proxmox, Ceph, Swarm) | Hébergement | Critique | 3 hyperviseurs sur un hôte parent, 1 site | 3 nœuds, HA, Ceph répliqué, 3 managers Raft |

Le paiement ne dépend pas, en fonctionnement, du détecteur, du moteur, de la supervision ni de
l'identité : les tests où ils sont tués montrent 0 s de panne. Ils sont nécessaires pour
réparer (détecteur, moteur, supervision) ou pour exploiter (identité).

La base est répliquée depuis le 21/10 (commit `4d660c1`) : avant, une instance unique épinglée
sur dockerwrk01 (volume local) faisait de ce worker un point de défaillance unique (91,9 s sans
paiement à sa perte). Détail : [application.md](application.md#base-de-données-haute-disponibilité-postgresql--patroni).

La connexion des opérateurs du back-office passe aussi par la reconnaissance faciale (service
auth) ; les clients et la sonde n'en dépendent pas. Détail et tests prévus :
[application.md](application.md#reconnaissance-faciale-du-back-office-consigne-additionnelle),
[tests-resilience.md](tests-resilience.md).

## 2. Scénarios couverts

| Scénario | Détection | Réponse automatique | RTO mesuré | RPO | Intervention humaine |
|---|---|---|---|---|---|
| API arrêtée proprement (Swarm ne relance pas) | Détecteur ML : anomalie en 2 à 4 s ; alerte `PaiementApiDown` | Moteur → passerelle → redémarrage (12,6 s) | 10 s | 0 | Non |
| Même panne 50 s après une première réparation | Idem | Retardée par la limite de la passerelle (60 s par service) | 72,5 s (avant correction d'un bug du moteur) | 0 | Non |
| Plantage d'un conteneur : payment-api / auth / frontal | Swarm (fin de tâche) ; sonde | Swarm relance | 17,4 s / 21,9 s / 11,1 s ; frontal à 3 réplicas : 0 s | 0 | Non |
| Plantage du détecteur ou du moteur | Swarm | Swarm relance | 0 s | 0 | Non |
| Plantage du PostgreSQL primaire | Patroni ; Swarm ; alertes `PaiementDbSansPrimaire`, `PaiementDatabaseDown` | Swarm relance le conteneur en ~5 s, qui reprend son verrou et redevient primaire | 0 s (7,5 s avec la base unique) | 0 (686 paiements avant, 687 après) | Non |
| Plantage d'un standby PostgreSQL | Patroni ; alerte `PaiementDbStandbyManquant` | Swarm relance, le standby rattrape son retard | 0 s (prototype) | 0 | Non |
| Rafale de requêtes (45 s, 40 en parallèle) | Détecteur ML en 4 s | Redémarrage de payment-api (13,8 s) ; bannissement au WAF au-delà de 20 requêtes/s par IP | 0 s | 0 | Non |
| Force brute sur la connexion | Règle Loki `WafSourceBruteForce` (10 échecs en 2 min) | IP bannie au WAF pour 15 min, humains prévenus sur Discord | Attaquant bloqué en 27 s | 0 | Débannissement éventuel |
| Injection SQL, attaques web | ModSecurity (OWASP CRS) | Requête refusée (403) ; IP bannie après 10 refus en 2 min | 0 s | 0 | Non |
| Perte d'un worker sans le primaire de la base | keepalived ; HA Proxmox ; alerte `SwarmNodeNotReady` | Adresse virtuelle déplacée, VM relancée en 31 s | 3 s (1 requête perdue) | 0 | Non |
| Perte du worker qui porte le primaire de la base | Idem ; Patroni (verrou etcd expiré) ; alerte `PaiementDbSansPrimaire` | Standby synchrone promu (23 s après la panne), clients reconnectés au nouveau primaire ; VM relancée par la HA (+47 s), ancien primaire revenu en standby par `pg_rewind` | **0 s** (91,9 s avec la base unique) | 0 (réplication synchrone ; 704 paiements avant, 707 après) | Non |
| Perte du manager leader | Raft ; alerte `SwarmNoLeader` si quorum perdu | Nouveau leader élu, VM relancée en 24 s | 0 s | 0 | Non |
| Perte de la supervision (monitoring01) | Watchdog absent → healthchecks.io (externe) | HA Proxmox relance le LXC ; les collecteurs gardent les métriques en tampon | 0 s (Grafana de retour à +28 s) | 0 pour les métriques (tampon des collecteurs) | Non |
| Perte d'une machine (données corrompues, suppression) | Humain | Aucune | Restauration PBS : 40 s, RTO ≈ 1 min | Âge de la dernière sauvegarde : jusqu'à 24 h (22 h 31 min au test) | Oui : lancer la restauration |
| Perte de données de la base | Humain | Aucune | Restauration du dump : 0,7 s (423 paiements) | 15 min au plus | Oui : décider et restaurer |
| Redémarrage complet du lab (coupure, extinction) | — | HA et Swarm redémarrent tout | Service rétabli en 5 min environ | 0 | Oui : `vault-unseal` |
| Vault scellé (après tout redémarrage de vault01) | Alerte `VaultSealed` (Discord) | Aucune ; l'application garde ses secrets | Paiement non touché ; déploiements bloqués | 0 | Oui : `vault-unseal` |
| Perte d'un hyperviseur entier | `PveNodeDown`, Ceph `HEALTH_WARN` | Quorum Proxmox 2/3, Ceph dégradé ; keepalived, Swarm et la base répliquée (perte d'un standby) masquent la panne ; HA Proxmox doit relancer les machines sur les 2 autres nœuds | 0 s : aucun échec sur les relevés (toutes les 20 s) pendant la coupure de ceph03 ; un 502 isolé au retour du nœud. Déplacement des machines par la HA non mesuré (nœud rallumé au bout de ~4 min, avant la fin du fencing) | 0 | `vault-unseal` (Vault revenu scellé) |
| Stripe indisponible | Alerte `PaiementProviderDown` (3 min) | Aucune | Dépend du prestataire | 0 | Information, attente |
| Perte du site (les 3 hyperviseurs) | Watchdog absent → healthchecks.io | Aucune | Non couvert | Non couvert | Reconstruction (§ 4) |

## 3. Sauvegardes et RPO par type de donnée

| Donnée | Mécanisme | Fréquence, rétention | RPO | Restauration testée | Procédure |
|---|---|---|---|---|---|
| Paiements et comptes clients (bases `payments`, `auth`) | `pg_dump` (format custom) depuis le poste de contrôle, timer `paiement-db-backup`, fait sur le primaire Patroni du moment ; dumps dans `/var/backups/paiement` | Toutes les 15 min, 96 dumps par base (24 h) | 15 min | Oui : 423 paiements en 0,7 s (`paiement-db-restore-test`) | Rôle `db_backup`, playbook `db-backup.yml` |
| Paiements en cours (panne de PostgreSQL ou de son worker) | Réplication synchrone par quorum (Patroni) : un COMMIT attend au moins un des deux standbys ; seul un standby à jour est promu. Chaque membre a son volume local, disque de VM sur Ceph | Continu | 0 pour toute transaction validée | Oui : prototype (0 écriture perdue sur 2 979 à la perte de la VM du primaire) ; production (`db-kill` 686 → 687, `db-node-crash` 704 → 707 paiements) | Automatique |
| VM et LXC (Swarm, identité, WAF, rag01) | Job PBS sur `workshop-local-pbs` (serveur PBS externe, hors du lab) | Chaque jour à 13h00 | 24 h (si le lab est allumé à 13h00) | Oui : vaultwarden01, 40 s | `pct restore` / `qmrestore` ([tests-resilience.md](tests-resilience.md#33-virtualisation)) |
| Poste de contrôle (dont les dumps de la base), collecteurs, supervision, templates | Job PBS sur `workshop-local-pbs` | Chaque jour à 21h00 | 24 h | Non | Idem |
| Secrets (Vault) | Stockage de vault01, dans le job PBS de 13h00 ; clés de descellement dans Vaultwarden | Chaque jour | 24 h | Indirectement (vaultwarden01) | [identites.md](identites.md) |
| Code, configuration, infrastructure | Git (GitHub, branche `INFRA`) ; tout est en code (Packer, Terraform, Ansible) | À chaque push | Dernier push | Redéploiements quotidiens | [deploiement.md](deploiement.md) |
| État Terraform | Bucket S3 externe | À chaque `apply` | 0 | — | [deploiement.md](deploiement.md) |
| Images applicatives | Registre privé sur dockerwrk01, non sauvegardé ; reconstruites depuis GitHub | — | Sans objet | Reconstruction : `app-build.yml` | [application.md](application.md) |
| Métriques et logs | monitoring01 (job PBS 21h00) ; tampon disque des collecteurs | Continu | Perte acceptée au-delà du tampon | Oui (`monitoring-crash`) | [supervision.md](supervision.md) |

La réplication protège contre la perte d'un membre, pas contre une erreur logique (suppression,
injection SQL) : celle-ci est répliquée aussitôt sur les standbys. Le dump de 15 min reste le
seul retour en arrière sur les données.

Chaque sauvegarde PBS gèle les VM concernées environ 45 s : les créneaux (13h00, 21h00, et la
sauvegarde de l'hôte parent vers 15h36) sont exclus des démonstrations et des tests.

## 4. Procédures de reprise

| Situation | Procédure | Référence |
|---|---|---|
| Démarrage du lab, ou après toute coupure | Quorum et HA, `vault-unseal`, contrôle Swarm et supervision ; `infra/demo/demo-check.sh` doit afficher PRÊT | [deploiement.md](deploiement.md#démarrage-du-lab) |
| Perte d'un hyperviseur | Aucune action pour le paiement. Au retour du nœud : `vault-unseal` si Vault est scellé, vérifier le quorum (`pvecm status`), le retour de Ceph à `HEALTH_OK` et des standbys de la base (`pctl list`), puis `infra/demo/demo-check.sh` | [tests-resilience.md](tests-resilience.md#6-perte-dun-hyperviseur) |
| Vault scellé | `vault-unseal` sur 10.0.1.110 (clés de secours dans Vaultwarden) | [identites.md](identites.md#descellement) |
| Données de la base perdues ou corrompues | Choisir le dump (`/var/backups/paiement`), le restaurer avec `pg_restore` sur le primaire (les standbys suivent) ; le script de test `paiement-db-restore-test` sert de modèle (il restaure dans une base temporaire du primaire) | Rôle `db_backup` |
| Base : savoir qui est primaire, bascule manuelle (maintenance d'un worker) | `docker exec <membre> pctl list` sur un worker, ou `infra/demo/demo-check.sh` ; `pctl switchover --candidate dbN --force paiement` (3,7 s mesurées sur le prototype) | [application.md](application.md#exploitation) |
| Base : standby qui ne se remet pas au niveau | `pctl reinit paiement dbN --force` (reconstruction par `pg_basebackup`) ; alerte `PaiementDbStandbyManquant` | [application.md](application.md#exploitation) |
| Base répliquée défaillante (retour arrière, jusqu'à la démo) | `app-deploy.yml -e app_db_mode=single` : recrée l'instance unique sur dockerwrk01 avec l'ancien volume `paiement_db-data`, gardé intact ; reporter les paiements écrits depuis la bascule par `pg_dump` / `pg_restore` | `/root/db-migration/RETOUR-ARRIERE.txt` sur le poste de contrôle |
| Machine perdue ou corrompue | Restauration PBS sur un nouvel ID, vérification, bascule | [tests-resilience.md](tests-resilience.md) |
| Reconstruction complète (perte de site) | Terraform puis Ansible depuis le dépôt, `app-build.yml` puis `app-deploy.yml`, restauration des données | [deploiement.md](deploiement.md) |
| Arrêter la remédiation automatique (intervention, emballement) | Interrupteur `/etc/remediation/disabled` sur les managers | [remediation.md](remediation.md#6-exploitation) |
| IP bannie à tort | `sudo waf-ban unban <ip>` sur waf01 (effet en 1 à 3 s) ; suspendre : `systemctl stop waf-ban` | [waf.md](waf.md#exploitation) |
| Rotation d'un secret après compromission | Procédure par secret | [comptes-et-rotation.md](comptes-et-rotation.md) |

## 5. Rôles techniques

| Acteur | Fait quoi | Quand |
|---|---|---|
| Swarm | Relance un conteneur arrêté en erreur, replace les tâches d'un nœud perdu, élit un nouveau leader | Secondes |
| Détecteur ML | Signale une anomalie de trafic (F1 0,86 ; précision 0,81 ; rappel 0,92 ; AUC 0,92) | 2 à 4 s |
| Moteur de remédiation | Lit les alertes et l'anomalie, redémarre payment-api par la passerelle, vérifie la reprise | Sur alerte |
| Passerelle `remediate` | Applique les actions autorisées : 60 s entre deux actions sur un service, 10 actions par 10 min | Sur demande du moteur |
| keepalived | Déplace l'adresse virtuelle vers un worker sain | 3 s |
| Patroni et etcd | Promeut un standby synchrone quand le verrou du primaire expire ; remet l'ancien primaire en standby (`pg_rewind`) | 11,8 à 23 s sans écriture possible, invisible pour la sonde en production |
| HA Proxmox | Relance une VM ou un LXC perdu, sur un autre nœud si besoin | 24 à 31 s |
| `waf-ban` | Bannit une IP source 15 min (au plus 20 IP, 5 par minute, liste blanche) | 27 s |
| vmalert, Alertmanager | Alertes vers Discord (humains) et vers le moteur ; Watchdog vers healthchecks.io | 30 s à quelques minutes |
| Timers et jobs | `pg_dump` toutes les 15 min ; PBS à 13h00 et 21h00 | Planifié |
| Astreinte infra (humain) | `vault-unseal`, restaurations, reconstruction, perte d'hyperviseur, suivi des alertes Discord | Sur alerte |
| Équipe cyber (humain) | WAF, règles, débannissement, analyse d'attaque | Sur alerte |
| Équipe applicative (humain) | Correctifs, nouvelles images | Après incident |

Points de décision humaine :

| Décision | Déclencheur | Enjeu |
|---|---|---|
| Restaurer la base depuis un dump | Données perdues ou corrompues (injection, erreur) | Perte de 15 min de paiements au plus ; arrêt du service pendant la restauration |
| Restaurer une machine depuis PBS | Machine corrompue ou supprimée | Perte jusqu'à 24 h de données de cette machine |
| Couper la remédiation automatique | Emballement, intervention en cours, moteur suspect | Plus de réparation automatique de payment-api ; Swarm et la HA continuent |
| Débannir une IP ou suspendre le bannissement | Client légitime bloqué (NAT partagé) | Risque de laisser revenir l'attaquant |
| Desceller Vault | Après tout redémarrage de vault01 | Sans cela, aucun déploiement ni changement d'infrastructure |
| Reconstruire ailleurs | Perte du site | Pas de site de secours aujourd'hui |

## 6. Risques résiduels et pistes

| Limite | Effet | Piste | Gain attendu |
|---|---|---|---|
| Base répliquée sur 3 membres, verrou dans etcd (quorum 2 sur 3) | La perte d'un worker est masquée (0 s mesurée, contre 91,9 s avec la base unique, traitée le 21/10). La perte simultanée de deux workers n'est pas testée : etcd perd son quorum, `failsafe_mode` garde le primaire seulement s'il joint les autres membres | Garder un membre par hyperviseur ; tester la double panne | — |
| Réplication contre erreur logique | Une suppression ou une injection SQL est répliquée sur les standbys | Dump toutes les 15 min (en place) ; archivage continu des WAL pour une restauration à la seconde | RPO logique 15 min → quelques secondes |
| Relance des machines d'un hyperviseur perdu par la HA non mesurée | Le test `node-loss` du 21/10 a été arrêté avant la fin du fencing (nœud rallumé à ~4 min) : le temps pour retrouver les machines du nœud ailleurs est inconnu ; le paiement n'a pas été coupé | Refaire le test en laissant le nœud éteint au-delà du fencing | RTO de la perte d'hyperviseur mesuré de bout en bout |
| payment-api et auth à une réplica | 17,4 s et 21,9 s de panne au plantage | 2 réplicas ou plus (état du freinage d'auth à partager) | Frontal : 11,1 s → 0 s mesuré avec 3 réplicas |
| `/api/health` ne teste pas la base ni auth | Une panne de base ou d'auth est invisible pour qui ne lit que le code HTTP | Point de santé qui échoue si une dépendance manque | Détection plus rapide, sans la sonde |
| Limite de la passerelle (60 s par service) | Seconde panne rapprochée : 72,5 s mesurés | Garder la limite (protection contre un moteur en boucle) ; escalade humaine si refus | — |
| Limites de la passerelle comptées par manager | Jusqu'à 3 fois le quota si le moteur alterne entre managers | État partagé | — |
| Le moteur dépend d'Alertmanager (monitoring01) | Pendant une panne de la supervision, seul Swarm répare | Supervision redondante | — |
| WAF en instance unique | Perte de waf01 = plus d'accès public jusqu'à sa relance par la HA (non mesuré) | Second WAF derrière NPM | — |
| Bannissement par IP | Une IP partagée (NAT d'entreprise, opérateur mobile) est bannie pour tous ; une attaque distribuée sous les seuils n'est pas arrêtée | Seuils élevés et durée courte (15 min) ; limitation de débit au WAF | — |
| Vault descellé à la main | Après un redémarrage, ni Ansible ni Terraform tant que personne n'agit | Auto-unseal (KMS ou HSM) | Démarrage à froid sans action humaine (5 min aujourd'hui) |
| Sauvegardes liées au lab allumé | Le lab est éteint la nuit : un job qui tombe pendant l'extinction ne tourne pas (22 h 31 min d'âge au test) | Jobs aux heures d'ouverture (fait : 13h00) ; deux jobs par jour | RPO machines 24 h → 12 h |
| Dumps de la base sur le poste de contrôle | Copiés hors du lab seulement par le job PBS de 21h00 | Copie des dumps vers S3 à chaque exécution | RPO base hors site : 24 h → 15 min |
| Un seul serveur de sauvegarde (PBS externe, hors du lab) | La perte du site est couverte, mais pas celle du serveur PBS lui-même ; restauration complète du lab depuis PBS jamais testée | Seconde copie (synchronisation PBS vers un autre site ou export S3) ; exercice de reprise complète | Deux copies hors site ; RTO de reprise totale mesuré |
| Pas de site de secours | Perte de site : reconstruction complète depuis Git et sauvegardes | Second site ou cloud | — |
| 3 hyperviseurs sur un seul hôte parent | La perte de l'hôte parent est une perte de site ; sa sauvegarde gèle les VM ~45 s vers 15h36 | Hors périmètre du lab | — |
| Registre d'images non sauvegardé | Perte de dockerwrk01 : images à reconstruire (`app-build.yml`) | Registre sur stockage partagé ou S3 | — |
| Stripe sans solution de repli | Panne du prestataire = pas de paiement | Second prestataire (PayPal est intégré, bascule non automatique) | — |
| Clés de descellement et token root sur le poste de contrôle | Le poste de contrôle reste un point sensible | Révocation du token root et suppression de `init.json` après la démo (prévu) | — |

## 7. Chiffres clés

| Indicateur | Valeur |
|---|---|
| Pannes injectées par `chaos.sh` sans intervention humaine | 16 sur 16 (hors restauration, manuelle par nature) ; perte d'hyperviseur : seule action `vault-unseal` |
| RTO, panne applicative réparée par le moteur | 10 s |
| RTO, plantage de conteneur | 0 à 21,9 s selon le service ; PostgreSQL primaire : 0 s |
| RTO, perte d'un worker / du leader | 3 s / 0 s |
| RTO, perte du worker du primaire de la base | **0 s** (91,9 s avant la réplication) ; nouveau primaire promu en 23 s |
| RTO, perte d'un hyperviseur | 0 s pendant la coupure (relevés toutes les 20 s), un 502 isolé au retour du nœud ; relance des machines par la HA non mesurée |
| RTO, restauration d'une machine | ≈ 1 min |
| RTO, démarrage à froid du lab | ≈ 5 min, une action humaine (`vault-unseal`) |
| RPO, panne (base, worker, hyperviseur) | 0 (réplication synchrone par quorum ; 0 écriture perdue sur 2 979 au prototype) |
| RPO, base restaurée depuis un dump | 15 min au plus |
| RPO, machine restaurée depuis PBS | 24 h au plus si le lab est allumé au créneau |
| Bannissement d'une force brute | 27 s, pour 15 min |
| Détection ML | F1 0,86 ; rappel 0,92 |
