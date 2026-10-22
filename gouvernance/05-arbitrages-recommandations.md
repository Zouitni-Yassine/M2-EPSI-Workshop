# 05 — Arbitrages et recommandations à la direction

**Destinataires** : Direction générale, RSSI, DSI, Responsable conformité et risques de
Resilience Pay SAS (organisation fictive, voir [00-cadre.md](00-cadre.md)).
**Objet** : ce que le démonstrateur protège, les compromis retenus, les indicateurs qui
permettent de piloter la résilience, et les investissements que nous recommandons.

Toutes les données d'entreprise et tous les coûts sont **fictifs et approximatifs** (ordres de
grandeur pour arbitrer, pas des devis). Les chiffres techniques sont **mesurés** sur le
démonstrateur les 20 et 21/10/2026 ; la source est citée à chaque fois. Les coûts de l'arrêt
sont détaillés dans [01-bia.md](01-bia.md), les scénarios de risque dans
[02-ebios-rm.md](02-ebios-rm.md), l'organisation de reprise dans [03-pca-pra.md](03-pca-pra.md)
et le cadre réglementaire dans [04-nis2-dora.md](04-nis2-dora.md).

## Synthèse pour la direction

1. **Nous avons protégé d'abord la capacité à encaisser un paiement (VM1).** Sur les pannes
   courantes, elle est démontrée : un client ne peut pas payer pendant 0 à 22 s, sans
   intervention humaine, sur 14 pannes injectées sur 14 (`tests-resilience.md`).
2. **La résilience démontrée est une résilience de disponibilité.** Redémarrer un service ne
   chasse pas un attaquant. La source d'une attaque web est bannie automatiquement (27 s), mais
   le traitement d'une compromission (isolement, rotation des secrets, restauration) reste
   humain.
3. **Trois risques dépassent l'appétence au risque** : la perte du site (aucun site de secours),
   les points uniques restants (WAF et Stripe sur le chemin du paiement ; Vault et supervision pour la reprise), et l'authentification du back-office
   par reconnaissance faciale sans détection du vivant.
4. **Nous demandons cinq décisions** (§ 6), dont un second site (≈ 100 à 150 k€ d'investissement)
   et le remplacement de la biométrie par des clés FIDO2 (≈ 5 k€).

## 1. Ce que nous avons choisi de protéger, et pourquoi

### 1.1 Encaisser un paiement d'abord

Le revenu de Resilience Pay est une commission par transaction (≈ 1 € en moyenne). Un arrêt
coûte donc immédiatement : ≈ 3 000 transactions par heure en pointe, soit ≈ 3 k€ de commissions
par heure, plus les pénalités du SLA à 99,9 % (≈ 43 min d'arrêt toléré par mois ; chaque tranche
de 0,1 % manquée coûte 5 % des abonnements, ≈ 3,6 k€) et la perte de confiance des commerçants.
Au total, ≈ 16 k€ pour 1 h d'arrêt et ≈ 103 k€ pour 4 h en soirée ([01-bia.md](01-bia.md)) ; en
pointe, un arrêt complet devient probablement un incident majeur DORA, à notifier à l'ACPR, dès
≈ 50 min ([04-nis2-dora.md](04-nis2-dora.md) § 4.1). C'est pourquoi la chaîne du paiement (VM1) a reçu
l'essentiel de l'effort :

| Ordre | Valeur métier | Ce qui a été fait | Statut |
|---|---|---|---|
| 1 | VM1 Encaisser un paiement | Redondance à chaque étage (3 hyperviseurs, Swarm, adresse virtuelle, frontal × 3, base répliquée), détection ML, remédiation automatique, sonde de transaction | **Démontré** |
| 2 | VM4 Superviser et rétablir | Supervision complète, chaîne d'alerte surveillée de l'extérieur (Watchdog), passerelle de remédiation | **Démontré** (les composants de pilotage peuvent tomber sans couper le paiement : 0 s mesuré) |
| 3 | VM3 Conserver l'historique | Base répliquée en synchrone, `pg_dump` toutes les 15 min, PBS hors du lab | **Démontré** pour les pannes (0 paiement perdu) ; **partiellement** pour un sinistre (RPO 15 min à 24 h) |
| 4 | VM2 Authentifier | SSO + TOTP pour les administrateurs, freinage anti force brute, bannissement au WAF, reconnaissance faciale des opérateurs | **Partiellement démontré** (auth à 1 réplica : 21,9 s de panne au plantage ; biométrie contournable par une photo, non testé) |
| 5 | VM5 Protéger les données personnelles | Aucune image conservée (gabarits seulement), secrets dans Vault, segmentation | **Partiellement démontré** ; analyse d'impact (AIPD) non réalisée |

### 1.2 Disponibilité ou confidentialité

Le sujet juge la reprise sans opérateur. Nous avons donc donné la priorité à la **disponibilité
et à l'intégrité des transactions**. Ce choix a deux conséquences que la direction doit
connaître :

- **Les actions automatiques sont courtes et réversibles** (redémarrer, revenir à la version
  précédente, ajuster le nombre de réplicas, bannir une IP pour 15 min). Elles rétablissent le
  service, elles ne garantissent pas qu'un attaquant a été chassé.
- **La confidentialité repose sur la prévention** (WAF, segmentation en VLAN, secrets dans
  Vault, droits réduits du moteur), pas sur une réponse automatique. L'isolement automatique
  d'un service compromis n'existe pas. Restaurer la base, faire tourner les secrets ou
  reconstruire depuis Git sont des **décisions humaines**, documentées
  (`pca-pra-technique.md` § 5).

Nous recommandons de garder ce partage en production : automatiser ce qui est réversible,
confier à un humain ce qui détruit ou expose des données.

### 1.3 Arbitrer sous contrainte de quatre jours

Avec quatre jours et une équipe pluridisciplinaire, trois règles ont guidé les arbitrages :

1. **Ce qui peut être mesuré passe avant ce qui peut être décrit.** Chaque mécanisme de reprise
   a un test scripté (`infra/chaos/chaos.sh`) et une mesure côté client (sonde de transaction).
2. **Retirer un point unique de défaillance du paiement passe avant l'ajout de fonctions.** Le
   frontal à 3 réplicas (11 s → 0 s) et la base répliquée (92 s → 0 s) ont été faits avant
   l'isolement automatique ou le second WAF.
3. **Ne pas changer ce qui est risqué à J-2.** Exemple : les VLAN dédiés à la supervision et à
   l'identité ont été refusés (adresses, certificats et URL du SSO à changer). La migration de la
   base vers la réplication, elle, a été faite et a provoqué un incident réel d'environ 10 min
   (historique absent, rétabli par restauration depuis une copie ; `application.md`). C'est
   l'argument le plus concret pour un processus de changement formel en production (§ 5).

## 2. Registre des arbitrages

Sources : `architecture.md` (décisions D1 à D10), `dossier/infra.md` § 2 et § 6,
`tests-resilience.md`.

| # | Décision | Alternatives écartées | Critère de choix | Coût / bénéfice | Risque accepté |
|---|---|---|---|---|---|
| A1 | 3 hyperviseurs Proxmox + Ceph, HA sur toutes les machines | Un PC hôte sous Docker Desktop (prévu par le sujet) | Pouvoir démontrer la perte d'une machine ou d'un hyperviseur | Exploitation plus lourde, compensée par l'automatisation complète / perte d'un hyperviseur sans arrêt du paiement (mesuré) | Les 3 nœuds sont sur un même hôte parent : sa perte est une perte de site |
| A2 | Docker Swarm, fichiers Compose | Kubernetes (k3s) ; Compose seul | Compétences de l'équipe en 4 jours ; consigne Compose respectée | Moins d'écosystème / relance, replanification, secrets, retour arrière disponibles tout de suite | Orchestrateur moins répandu : recrutement et outillage plus difficiles à long terme |
| A3 | Passerelle de remédiation à liste fermée (5 actions, quotas) | Donner le socket Docker au moteur | Un moteur compromis ne doit pas devenir root sur le cluster | Développement de la passerelle / 11 cas de test conformes, injections refusées | Quota de 60 s par service : une seconde panne rapprochée a pris 72,5 s (bug corrigé depuis, limite gardée) |
| A4 | Terraform et Ansible hors de la boucle automatique | Remédiation par playbook | Actions courtes et réversibles seulement | Pas de reconstruction automatique / pas de destruction de VM par erreur d'automate | Les sinistres (machine perdue, site perdu) demandent un humain |
| A5 | WAF unique en DMZ (ModSecurity + OWASP CRS) | Deux WAF, protection DDoS en amont | Temps ; WAF fourni par l'équipe cyber | Seul point d'entrée public, injections bloquées / zéro accès sans filtrage | Perte du WAF = plus d'accès public jusqu'à sa relance par la HA (non mesuré) ; aucune protection volumétrique |
| A6 | Vault à un nœud, descellé à la main | Vault Raft 3 nœuds, auto-unseal (KMS, HSM) | Exigence du sujet couverte vite ; pas de KMS dans le lab | Secrets centralisés et audités / un geste humain après chaque redémarrage | Sans descellement, ni déploiement ni changement d'infrastructure (le paiement continue) |
| A7 | Base répliquée (Patroni + etcd, synchrone) | Base unique épinglée sur un worker | Le worker de la base était le pire point unique mesuré | Complexité (etcd, migration) et un incident de migration / **92 s → 0 s**, 0 écriture validée perdue | Pas de fencing matériel ; etcd sans TLS sur réseau interne chiffré ; perte de 2 nœuds sur 3 = écritures bloquées |
| A8 | `auth` et `payment-api` à 1 réplica | Plusieurs réplicas | L'état anti force brute d'auth est en mémoire : le dupliquer le casserait | Pas de développement / l'anti force brute reste cohérent | 17,4 s (API) et 21,9 s (auth) de panne au plantage |
| A9 | Bannissement automatique par IP au WAF (15 min, 20 IP au plus, liste blanche) | Pas de blocage ; limitation de débit ; réputation d'IP | Le redémarrage ne bloque pas la source | Quelques heures de travail / force brute bannie en **27 s** | NAT partagé (entreprise, opérateur mobile) banni pour tous ; attaque distribuée sous les seuils non arrêtée |
| A10 | Reconnaissance faciale des opérateurs sans détection du vivant | Clé FIDO2 ; détection du vivant certifiée | Consigne additionnelle du sujet ; modèles légers sur CPU | Aucune image conservée / un facteur de plus avant le mot de passe | Une photo ou une vidéo de l'opérateur peut suffire (non testé) ; donnée biométrique (RGPD art. 9) sans AIPD |
| A11 | Assistant IA en lecture seule (comptes de supervision limités aux requêtes) | Assistant qui agit (redémarrer, bannir) | Une injection de consignes via les journaux ne doit produire qu'une mauvaise réponse | Utilité limitée au conseil / aucun effet possible sur la production | Réponses lentes (20 à 80 s) ; en secours CPU, le petit modèle peut présenter la doc comme un fait |
| A12 | Modèle 27B sur le GPU d'un membre de l'équipe, par tunnel (dérogation validée par le coach) | 3B sur CPU seulement | Qualité des réponses et appel d'outils | Pas d'achat de GPU / réponses exploitables | Données de supervision traitées sur un poste non maîtrisé ; disponibilité liée à ce poste (secours CPU automatique) |
| A13 | Démarrage à froid automatique, sauf descellement de Vault | Clés de descellement sur une machine du lab | Ne pas stocker la clé à côté du coffre | Sécurité des secrets / ≈ 5 min de démarrage, un geste humain | Dépendance à une personne disposant des clés (Vaultwarden) |
| A14 | Un seul site, PBS externe, `pg_dump` toutes les 15 min | Second site, réplication distante | Hors de portée du lab | Coût nul / sinistre couvert par reconstruction | Perte de site : reconstruction depuis Git et sauvegardes, durée **non mesurée**, au-delà de la DMIA de 4 h ; RPO jusqu'à 24 h pour les machines, 15 min pour la base (cible 5 min), 24 h pour la base si le poste de contrôle qui porte les dumps est perdu (Rec6) |

## 3. Indicateurs vérifiables pour piloter la résilience

Un indicateur n'est retenu que s'il est **produit par l'outillage existant** : sonde de
transaction (un vrai paiement toutes les 30 s, vérification légère toutes les 5 s), `chaos.sh`
(`/root/chaos/resultats.tsv`), Loki, VictoriaMetrics et Grafana. Les cibles sont celles que nous
proposons à la direction pour la production.

### 3.1 Indicateurs de performance (KPI)

| Indicateur | Définition | Mesuré sur le démonstrateur | Cible proposée | Source |
|---|---|---|---|---|
| MTTD applicatif | Panne ou anomalie → première alerte | 2 à 4 s (détecteur ML) | < 10 s | Métriques `detector_*`, Grafana « Démo / Remédiation » |
| MTTR panne courante | Durée pendant laquelle un client ne peut pas payer | 0 à 21,9 s selon le service ; 10 s pour une API arrêtée | < 1 min (RTO cible du BIA ; DMIA de l'encaissement : 15 min) | Sonde de transaction, `resultats.tsv` |
| Taux de reprise sans humain | Pannes réparées sans geste humain / pannes injectées | 14 / 14 (hors restauration) | 100 % sur les scénarios couverts | `chaos.sh` |
| Tests de chaos réussis dans la cible | Tests `OK` avec MTTR < 1 min / tests joués | 12 / 14 (72,5 s : limite de la passerelle et bug du moteur, corrigé ; 91,9 s : base unique, ramené à 0 s par la base répliquée) | ≥ 95 %, chaque mois | `resultats.tsv`, annotations Grafana `chaos` |
| Disponibilité mensuelle | Temps où la sonde paie / temps total | Non mesurable (lab éteint la nuit) | ≥ 99,9 % (SLA) ; budget d'erreur 43 min | Sonde, VictoriaMetrics |
| RPO panne | Paiements perdus lors d'une panne | 0 (116 → 117 ; 0 sur 2 979 écritures en bascule) | 0 | Comptage en base avant / après |
| RPO base restaurée | Âge du dernier dump utilisable | 15 min au plus | ≤ 5 min (cible du BIA), copie hors site incluse : **écart** (hors site : 24 h), voir Rec6 | Timer `paiement-db-backup` |
| RTO restauration machine | Restauration PBS → service vérifié | ≈ 1 min (40 s + vérification) | < 15 min | Test `restore` |
| Délai de bannissement | Première tentative → IP bannie | 27 s (force brute) | < 30 s | Loki (`waf-ban`), Alertmanager |
| Couverture des journaux | Machines qui envoient à Loki / machines du périmètre | 17 / 17, hyperviseurs et WAF compris | 100 %, alerte si une source se tait | Loki, Alloy |
| Qualité de détection | Précision / rappel du détecteur | 0,81 / 0,92 (F1 0,86) | Précision ≥ 0,9 sans perte de rappel | Jeu d'évaluation de l'équipe applicative |

### 3.2 Indicateurs de risque (KRI)

| Indicateur | Pourquoi il compte | Valeur au 22/10 | Seuil d'alerte | Source |
|---|---|---|---|---|
| Points uniques de défaillance sur le chemin du paiement | Chacun est une panne totale possible | 5 : site, WAF, Stripe (bascule vers PayPal non automatique), `auth`, `payment-api` | > 0 sans plan daté | Revue d'architecture |
| Âge de la dernière restauration testée | Une sauvegarde non testée ne vaut rien | Machine : 21/10 ; base : 21/10 | > 30 jours | `restore`, `paiement-db-restore-test` |
| Âge de la sauvegarde restaurée | Mesure réelle du RPO machine | 22 h 31 min | > 24 h | Test `restore` |
| Actions humaines au démarrage | Chaque geste humain retarde la reprise | 1 (`vault-unseal`) | > 0 après auto-unseal | `deploiement.md` |
| Watchdog absent | La chaîne d'alerte elle-même est morte | Jamais déclenché en test | Toute absence > 5 min | healthchecks.io (hors lab) |
| Écart `/api/health` / sonde | Une supervision qui ne voit pas la panne | `kill-auth` : 0 s contre 21,9 s | Tout écart > 5 s | `resultats.tsv` |
| Remédiations répétées sur un même service | Un problème de fond masqué par les redémarrages | Quota de 10 actions / 10 min | > 3 par jour | Loki `{identifier="remediate"}` |
| Débannissements manuels | Clients légitimes bloqués (NAT partagé) | 0 | > 1 par semaine | `waf-ban list`, Loki |
| Secrets non renouvelés | Exposition d'un secret ancien | 7 jamais renouvelés (token root, clés de descellement, clé du moteur, UniFi, webhook Discord, healthchecks.io, S3) ; le reste renouvelé le 20/10 | > 90 jours ; token root ≠ 0 | `comptes-et-rotation.md`, audit Vault |

**Recommandation de pilotage** : un tableau de bord trimestriel au comité des risques, avec ces
indicateurs, tiré des mêmes sources que le dashboard « Démo / Remédiation ». Aucun chiffre
déclaratif : chaque valeur doit pointer vers une ligne de `resultats.tsv`, une requête Loki ou
une série de VictoriaMetrics.

## 4. Recommandations priorisées

Coûts **fictifs**, en jours-homme (j-h, ≈ 700 € chargés) et en euros ; ordres de grandeur à
confirmer par devis. Les recommandations sont numérotées **Rec1 à Rec18** pour ne pas les
confondre avec les risques **R1 à R10** de l'analyse EBIOS RM ([02-ebios-rm.md](02-ebios-rm.md)
§ 5.1), cités entre parenthèses dans la colonne « Risque réduit » avec la priorité P0–P3 du
PACS (02 § 5.5) quand elle existe.

### 4.1 Court terme (0 à 3 mois) : retirer les points uniques et les dettes connues

| # | Recommandation | Risque réduit | Coût estimé |
|---|---|---|---|
| Rec1 | Révoquer le token root de Vault, détruire `init.json`, sortir la clé de la CA racine du poste de contrôle (CA racine hors ligne, intermédiaire dans Vault) | Compromission du poste de contrôle = contrôle total (R9 ; PACS P0) | 2 j-h |
| Rec2 | Point de santé complet (échoue si la base ou `auth` manque), état anti force brute partagé (Redis répliqué), 2 réplicas ou plus pour `auth` et `payment-api` | 17,4 s et 21,9 s de panne au plantage ; pannes invisibles pour la supervision (R1, R2 ; P1) | 10 à 15 j-h |
| Rec3 | Vault en cluster Raft à 3 nœuds avec auto-unseal (KMS d'un fournisseur ou HSM) | Geste humain au démarrage ; Vault point unique (R9 ; P2) | 5 j-h + KMS ≈ 50 €/mois, ou HSM 15 à 30 k€ |
| Rec4 | Second WAF derrière le proxy TLS, limitation de débit, protection DDoS en amont (service d'un opérateur ou d'un CDN) | Perte d'accès public ; attaque volumétrique ; attaque distribuée sous les seuils de bannissement (R1 ; P1) | 5 j-h + 1 à 3 k€/mois |
| Rec5 | Back-office : remplacer la reconnaissance faciale par des clés FIDO2 (ou exiger une détection du vivant certifiée, plus coûteuse) ; AIPD si la biométrie est gardée | Usurpation d'un opérateur par photo ; donnée biométrique sensible (R5, ER6 ; P1–P2) | ≈ 1 k€ de clés (20 opérateurs) + 5 j-h |
| Rec6 | **Dès maintenant : copier chaque `pg_dump` hors du lab à chaque exécution** (toutes les 15 min, vers un stockage externe chiffré, avec alerte en cas d'échec) ; puis archivage continu des journaux de transactions de PostgreSQL (WAL) avec restauration à un instant donné (PITR), copié hors site ; seconde copie immuable des sauvegardes PBS ; restauration testée chaque mois | RPO « rançongiciel » aujourd'hui de **24 h** (les dumps restent sur le poste de contrôle et ne sortent du lab que par le job PBS de 21h00) → 15 min avec la copie à chaque exécution → < 5 min avec le WAL (cible du BIA) ; perte du serveur de sauvegarde (R7, ER3 ; P1) | 5 j-h + ≈ 100 €/mois |
| Rec7 | Exercice de crise trimestriel (rejouer `chaos.sh` et une simulation d'incident majeur avec DG, RSSI, conformité, communication) | Décisions humaines lentes ou mal coordonnées ; délais de notification (un arrêt complet de ≈ 50 min en pointe est déjà probablement majeur au sens de DORA) | 3 j-h par exercice |
| Rec8 | Supprimer le moteur de paiement de démonstration (`ownEngine.ts`) : seul Stripe Elements ou PayPal reçoit le numéro de carte | Numéro de carte transitant par nos services, donc tout le SI dans le périmètre PCI DSS (constat de 02 § 1.4 ; ER4 ; P1) | 2 j-h |

### 4.2 Moyen terme (3 à 12 mois) : couvrir le sinistre et la compromission

| # | Recommandation | Risque réduit | Coût estimé |
|---|---|---|---|
| Rec9 | **Second site** (centre de données distinct ou cloud) : réplication de la base en standby distant, synchronisation PBS, reconstruction par Terraform/Ansible testée de bout en bout, PRA chronométré | Perte du site (aujourd'hui non couverte, durée de reconstruction non mesurée) (R7, ER2 ; P3) | 100 à 150 k€ d'investissement + 2 à 4 k€/mois |
| Rec10 | Supervision redondante (VictoriaMetrics et Loki en cluster, Alertmanager à plusieurs instances) ; une sonde hors du Swarm | Le moteur dépend d'une seule instance d'Alertmanager ; la sonde peut disparaître avec ce qu'elle mesure (ER8 ; P3) | 15 j-h |
| Rec11 | Réponse à la compromission : isolement réseau automatique d'un service (réversible), rotation des secrets scriptée, playbooks de réponse | Aujourd'hui la réponse automatique ne traite que la disponibilité (R4, R6, R9 ; P2) | 15 à 20 j-h |
| Rec12 | Chaîne d'approvisionnement : protection des branches et revue à deux en premier (PACS P1), puis signature et vérification des images, inventaire des composants (SBOM), analyse de vulnérabilités, registre répliqué et sauvegardé, miroir du code hors GitHub | Image piégée ; registre non sauvegardé ; dépendance à GitHub pour reconstruire (R8 ; P1–P2) | 10 j-h + ≈ 200 €/mois |
| Rec13 | Registre des prestataires TIC et stratégie de sortie (Stripe, PayPal, GitHub, S3, Discord, healthchecks.io, Let's Encrypt, FAI) ; bascule automatique Stripe → PayPal ; outil d'astreinte professionnel à la place de Discord | Panne d'un prestataire = arrêt ; alertes sur un service grand public (ER1 ; DORA art. 28) | 10 j-h conformité + 15 j-h dev |
| Rec14 | Programme de formation : opérateurs (procédures, crise), développeurs (sécurité applicative), tous (hameçonnage) ; postes d'administration dédiés | Le scénario red team part d'un PC d'administrateur compromis (R3 ; P2) | ≈ 15 k€ par an |

### 4.3 Long terme (au-delà de 12 mois)

| # | Recommandation | Risque réduit | Coût estimé |
|---|---|---|---|
| Rec15 | Tests d'intrusion annuels ; TLPT si l'autorité le requiert (DORA, art. 26, à vérifier selon la désignation de l'entité) | Failles non vues par une équipe interne (tous ; P3) | 30 à 80 k€ par campagne |
| Rec16 | Surveillance 24/7 (SOC interne ou prestataire de détection et réponse) | Attaque hors heures ouvrées ; dépendance aux alertes Discord (R3, R4) | 60 à 120 k€ par an |
| Rec17 | Réévaluer l'orchestrateur (Kubernetes managé) quand l'équipe le maîtrise | Écosystème et recrutement liés à Swarm | Projet de migration, 40 à 60 j-h |
| Rec18 | Démarche de certification (ISO 22301 continuité, ISO 27001 sécurité) | Preuve externe de maturité pour les commerçants et le régulateur | 40 à 80 k€ (accompagnement + audit) |

**Mise en perspective** ([01-bia.md](01-bia.md)) : un arrêt coûte ≈ 16 k€ à 1 h, ≈ 103 k€ à
4 h, ≈ 463 k€ à 24 h et ≈ 1,3 M€ à 72 h (G4, retrait d'agrément possible). Le court terme (Rec1 à
Rec8) coûte de l'ordre de 45 à 75 k€ la première année (hors HSM), soit moins qu'un seul arrêt
de 4 h. Le second site (Rec9) est l'investissement le plus élevé, mais c'est le seul qui traite la perte de
site, dont la reconstruction se compte en jours (G4).

## 5. Ce que nous ferions différemment dans un contexte industriel

| Domaine | Dans le démonstrateur (4 jours) | En production |
|---|---|---|
| Socle | 3 hyperviseurs virtuels sur un même hôte parent, lab éteint la nuit | Matériel physique sur deux sites, fonctionnement 24/7, double alimentation et double réseau (deux liens corosync) |
| Réseau | Supervision et identité sur le VLAN des hyperviseurs | VLAN dédiés à la supervision, à l'identité et au stockage |
| Changements | Modifications directes depuis le poste de contrôle, tests de chaos sur le seul environnement | Environnement de préproduction, chaîne CI/CD avec validation à quatre yeux, fenêtres de changement ; chaos en préproduction puis en production encadrée |
| Données de paiement | Stripe et PayPal en mode test, aucune donnée réelle | Périmètre PCI DSS à établir, tokenisation chez le prestataire, conservation et chiffrement des données encadrés |
| Secrets | Vault à un nœud, token root et clés de descellement sur le poste de contrôle | Vault en cluster, auto-unseal sur HSM, secrets dynamiques à durée courte, token root révoqué |
| Identités | Comptes créés par l'équipe, SSO + TOTP | Fédération avec l'annuaire RH (arrivées, mobilités, départs), FIDO2 pour les accès privilégiés, revue trimestrielle des droits |
| Alertes et astreinte | Discord, une équipe présente en journée | Outil d'astreinte avec escalade, rotation documentée, astreinte 24/7 |
| Mesure | RTO mesurés par tests ponctuels sur deux jours | SLO mesurés en continu sur le mois, budget d'erreur suivi en comité |
| Journaux | Loki sur une instance, rétention courte | Journaux centralisés redondants, intégrité garantie (stockage non réécrivable), rétention alignée sur les obligations réglementaires |
| IA | Assistant en lecture seule, modèle sur le GPU d'un membre, agent IA de développement avec accès administrateur au lab | GPU interne, aucune donnée de supervision hors des machines maîtrisées ; aucun agent IA avec des droits d'administration en production |
| Gouvernance | Rôles de l'entreprise fictive, décisions prises en équipe projet | Fonction de contrôle du risque TIC indépendante, comité des risques, registre des incidents et des prestataires tenu à jour |

## 6. Décisions demandées à la direction

| # | Décision | Coût estimé (fictif) | Bénéfice | Échéance |
|---|---|---|---|---|
| D1 | Lancer le **second site** (Rec9) et fixer les objectifs de reprise de site : RTO 4 h et RPO 15 min (DMIA et PDMA du BIA pour un sinistre de site), 5 min visés avec le WAL (Rec6) | 100 à 150 k€ + 2 à 4 k€/mois | Couvre le seul scénario G4 non traité aujourd'hui (perte de site) ; un seul jour d'arrêt coûte ≈ 463 k€, trois jours ≈ 1,3 M€ | Décision au prochain comité ; site opérationnel et PRA testé sous 9 mois |
| D2 | Financer le **programme « zéro point unique »** (Rec1 à Rec4, Rec6, Rec8), en commençant par la copie des dumps hors du lab à chaque exécution | 35 à 60 k€ la première année | Plus aucun point unique sur le chemin du paiement ; démarrage à froid sans geste humain | 3 mois |
| D3 | **Remplacer la reconnaissance faciale par FIDO2** pour le back-office, et suspendre l'enrôlement biométrique d'ici là (ou commander une AIPD si la biométrie est maintenue) | ≈ 5 k€ | Supprime un contournement par photo et une donnée sensible au sens du RGPD | 1 mois |
| D4 | **Adopter les indicateurs du § 3** et leurs cibles comme référentiel de pilotage, avec un rapport trimestriel au comité des risques | Moins de 5 j-h par trimestre | Décisions fondées sur des mesures, pas sur des déclarations ; preuves prêtes pour l'ACPR | Premier rapport sous 3 mois |
| D5 | Engager le **programme d'exercices, de formation et de gestion des prestataires** (Rec7, Rec13, Rec14) | ≈ 40 k€ la première année, ≈ 25 k€ par an ensuite | Décisions humaines plus rapides en crise ; stratégie de sortie pour chaque prestataire critique | 6 mois |

**Ce que nous ne recommandons pas** : automatiser les actions destructrices (restauration de la
base, reconstruction de machines) ou donner à l'assistant IA des droits d'action. Le gain de
quelques minutes ne compense pas le risque d'une erreur d'automate sur les données de paiement.
