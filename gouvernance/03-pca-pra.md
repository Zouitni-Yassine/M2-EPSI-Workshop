# 03 — PCA / PRA de Resilience Pay

Plan de continuité et de reprise d'activité **organisationnel** de la plateforme de paiement
livrée. Il dit qui décide, quand, sur quels éléments, et ce qui reste à faire une fois le
service rétabli. La matière technique (services critiques, sauvegardes, procédures, chiffres
bruts) est dans [`../infra/docs/pca-pra-technique.md`](../infra/docs/pca-pra-technique.md) et
[`../infra/docs/tests-resilience.md`](../infra/docs/tests-resilience.md) : ce document y renvoie
sans la recopier. Hypothèses d'entreprise, rôles et échelles : [`00-cadre.md`](00-cadre.md).
Coûts d'arrêt et objectifs métier : [`01-bia.md`](01-bia.md). Scénarios de risque :
[`02-ebios-rm.md`](02-ebios-rm.md). Obligations réglementaires : [`04-nis2-dora.md`](04-nis2-dora.md).

Statut des affirmations : **D** = démontré par un essai mesuré, **P** = partiellement démontré,
**N** = non démontrable en 4 jours (organisation décrite, non exercée).

## 1. Objet, périmètre, hypothèses

### 1.1 Objet

| Plan | Question | Dans Resilience Pay |
|---|---|---|
| **PCA** (continuer) | Comment les commerçants continuent-ils d'encaisser pendant l'incident ? | Redondance et réparation automatique : 3 hyperviseurs en HA, Swarm, base répliquée (Patroni), frontal à 3 réplicas, adresse virtuelle, détecteur ML, moteur de remédiation, bannissement au WAF |
| **PRA** (reprendre) | Comment revient-on à un état sain quand la continuité n'a pas suffi ? | Restauration PBS, restauration d'un `pg_dump`, reconstruction depuis Git (Terraform, Ansible), rotation des secrets |

Activité protégée : **VM1 encaisser un paiement**, puis VM2 (authentifier), VM3 (historique),
VM4 (superviser et rétablir), VM5 (données personnelles et biométriques).

### 1.2 Périmètre

Inclus : la chaîne de paiement NPM → WAF → adresse virtuelle → frontal → auth → payment-api →
PostgreSQL, le socle (Proxmox, Ceph, Swarm), la supervision, l'identité et les secrets, les
sauvegardes, les prestataires listés au § 5 de `00-cadre.md`.

Exclus : l'hôte parent et le réseau de l'utilisateur (NPM, accès Internet), les systèmes
internes de l'entreprise fictive (messagerie, finance), l'acquisition par Stripe et PayPal.

### 1.3 Hypothèses

- Un service est **rétabli** quand un client peut de nouveau payer : une transaction réussie,
  constatée par la sonde (paiement complet toutes les 30 s), commencée **après** la panne. Un
  conteneur relancé ne suffit pas, et `/api/health` non plus : il reste à 200 base arrêtée
  (`tests-resilience.md` § 4.2).
- Le RTO est la panne vue par la sonde ; le RPO est l'âge de la dernière copie utilisable.
- Le lab est éteint la nuit ; l'entreprise fictive, elle, fonctionne 24 h sur 24 : l'astreinte
  décrite ici est une cible organisationnelle (**N**).

### 1.4 Ce que l'automatisation couvre, où l'humain reprend la main

Le sujet exige une reprise sans intervention humaine (zero-touch recovery). Le plan sépare
nettement ce que les machines font seules de ce que seul un humain peut décider.

| Automatique (aucune décision humaine) | Humain (décision ou geste obligatoire) |
|---|---|
| Relance d'un conteneur planté (Swarm, 7 à 22 s) | Restaurer la base depuis un dump (perte de 15 min de paiements au plus) |
| Redémarrage d'un service arrêté ou anormal (détecteur ML + moteur + passerelle, 10 s) | Restaurer une machine depuis PBS (perte jusqu'à 24 h) |
| Bascule de l'adresse virtuelle (3 s), élection d'un leader Swarm (0 s) | Desceller Vault après tout redémarrage de vault01 |
| Bascule du primaire PostgreSQL (Patroni, 0 s en production) | Qualifier un incident de sécurité, isoler un service compromis |
| Relance d'une machine perdue par la HA Proxmox (24 à 31 s) | Faire tourner des secrets, invalider des sessions |
| Bannissement d'une IP source au WAF (27 s, 15 min) | Débannir un client légitime, couper la remédiation automatique |
| Alerte des humains (Discord) et de l'extérieur (healthchecks.io) | Notifier ACPR, CNIL ; communiquer aux commerçants |
| | Reconstruire ailleurs (perte de site) |

Règle : **l'automatisation rétablit la disponibilité ; elle ne traite ni une compromission ni
une fuite.** Dès qu'un incident a une composante malveillante ou touche l'intégrité des données,
la main passe à l'humain, même si le service est déjà revenu (§ 3, scénarios S6 à S8).

## 2. Organisation de crise

### 2.1 Niveaux d'incident

Les niveaux reprennent l'échelle de gravité G1–G4 (`00-cadre.md` § 4). Le niveau I3 correspond
au seuil où un incident est **susceptible d'être majeur au sens de DORA** et doit être classé
selon les critères du règlement délégué (UE) 2024/1772 (`04-nis2-dora.md` § 4.1) : service
critique touché, et soit accès malveillant ayant entraîné une perte de données, soit deux
critères dépassés parmi les clients touchés, la durée, l'étendue géographique, les pertes de
données, l'impact économique.

Le seuil réglementaire arrive avant le seuil financier. En heure de pointe (3 000 transactions
par heure), un arrêt complet atteint le seuil de 10 % des transactions quotidiennes (2 500) en
**≈ 50 min**, et celui des clients touchés en même temps : un arrêt d'une heure en pointe est
donc probablement majeur, alors qu'il ne coûte que ≈ 16 k€ (G2). Hors pointe, la lecture du BIA
reste valable (2 h de durée, puis ≈ 100 k€ vers 4 h). Règle : **dès que la DMIA de 15 min est
dépassée, l'incident passe en I3 et la conformité prépare la classification DORA**, sans
attendre le seuil de durée de 2 h.

| Niveau | Gravité | Coût d'arrêt (BIA § 2.4) | Exemples | Qui pilote | Déclencheur |
|---|---|---|---|---|---|
| **I1 — Auto-résolu** | G1 | ≈ 0 € (15 s mesurées) | Conteneur relancé, VM relancée par la HA, IP bannie, panne de la supervision | Automatisation ; l'astreinte N1 constate | Alerte résolue seule, transaction de la sonde réussie |
| **I2 — Dégradé** | G2 | 0,6 k€ (5 min) à ≈ 1 k€ (15 min) | Panne visible des clients résolue sous la DMIA de 15 min ; auto-réparation refusée (limite de la passerelle) ; Vault scellé ; perte d'un hyperviseur | Astreinte N2 (exploitation) | Panne sonde > 1 min (RTO cible), alerte `remediation="manual"`, ou action humaine requise |
| **I3 — Grave** | G3 (par le coût, ou au titre de DORA dès ≈ 50 min en pointe) | 16 k€ (1 h) à 103 k€ (4 h) | Arrêt > 15 min (DMIA dépassée), Stripe indisponible > 15 min, incident de sécurité avéré (compte compromis, intrusion, fuite limitée), restauration de la base ; incident majeur DORA probable (≈ 50 min d'arrêt complet en pointe, 2 à 4 h hors pointe) | **Cellule de crise** (DSI + RSSI) ; la conformité prépare la classification DORA dès l'ouverture | Indisponibilité > 15 min, intégrité douteuse, ou malveillance confirmée |
| **I4 — Critique** | G3 élevé → G4 | 463 k€ (24 h) à 1,3 M€ (72 h) | Rançongiciel, destruction, fuite massive, perte de site | **Cellule de crise présidée par la DG** | Reprise prévisible au-delà de 4 h (DMIA d'un sinistre de site), ou données massivement exposées |

Un incident peut monter de niveau à tout moment ; il ne descend qu'à la clôture (§ 3.3). Le
seuil de 43 min (budget SLA mensuel, pénalités au-delà) est suivi par la conformité dès I2.

### 2.2 Astreinte et escalade

| Échelon | Qui (organisation fictive) | Rôle | Délai cible (**N**) |
|---|---|---|---|
| N1 | Astreinte d'exploitation (rotation sur les 12 personnes exploitation/sécurité) | Lit Discord et Grafana, vérifie que l'automatisation a réparé, n'intervient pas pendant une reprise automatique | Prise en compte en 15 min, 24/7 |
| N2 | Ingénieur infrastructure ou sécurité d'astreinte | Décisions techniques du § 4 (débannir, couper la remédiation, desceller Vault, restaurer une machine) | Sur place ou à distance en 30 min |
| N3 | DSI / responsable de production, RSSI | Ouvrent la cellule de crise, décident d'une restauration de la base | 1 h |
| Direction | DG, conformité, DPO, communication | Notification, communication externe, arbitrages financiers | 2 h (I3), 1 h (I4) |

Règles d'escalade :

- **N1 → N2** : l'alerte n'est pas résolue 15 min après son déclenchement, l'alerte porte
  `remediation="manual"` (base, prestataire, force brute, sonde en échec), ou la passerelle a
  refusé une action (`RateLimited`).
- **N2 → N3** : indisponibilité > 15 min, suspicion de malveillance au-delà d'un bannissement
  ordinaire, intégrité des paiements douteuse, ou décision de restauration de données.
- **N3 → Direction** : niveau I3 ou I4 confirmé ; tout incident pouvant donner lieu à
  notification (ACPR, CNIL).
- Pendant une reprise automatique, l'astreinte **observe et ne corrige pas** : une action manuelle
  concurrente (redémarrage, playbook) fausse la reprise et peut la retarder (limite de 60 s de la
  passerelle). Si elle doit agir, elle coupe d'abord la remédiation automatique
  (`/etc/remediation/disabled`, `remediation.md` § 6).

### 2.3 Cellule de crise

| Membre | Rôle dans la cellule |
|---|---|
| DSI / responsable de production | **Pilote technique** : choisit entre redémarrer, restaurer, reconstruire (§ 4) |
| RSSI | **Pilote sécurité** : qualifie la compromission, fixe le périmètre à isoler et les secrets à faire tourner, préserve les preuves |
| Responsable conformité / risques | Classe l'incident (DORA), prépare et dépose les rapports à l'ACPR, tient le registre |
| DPO | Évalue l'atteinte aux données personnelles et biométriques, notifie la CNIL, décide de l'information des personnes |
| Communication | Messages aux commerçants, aux payeurs, à la presse (§ 5) |
| DG | Préside en I4, arbitre (coupure volontaire du service, coûts, communication publique), signe les notifications |
| Secrétaire de crise (N2 désigné) | Main courante horodatée : décisions, heures, auteurs. Base des rapports réglementaires et du retour d'expérience |

Points de situation toutes les 30 min en I3, toutes les 15 min en I4.

### 2.4 RACI

R = réalise, A = rend compte (un seul par ligne), C = consulté, I = informé.
« Auto » : l'activité est faite par l'automatisation, l'humain en est garant.

| Activité | Auto | Astreinte N1/N2 | DSI / prod | RSSI | Conformité | DPO | Communication | DG |
|---|---|---|---|---|---|---|---|---|
| Détection (ML, vmalert, Loki, sonde, healthchecks.io) | R | R (surveillance) | A | I | | | | |
| Qualification du niveau d'incident | | R | A | R (sécurité) | C | C | I | I |
| Réparation automatique (redémarrage, bascule, bannissement) | R | I (vérifie) | A | I | | | | |
| Couper la remédiation automatique, débannir une IP | | R | A | C | | | | |
| Desceller Vault | | R | A | I | | | | |
| **Décision de restaurer la base** (perte ≤ 15 min) | | C | **A** | C | C | C | I | I (I3), C (I4) |
| Restauration de la base / d'une machine | | R | A | C | | | | |
| Reconstruction depuis Git (perte de site) | | R | A | C | I | | I | C |
| Isolement d'un service compromis, préservation des preuves | | R | C | **A** | I | I | | I |
| **Rotation des secrets** | | R | C | **A** | | | | |
| Classification DORA (incident majeur ou non) | | | C | C | **A/R** | C | | I |
| **Notification ACPR** (initiale, intermédiaire, finale) | | | C | C | R | | I | **A** (signe) |
| **Notification CNIL**, information des personnes | | | C | C | C | R | C | **A** |
| **Communication commerçants** (statut, courriel) | | I | C | C | C | C | R | **A** |
| Clôture, retour d'expérience, mise à jour du plan | | C | **A** | R | R | C | I | I |

### 2.5 Outils de crise

| Outil | Usage | Limite |
|---|---|---|
| Discord, salon d'alertes (Alertmanager) | Alertes et résolutions, chaque bannissement au WAF | Prestataire externe ; s'il tombe, plus de notification aux humains (S9) |
| healthchecks.io (Watchdog, chaque minute) | Prévient si la chaîne d'alerte elle-même est morte | Externe, seul canal indépendant du lab |
| Grafana « Démo / Remédiation » | État du paiement (sonde), score d'anomalie, actions du moteur, porteur de l'adresse virtuelle, annotations de chaos | Sur monitoring01, instance unique |
| Grafana « Plateforme - vue centrale », « Cyber » | Socle, Ceph, Swarm ; événements WAF et SIEM | Idem |
| Assistant RAG (bot Discord #assistance-rag) | Questions en langage naturel sur la supervision et la documentation | **Lecture seule** (compte `rag-readonly`) ; réponses en 20 à 80 s ; aide à la lecture, jamais source de décision sans vérification dans Grafana ou Loki |
| `infra/demo/demo-check.sh` | Contrôle en lecture seule de l'état nominal (verdict PRÊT) | Sur le poste de contrôle |
| Vaultwarden | Comptes de secours, clés de descellement | Si vaultwarden01 est perdu : restauration PBS (testée, 40 s) |
| Canal hors bande (téléphone, liste d'appel) | Si Discord est indisponible ou si l'on soupçonne la compromission d'un compte d'équipe | **N** : à créer |

## 3. Scénarios couverts

### 3.1 Synthèse

Les temps mesurés sont ceux de `tests-resilience.md` et du § 6 de `00-cadre.md` ; les cibles
sont celles du BIA (`01-bia.md` § 3 : DMIA encaissement 15 min, RTO cible panne courante 1 min,
RPO cible base restaurée 5 min, sinistre de site 4 h / 15 min). Une cible « proposée » n'existe
pas dans le BIA et est fixée ici.

| # | Scénario | Déclencheur | Réponse automatique (mesurée) | Décision humaine | RTO cible / mesuré | RPO cible / mesuré | Statut |
|---|---|---|---|---|---|---|---|
| S1 | Panne d'un service applicatif | Service arrêté, conteneur planté | Moteur + passerelle : 10 s ; Swarm : 17,4 s (API), 21,9 s (auth), frontal 0 s | Aucune ; N2 si seconde panne < 60 s (72,5 s mesurés, bug corrigé depuis) | 1 min / 0 à 22 s | 0 / 0 | D |
| S2 | Rafale / DoS applicatif | Trafic anormal | Anomalie à +4 s, redémarrage 13,8 s, 0 s de panne ; bannissement au-delà de 20 req/s par IP | Attaque distribuée sous les seuils : escalade vers le fournisseur d'accès ou un service anti-DDoS | 1 min / 0 s (source unique) | 0 / 0 | D ; P si distribuée |
| S3 | Force brute sur la connexion | 10 échecs en 2 min par IP | IP bannie en 27 s pour 15 min | Débannir un NAT légitime ; vérifier qu'aucun compte n'a cédé | 1 min / 0 s pour les autres clients | 0 / 0 | D |
| S4 | Perte de la base ou d'un worker | PostgreSQL tué, VM tuée | Base tuée : 7,5 s, 0 paiement perdu ; worker du primaire : 0 s (92 s avant réplication) ; autre worker : 3 s | Aucune | 1 min / 0 à 7,5 s | 0 / 0 | D |
| S5 | Perte d'un hyperviseur | Nœud coupé | Quorum 2/3, Ceph, Swarm, base répliquée : aucun échec relevé pendant la coupure | `vault-unseal` si vault01 était sur le nœud ; surveiller la reconstruction de Ceph | 5 min / ≈ 0 s | 0 / 0 | P (déplacement HA à remesurer) |
| S6 | Compromission d'un service ou d'un compte opérateur | Alerte WAF/SIEM, connexion anormale, alerte `AuthFaceRejectBurst` | Bannissement de la source ; aucune isolation automatique | Isoler, faire tourner les secrets (Vault : DMIA 1 h en crise), reconstruire depuis Git | 4 h proposé / non mesuré | 5 min / 15 min si restauration de la base | N |
| S7 | Fuite de données | Exfiltration constatée (WAF, Loki, signalement) | Aucune | Contenir, évaluer, notifier CNIL / ACPR | Sans objet (disponibilité intacte) | Sans objet | N |
| S8 | Rançongiciel / destruction | Machines chiffrées ou supprimées | Aucune | Reconstruire, restaurer PBS et `pg_dump` sains | 4 h / non exercé | 5 min (corruption) à 15 min (site) / 15 min si les dumps sont intacts, 24 h sinon | P (restaurations unitaires testées) |
| S9 | Perte d'un prestataire tiers | Stripe/PayPal, GitHub, Discord en panne | Alerte `PaiementProviderDown` (3 min) ; Watchdog externe | Bascule vers PayPal, gel des déploiements | Stripe : 15 min / dépend du tiers (**non tenu**) | 0 / 0 | P |
| S10 | Sinistre de site | Perte des 3 hyperviseurs ou de l'hôte parent | Watchdog absent → healthchecks.io | Reconstruction complète ailleurs | 4 h / **non couvert** (plusieurs jours) | 15 min / 24 h | N |
| S11 | Vault scellé après redémarrage | Redémarrage de vault01, démarrage du lab | Alerte `VaultSealed` en 1 min ; l'application garde ses secrets | `vault-unseal` | 15 min / manuel (paiement : 0 s) ; démarrage à froid ≈ 5 min | 24 h / 24 h | D (écart : geste humain) |

### 3.2 Fiches scénario

**S1 — Panne d'un service applicatif (payment-api, auth, frontal).**
*Réponse* : Swarm relance un conteneur planté ; un service arrêté proprement, que Swarm ne relance
pas, est vu par le détecteur ML en 2 à 4 s, et le moteur le redémarre par la passerelle
(`api-stop` : 10 s). *Humain* : aucun. Si la passerelle refuse (60 s entre deux actions sur un
service, 10 par 10 min), l'astreinte N2 est alertée et **attend** la réparation, sans relancer à
la main. *Retour à la normale* : transaction de la sonde réussie, réplicas au complet.
*Faiblesse* : auth et payment-api à une réplica (17 à 22 s de coupure au plantage).

**S2 — Rafale / DoS applicatif.**
*Réponse* : anomalie à +4 s (score 0,88), redémarrage préventif de payment-api en 13,8 s, 0 s
de panne pour la sonde ; au-delà de 1 200 requêtes par minute et par IP, bannissement au WAF.
*Humain* : si le trafic vient de nombreuses IP sous les seuils (attaque distribuée), le
bannissement par IP ne suffit pas : N2 alerte le RSSI, qui sollicite le fournisseur d'accès ou un
service de filtrage (contrat à prévoir, **N**). *Retour* : score revenu sous le seuil,
transaction réussie, aucune IP légitime bannie.

**S3 — Force brute sur la connexion.**
*Réponse* : règle Loki `WafSourceBruteForce`, IP bannie en 27 s pour 15 min, humains prévenus.
Le freinage applicatif d'auth bloque aussi l'identifiant visé. *Humain* : RSSI vérifie dans Loki
qu'aucune connexion n'a réussi depuis la source (sinon → S6) ; N2 débannit un NAT d'entreprise
bloqué à tort (`waf-ban unban`). *Retour* : bannissement expiré ou levé, aucun compte touché.

**S4 — Perte de la base ou d'un worker.**
*Réponse* : PostgreSQL tué relancé en 7,5 s sans perte (116 paiements avant, 117 après) ; perte
de la VM du primaire : Patroni promeut un réplica synchrone, 0 s de panne en production (92 s
quand la base était unique). Perte d'un autre worker : adresse virtuelle déplacée en 3 s, VM
relancée par la HA en 31 s. *Humain* : aucun. *Retour* : 3 membres Patroni dont un primaire,
nombre de paiements après ≥ avant, transaction réussie.

**S5 — Perte d'un hyperviseur.**
*Réponse* : ceph03 coupé brutalement : quorum à 2/3, Ceph dégradé mais lisible, Swarm et base
répliquée continuent ; aucun échec sur les relevés, un 502 isolé au retour du nœud
(`dossier/infra.md` § 5). *Humain* : `vault-unseal` si vault01 était sur ce nœud ; suivi de Ceph
jusqu'à `HEALTH_OK`. Pendant la dégradation, une **seconde** perte de nœud ferait perdre le
quorum : l'incident reste en I2 tant que la redondance n'est pas revenue. *Retour* : 3 nœuds,
12 machines du socle en marche, Ceph `HEALTH_OK`.

**S6 — Compromission d'un service ou d'un compte opérateur.**
*Déclencheur* : connexion réussie après une série d'échecs, connexion d'un opérateur depuis une
source inhabituelle, rafale de refus de visage (`AuthFaceRejectBurst`), alertes de la règle
cyber, comportement anormal d'un conteneur. *Réponse automatique* : bannissement de la source
seulement. **Redémarrer un service compromis ne le décontamine pas** : la remédiation
automatique est coupée pour ce service dès que la compromission est suspectée.
*Décisions humaines* (cellule de crise, I3) :
1. Contenir : bannir, désactiver le compte (Keycloak pour les administrateurs, base `auth` pour
   les opérateurs), mettre le service à 0 réplica ou le retirer du réseau ; l'isolement n'est
   pas automatisé (`remediation.md`, piste `isolate`).
2. Préserver les preuves avant toute reconstruction : journaux Loki (WAF, auth, passerelle,
   audit Vault), copie de la VM ou du conteneur.
3. Faire tourner les secrets touchés (`comptes-et-rotation.md`) ; la rotation de la clé JWT
   déconnecte toutes les sessions.
4. Reconstruire depuis Git (images reconstruites par `app-build.yml`, pas réutilisées).
5. Contrôler l'intégrité des paiements (rapprochement avec Stripe) ; restaurer un dump antérieur
   à l'intrusion seulement si des écritures frauduleuses sont établies.
*Retour* : cause identifiée et fermée, secrets renouvelés, transaction réussie, surveillance
renforcée 72 h.

**S7 — Fuite de données.**
Une fuite ne coupe pas le service : aucune automatisation ne la « répare ». *Décisions* : RSSI
contient (bannir, couper le flux, désactiver le compte utilisé), DPO qualifie les données
(paiements, comptes, **gabarits biométriques** des opérateurs, donnée sensible au sens de
l'article 9 du RGPD), conformité évalue le caractère majeur au sens de DORA. *Notifications* :
CNIL dans les 72 h (RGPD art. 33), personnes concernées si risque élevé (art. 34), ACPR si
incident majeur. *Retour* : vecteur fermé, secrets exposés renouvelés, notifications faites.
Les dumps de la base contiennent les gabarits : leur accès est un vecteur de fuite à part entière.

**S8 — Rançongiciel / destruction.**
*Réponse automatique* : aucune ; la HA relancerait des machines chiffrées. *Décisions* (I4) :
1. Isoler le lab (coupure des flux sortants, révocation de l'AppRole et des tokens Proxmox).
2. Choisir un **point de restauration antérieur à l'intrusion**, établi par les journaux, et
   vérifier qu'il est sain avant usage (§ 4.4).
3. Reconstruire le socle depuis Git si les hyperviseurs sont touchés, sinon restaurer les
   machines depuis PBS (40 s par machine testée ; reprise complète jamais exercée).
4. Restaurer la base depuis le dernier `pg_dump` sain (423 paiements en 0,7 s).
5. Faire tourner tous les secrets, rouvrir le trafic après une transaction réussie.
*RPO* : 15 min si les dumps du poste de contrôle sont intacts. S'il est touché, le dernier dump
hors du lab est celui copié par le job PBS de 21h00 : **jusqu'à 24 h** de paiements à
reconstituer depuis Stripe.

**S9 — Perte d'un prestataire tiers.**

| Prestataire | Effet | Réponse | Décision humaine |
|---|---|---|---|
| Stripe | Plus de confirmation de paiement | Alerte `PaiementProviderDown` (3 min), pas de redémarrage inutile de l'API | Bascule vers PayPal (intégré, bascule non automatique) ; information des commerçants si > 15 min |
| PayPal | Moyen de paiement secondaire indisponible | Alerte | Information |
| GitHub | Plus de build ni de déploiement ; la production continue (images dans le registre privé et pré-téléchargées sur les workers) | Aucune | Gel des déploiements ; un clone complet du dépôt existe sur le poste de contrôle |
| Discord | Les humains ne reçoivent plus les alertes ; la remédiation continue (le moteur lit Alertmanager) | healthchecks.io reste actif | Bascule sur le canal hors bande, consultation directe de Grafana |
| healthchecks.io | Plus de surveillance de la chaîne d'alerte | Aucune | Contrôle manuel de Grafana |
| S3 (état Terraform) | Plus de `tf apply` | Aucune | Report des changements d'infrastructure |
| Fournisseur d'accès, NPM, Let's Encrypt | Plus d'accès public | Aucune | Hors périmètre ; information des commerçants |

**S10 — Sinistre de site (non couvert).**
Les 3 hyperviseurs sont des VM d'un même hôte parent, sur un seul site. Sa perte arrête tout.
Ressources hors du site : Git (GitHub), état Terraform (S3), sauvegardes (PBS externe). La
reconstruction suit `deploiement.md` (Terraform, Ansible, `app-build.yml`, `app-deploy.yml`, puis
restauration des données) mais **n'a jamais été exercée** et suppose du matériel de
remplacement. RTO de plusieurs jours, RPO de 24 h. C'est la principale limite du plan
(`05-arbitrages-recommandations.md`).

**S11 — Vault scellé après redémarrage.**
L'application tourne (secrets déjà en mémoire dans Swarm) ; ni Ansible ni Terraform ne
fonctionnent. Alerte `VaultSealed` sur Discord en 1 min. *Humain* : `vault-unseal` (3 clés sur 5,
détenues par des personnes différentes une fois `init.json` supprimé). Démarrage à froid complet :
≈ 5 min, c'est le seul geste humain. *Risque* : si les détenteurs de clés sont absents, aucune
rotation de secret n'est possible pendant une crise S6 à S8. Il faut donc toujours deux
détenteurs joignables dans l'astreinte (**N**).

### 3.3 Critère de retour à la normale et clôture

| Étape | Critère vérifiable | Source |
|---|---|---|
| Service rétabli | Transaction de la sonde réussie, commencée après la panne | Loki `{stack="probe"}`, tuile « Paiements » |
| Redondance revenue | Réplicas au complet, nœuds `Ready`, Patroni à 3 membres, Ceph `HEALTH_OK` | `demo-check.sh` : PRÊT |
| Données cohérentes | Paiements après ≥ avant ; rapprochement avec Stripe si restauration | Base, tableau de bord Stripe |
| Sécurité (S6–S8) | Cause fermée, secrets renouvelés, aucune nouvelle alerte 72 h | RSSI |
| Clôture | Main courante complète, rapport final déposé si notification, actions de retour d'expérience ouvertes | Conformité, DSI |

## 4. Choix de restauration et arbitrages

### 4.1 Redémarrer, restaurer ou reconstruire

| Option | Quand | Délai | Perte de données | Qui décide |
|---|---|---|---|---|
| **Redémarrer** (Swarm, moteur, HA) | Panne sans atteinte aux données ni malveillance | Secondes | 0 | Automatique |
| **Basculer** (Patroni, keepalived) | Perte d'un membre redondant | 0 à 3 s | 0 | Automatique |
| **Restaurer une machine** (PBS) | Machine corrompue ou supprimée, sans compromission | ≈ 1 min par machine | Jusqu'à 24 h pour cette machine | N2, accord DSI |
| **Restaurer la base** (`pg_dump`) | Données détruites ou falsifiées (erreur, injection) | Secondes à minutes | ≤ 15 min de paiements | **DSI**, avis RSSI et conformité |
| **Reconstruire depuis le code** (Terraform, Ansible, images rebâties) | Compromission, doute sur l'intégrité d'une machine, perte de site | Heures (non mesuré) | Aucune pour le code ; données restaurées à part | DSI et RSSI en cellule de crise |

Principe : on choisit l'option **la plus légère qui rétablit un état sûr**, pas seulement
disponible.

### 4.2 Restaurer la base : une décision humaine

Restaurer un dump efface les paiements faits depuis (jusqu'à 15 min, soit ≈ 260 transactions au
volume moyen et jusqu'à 750 en pointe, selon les hypothèses du cadre) et arrête le service le
temps de la restauration. C'est trois fois l'objectif du BIA (RPO cible 5 min, `01-bia.md`
§ 3.2) : l'écart ne se comble que par l'archivage continu du journal PostgreSQL hors site. Ces paiements existent pourtant chez Stripe : il faut les reconstituer par
rapprochement. Une machine ne peut pas juger si cette perte vaut mieux que des données falsifiées.
La décision revient au DSI, sur avis du RSSI (la falsification est-elle établie ?) et de la
conformité (l'incident devient-il majeur ?). La restauration se fait d'abord dans une base
temporaire (modèle : `paiement-db-restore-test`), comparée à la production, puis bascule.

### 4.3 Pourquoi Terraform et Ansible restent hors de la boucle automatique

Choix argumenté dans `dossier/infra.md` § 2 : ils prennent des minutes, peuvent détruire une VM et
dépendent de Vault, qui peut être scellé. La boucle automatique ne fait que des actions courtes,
réversibles et bornées (`restart`, `rollback`, `scale`, par une passerelle à liste fermée). Une
reconstruction est une **décision**, prise par un humain qui sait si l'état de départ est sain.

### 4.4 Ne pas restaurer une sauvegarde compromise

Une restauration rétablit aussi ce que contenait la sauvegarde : porte dérobée, compte ajouté,
secret volé. En cas de compromission :

1. dater l'intrusion par les journaux (Loki, audit Vault, journaux de la passerelle) ;
2. restaurer **les données** (dump, sauvegarde PBS) d'avant cette date, de préférence dans un
   environnement isolé (comme le test `restore` : nouvel ID, sans réseau) ;
3. reconstruire **les systèmes** depuis Git plutôt que de restaurer des machines ;
4. faire tourner **tous** les secrets connus de la machine touchée, même ceux dont la fuite n'est
   pas prouvée, dans l'ordre de `comptes-et-rotation.md` (clients avant serveurs).

Les journaux eux-mêmes sont sur monitoring01, dans le même site : s'il est touché, la datation
de l'intrusion devient incertaine (risque résiduel § 7).

### 4.5 Ordre de redémarrage du lab

Après une coupure générale (vérifié chaque matin, ≈ 5 min), ou après reconstruction :

| Ordre | Couche | Vérification |
|---|---|---|
| 1 | Hyperviseurs, quorum corosync, Ceph | `pvecm status`, Ceph lisible |
| 2 | HA Proxmox : relance de toutes les machines | `ha-manager status` : `started` |
| 3 | **Vault** : `vault-unseal` (seul geste humain) | `vault-env true` |
| 4 | Identité (Keycloak, Vaultwarden) | Connexion SSO |
| 5 | Supervision (VictoriaMetrics, Loki, Alertmanager, Grafana) | 0 cible down, Watchdog vert |
| 6 | Swarm : managers puis workers | 6 nœuds `Ready` |
| 7 | Base (etcd, Patroni) | Un primaire, deux réplicas |
| 8 | Application, sonde | Réplicas au complet |
| 9 | WAF puis exposition publique (NPM) | Page 200, injection SQL 403 |
| 10 | Ouverture au trafic | Transaction de la sonde réussie ; `demo-check.sh` : PRÊT |

L'exposition publique vient en dernier : on n'ouvre aux clients qu'un service vérifié.

## 5. Communication de crise

### 5.1 Délais

| Destinataire | Quand | Canal | Responsable |
|---|---|---|---|
| Astreinte | Immédiat (automatique) | Discord, healthchecks.io | Automatisation |
| Cellule de crise | I3 : sous 30 min ; I4 : sous 15 min | Téléphone, canal de crise | N3 |
| Commerçants | Panne visible > 15 min, ou fuite les concernant | Page de statut, courriel | Communication |
| ACPR (incident majeur DORA) | Notification initiale sous 4 h après la classification et au plus tard 24 h après la détection ; rapport intermédiaire sous 72 h ; rapport final sous 1 mois (délais du règlement délégué (UE) 2025/301, à vérifier) | Portail de l'ACPR | Conformité, signé par la DG |
| CNIL | 72 h après la prise de connaissance d'une violation de données personnelles (RGPD art. 33) | Téléservice CNIL | DPO |
| Personnes concernées | Sans délai injustifié si risque élevé (RGPD art. 34) | Courriel | DPO, communication |
| Presse | Sur décision de la DG, en I4 | Communiqué | Communication |

### 5.2 Modèles de messages

**Interne (cellule de crise).**
> [I3] Incident ouvert à HH:MM. Effet : paiements [indisponibles / dégradés] depuis HH:MM.
> Cause supposée : [...]. Automatisation : [a réparé / insuffisante]. Décision attendue :
> [...]. Prochain point : HH:MM. Pilote : [nom].

**Commerçants (page de statut, premier message).**
> Depuis HH:MM, une partie des paiements en ligne peut échouer. Nos équipes sont mobilisées.
> Les paiements déjà confirmés ne sont pas affectés. Prochaine information à HH:MM.

**Commerçants (rétablissement).**
> Le service de paiement fonctionne normalement depuis HH:MM. Durée de l'incident : N min.
> Les paiements tentés entre HH:MM et HH:MM peuvent être à relancer : la liste est disponible
> dans votre espace. Un compte rendu suivra sous 5 jours ouvrés.

**Commerçants (restauration avec perte de données).**
> Pour rétablir l'intégrité des données, nous avons restauré l'état de HH:MM. Les paiements
> enregistrés entre HH:MM et HH:MM sont en cours de rapprochement avec notre prestataire ; aucun
> débit en double ne sera effectué. Nous vous recontactons sous 24 h.

**ACPR (notification initiale, éléments).** Identité de l'établissement, heure de détection et
de classification, services touchés, nombre estimé de commerçants et de payeurs touchés, durée,
données touchées, cause suspectée, mesures prises, contact. Le contenu exact suit les modèles
officiels (à vérifier).

**CNIL (éléments).** Nature de la violation, catégories et nombre approximatif de personnes et
d'enregistrements (en signalant les gabarits biométriques s'ils sont touchés), conséquences
probables, mesures prises, contact du DPO.

## 6. Maintien en condition opérationnelle du plan

### 6.1 Tests

| Test | Réalisé (20–22/10) | Fréquence proposée |
|---|---|---|
| Chaos applicatif et conteneurs (`chaos.sh` : `api-stop`, `db-kill`, `burst`, `kill-*`, `worker-crash`, `leader-crash`) | 14 pannes, 0 intervention humaine (**D**) | Chaque semaine en préproduction, chaque mois en production hors pic, et après chaque changement d'architecture |
| Restauration d'un dump dans une base temporaire | 423 paiements en 0,7 s (**D**) | Chaque jour, automatique, avec alerte en cas d'échec |
| Restauration PBS d'une machine | vaultwarden01 en 40 s (**D**) | Chaque mois, une machine différente |
| Perte d'un hyperviseur | ceph03 coupé (**P**) | Chaque trimestre |
| Démarrage à froid et descellement de Vault | Chaque matin (**D**) | Chaque trimestre une fois l'auto-unseal en place |
| Reprise complète depuis Git et PBS (site) | Jamais (**N**) | Chaque année, sur un autre site |
| Exercice de crise sur table (cellule, RACI, notification) | Jamais (**N**) | Deux fois par an, dont un scénario cyber (S6 à S8) |
| Rotation de l'ensemble des secrets | 20/10, sauf les secrets « jamais » (**P**) | Chaque année et après tout départ ou incident |

DORA impose de tester les plans de continuité TIC au moins une fois par an (article 11, à
vérifier dans `04-nis2-dora.md`) ; le chaos automatisé permet d'aller bien au-delà pour les
scénarios S1 à S5.

### 6.2 Revue

Revue du plan : chaque année, après chaque incident I3 ou I4, et après tout changement
d'architecture (exemple : la réplication de la base a changé S4, de 92 s à 0 s). Propriétaire :
DSI ; validation : DG ; contrôle : conformité.

### 6.3 Indicateurs

| Indicateur | Valeur mesurée | Cible |
|---|---|---|
| Part des pannes injectées réparées sans humain | 14 / 14 | 100 % sur S1 à S5 |
| RTO d'une panne applicative | 0 à 22 s | ≤ 1 min (BIA) |
| Délai de détection (ML) | 2 à 4 s | ≤ 10 s |
| RPO de la base restaurée | 15 min ; 24 h hors site | ≤ 5 min (BIA) |
| Âge de la dernière sauvegarde PBS | Jusqu'à 24 h (22 h 31 min au test) | ≤ 12 h |
| Dernier test de restauration réussi | 21/10/2026 | < 7 jours |
| Délai de descellement de Vault après redémarrage | Minutes, selon la présence d'un humain | ≤ 15 min (BIA), 0 avec auto-unseal |
| Indisponibilité cumulée du mois | — | < 43,2 min (SLA 99,9 %) |
| Secrets jamais renouvelés | 7 (token root, clés de descellement, clé du moteur, UniFi, webhook Discord, healthchecks.io, S3 : `comptes-et-rotation.md`) | 0 |
| Actions de retour d'expérience ouvertes | — | Aucune de plus de 90 jours |

## 7. Risques qui subsistent après la reprise

Un service rétabli n'est pas un incident terminé. Les risques ci-dessous restent après la
reprise et doivent être suivis jusqu'à leur traitement.

| Risque résiduel | Scénarios | Conséquence | Action | Porteur |
|---|---|---|---|---|
| Données perdues (paiements après le dernier dump) | S6, S8 | Jusqu'à 15 min, voire 24 h si le poste de contrôle est perdu | Rapprochement avec Stripe ; copie des dumps hors site à chaque exécution | DSI |
| Secrets possiblement exposés | S6, S7, S8 | Retour de l'attaquant avec un secret valide | Rotation complète ; secrets dynamiques à terme | RSSI |
| Cause racine non traitée | S1, S2, S6 | La panne revient ; la limite de la passerelle (60 s) ralentit la seconde reprise (72,5 s mesurés) | Retour d'expérience, correctif applicatif ; ne pas confondre redémarrage et correction | DSI, équipe applicative |
| Attaquant non arrêté | S2, S3 | Bannissement de 15 min contournable (autre IP, attaque distribuée) | Limitation de débit au WAF, réputation d'IP, filtrage amont | RSSI |
| Client légitime banni | S2, S3 | Commerçants derrière un NAT bloqués 15 min | Débannissement par N2 ; seuils revus | Astreinte |
| Redondance non revenue | S4, S5 | Une seconde panne ne serait plus absorbée (quorum à 2/3, Ceph dégradé) | Incident maintenu ouvert jusqu'à `HEALTH_OK` et PRÊT | DSI |
| Un seul site | S10 | Arrêt de plusieurs jours | Second site ou cloud, reprise complète exercée | DG (budget) |
| Vault descellé à la main | S5, S8, S11 | Aucune rotation de secret possible sans détenteur de clés | Auto-unseal (KMS ou HSM) ; deux détenteurs dans l'astreinte | DSI |
| Clés de descellement et token root sur le poste de contrôle | S6, S8 | Compromission du poste = tous les secrets | Révocation du token root et suppression de `init.json` après la démo (planifié) | RSSI |
| Sauvegarde compromise ou unique | S8 | Restauration d'un état infecté ; perte du serveur PBS = plus de sauvegardes | Point de restauration daté, seconde copie hors site immuable | DSI |
| Journaux sur le site attaqué | S6, S7, S8 | Datation de l'intrusion et preuves incertaines | Copie des journaux de sécurité hors site | RSSI |
| Gabarits biométriques multipliés par la résilience | S7 | Base `auth`, 3 membres Patroni, dumps, PBS : autant de copies à purger | Chiffrement des gabarits, rétention courte, purge après la démo | DPO |
| Pas d'isolement automatique | S6 | Un service compromis reste en ligne jusqu'à décision humaine | Action `isolate` de la passerelle | RSSI |
| Supervision, WAF, auth et payment-api en instance unique | S1, S6 | Perte de visibilité ou de point d'entrée ; 17 à 22 s de coupure | Redondance (`dossier/infra.md` § 6) | DSI |
| Organisation non exercée | Tous | RACI et délais de notification théoriques | Exercice de crise semestriel | Conformité |

Ce plan démontre la **continuité** pour les pannes courantes (S1 à S5, 0 à 22 s, sans perte de
données) ; la **reprise** après une compromission, une destruction ou une perte de site repose
sur des décisions humaines et des procédures testées une à une, jamais enchaînées. C'est là que
les investissements proposés dans `05-arbitrages-recommandations.md` ont le plus d'effet.
