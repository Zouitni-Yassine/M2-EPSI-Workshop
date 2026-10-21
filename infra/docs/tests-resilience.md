# Tests de résilience

Ce document rend compte des tests de panne menés les 20 et 21/10/2026 sur Resilience Pay : ce
qui a été cassé, qui a réparé, en combien de temps, et ce que les tests ont appris. Les
chiffres viennent de `/root/chaos/resultats.tsv` et des journaux de chaque test, sur le poste
de contrôle (10.0.1.110). La matière pour le PCA/PRA est dans
[pca-pra-technique.md](pca-pra-technique.md).

## 1. But

Le sujet demande une plateforme qui encaisse un incident et revient seule à un état
utilisable. Il faut donc le prouver, couche par couche :

| Couche | Question posée | Mécanismes testés |
|---|---|---|
| Appli | L'application se rétablit-elle quand un service s'arrête, que la base tombe ou qu'une rafale arrive ? | Détecteur ML, moteur de remédiation, passerelle `remediate`, Swarm |
| Conteneur | Que se passe-t-il quand un conteneur est tué, ou qu'une VM du Swarm disparaît ? | Swarm (relance, replanification, Raft), keepalived (adresse virtuelle) |
| Virtualisation | La supervision, une machine restaurée, un hyperviseur entier ? | HA Proxmox, Ceph, PBS |

Règle commune : pendant un test, personne n'intervient. L'outil de test casse et mesure, il ne
répare rien.

## 2. Méthode

### 2.1 L'outil : `infra/chaos/chaos.sh`

```text
infra/chaos/chaos.sh list                 liste des tests
infra/chaos/chaos.sh <test> [--yes]       lance un test (confirmation demandée sans --yes)
```

Le script passe par `vault-env` (mot de passe admin Grafana lu dans Vault, jamais écrit). Pour
chaque test :

1. **Vérifications préalables** : `/api/health` répond 200 par l'adresse virtuelle, la sonde a
   réussi une transaction dans les 2 dernières minutes, aucune sauvegarde `vzdump` ne tourne sur
   les hyperviseurs. Sinon le test n'est pas lancé.
2. **Annotation Grafana** (tag `chaos`) : la panne apparaît comme une zone sur le dashboard
   « Démo / Remédiation ».
3. **Injection de la panne** (tableau ci-dessous).
4. **Mesure côté client** pendant toute la durée : `GET /api/health` sur l'adresse virtuelle
   10.30.1.200:5173, toutes les secondes, délai de 2 s.
5. **Attente du retour**, dans cet ordre : l'API répond, puis une transaction de la sonde
   commencée après la panne réussit, puis l'état nominal propre au test est atteint
   (§ 2.3). Délai maximal : 900 s, au-delà le verdict est `ECHEC`.
6. **Résultat** : annotation fermée avec le résumé, une ligne dans `resultats.tsv`, journaux
   dans `/root/chaos/<date>-<test>/`.

| Panne | Comment elle est provoquée | Pourquoi |
|---|---|---|
| Arrêt propre d'un service | `docker stop` du conteneur | Code de sortie 0 : Swarm ne relance pas (`restart_policy: on-failure`), seul le moteur de remédiation peut réparer |
| Arrêt brutal d'un conteneur | `docker kill` (SIGKILL) | Plantage : Swarm doit relancer |
| Perte d'une VM | `kill -9` du processus KVM sur l'hyperviseur | Un `qm stop` serait un arrêt demandé, que la HA Proxmox respecterait |
| Perte d'un LXC | `lxc-stop -k` | Même raison |
| Rafale | 45 s de `POST /api/payment_intents`, 40 requêtes en parallèle | Anomalie de trafic pour le détecteur ML |
| Restauration | `pct restore` de la dernière sauvegarde PBS sur un nouvel ID, sans réseau | Mesurer le temps de restauration et l'âge de la sauvegarde, sans toucher à la production |
| Perte d'un hyperviseur | Coupure à la main depuis l'hôte parent | Le script attend que le nœud ne réponde plus au ping |

### 2.2 Ce qui est mesuré

| Mesure | Colonne de `resultats.tsv` | Source | Précision |
|---|---|---|---|
| **Panne vue par la sonde** | `panne_sonde_s` | Sonde de transaction (stack `probe`) : somme des incidents qu'elle a vus pendant le test | 5 s |
| Coupure de `/api/health` | `coupure_health_s`, `echecs_http` | Sondage du script, toutes les secondes : du premier échec au premier succès qui suit, et nombre de secondes en échec | 1 s |
| Première transaction réussie | `transaction_ok_s` | Loki : première ligne `result=ok` de la sonde après la panne, depuis le début du test | 5 s |
| Retour à l'état nominal | `nominal_s` | Fin des vérifications du § 2.3, depuis le début du test | 2 s |
| Âge de la sauvegarde | `rpo_s` | Test `restore` uniquement | 1 s |

La **sonde de transaction** joue le rôle d'un client réel ([application.md](application.md#sonde-de-transaction-et-dashboard-démo)) :

- toutes les 5 s, `GET /` et `GET /api/health` ;
- toutes les 30 s, un paiement complet : connexion du compte `client`, création d'un paiement
  de 100 centimes, confirmation avec la carte de test Stripe ;
- après une panne, une transaction est rejouée dès que la vérification légère repasse (au plus
  6 fois, une toutes les 5 s) : la fin de panne est donc connue à 5 s près.

Définitions retenues :

- **RTO mesuré** = panne vue par la sonde : durée pendant laquelle un client ne peut pas payer.
  C'est la mesure de référence. `/api/health` seul ne suffit pas : il reste à 200 quand la base
  ou le service d'authentification sont arrêtés (§ 4.2).
- **Retour à l'état nominal** : la redondance est revenue (VM relancée, nœud Swarm prêt, toutes
  les réplicas en marche). Le service peut être rendu bien avant.
- **RPO** = données perdues. Pour une panne, on compare le nombre de paiements en base avant et
  après. Pour une restauration, c'est l'âge de la sauvegarde restaurée.

### 2.3 État nominal attendu, par test

| Test | Conditions vérifiées, dans l'ordre |
|---|---|
| Tous (sauf `restore`) | `/api/health` 200 par l'adresse virtuelle ; une transaction de la sonde commencée après la panne a réussi |
| `api-stop`, `kill-*` | Le service visé a toutes ses réplicas en marche |
| `db-kill` | `paiement_db` 1/1 ; nombre de paiements après ≥ nombre avant |
| `worker-crash`, `leader-crash` | VM relancée par la HA Proxmox ; nœud `Ready` dans Swarm ; les 6 services `paiement_*` complets ; nouveau leader (pour `leader-crash`) |
| `monitoring-crash` | LXC monitoring01 relancé ; Grafana répond |
| `node-loss` | Les 12 machines du socle (211-213, 221-223, 231-233, 241-243) en marche |
| `restore` | Vaultwarden actif dans la copie ; base SQLite présente et non vide ; copie supprimée |

Les conditions sont vérifiées l'une après l'autre : l'heure à laquelle une condition est notée
dans le journal est une borne haute (exemple : la VM peut être relancée avant que la transaction
de la sonde ne soit constatée).

### 2.4 Garde-fous

- **Pas de test pendant une sauvegarde** : une sauvegarde PBS gèle les VM environ 45 s
  (créneaux 13h00 et 21h00), et la sauvegarde de l'hôte parent gèle les VM de ceph01 vers 15h36.
  Le script refuse de démarrer si `vzdump` tourne.
- **60 s au moins entre deux tests qui sollicitent le moteur** : la passerelle refuse une
  seconde action sur le même service dans les 60 s ([remediation.md](remediation.md#4-garde-fous)).
  Le second `api-stop` du 20/10 montre l'effet de cette limite (§ 4.2).
- **Quota de la passerelle** : 10 actions modifiantes par 10 min ; `infra/demo/demo-check.sh`
  indique le quota entamé.
- **Restauration sans risque** : copie sur un ID libre (9243), sans carte réseau (pas de
  doublon d'adresse ni de service), supprimée après vérification.
- **État de départ sain** : un test ne démarre que si l'application et la sonde sont nominales.

## 3. Résultats

20/10/2026 (Appli) et 21/10/2026 (Conteneur, Virtualisation). Toutes les pannes ont été
réparées sans intervention humaine, sauf la restauration qui est par nature une procédure
lancée par un humain.

### 3.1 Appli

| Test | Panne provoquée | Qui répare | Panne vue par la sonde | `/api/health` en échec | État nominal | Verdict |
|---|---|---|---|---|---|---|
| `api-stop` | `docker stop` de payment-api | Détecteur ML (anomalie en 2 à 4 s), moteur, passerelle (redémarrage en 12,6 s) | **10 s** | 13,3 s | 17,9 s | OK |
| `api-stop`, relancé 50 s après | Idem | Idem, retardé par la limite de la passerelle et un bug du moteur (§ 4.2) | **72,5 s** | 71,0 s | 79,8 s | OK, RTO dégradé |
| `db-kill` | SIGKILL de PostgreSQL | Swarm | **7,5 s** | 0 s | 26,3 s | OK, 0 paiement perdu (116 avant, 117 après) |
| `burst` | 45 s de rafale, 40 requêtes en parallèle | Détecteur ML (anomalie en 4 s, score 0,88), moteur (redémarrage en 13,8 s) | **0 s** | 0 s | 74,6 s | OK |

### 3.2 Conteneur

| Test | Panne provoquée | Qui répare | Panne vue par la sonde | `/api/health` en échec | État nominal | Verdict |
|---|---|---|---|---|---|---|
| `kill-payment-api` | SIGKILL de payment-api | Swarm et moteur | **17,4 s** | 17,4 s | 23,8 s | OK |
| `kill-auth` | SIGKILL d'auth | Swarm | **21,9 s** | 0 s (ne voit pas la panne) | 32,5 s | OK |
| `kill-frontend`, 1 réplica | SIGKILL du frontal | Swarm | **11,1 s** | 19,3 s | 31,9 s | OK |
| `kill-frontend`, 3 réplicas | SIGKILL d'une des 3 réplicas | Maillage de routage (2 réplicas restantes), Swarm | **0 s** | 0 s | 34,7 s | OK |
| `kill-detector` | SIGKILL du détecteur ML | Swarm | **0 s** | 0 s | 22,8 s | OK |
| `kill-remediation` | SIGKILL du moteur | Swarm | **0 s** | 0 s | 32,2 s | OK |
| `worker-crash` (dockerwrk03, sans la base) | `kill -9` de la VM qui porte l'adresse virtuelle | keepalived (bascule de l'adresse), HA Proxmox (VM relancée en 31 s), Swarm | non mesurée (note 1) | **3,0 s** | 59,9 s | OK |
| `worker-crash` (dockerwrk01, avec la base) | Idem, le worker porte aussi PostgreSQL | keepalived, HA Proxmox, Swarm | **91,9 s** | 3,0 s | 115,8 s | OK, RTO dégradé (§ 4.2) |
| `leader-crash` (dockermgr03) | `kill -9` du manager leader | Raft (nouveau leader : dockermgr01), HA Proxmox (VM relancée en 24 s) | **0 s** | 0 s | 64,4 s | OK |

Note 1 : pendant le premier `worker-crash`, la sonde tournait sur dockerwrk03, la VM tuée. Elle
a disparu avec lui et n'a donc pas vu la panne (0 s enregistré). On retient la mesure de
`/api/health` : 3 s, une requête en échec, le temps que keepalived déplace l'adresse virtuelle.

### 3.3 Virtualisation

| Test | Panne provoquée | Qui répare | Panne vue par la sonde | Retour | Verdict |
|---|---|---|---|---|---|
| `monitoring-crash` | `lxc-stop -k` de monitoring01 (VictoriaMetrics, Loki, Grafana, alertes) | HA Proxmox | **0 s** (paiements non concernés) | Grafana répond à +28 s | OK |
| `restore` | Restauration PBS de vaultwarden01 sur l'ID 9243, sans réseau | Procédure lancée par un humain | sans objet | Restauré et démarré en 40,3 s ; service et données vérifiés à +49,5 s : **RTO ≈ 1 min** | OK |
| `node-loss` | Perte d'un hyperviseur entier | HA Proxmox, Ceph, Swarm, keepalived | À COMPLÉTER (§ 6) | À COMPLÉTER | À COMPLÉTER |

RPO du test `restore` : la sauvegarde restaurée datait du 20/10 à 14h53 (heure de Paris), soit
**22 h 31 min** (81 115 s) au moment du test. Le job PBS de 22h30 n'avait pas tourné : le lab est
éteint la nuit. Le job a été déplacé à 13h00 et rag01 y a été ajouté.

### 3.4 Tests complémentaires (hors `chaos.sh`)

| Test | Résultat |
|---|---|
| Restauration de la sauvegarde logique de la base (`paiement-db-restore-test` : dernier dump `payments` restauré dans une base temporaire, comparé à la production) | 423 paiements restaurés en 0,7 s ; RPO = âge du dump, 15 min au plus |
| Démarrage à froid du lab complet | Service rétabli en 5 min environ ; seule action manuelle : `vault-unseal` |
| Force brute sur `/auth/login` par l'URL publique (12 essais) | IP bannie au WAF en 27 s, pour 15 min ([waf.md](waf.md#5-bannissement-automatique)) |
| Détection ML (jeu d'évaluation de l'équipe applicative) | F1 0,86 ; précision 0,81 ; rappel 0,92 ; AUC 0,92 |
| Remédiation de bout en bout du 20/10 (avant `chaos.sh`) | `docker stop` de payment-api, reprise en 16 s ([application.md](application.md#test-de-reprise-de-bout-en-bout-20102026)) |

## 4. Analyse

### 4.1 Ce qui marche

- **Aucune intervention humaine** sur 14 pannes injectées (hors restauration, manuelle par
  nature). Chaque couche répare ce qui la concerne :

  | Mécanisme | Ce qu'il répare | Délai observé |
  |---|---|---|
  | Swarm | Conteneur planté (SIGKILL), base comprise | 7 à 22 s |
  | Détecteur ML et moteur de remédiation | Service arrêté proprement, que Swarm ne relance pas ; anomalie de trafic | 10 s (détection 2 à 4 s, redémarrage 12,6 à 13,8 s) |
  | keepalived | Perte du worker qui porte l'adresse virtuelle | 3 s, 1 à 2 requêtes perdues |
  | Raft (Swarm) | Perte du manager leader | Invisible pour le client |
  | HA Proxmox | VM ou LXC disparu | 24 à 31 s pour relancer la machine, 28 s pour la supervision |

- **Aucune donnée perdue** lors de l'arrêt brutal de PostgreSQL (116 paiements avant, 117
  après : le seul nouveau est celui de la sonde).
- **Les composants de pilotage ne sont pas des points de défaillance du paiement** : détecteur,
  moteur, supervision et manager leader tués sans effet sur les clients.
- **La rafale ne coupe pas le service** : l'anomalie est vue en 4 s et le moteur agit, sans
  panne pour la sonde.

### 4.2 Constats

| Constat | Effet mesuré | Cause | Suite |
|---|---|---|---|
| `/api/health` reste à 200 quand la base ou auth sont arrêtées | `db-kill` : 0 s pour `/api/health`, 7,5 s pour la sonde ; `kill-auth` : 0 s contre 21,9 s ; `worker-crash` avec la base : 3 s contre 91,9 s | Le point de santé ne teste pas ses dépendances : le champ `db` passe à `false`, le code reste 200 | La sonde de transaction est la mesure de référence. Signalé à l'équipe applicative |
| La base est un point de défaillance unique | `worker-crash` sur dockerwrk01 : 91,9 s sans paiement, contre 3 s quand la base n'est pas sur le worker tué | PostgreSQL épinglé sur dockerwrk01 (volume local) : il attend le retour de la VM | Base répliquée en cours de mise en place (§ 5) |
| Une seconde panne rapprochée est réparée lentement | `api-stop` relancé 50 s après le premier : 72,5 s au lieu de 10 s | Limite de la passerelle (60 s entre deux actions sur un service), aggravée par un bug du moteur : `retry_in = 0` traité comme absent, d'où 45 s d'attente au lieu de 5 | Bug corrigé (`if exc.retry_in is not None`). La limite est voulue : elle empêche un moteur en boucle de redémarrer un service sans fin |
| Un service à réplica unique coupe le service pendant sa relance | `kill-frontend` : 11,1 s ; `kill-payment-api` : 17,4 s ; `kill-auth` : 21,9 s | Une seule réplica de frontal, d'API et d'auth (état en mémoire pour auth et le détecteur) | Frontal passé à 3 réplicas (§ 4.3). API et auth : à voir avec l'équipe applicative |
| La rafale n'est pas bloquée à la source | Le redémarrage rétablit le service, la source continue | L'action « bannir l'IP » affichée par le scénario du frontal n'existait pas | Bannissement automatique au WAF ajouté le 21/10 (force brute bannie en 27 s) |
| La sonde peut disparaître avec ce qu'elle mesure | Premier `worker-crash` : 0 s enregistré à tort | La sonde est un service Swarm, elle tournait sur le worker tué | Croiser avec `/api/health` ; piste : une sonde hors du Swarm |
| Le moteur dépend de la supervision | Non mesuré : supervision coupée 28 s pendant `monitoring-crash`, sans panne applicative en même temps | Le moteur lit les alertes dans Alertmanager (monitoring01) | Pendant une panne de monitoring01, seul Swarm répare |

Bugs trouvés grâce aux tests et corrigés :

- moteur : `retry_in = 0` traité comme absent (attente de 45 s au lieu de 5) ;
- `chaos.sh` : la première transaction réussie était cherchée depuis le début du test, et non
  depuis la panne effective. Un `docker stop` laisse finir les requêtes en cours : une
  transaction commencée avant l'arrêt pouvait compter comme une reprise. D'où la mention
  « mesure transaction invalide » sur la première ligne `api-stop` du 20/10 (transaction OK
  à +3,3 s, impossible puisque l'API était coupée 13,3 s) ; la panne vue par la sonde (10 s)
  n'est pas concernée. Le script mesure depuis `T_FAULT` depuis.

### 4.3 Avant / après : frontal à 3 réplicas

Le frontal (`paiement_frontend`) est passé de 1 à 3 réplicas, une par worker
(`max_replicas_per_node: 1`), le 21/10 entre les deux séries de tests.

| Test | 1 réplica (09h51) | 3 réplicas (10h41) |
|---|---|---|
| `kill-frontend` : panne vue par la sonde | 11,1 s | **0 s** |
| `kill-frontend` : `/api/health` en échec | 19,3 s (7 échecs) | 0 s |
| `kill-frontend` : état nominal | 31,9 s | 34,7 s |

Avec 3 réplicas, le maillage de routage de Swarm (IPVS) envoie les requêtes aux deux réplicas
restantes pendant que Swarm relance la troisième. L'adresse virtuelle reste en actif/passif
(un seul worker la porte) ; la répartition est faite par IPVS.

Le même gain est attendu pour payment-api et auth avec 2 réplicas ou plus, à condition que
l'application le permette (état en mémoire d'auth : freinage anti force brute).

## 5. Base répliquée

**À COMPLÉTER** quand la réplication PostgreSQL sera en place (travail en cours,
`infra/app/postgres-ha/`).

| Test | Panne provoquée | Qui répare | Panne vue par la sonde | État nominal | Paiements avant / après | Verdict |
|---|---|---|---|---|---|---|
| `db-kill` | SIGKILL du primaire | | | | | |
| `worker-crash` (worker du primaire) | `kill -9` de la VM | | | | | |

À comparer avec : `db-kill` 7,5 s et `worker-crash` avec la base 91,9 s (base unique).

## 6. Perte d'un hyperviseur

**À COMPLÉTER** après le test `node-loss`.

Déroulé prévu : `infra/chaos/chaos.sh node-loss`, puis coupure brutale de l'hyperviseur choisi
depuis l'hôte parent. Le script attend que le nœud ne réponde plus au ping, puis que les 12
machines du socle soient de nouveau en marche. Au retour du nœud, Vault peut être scellé
s'il était sur ce nœud : `vault-unseal` (seule action humaine attendue).

| Mesure | Valeur |
|---|---|
| Hyperviseur coupé, machines qu'il portait | |
| Panne vue par la sonde | |
| `/api/health` en échec | |
| Toutes les machines relancées par la HA | |
| État de Ceph pendant et après (`HEALTH_WARN` attendu tant que le nœud est absent) | |
| Retour du nœud, retour des machines sur leur nœud d'origine | |
| Intervention humaine | |
| Verdict | |

## 7. Rejouer les tests

Depuis le poste de contrôle, en root, hors des créneaux de sauvegarde (13h00, 15h36, 21h00) :

```sh
cd /srv/M2-EPSI-Workshop/infra
infra/demo/demo-check.sh             # état de départ : doit afficher PRÊT
chaos/chaos.sh list                  # tests disponibles
chaos/chaos.sh api-stop              # confirmation demandée (oui/non)
chaos/chaos.sh kill-auth --yes       # sans confirmation
```

- Attendre 60 s au moins après un test qui a fait agir le moteur avant le suivant.
- `CHAOS_TIMEOUT=<secondes>` change le délai maximal d'attente (900 s par défaut).
- `restore` demande que l'ID 9243 soit libre.
- `node-loss` demande une personne sur l'hôte parent pour couper l'hyperviseur.

## 8. Où sont les résultats

| Quoi | Où |
|---|---|
| Une ligne par test | `/root/chaos/resultats.tsv` (poste de contrôle) |
| Déroulé horodaté d'un test | `/root/chaos/<date>-<test>/journal.txt` |
| Sondage `/api/health` seconde par seconde | `/root/chaos/<date>-<test>/sonde-http.log` |
| Zones de panne et résumés | Grafana, dashboard « Démo / Remédiation », annotations « Tests de chaos » (tag `chaos`) |
| Incidents et transactions de la sonde | Loki : `{stack="probe", service="probe_transactions"}` |
| Actions de la passerelle | Loki : `{identifier="remediate"}` |

## Annexe : données brutes

Lignes de `/root/chaos/resultats.tsv` (durées en secondes depuis le début du test ; `-` : sans
objet).

| Date | Test | Couche | Verdict | Panne sonde | Coupure health | Échecs HTTP | Transaction OK | Nominal | RPO | Cible |
|---|---|---|---|---|---|---|---|---|---|---|
| 20/10 19:09:03 | api-stop | Appli | OK (mesure transaction invalide) | 10.0 | 13.3 | 9 | 3.3 (invalide) | 17.9 | - | - |
| 20/10 19:09:53 | api-stop | Appli | OK | 72.5 | 71.0 | 65 | 77.3 | 79.8 | - | - |
| 20/10 19:11:54 | db-kill | Appli | OK | 7.5 | 0 | 0 | 21.8 | 26.3 | - | - |
| 20/10 19:13:04 | burst | Appli | OK | 0.0 | 0 | 0 | 72.4 | 74.6 | - | - |
| 21/10 09:51:19 | kill-frontend | Conteneur | OK | 11.1 | 19.3 | 7 | 28.8 | 31.9 | - | - |
| 21/10 09:53:38 | kill-auth | Conteneur | OK | 21.9 | 0 | 0 | 29.3 | 32.5 | - | - |
| 21/10 09:55:58 | kill-detector | Conteneur | OK | 0.0 | 0 | 0 | 9.7 | 22.8 | - | - |
| 21/10 09:58:09 | kill-remediation | Conteneur | OK | 0.0 | 0 | 0 | 28.6 | 32.2 | - | - |
| 21/10 10:00:27 | kill-payment-api | Conteneur | OK | 17.4 | 17.4 | 13 | 22.1 | 23.8 | - | - |
| 21/10 10:02:56 | worker-crash | Conteneur | OK | 0.0 (invalide, note 1) | 3.0 | 1 | 32.2 | 59.9 | - | dockerwrk03 |
| 21/10 10:06:10 | leader-crash | Conteneur | OK | 0.0 | 0 | 0 | 18.2 | 64.4 | - | dockermgr03 |
| 21/10 10:41:15 | kill-frontend | Conteneur | OK | 0.0 | 0 | 0 | 32.3 | 34.7 | - | - |
| 21/10 10:43:29 | worker-crash | Conteneur | OK | 91.9 | 3.0 | 2 | 108.1 | 115.8 | - | dockerwrk01 |
| 21/10 11:22:57 | monitoring-crash | Virtualisation | OK | 0.0 | 0 | 0 | 21.0 | 27.8 | - | - |
| 21/10 11:25:31 | restore | Virtualisation | OK | - | - | - | 46.6 | 57.5 | 81115 | - |

Essais sans ligne dans le fichier, tous dus à des bugs de `chaos.sh` corrigés depuis :
`kill-frontend` à 09h49 (refusé à tort par la vérification préalable : heure de départ
calculée en notation scientifique par awk), `kill-frontend` à 10h23 (panne client nulle, mais
le script attendait « 1/1 » et ne savait pas lire « 3/3 (max 1 per node) » : faux `ECHEC`,
rejoué à 10h41) et `worker-crash` à 10h40 (arrêté avant la panne : la recherche du porteur
de l'adresse virtuelle interrompait le script).
