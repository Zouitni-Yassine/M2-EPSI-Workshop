# 00 — Cadre commun de la gouvernance

Ce document fixe les hypothèses partagées par tous les documents de gouvernance (BIA, EBIOS RM,
PCA/PRA, NIS2/DORA, recommandations). **Toute donnée d'entreprise ci-dessous est fictive**, comme
l'exige le sujet. Les chiffres techniques, eux, sont **mesurés** sur le démonstrateur (§ 6).

## 1. L'organisation fictive

**Resilience Pay SAS** : établissement de paiement fictif, agréé par l'ACPR (hypothèse), qui
fournit à des e-commerçants un service d'encaissement en ligne (passerelle de paiement). Les
paiements sont acquis par des prestataires tiers (Stripe, PayPal ; en mode test dans le
démonstrateur).

| Donnée | Hypothèse |
|---|---|
| Effectif | 85 salariés, dont 12 en exploitation / sécurité |
| Clients | 2 400 e-commerçants (TPE/PME), environ 1,1 million de payeurs par an |
| Chiffre d'affaires | 9 M€ par an (commissions) |
| Volume | 9 millions de transactions par an, soit ≈ 25 000 par jour |
| Flux encaissé | ≈ 470 M€ par an, panier moyen 52 € |
| Revenu par transaction | ≈ 1,00 € (commission 1,4 % + 0,25 €, moyenne nette) |
| Pic de charge | 18h–22h et périodes de soldes : ≈ 3 000 transactions par heure, 6 par seconde au plus |
| Engagement contractuel (SLA) | Disponibilité mensuelle 99,9 % (≈ 43 min d'arrêt par mois) ; pénalité : 5 % de l'abonnement mensuel du commerçant par tranche de 0,1 % manquée |
| Abonnement moyen d'un commerçant | 30 € par mois (≈ 72 000 € par mois au total) |

## 2. Rôles (organisation fictive)

| Rôle | Responsabilité dans la résilience |
|---|---|
| Direction générale (DG) | Décide en crise majeure, arbitre les budgets, signe les notifications réglementaires |
| RSSI | Analyse de risques, pilotage de la sécurité, qualification des incidents de sécurité |
| DSI / Responsable de production | Exploitation, PCA/PRA technique, décisions de restauration |
| Responsable conformité / risques (fonction DORA de contrôle) | Cadre de gestion du risque TIC, notifications ACPR, registre des prestataires |
| DPO | Données personnelles et biométriques, notification CNIL |
| Astreinte d'exploitation (N1/N2) | Surveillance, escalade ; **n'intervient pas** dans la reprise automatique, seulement dans les décisions humaines |
| Communication | Commerçants, payeurs, presse |
| Équipe du workshop | Dev, Infra, IA, Cyber, Gouvernance (rôles du consortium, à distinguer des rôles de l'entreprise fictive) |

## 3. Valeurs métier (reprises par EBIOS RM et le BIA)

| Id | Valeur métier | Critères de sécurité clés |
|---|---|---|
| VM1 | Encaisser un paiement (initier, autoriser, confirmer une transaction) | Disponibilité, intégrité |
| VM2 | Authentifier les payeurs et les opérateurs du back-office | Confidentialité, intégrité |
| VM3 | Conserver l'historique des transactions (preuve, rapprochement, litiges) | Intégrité, traçabilité, disponibilité |
| VM4 | Superviser et rétablir le service (détection, remédiation, alerte) | Disponibilité, intégrité |
| VM5 | Protéger les données personnelles, dont les gabarits biométriques des opérateurs | Confidentialité |

## 4. Échelles communes

**Gravité (impact)**

| Niveau | Libellé | Repère |
|---|---|---|
| G1 | Mineure | Gêne interne, aucun commerçant touché, < 5 k€ |
| G2 | Significative | Arrêt < 1 h hors heure de pointe, ou dégradation visible, pénalités SLA possibles, 5–50 k€ |
| G3 | Grave | Arrêt de plusieurs heures, fuite limitée, incident majeur DORA probable, 50–500 k€ |
| G4 | Critique | Arrêt > 24 h, fuite massive ou fraude, retrait d'agrément possible, > 500 k€ |

**Vraisemblance**

| Niveau | Libellé | Repère |
|---|---|---|
| V1 | Peu vraisemblable | Attaquant très ciblé et très outillé, aucun précédent |
| V2 | Vraisemblable | Déjà vu dans le secteur, moyens importants |
| V3 | Très vraisemblable | Courant (outils publics, botnets, phishing) |
| V4 | Quasi certain | Observé en continu sur tout service exposé |

Matrice de risque : risque = gravité × vraisemblance ; seuil d'acceptation = G1–G2 en V1–V2.

## 5. Biens supports (périmètre du démonstrateur)

Infrastructure réelle décrite dans `../infra/docs/` (lecture conseillée : `dossier/infra.md`,
`architecture.md`, `reseau.md`, `pca-pra-technique.md`, `tests-resilience.md`, `waf.md`,
`identites.md`, `application.md`, `remediation.md`, `supervision.md`, `rag.md`).

- Socle : 3 hyperviseurs Proxmox VE 9 + Ceph, HA ; un seul site, un même hôte parent.
- Orchestration : Docker Swarm, 3 managers drainés, 3 workers ; adresse virtuelle keepalived.
- Application : frontal React (3 réplicas), `auth` (comptes, JWT, anti force brute,
  reconnaissance faciale des opérateurs), `payment-api`, PostgreSQL répliqué (Patroni + etcd,
  3 membres, réplication synchrone), détecteur ML, moteur de remédiation, passerelle
  `remediate` à liste fermée.
- Exposition : NPM (TLS) → WAF ModSecurity + CRS en DMZ → application ; bannissement d'IP
  automatique.
- Supervision : VictoriaMetrics, vmalert, Alertmanager (Discord), Loki, Grafana, Alloy ;
  sonde de transaction (un vrai paiement toutes les 30 s) ; healthchecks.io (hors lab).
- Identité et secrets : Keycloak (SSO + TOTP), HashiCorp Vault, Vaultwarden, CA interne.
- Sauvegardes : PBS externe (13h00 et 21h00), `pg_dump` toutes les 15 min.
- Assistant opérateur : RAG (Ollama, LangChain) en lecture seule sur la supervision.
- Prestataires tiers : Stripe, PayPal, GitHub (code, build), stockage S3 (état Terraform),
  Discord (alertes), healthchecks.io, Let's Encrypt, fournisseur d'accès Internet.

## 6. Faits mesurés sur le démonstrateur (à citer comme preuves)

Référence : panne vue par la sonde de transaction (un vrai client qui paie). Source :
`../infra/docs/tests-resilience.md`.

| Événement | Résultat mesuré |
|---|---|
| API de paiement arrêtée | Reprise automatique en **10 à 16 s**, 0 intervention humaine |
| Détection d'anomalie (ML IsolationForest, F1 0,86, rappel 0,92) | **2 à 4 s** |
| Rafale applicative (40 requêtes parallèles) | **0 s** de panne, anomalie détectée à +4 s |
| Force brute sur la connexion | **IP bannie au WAF en 27 s** |
| Base de données tuée | 7,5 s, **0 paiement perdu** |
| Perte de la VM portant la base : avant / après réplication | **92 s → 0 s** |
| Frontal tué : 1 réplica / 3 réplicas | 11 s → **0 s** |
| Perte d'un hyperviseur entier | Application disponible pendant la coupure |
| Restauration d'une machine (PBS) | 40 s, RTO ≈ 1 min |
| Restauration de la base (dump) | 423 paiements en 0,7 s |
| Démarrage à froid du lab | ≈ 5 min, seul geste humain : desceller Vault |
| RPO | 0 en panne courante ; 15 min pour une base restaurée ; 24 h pour une machine restaurée |

Limites connues : un seul site ; Vault à un nœud descellé à la main ; WAF et supervision en
instance unique ; `auth` et `payment-api` à 1 réplica ; `/api/health` ne teste pas la base ;
bannissement par IP contournable par une attaque distribuée ; reconnaissance faciale sans
détection du vivant ; pas d'isolement automatique d'un service compromis.

## 7. Règles de rédaction

- Français, phrases courtes, ton de conseil à une direction ; pas de superlatifs.
- **Relier chaque affirmation à l'architecture et aux essais** (le sujet refuse un rapport de
  conformité générique). Citer le chiffre mesuré et le document source.
- Distinguer ce qui est **démontré**, **partiellement démontré**, **non démontrable en 4 jours**.
- Distinguer **restauration de la disponibilité** et **traitement d'une compromission ou d'une fuite**.
- Références réglementaires : citer les articles avec prudence ; en cas de doute, écrire
  « à vérifier » plutôt qu'inventer.
- Aucun secret, aucune donnée réelle.
