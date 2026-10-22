# Gouvernance : risques, continuité et conformité

Organisation fictive : **Resilience Pay SAS**, établissement de paiement agréé par l'ACPR,
85 salariés, 2 400 e-commerçants, 25 000 transactions par jour (3 000 par heure en pointe,
18h–22h), 1 € de commission par transaction, SLA de 99,9 %. Les chiffres techniques sont
**mesurés** sur le démonstrateur (20–21/10/2026). Documents complets : dossier `gouvernance/`
du dépôt (`00-cadre.md` à `05-arbitrages-recommandations.md`).

## 1. Services critiques et coût de l'arrêt

Services vitaux : **encaissement** (frontal, `payment-api`, base), **authentification des
payeurs** (`auth`) et **écriture de l'historique**. Détection, remédiation, supervision et Vault
sont critiques pour la **reprise**, pas pour l'exécution : leur perte n'a coupé aucun paiement
(0 s mesuré). Détail : `01-bia.md` § 1.

| Durée d'arrêt complet (pointe) | Commissions perdues (brut) | Ventes des commerçants bloquées | Pénalités SLA | Coût total (avec crise, attrition, réglementaire) | Gravité |
|---|---|---|---|---|---|
| 15 s (panne réparée seule, mesuré) | 13 € | 650 € | 0 € | ≈ 0 € | G1 |
| 5 min | 250 € | 13 000 € | 0 € | ≈ 0,6 k€ | G2 |
| 1 h | 3 000 € | 156 000 € | 3 600 € | ≈ 16 k€ | G2 par le coût, **G3 au titre de DORA** |
| 4 h | 12 000 € | 624 000 € | 18 000 € | ≈ 103 k€ | G3 |
| 24 h (journée normale) | 25 000 € | 1,3 M€ | 72 000 € (plafond) | ≈ 463 k€ | G3, limite G4 |
| 72 h | 75 000 € | 3,9 M€ | 72 000 € | ≈ 1,3 M€ | G4 (agrément) |

La commission perdue pèse peu ; le coût vient des pénalités dès **43 min** d'arrêt dans le mois,
puis de l'attrition des commerçants et du réglementaire. **Le seuil réglementaire arrive avant
le seuil financier** : en pointe, un arrêt complet atteint en **≈ 50 min** le seuil d'incident
majeur DORA (10 % des transactions quotidiennes, soit 2 500), hors pointe vers 2 à 4 h.

## 2. Analyse de risques (EBIOS Risk Manager)

Cinq ateliers sur l'architecture déployée : 8 événements redoutés, 4 sources de risque retenues
(cybercriminel, hacktiviste, opportuniste, initié ou administrateur compromis), 10 scénarios
opérationnels. Échelle : gravité G1–G4 × vraisemblance V1–V4. Détail : `02-ebios-rm.md`.

| Risque | Initial (lundi) | Mesures prouvées | Actuel (jeudi) | Cible (PACS) |
|---|---|---|---|---|
| R1 Déni de service | Critique | Rafale : 0 s de panne ; frontal × 3 ; source unique bannie | Élevé | Faible |
| R2 Bourrage d'identifiants | Critique | argon2id, freinage, IP bannie en 27 s | Moyen | Faible |
| R3 PC administrateur compromis | Critique | VLAN, nftables `drop`, SSO + TOTP, passage obligé par le WAF | Élevé | Moyen |
| R4 Injection SQL / XSS | Critique | CRS en blocage (403), requêtes paramétrées | Moyen | Moyen |
| R5 Usurpation d'un opérateur | Critique | Visage + mot de passe (sans détection du vivant) | Élevé | Moyen |
| R6 Abus du moteur de remédiation | Élevé | Passerelle à liste fermée, 11 cas sur 11 conformes | Faible | Faible |
| R7 Rançongiciel | Critique | PBS externe, restaurations testées (40 s, 0,7 s), IaC | Élevé | Moyen |
| R8 Chaîne d'approvisionnement | Élevé | Build depuis un commit figé, tags immuables | Élevé | Moyen |
| R9 Vol de secrets | Critique | Vault, AppRole limité, audit, rotation du 20/10 | Élevé | Moyen |
| R10 Assistant IA manipulé | Moyen | Lecture seule, aucune action | Faible | Faible |

Les 7 risques critiques de départ sont ramenés à « élevé » ou moins, surtout par une baisse de
la vraisemblance (filtrage, segmentation, bannissement, secrets dans Vault). Les cinq risques
encore élevés en gravité G4 (R3, R5, R7, R8, R9) supposent un compte privilégié ou la chaîne de
production compromis : la reprise automatique n'y sert à rien, puisqu'elle relance ce que
l'attaquant contrôle. Aucun risque G4 n'est accepté durablement ; les acceptations temporaires
(3 mois) relèvent de la direction générale.

## 3. Objectifs de continuité et de reprise

DMIA de l'encaissement : **15 min** par incident ; PDMA : **0** pour un paiement confirmé,
**15 min** en sinistre logique. Les RTO cibles sont pris en dessous pour garder une marge.
Détail : `01-bia.md` § 3.

| Scénario | RTO cible | RTO mesuré (sonde) | RPO cible | RPO mesuré | Écart |
|---|---|---|---|---|---|
| Service applicatif arrêté ou planté | 1 min | 10 à 22 s, 0 intervention | 0 | 0 | Atteint |
| Base tuée / perte de la VM du primaire | 1 min | 7,5 s / 92 s → **0 s** (Patroni) | 0 | 0 paiement perdu | Atteint |
| Perte d'un hyperviseur | 5 min | Aucun échec relevé | 0 | 0 | Partiel (HA non chronométrée) |
| Force brute | 1 min | 0 s ; IP bannie en 27 s | — | — | Atteint (source unique) |
| Corruption de la base (décision humaine) | 30 min | 0,7 s de restauration + décision | 5 min | 15 min ; **24 h hors du lab** | Dépassé |
| Machine corrompue (PBS) | 1 h | ≈ 1 min | 24 h | 22 h 31 min | Atteint de justesse |
| Vault scellé | 15 min | Manuel (paiement : 0 s) | 24 h | 24 h | Geste humain |
| Sinistre de site | 4 h | Non couvert | 15 min | 24 h | **Écart majeur** |

Sur 14 pannes injectées par `chaos.sh`, 14 sont réparées sans humain et 12 dans la cible de
1 min (72,5 s pour une panne rapprochée, cause corrigée ; 92 s avant la réplication de la base).

## 4. PCA / PRA

**Organisation** (`03-pca-pra.md` § 2). Quatre niveaux : I1 auto-résolu (l'astreinte constate),
I2 dégradé (astreinte N2), I3 grave (cellule de crise DSI + RSSI), I4 critique (cellule
présidée par la DG). **Dès que la DMIA de 15 min est dépassée, l'incident passe en I3 et la
conformité prépare la classification DORA.** Pendant une reprise automatique, l'astreinte
observe et ne corrige pas. Un RACI fixe un seul responsable par décision : DSI pour restaurer
la base, RSSI pour isoler et faire tourner les secrets, conformité pour classer, DG pour signer
les notifications.

**Scénarios couverts.** Démontrés : panne d'un service (S1), rafale (S2), force brute (S3), perte
de la base ou d'un worker (S4), Vault scellé (S11, avec geste humain). Partiels : perte d'un
hyperviseur (S5), rançongiciel (S8, restaurations unitaires seulement), perte d'un prestataire
(S9, bascule Stripe → PayPal manuelle). Décrits mais non exercés : compromission (S6), fuite
(S7), sinistre de site (S10).

**Choix de restauration.** On choisit l'option la plus légère qui rétablit un état **sûr** :
redémarrer (automatique, secondes) ; basculer (automatique, 0 à 3 s) ; restaurer une machine
(N2, ≈ 1 min, jusqu'à 24 h perdues) ; restaurer la base (décision du DSI, jusqu'à 15 min de
paiements à rapprocher avec Stripe) ; reconstruire depuis Git (cellule de crise, heures).
Terraform et Ansible restent hors de la boucle automatique : une reconstruction est une
décision. En cas de compromission, on restaure les **données** d'avant l'intrusion, on
reconstruit les **systèmes** depuis le code et on fait tourner tous les secrets.

**Risques qui subsistent après la reprise** (`03-pca-pra.md` § 7) : paiements perdus après le
dernier dump (15 min, **24 h si le poste de contrôle qui porte les dumps est chiffré**) ;
secrets possiblement exposés ; cause racine non traitée ; attaquant distribué non arrêté ;
redondance non revenue ; site unique ; journaux de sécurité sur le site attaqué ; gabarits
biométriques multipliés par la réplication et les sauvegardes ; organisation jamais exercée.

## 5. NIS2 et DORA

**Applicabilité** (`04-nis2-dora.md` § 1). DORA s'applique directement et en entier : un
établissement de paiement agréé est une entité financière (art. 2), non exemptée du régime
simplifié (art. 16) ; autorité : ACPR. NIS2 n'a qu'un effet indirect : les établissements de
paiement ne figurent pas à ses annexes, et DORA prime comme acte sectoriel. Elle reste utile
pour évaluer les prestataires et comme grille de lecture (art. 21).

| Domaine DORA | Preuve du démonstrateur | Statut |
|---|---|---|
| Protection (art. 9) | Segmentation testée, WAF seul point d'entrée, SSO + TOTP, secrets dans Vault | Démontré (technique) |
| Détection (art. 10) | Anomalie en 2 à 4 s, journaux de 17 machines, Watchdog externe | Démontré |
| Réponse et rétablissement (art. 11) | Reprise en 10 à 16 s sans humain ; compromission non traitée automatiquement | Démontré (disponibilité) / partiel |
| Sauvegardes (art. 12) | Restaurations testées ; un seul site, RPO hors site 24 h | Démontré / partiel |
| Tests (art. 24-25) | 14 tests scriptés, 14 pannes réparées sans humain | Démontré (programme technique) |
| Classification des incidents (art. 18) | Données disponibles (sonde, comptage en base, Loki) ; pas d'outil de classification | Partiel |
| Prestataires (art. 28-30) | Liste des prestataires ; PayPal sans bascule automatique | Partiel |
| Gouvernance, notification, registre, TLPT, formation (art. 5, 19, 26, 28(3), 13(6)) | Aucune : obligations de décision, de contrat et de durée | Non démontrable en 4 jours |

**Cas pratique** (`04-nis2-dora.md` § 4) : la rafale de la démonstration (0 s de panne, 0
transaction perdue) **n'est pas majeure** ; la même attaque sans parade pendant 3 h en pointe le
serait (9 000 transactions bloquées et plus de 2 h d'indisponibilité) ; le PC administrateur
compromis est majeur **dès qu'un accès malveillant réussit**, quelle que soit la durée. La
notification initiale à l'ACPR est due dans les 4 h suivant la classification.

## 6. Arbitrages et recommandations

Principaux arbitrages (`05-arbitrages-recommandations.md` § 2) : mesurer avant de décrire ;
retirer un point unique du paiement avant d'ajouter une fonction ; automatiser seulement les
actions courtes et réversibles (passerelle à liste fermée plutôt que socket Docker) ; garder
Vault descellé à la main plutôt que poser la clé à côté du coffre ; accepter un site unique,
faute de moyens dans un lab.

Cinq recommandations prioritaires (sur 18) :

1. **Copier chaque dump de la base hors du lab à chaque exécution**, puis archiver le journal
   PostgreSQL (WAL) hors site : RPO « rançongiciel » de 24 h → 15 min → moins de 5 min (Rec6).
2. **Révoquer le token root de Vault et sortir la clé de la CA du poste de contrôle**, puis Vault
   à 3 nœuds avec auto-unseal (Rec1, Rec3).
3. **Retirer les points uniques restants** : 2 réplicas pour `auth` et `payment-api`, second
   WAF et protection anti-DDoS en amont, bascule automatique Stripe → PayPal (Rec2, Rec4, Rec13).
4. **Remplacer la reconnaissance faciale par des clés FIDO2** pour le back-office (Rec5).
5. **Outiller et exercer la crise** : grille de classification DORA, notification à blanc en
   moins de 4 h, exercice trimestriel avec la direction (Rec7).

Le court terme coûte de l'ordre de 45 à 75 k€ la première année, moins qu'un seul arrêt de 4 h
(≈ 103 k€).

## 7. Décisions demandées à la direction

| # | Décision | Coût (fictif) | Échéance |
|---|---|---|---|
| D1 | Lancer un **second site** ; objectifs de reprise de site : RTO 4 h, RPO 15 min | 100 à 150 k€ + 2 à 4 k€/mois | PRA testé sous 9 mois |
| D2 | Financer le programme **« zéro point unique »**, en commençant par la copie des dumps hors du lab | 35 à 60 k€ la première année | 3 mois |
| D3 | **FIDO2** à la place de la biométrie, enrôlement suspendu d'ici là (ou AIPD) | ≈ 5 k€ | 1 mois |
| D4 | Adopter les **indicateurs mesurés** (MTTR vu par la sonde, délai de bannissement, âge de la dernière restauration testée…) avec un rapport trimestriel au comité des risques | < 5 j-h par trimestre | 3 mois |
| D5 | Programme d'**exercices, de formation et de gestion des prestataires** (registre DORA, stratégie de sortie) | ≈ 40 k€ la première année | 6 mois |

Nous ne recommandons pas d'automatiser les actions destructrices (restauration de la base,
reconstruction) ni de donner à l'assistant IA des droits d'action : quelques minutes gagnées ne
compensent pas le risque d'une erreur d'automate sur les données de paiement.
