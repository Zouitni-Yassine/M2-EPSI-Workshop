# 01 — Bilan d'impact sur l'activité (BIA)

Ce document chiffre ce que coûte à Resilience Pay l'arrêt de ses services, fixe les durées
d'interruption et les pertes de données admissibles, puis compare les objectifs qui en découlent
aux valeurs **mesurées** sur le démonstrateur. Les données d'entreprise sont fictives et viennent
de [00-cadre.md](00-cadre.md) (§ 1 à 4). Les mesures viennent de
[tests-resilience.md](../infra/docs/tests-resilience.md),
[pca-pra-technique.md](../infra/docs/pca-pra-technique.md) et
[dossier/infra.md](../infra/docs/dossier/infra.md). Toute hypothèse propre à ce document est
signalée « (hyp.) ».

## 1. Services critiques et dépendances

### 1.1 Services, valeurs métier, criticité

| Service | Valeurs métier | Biens supports (démonstrateur) | Criticité | Justification |
|---|---|---|---|---|
| **S1 Encaissement** (création et confirmation d'un paiement) | VM1 | Frontal (3 réplicas), `payment-api` (1 réplica), PostgreSQL Patroni (3 membres), adresse virtuelle, WAF, NPM | **Vitale** | Chaque minute d'arrêt est une perte de commissions et entame le budget SLA de 43 min par mois |
| **S2 Authentification des payeurs** | VM1, VM2 | `auth` (1 réplica, JWT, freinage anti force brute), base `auth` | **Vitale** | Pas de connexion, pas de paiement : la sonde de transaction le montre (`kill-auth` : 21,9 s de panne) |
| **S3 Historique des transactions** (preuve, rapprochement, litiges) | VM3 | Base `payments` répliquée, `pg_dump` toutes les 15 min, PBS | **Vitale en écriture, importante en lecture** | Un paiement confirmé puis perdu crée un litige et un défaut de traçabilité ; la consultation peut attendre |
| **S4 Back-office opérateurs** (connexion des opérateurs, reconnaissance faciale) | VM2, VM5 | `auth`, Keycloak (SSO + TOTP) pour l'administration | Importante | N'interrompt pas l'encaissement |
| **S5 Détection et remédiation** | VM4 | Détecteur ML, moteur de remédiation, passerelle `remediate`, Swarm, HA Proxmox | **Critique pour la reprise** | Sans eux le paiement fonctionne, mais une panne n'est plus réparée seule |
| **S6 Supervision et alerte** | VM4 | VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana (monitoring01), Alloy, sonde, healthchecks.io | Critique pour la reprise | Le moteur lit ses alertes dans Alertmanager ; les journaux servent de preuve |
| **S7 Secrets et identités d'exploitation** | VM5 | Vault (1 nœud), Vaultwarden, CA interne | Importante (critique en crise de sécurité) | L'application garde ses secrets si Vault est scellé ; sans Vault, ni déploiement ni rotation |
| **S8 Assistant opérateur** (RAG, bot Discord) | — | rag01, Ollama | Faible | Lecture seule, aucun rôle dans la reprise |

### 1.2 Dépendances

| Dépendance | Type | Services touchés | Effet si elle manque | Redondance actuelle |
|---|---|---|---|---|
| Socle Proxmox + Ceph (3 nœuds) | Technique interne | Tous | Perte d'un nœud : application disponible pendant la coupure (cadre § 6) | 3 nœuds, HA, Ceph répliqué |
| Hôte parent unique, site unique | Technique interne | Tous | Perte totale : aucun service | **Aucune** |
| Docker Swarm (3 managers, 3 workers), keepalived | Technique interne | S1, S2, S5 | Perte du leader : 0 s ; perte d'un worker : 3 s | Raft, adresse virtuelle |
| PostgreSQL (Patroni + etcd) | Technique interne | S1, S2, S3 | Perte de la VM du primaire : 0 s (92 s avant réplication) | 3 membres, réplication synchrone |
| WAF `waf01` | Technique interne | S1, S2 (accès public) | Plus d'accès public jusqu'à sa relance par la HA | **Instance unique** |
| Stripe (et PayPal) | Tiers critique | S1 | Plus d'autorisation de paiement | PayPal intégré, bascule **non automatique** |
| NPM, fournisseur d'accès Internet | Tiers / réseau de l'hébergeur | S1, S2 | Plus d'accès public | Hors périmètre (lien unique : à vérifier) |
| Let's Encrypt | Tiers | S1 (TLS public) | Aucun effet immédiat ; certificat valable 90 jours | Délai de plusieurs semaines |
| GitHub | Tiers | Reconstruction, déploiement | Plus de construction d'image ; le service en place continue | Images dans le registre privé |
| Stockage S3 (état Terraform) | Tiers | Reconstruction | Plus de changement d'infrastructure | — |
| Discord, healthchecks.io | Tiers | S6 (alerte des humains) | Les humains ne sont plus prévenus ; la réparation automatique continue | Deux canaux distincts |
| PBS externe | Tiers / hors lab | S3, restaurations | Plus de restauration de machine | **Copie unique** |

Constat clé (mesuré) : détecteur, moteur, supervision, manager leader et Vault peuvent tomber
**sans couper le paiement** (0 s de panne vue par la sonde). Ils conditionnent la **reprise**,
pas l'**exécution**. Le BIA les traite donc avec une DMIA plus longue, mais ils ne doivent pas
être absents au moment d'une autre panne.

## 2. Coût de l'arrêt de la fonction de paiement

### 2.1 Profil de charge et perte de commissions par heure

Données du cadre : 25 000 transactions par jour, 1,00 € de revenu par transaction, panier moyen
52 €, pointe à 3 000 transactions par heure entre 18h et 22h. Répartition horaire (hyp.),
construite pour retomber sur 25 000 par jour :

| Plage | Transactions par heure | Calcul de la journée | Commissions perdues par heure d'arrêt | Ventes des commerçants bloquées par heure |
|---|---|---|---|---|
| Nuit, heure creuse (0h–7h) | 200 (hyp.) | 7 × 200 = 1 400 | **200 €** | 200 × 52 = 10 400 € |
| Journée (7h–18h) | 800 (hyp.) | 11 × 800 = 8 800 | 800 € | 41 600 € |
| **Pointe (18h–22h)** | **3 000** (cadre) | 4 × 3 000 = 12 000 | **3 000 €** | **156 000 €** |
| Soirée (22h–24h) | 1 400 (hyp.) | 2 × 1 400 = 2 800 | 1 400 € | 72 800 € |
| Total journée normale | — | **25 000** | 25 000 € par jour | 1,3 M€ par jour |
| **Jour de soldes** | 3 000 de 10h à 22h (hyp.) | 36 000 + 6 600 hors pointe = **42 600** | 3 000 € par heure, **42 600 €** par jour | 2,2 M€ par jour |

La commission est une perte **brute** : une partie des payeurs réessaie plus tard. Taux de report
retenu (hyp.) : 90 % pour un arrêt de quelques secondes, 80 % à 5 min, 50 % à 1 h, 30 % à 4 h,
10 % au-delà de 24 h (le payeur achète ailleurs). Pour le commerçant, la vente non reportée est
perdue définitivement.

### 2.2 Pénalités SLA

- Budget : 99,9 % sur un mois de 30 jours = 43 200 min × 0,1 % = **43,2 min d'arrêt par mois**.
- Pénalité : 5 % de l'abonnement mensuel par tranche de 0,1 % manquée. Un arrêt de la
  plateforme touche les 2 400 commerçants : une tranche coûte 5 % × 72 000 € = **3 600 €**.
- Hypothèses de calcul (à préciser au contrat) : toute tranche **entamée** est due ; la
  pénalité est **plafonnée à 100 %** de l'abonnement, soit 72 000 € par mois ; aucun autre
  arrêt dans le mois.
- Formule : tranches = arrondi supérieur de (durée − 43,2) / 43,2.

| Arrêt dans le mois | Disponibilité | Tranches manquées | Pénalité |
|---|---|---|---|
| ≤ 43,2 min | ≥ 99,9 % | 0 | **0 €** : premier seuil à **43 min** d'arrêt cumulé |
| 1 h (60 min) | 99,86 % | (60 − 43,2) / 43,2 = 0,39 → 1 | **3 600 €** |
| 4 h (240 min) | 99,44 % | (240 − 43,2) / 43,2 = 4,56 → 5 | **18 000 €** |
| > 14,4 h (864 min) | < 98,0 % | 20 et plus | **72 000 €** (plafond) |
| 24 h et 72 h | 96,7 % / 90,0 % | 33 / 99 | 72 000 € (plafond ; 144 000 € si l'arrêt chevauche deux mois) |

Au regard du SLA, une panne réparée en 10 à 16 s (mesuré, `api-stop`) consomme 0,4 à 0,6 %
du budget mensuel : il faudrait 160 à 260 pannes de ce type dans le mois pour déclencher une
pénalité. Une seule panne de 92 s (base non répliquée, mesuré le 21/10) en consommait 3,5 %.

### 2.3 Coûts indirects (hypothèses)

| Poste | Hypothèse | Base de calcul |
|---|---|---|
| Gestion de crise | Cellule de crise de 8 personnes à 100 €/h chargé = 800 €/h, sur une durée double de l'arrêt (préparation, retour d'expérience) pour les arrêts courts, plafonnée à 36 h pour un arrêt de 24 h et à 96 h pour un arrêt de 72 h (la cellule ne siège pas en continu) ; communication externe : 5 k€ à 4 h, 20 k€ à 24 h, 50 k€ à 72 h | Rôles du cadre § 2 |
| Attrition des commerçants | Un commerçant rapporte 9 M€ / 2 400 = **3 750 € de commissions par an**. Départs (hyp.) : 0,1 % après 1 h, 0,5 % après 4 h, 3 % après 24 h, 10 % après 72 h | Perte de chiffre d'affaires sur 12 mois |
| Image | Non chiffrée à part : elle se traduit dans l'attrition et le coût d'acquisition des nouveaux commerçants | — |
| Réglementaire (ACPR) | Un établissement de paiement relève de DORA. Un arrêt complet de l'encaissement devient probablement un **incident majeur** (règlement délégué (UE) 2024/1772, art. 9 : service critique et deux seuils dépassés) : **dès ≈ 50 min en heure de pointe** (10 % des transactions quotidiennes, soit 2 500, et 10 % des clients touchés), **vers 2 à 4 h hors pointe** (seuil de durée de 2 h, puis seuil économique de 100 k€ vers 4 h). Calcul dans [04-nis2-dora.md](04-nis2-dora.md) § 4.1. Conséquences : notification initiale, intermédiaire et finale à l'ACPR (délais de l'ordre de 4 h / 24 h, 72 h et 1 mois, à vérifier), analyse des causes, audit, plan de remédiation suivi par le superviseur. Coût de traitement (hyp.) : 20 k€ à 4 h, 50 k€ à 24 h, 150 k€ à 72 h ; pour un incident majeur d'une heure en pointe, il est compté dans le coût de crise (non chiffré à part). **Sanction pécuniaire non chiffrée** ; un arrêt long et répété peut remettre en cause l'agrément (G4) | Détail dans [04-nis2-dora.md](04-nis2-dora.md) |

### 2.4 Coût total par durée d'arrêt

Arrêt complet de l'encaissement, survenant en heure de pointe (18h) pour les durées courtes,
journée normale pour 24 h et 72 h. Montants arrondis.

| Durée | Transactions bloquées | Commissions brutes / nettes du report | Ventes des commerçants bloquées | Pénalités SLA | Crise | Attrition (CA perdu sur 12 mois) | Réglementaire | **Total** | **Gravité** |
|---|---|---|---|---|---|---|---|---|---|
| 15 s (mesuré, panne réparée seule) | 3 000 × 15 / 3 600 ≈ 13 | 13 € / 1 € | 650 € | 0 € | 0 € | 0 € | — | **≈ 0 €** | **G1** |
| 5 min | 250 | 250 € / 50 € | 13 000 € | 0 € | 500 € (forfait astreinte) | 0 € | — | **≈ 0,6 k€** | **G2** (commerçants touchés ; coût < 5 k€) |
| 1 h | 3 000 | 3 000 € / 1 500 € | 156 000 € | 3 600 € | 1 600 € | 2,4 × 3 750 = 9 000 € | **Incident majeur probable en pointe** (seuil de 2 500 transactions atteint vers 50 min) : notification ACPR, coût de traitement compris dans la crise | **≈ 16 k€** | **G2 par le coût ; G3 au titre de DORA** en pointe (G2 hors pointe) |
| 4 h (18h–22h) | 12 000 | 12 000 € / 8 400 € | 624 000 € | 18 000 € | 6 400 + 5 000 = 11 400 € | 12 × 3 750 = 45 000 € | 20 000 € | **≈ 103 k€** | **G3** |
| 24 h | 25 000 | 25 000 € / 22 500 € | 1,3 M€ | 72 000 € | 28 800 + 20 000 = 48 800 € | 72 × 3 750 = 270 000 € | 50 000 € | **≈ 463 k€** | **G3, limite G4** |
| 72 h | 75 000 | 75 000 € / 67 500 € | 3,9 M€ | 72 000 € | 76 800 + 50 000 = 126 800 € | 240 × 3 750 = 900 000 € | 150 000 € + sanction | **≈ 1,3 M€** | **G4** |

Un jour de soldes porte le volume à 42 600 transactions : les commissions perdues sur 24 h
passent de 25 000 € à 42 600 € (+70 %), et l'attrition serait plus forte (hyp.).

Lecture pour la direction :

- **La commission perdue pèse peu** (5 à 10 % du total au-delà d'une heure). Le coût vient des
  pénalités SLA dès la 44e minute, puis surtout de l'**attrition** et du **réglementaire**
  au-delà de quelques heures.
- **Trois seuils** structurent l'impact : **43 min** (pénalités SLA) ; l'**incident majeur
  DORA probable**, atteint dès **≈ 50 min en heure de pointe** (2 500 transactions bloquées)
  et vers **2 à 4 h hors pointe** (seuil de durée de 2 h, puis 100 k€ de coûts vers 4 h,
  passage en G3) ; **24 h** (G4, agrément).
- **Le seuil réglementaire arrive avant le seuil financier** : en pointe, un arrêt d'une heure
  coûte ≈ 16 k€ (G2) mais doit probablement être notifié à l'ACPR. D'où la règle du PCA/PRA :
  préparer la classification DORA dès que la DMIA de 15 min est dépassée
  ([03-pca-pra.md](03-pca-pra.md) § 2.1).
- Pour les commerçants, une heure de pointe arrêtée bloque **156 000 € de ventes**, 52 fois la
  perte de commissions de Resilience Pay : c'est l'argument commercial de la résilience.

## 3. DMIA, PDMA et objectifs RTO / RPO

### 3.1 DMIA et PDMA par service

DMIA : durée maximale d'interruption admissible, fixée par le métier à partir du § 2. PDMA :
perte de données maximale admissible.

| Service | DMIA | Justification | PDMA | Justification |
|---|---|---|---|---|
| S1 Encaissement | **15 min** par incident | Un tiers du budget SLA mensuel ; 750 € de commissions en pointe ; reste en G2 | **0** pour un paiement confirmé | Un paiement confirmé chez Stripe mais absent de l'historique = litige, rapprochement faux |
| S2 Authentification payeurs | 15 min | Même chaîne que S1 | 15 min pour les créations de compte | Un compte perdu se recrée ; un mot de passe changé se rechange |
| S3 Historique (écriture) | Comme S1 | L'écriture fait partie du paiement | **0** en panne ; **15 min** en sinistre logique (corruption, injection) | Au-delà, rapprochement manuel avec Stripe trop lourd |
| S3 Historique (consultation, back-office) | 4 h | Rapprochement et litiges peuvent attendre | — | — |
| S4 Back-office opérateurs | 4 h | Aucun effet sur l'encaissement | 24 h | Données de configuration peu changeantes |
| S5 Détection et remédiation | **15 min** | Au-delà, une seconde panne ne serait plus réparée seule : le risque rejoint celui de S1 | Sans objet | État reconstruit au redémarrage |
| S6 Supervision, alerte, journaux | 1 h (alerte) | Les humains et le moteur dépendent des alertes | 1 h pour les métriques ; **0 pour les journaux de sécurité** | Les journaux sont des preuves (incident, notification, litige) |
| S7 Vault, secrets d'exploitation | 4 h hors crise ; **1 h en crise de sécurité** | Sans Vault, aucune rotation de secret après compromission | 24 h | Secrets peu changeants, rotation possible |
| S8 Assistant opérateur | 72 h | Confort de l'opérateur, aucun rôle dans la reprise | Sans objet | Corpus versionné dans Git |
| **Sinistre de site** (toute la plateforme) | **4 h** | Au-delà : G3 puis G4 (§ 2.4) | **15 min** | Même exigence que S3 |

### 3.2 Objectifs RTO / RPO comparés au démonstrateur

Les objectifs RTO / RPO sont pris **en dessous** des DMIA / PDMA pour garder une marge (détection,
décision, vérification). Mesures : panne vue par la sonde de transaction (un vrai paiement).

| Scénario | RTO cible | RTO mesuré | RPO cible | RPO mesuré | Écart | Action |
|---|---|---|---|---|---|---|
| API de paiement arrêtée (S1) | 1 min | **10 à 16 s**, 0 intervention | 0 | 0 | Atteint | — |
| Même panne 50 s après la première | 1 min | 72,5 s | 0 | 0 | **Dépassé** (limite de 60 s de la passerelle + bug du moteur, corrigé) | Rejouer le test après correctif ; escalade humaine si la passerelle refuse |
| Plantage de `payment-api` / `auth` / frontal | 1 min | 17,4 s / 21,9 s / 11,1 s ; frontal **0 s** à 3 réplicas | 0 | 0 | Atteint ; 0 s possible avec plusieurs réplicas | 2 réplicas pour `payment-api` et `auth` (état anti force brute à partager) |
| Base de données tuée | 1 min | 7,5 s | 0 | **0 paiement perdu** (116 → 117) | Atteint | — |
| Perte de la VM portant la base | 1 min | 92 s → **0 s** avec Patroni | 0 | 0 (prototype : 0 écriture perdue sur 2 979) | Atteint depuis la réplication | Garder le test dans la recette |
| Perte d'un worker / du manager leader | 1 min | 3 s / 0 s | 0 | 0 | Atteint | — |
| Perte d'un hyperviseur entier | 5 min | Application disponible pendant la coupure (relevés toutes les 20 s ; un 502 isolé au retour du nœud) | 0 | 0 | Partiellement démontré : déplacement des machines par la HA non mesuré | Refaire `node-loss` avec mesure par la sonde |
| Rafale / force brute (S1, S2) | 1 min | 0 s de panne ; anomalie à +4 s ; IP bannie en 27 s | — | — | Atteint pour une source unique | Limitation de débit au WAF contre une attaque distribuée |
| WAF perdu (accès public) | 1 min | **Non mesuré** (HA : 24 à 31 s pour les autres VM) | — | — | Non démontré ; point de défaillance unique | Second WAF derrière NPM ; test `kill` de waf01 |
| Stripe indisponible | 15 min | Dépend du prestataire ; alerte à 3 min | 0 | 0 | **Non tenu** | Bascule vers PayPal (intégré), automatique ou par décision d'astreinte |
| Détecteur ou moteur tué (S5) | 5 min | 0 s pour le paiement ; nominal en 22,8 s / 32,2 s | — | — | Atteint | — |
| Supervision perdue (S6) | 15 min | 0 s pour le paiement ; Grafana revenu à +28 s | 1 h | Tampon des collecteurs ; PBS 24 h pour monitoring01 | Atteint en panne ; journaux non dupliqués | Supervision redondante ou copie des journaux de sécurité hors site |
| Corruption de la base (S3, décision humaine) | 30 min | Restauration : 0,7 s pour 423 paiements, hors temps de décision | **5 min** | **15 min** (dump) ; **24 h hors site** (dumps copiés par le job PBS de 21h00) | **Dépassé** | Archivage continu du journal PostgreSQL (WAL) vers S3 ; copie des dumps hors site à chaque exécution |
| Machine corrompue (restauration PBS) | 1 h | **≈ 1 min** (40 s de restauration) | 24 h | 24 h (22 h 31 min au test : job manqué lab éteint) | Atteint de justesse | Deux jobs par jour : RPO 12 h |
| Vault scellé (S7) | 15 min | **Manuel** : dépend de la présence d'un humain ; paiement non touché | 24 h | 24 h | **Écart** : seule action humaine du démarrage à froid | Vault à 3 nœuds et descellement automatique (KMS, HSM) |
| Démarrage à froid complet | 15 min | ≈ 5 min, plus `vault-unseal` | 0 | 0 | Atteint si un humain est présent | Idem Vault |
| **Sinistre de site** | **4 h** | **Non couvert** : reconstruction depuis Git et PBS jamais testée de bout en bout | **15 min** | 24 h (dumps hors site à 21h00) | **Écart majeur** | Second site ou cloud, exercice de reprise complète, dumps et WAL hors site |

Synthèse : les objectifs de **panne courante** (composant, conteneur, VM, hyperviseur) sont
tenus avec une marge d'un facteur 3 à 6 et **sans intervention humaine**. Les écarts portent sur
les situations qui demandent un humain (Vault, corruption de données) et sur les points
uniques restants (WAF, Stripe, site).

## 4. Modes dégradés acceptables

| Mode dégradé | Ce qui continue | Ce qui manque | Acceptable pendant | Condition |
|---|---|---|---|---|
| Back-office indisponible (connexion opérateurs, Keycloak) | Encaissement, authentification des payeurs | Consultation, litiges, administration | 4 h | Aucun changement d'infrastructure urgent |
| Assistant IA indisponible (rag01, bot Discord) | Tout ; la reprise est automatique | Aide à l'analyse pour l'opérateur | 72 h | **Aucun impact sur la reprise** (lecture seule, hors boucle) |
| Supervision indisponible | Encaissement ; Swarm et HA réparent toujours | Alertes, tableaux de bord, réparation des arrêts « propres » par le moteur | 1 h | Astreinte en veille active ; healthchecks.io prévient de l'absence du Watchdog |
| Détecteur ou moteur arrêté | Encaissement ; Swarm relance les conteneurs plantés | Détection d'anomalie, réparation d'un service arrêté proprement | 15 min | Swarm le relance (mesuré : 0 s de panne) |
| Vault scellé | Encaissement (secrets déjà chargés) | Déploiement, rotation, changement d'infrastructure | 4 h hors crise | **Non acceptable** pendant une compromission : desceller en priorité |
| Un hyperviseur perdu | Encaissement (mesuré) | Redondance : Ceph en `HEALTH_WARN`, plus de marge pour une 2e panne | 24 h | Gel des changements, pas de sauvegarde lourde |
| Bannissement automatique suspendu (`waf-ban` arrêté) | Encaissement ; filtrage ModSecurity | Blocage automatique des sources agressives | 1 h | Surveillance humaine des règles Loki |
| Stripe indisponible, PayPal seul | Paiements par PayPal | Paiements par carte via Stripe | Durée de la panne Stripe | Bascule décidée par l'astreinte (non automatique aujourd'hui) |
| **Non acceptables** | — | Encaissement sans WAF (exposition directe), paiement sans écriture dans l'historique, remédiation automatique d'un service compromis | Jamais | La disponibilité ne justifie pas de perdre l'intégrité ou la traçabilité |

## 5. Conclusion pour la direction

**Ce que le démonstrateur prouve (mesuré).** Sur les pannes courantes, la plateforme se
rétablit seule bien en deçà de la DMIA de 15 min : 10 à 16 s pour un service arrêté, 0 s pour la
perte de la VM de la base depuis la réplication (92 s avant), 0 s pour un frontal tué à 3
réplicas, aucune panne vue par les clients lors de la coupure d'un hyperviseur, aucun paiement
perdu. Ces durées restent en **G1** : quelques euros de commissions, aucune pénalité SLA, aucun
incident à notifier. Les fonctions de pilotage (détection, supervision, IA) ne sont pas des
points de défaillance du paiement.

**Ce qu'il démontre en partie.** La restauration (machine en ≈ 1 min, base en 0,7 s) est rapide,
mais le RPO de la base restaurée (15 min) dépasse l'objectif de 5 min, et la copie hors site
des dumps n'a lieu qu'une fois par jour. Le démarrage à froid demande un humain pour desceller
Vault. Le blocage d'une attaque ne vaut que pour une source unique.

**Ce qu'il ne prouve pas.** Un seul site et un seul hôte parent : la **DMIA de 4 h d'un sinistre
de site n'est pas tenue**, la reconstruction n'a jamais été chronométrée. Un arrêt complet en
heure de pointe devient probablement un incident majeur DORA dès ≈ 50 min ; en coût, il passe en
G3 vers 4 h (≈ 100 k€) puis en G4 à 24 h (≈ 0,5 M€) et 72 h (≈ 1,3 M€). La dépendance à Stripe sans bascule automatique et le WAF unique restent des
points uniques. Enfin, le BIA traite la **disponibilité** : la réponse à une compromission ou à
une fuite (VM5) relève de l'analyse de risques ([02-ebios-rm.md](02-ebios-rm.md)) et du
PCA/PRA ([03-pca-pra.md](03-pca-pra.md)).

**Priorités qui découlent du BIA** (arbitrées dans
[05-arbitrages-recommandations.md](05-arbitrages-recommandations.md)) : site de secours et
exercice de reprise complète (réduit le risque G4) ; copie des dumps hors du lab à chaque
exécution (RPO hors site 24 h → 15 min), puis WAL hors site en continu (RPO 15 min → < 5 min) ; bascule de prestataire de paiement ; second WAF ; descellement automatique
de Vault.

## Annexe : chiffres de référence pour les autres documents

| Indicateur | Valeur retenue |
|---|---|
| Commissions perdues par heure : creuse / journée / pointe | 200 € / 800 € / **3 000 €** |
| Ventes des commerçants bloquées par heure de pointe | 156 000 € |
| Incident majeur DORA probable (arrêt complet) | **≈ 50 min en pointe** ; 2 à 4 h hors pointe |
| Budget SLA mensuel avant pénalité | **43,2 min** ; 3 600 € par tranche de 43,2 min ; plafond 72 000 € (atteint à 14,4 h) |
| Coût total d'un arrêt : 5 min / 1 h / 4 h / 24 h / 72 h | 0,6 k€ (G2) / **16 k€ (G2)** / **103 k€ (G3)** / 463 k€ (G3–G4) / 1,3 M€ (G4) |
| DMIA encaissement / sinistre de site | **15 min** / **4 h** |
| PDMA paiement confirmé / sinistre logique de la base | **0** / **15 min** |
| RTO cible panne courante (encaissement) | **1 min** (mesuré : 0 à 22 s ; 72,5 s pour une panne rapprochée) |
| RPO cible restauration de la base | **5 min** (mesuré : 15 min, 24 h hors site) |
| RTO / RPO cibles sinistre de site | **4 h / 15 min** (non couvert) |
