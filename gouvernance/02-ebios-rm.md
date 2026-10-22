# 02 — Analyse de risques EBIOS Risk Manager

Analyse conduite selon la méthode EBIOS Risk Manager de l'ANSSI, en cinq ateliers, sur
**l'architecture réellement déployée** pour Resilience Pay (organisation fictive décrite dans
[00-cadre.md](00-cadre.md)). Les échelles de gravité (G1–G4), de vraisemblance (V1–V4) et les
valeurs métier (VM1–VM5) sont celles du cadre commun. Les chiffres cités sont mesurés sur le
démonstrateur ; la source est indiquée entre crochets :

- [TR] `infra/docs/tests-resilience.md` (version à jour de la branche `INFRA`) ;
- [WAF] `infra/docs/waf.md` ;
- [REM] `infra/docs/remediation.md` ;
- [ID] `infra/docs/identites.md` ;
- [RES] `infra/docs/reseau.md` ;
- [DOS] `infra/docs/dossier/infra.md` ;
- [AUTH] `auth/README.md` ;
- [RAG] `infra/docs/rag.md`.

Les coûts d'arrêt sont détaillés dans le BIA ([01-bia.md](01-bia.md)), la reprise dans le
PCA/PRA ([03-pca-pra.md](03-pca-pra.md)).

**Lecture des niveaux de risque.** Le risque croise la gravité et la vraisemblance. Seule la zone
« Faible » (G1–G2 en V1–V2) est acceptable sans décision particulière, comme le fixe le cadre.

| | G1 | G2 | G3 | G4 |
|---|---|---|---|---|
| **V4** | Moyen | Élevé | Critique | Critique |
| **V3** | Moyen | Moyen | Élevé | Critique |
| **V2** | Faible | Faible | Moyen | Élevé |
| **V1** | Faible | Faible | Moyen | Moyen |

Chaque risque est évalué trois fois :

- **initial** : sans les mesures construites pendant le workshop. C'est le point de départ du
  lundi : réseau plat, secrets dans des fichiers `.env`, une seule instance de chaque service ;
- **actuel** : avec les mesures en place et prouvées par un essai ;
- **cible** : après le plan d'amélioration (PACS, § 5.5).

---

## Atelier 1 — Cadrage et socle de sécurité

### 1.1 Périmètre

| Élément | Contenu |
|---|---|
| Mission | Encaisser en ligne les paiements des e-commerçants clients, 24 h sur 24, avec un SLA de 99,9 % |
| Périmètre de l'étude | La chaîne de paiement de bout en bout et tout ce qui la répare. **Exposition** : NPM, WAF. **Application** : frontal, `auth`, `payment-api`, PostgreSQL. **Pilotage** : détection, remédiation, supervision. **Socle** : Proxmox, Ceph, Swarm. **Identité et secrets** : Keycloak, Vault, Vaultwarden, CA interne. **Sauvegardes** : PBS, `pg_dump`. **Hors du lab** : poste de contrôle IaC, assistant RAG |
| Hors périmètre | Systèmes internes des prestataires (Stripe, PayPal, GitHub) ; poste de travail des commerçants et des payeurs ; réseaux du campus |
| Participants (organisation fictive) | RSSI (pilote), DSI, conformité / risques, DPO, métier ; validation par la DG |
| Horizon | Cycle stratégique 12 mois, cycle opérationnel 3 mois (revue après chaque incident majeur) |

### 1.2 Valeurs métier et biens supports

| VM | Valeur métier | Biens supports principaux |
|---|---|---|
| VM1 | Encaisser un paiement | NPM, waf01, adresse virtuelle 10.30.1.200, frontal (3 réplicas), `payment-api`, Swarm, workers, Stripe/PayPal |
| VM2 | Authentifier payeurs et opérateurs | `auth` (JWT Ed25519, argon2id, reconnaissance faciale), Keycloak (TOTP) pour les administrateurs |
| VM3 | Conserver l'historique des transactions | PostgreSQL Patroni (3 membres, synchrone), etcd, Ceph, PBS, `pg_dump` toutes les 15 min |
| VM4 | Superviser et rétablir | Détecteur ML, moteur de remédiation, passerelle `remediate`, VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana, healthchecks.io, Discord |
| VM5 | Protéger les données personnelles et biométriques | Table `face_templates` (gabarits SFace, aucune image conservée), comptes payeurs, journaux |

Biens transverses : le poste de contrôle 10.0.1.110 (Terraform, Ansible, clé de la CA,
identifiants de l'AppRole Vault) et Vault. **Leur compromission touche toutes les valeurs
métier.**

### 1.3 Événements redoutés

| ER | Événement redouté | VM | Impacts | G |
|---|---|---|---|---|
| ER1 | Paiement indisponible plusieurs heures (pic 18h–22h ou soldes) | VM1 | 3 000 € de commissions et 156 000 € de ventes des commerçants bloqués par heure de pointe. Arrêt de 4 h : ≈ 103 k€. Incident majeur DORA probable dès ≈ 50 min d'arrêt complet en pointe (2 500 transactions, 10 % du volume quotidien), vers 2 à 4 h hors pointe. (Un arrêt d'une heure, ≈ 16 k€, reste G2 par le coût, mais pas au regard de DORA en pointe : [04-nis2-dora.md](04-nis2-dora.md) § 4.1) | **G3** |
| ER2 | Paiement indisponible plus de 24 h (socle détruit ou chiffré) | VM1, VM3 | 24 h : ≈ 463 k€ (limite G4) ; 72 h : ≈ 1,3 M€. Perte de clients, notification ACPR, retrait d'agrément possible | **G4** |
| ER3 | Transactions altérées ou perdues (historique non fiable) | VM3 | Litiges et rapprochements impossibles, fraude masquée | **G4** |
| ER4 | Fuite de données de payeurs ou de comptes | VM2, VM5 | Notification CNIL (RGPD art. 33-34), image | **G3** (G4 si massive) |
| ER5 | Prise de contrôle d'un compte opérateur du back-office : transactions, soldes, habilitations | VM2, VM1 | Fraude, création de comptes, effacement de traces | **G4** |
| ER6 | Fuite des gabarits biométriques des opérateurs | VM5 | Donnée sensible (RGPD art. 9), non révocable comme un mot de passe | **G3** |
| ER7 | Moteur de remédiation détourné pour arrêter le service | VM4, VM1 | Arrêt provoqué par nos propres outils | **G3** |
| ER8 | Perte de la supervision et de la reprise automatique | VM4 | Reprise ralentie : seul Swarm répare [TR § 4.2] | **G2** |

### 1.4 Socle de sécurité

| Référentiel | Exigences retenues | Application dans le démonstrateur | Écarts connus |
|---|---|---|---|
| Guide d'hygiène informatique ANSSI (42 mesures) | Authentification forte des administrateurs, cloisonnement, moindre privilège, journalisation, sauvegardes, mises à jour | SSO Keycloak + TOTP (Grafana, Proxmox). VLAN RA-APP / RA-DMZ / RA-VPN, nftables en `drop`. SSH par clé, root interdit. Alloy sur toutes les machines. PBS externe. Mises à jour de sécurité automatiques (LXC) | Supervision et identité sur le VLAN des hyperviseurs. Pas de poste d'administration dédié. Interface UniFi joignable depuis RA-* [RES § 4] |
| DORA (règlement UE 2022/2554) | Cadre de gestion du risque TIC (art. 6), protection (art. 9), détection (art. 10), réponse et rétablissement (art. 11), sauvegardes (art. 12), tests (art. 24-25), prestataires tiers (art. 28) | Chaîne détection → remédiation mesurée. Tests de chaos répétables (`chaos.sh`). Restauration testée. Registre des prestataires en § 5 du cadre | Un seul site. Pas de test de pénétration fondé sur la menace (TLPT, art. 26), non démontrable en 4 jours. Clauses contractuelles avec les prestataires non rédigées |
| RGPD | Minimisation, sécurité (art. 32), données sensibles (art. 9), notification (art. 33-34), AIPD (art. 35) | Aucune image de visage conservée, gabarits seuls. Mots de passe en argon2id. Aucun numéro de carte ni nom de porteur dans les journaux | AIPD de la reconnaissance faciale non réalisée. Consentement ou base légale des opérateurs à formaliser (à vérifier avec le DPO). Gabarits non chiffrés au niveau applicatif (à vérifier) |
| PCI DSS | Protection des données de carte | Paiements par Stripe et PayPal en mode test. Le moteur Stripe du frontal (`StripeCardForm.tsx`) utilise Stripe Elements : le numéro est saisi chez Stripe, jamais chez nous (périmètre réduit, de type SAQ A) | **Constat** : le moteur de démonstration (`ownEngine.ts`) envoie le numéro et le titulaire de la carte à notre propre API, qui les associe à une carte de test Stripe. Dans ce mode, le numéro transite par nos services : tout le SI entrerait dans le périmètre PCI DSS (SAQ D). **Mesure** : supprimer ce mode avant la mise en production (PACS P1) |
| Consignes du sujet (§ 3.4, § 5) | Secrets dans Vault ou SOPS ; moteur de remédiation sans interface d'administration ouverte ; aucune clé confiée à une IA | Vault (KV v2, AppRole limité à .110, audit de chaque lecture). Passerelle à liste fermée. Clés Stripe et PayPal rangées dans Vault par un humain | Token root et clés de descellement sur .110 jusqu'après la démo [ID § 7] |

---

## Atelier 2 — Sources de risque et objectifs visés

| SR | Source de risque | OV | Objectif visé | Motivation | Ressources | Pertinence | Décision |
|---|---|---|---|---|---|---|---|
| SR1 | Cybercriminel à but lucratif | OV1 | Rançongiciel : chiffrer socle et sauvegardes, extorquer | Forte : un établissement de paiement arrêté paie vite | Importantes (affiliés, accès achetés) | Élevée | **Retenu** |
| SR1 | | OV2 | Fraude : détourner des paiements ou des soldes par le back-office | Forte | Moyennes à importantes | Élevée | **Retenu** |
| SR1 | | OV3 | Voler et revendre des données (comptes, gabarits) | Moyenne | Moyennes | Moyenne | **Retenu** |
| SR2 | Hacktiviste | OV4 | Rendre le paiement indisponible pendant les soldes (déni de service) | Moyenne (visibilité) | Botnets loués, outils publics | Élevée | **Retenu** |
| SR3 | Attaquant opportuniste | OV5 | Prise de comptes par force brute ou bourrage d'identifiants ; exploitation de failles web connues | Faible, mais attaque permanente et automatisée | Outils publics, listes d'identifiants fuités | Très élevée | **Retenu** |
| SR4 | Initié malveillant ou administrateur compromis | OV2, OV1, OV6 | Fraude, sabotage, vol des secrets (Vault, CA) | Variable | Accès légitimes, connaissance du SI | Élevée | **Retenu** (cas du « PC admin compromis » de la red team) |
| SR5 | Concurrent | — | Espionnage commercial, atteinte à l'image | Faible : marché fragmenté, risque pénal élevé | Moyennes | Faible | **Écarté** (un DoS commandité est couvert par SR2) |
| SR6 | Attaquant étatique | — | Déstabilisation du secteur financier | Faible pour une PME de 85 salariés | Très importantes | Faible | **Écarté** (à réexaminer si l'entreprise devient fournisseur d'un acteur systémique) |

---

## Atelier 3 — Scénarios stratégiques

### 3.1 Cartographie de l'écosystème

**Échelle de lecture.** Chaque critère est noté de 1 à 4. La menace d'une partie prenante est
le rapport (dépendance × pénétration) / (maturité × confiance) : au-delà de 2, elle est
**élevée** ; entre 1 et 2, elle est **moyenne** ; sous 1, elle est **faible**.

| Partie prenante | Lien avec le SI | Dép. | Pén. | Mat. | Conf. | Menace | Commentaire |
|---|---|---|---|---|---|---|---|
| Équipe d'exploitation (12 personnes) | Accès administrateur, VPN, SSO, poste de contrôle | 4 | 4 | 3 | 3 | **Élevée** (1,8) | Point d'entrée privilégié d'un attaquant (SO3, SO9) |
| Payeurs (1,1 M/an) | Comptes clients, navigateur | 3 | 2 | 1 | 2 | **Élevée** (3,0) | Mots de passe réutilisés : bourrage d'identifiants (SO2) |
| E-commerçants (2 400) | Intégration de l'API, comptes | 4 | 2 | 1 | 2 | **Élevée** (4,0) | TPE/PME peu outillées ; un commerçant compromis émet des paiements frauduleux |
| GitHub (dépôt public, build) | Source de toutes les images | 4 | 3 | 3 | 2 | **Élevée** (2,0) | Dépôt public : la chaîne de construction est une cible (SO8) |
| Hébergement, hôte parent, FAI | Les 3 hyperviseurs et l'accès Internet | 4 | 4 | 3 | 3 | **Moyenne** (1,8) | Point unique de défaillance physique (un seul site) |
| Stripe, PayPal | Acquisition des paiements | 4 | 1 | 4 | 3 | Faible (0,3) | Dépendance critique mais maturité élevée ; une panne prestataire n'est pas une attaque contre nous |
| Stockage S3 (état Terraform) | Description complète de l'infrastructure | 2 | 2 | 3 | 3 | Faible (0,4) | L'état peut contenir des données sensibles |
| Discord, healthchecks.io | Alertes humaines, veille de la chaîne d'alerte | 2 | 1 | 3 | 2 | Faible (0,3) | Fuite d'informations d'exploitation possible ; aucun accès entrant |
| Poste de délestage IA (GPU) | Tunnel SSH inverse vers rag01, modèle de langage | 1 | 1 | 2 | 2 | Faible (0,3) | Aucun accès privilégié, assistant en lecture seule [RAG § 2] |
| Let's Encrypt | Certificat public | 2 | 1 | 4 | 4 | Faible (0,1) | — |

### 3.2 Chemins d'attaque stratégiques

| SS | Chemin (source → intermédiaire → cible) | ER visés | G |
|---|---|---|---|
| SS1 | Hacktiviste (SR2) → botnet → frontal public, pendant les soldes | ER1 | G3 |
| SS2 | Opportuniste (SR3) → identifiants fuités des payeurs → comptes clients | ER4 | G3 |
| SS3 | Cybercriminel (SR1) → hameçonnage d'un administrateur → poste et VPN → back-office ou socle | ER5, ER2, ER3 | G4 |
| SS4 | Cybercriminel (SR1) → dépôt GitHub ou dépendance publique → image malveillante → données et secrets | ER4, ER3 | G4 |
| SS5 | Cybercriminel (SR1) → socle et sauvegardes → chiffrement | ER2, ER3 | G4 |
| SS6 | Initié ou administrateur compromis (SR4) → poste de contrôle et Vault → tous les secrets | ER2 à ER6 | G4 |
| SS7 | Cybercriminel (SR1) → usurpation d'un opérateur (photo + mot de passe volé) → fraude | ER5 | G4 |

### 3.3 Mesures sur l'écosystème

| Partie prenante | Mesure recommandée | État |
|---|---|---|
| Équipe d'exploitation | Postes d'administration dédiés, MFA résistante à l'hameçonnage (FIDO2), sensibilisation, revue trimestrielle des droits | TOTP en place ; le reste est à faire |
| Payeurs | MFA proposée (clés d'accès / passkeys), détection des identifiants fuités, notification de connexion inhabituelle | Freinage et bannissement en place |
| E-commerçants | Clés d'API par commerçant, révocables, avec plafonds ; MFA sur leur espace | Non démontré |
| GitHub | Protection des branches, revue obligatoire, commits signés, analyse des dépendances | Build depuis un commit figé seulement [`application.md`] |
| Stripe, PayPal | Clauses DORA (art. 28 et suivants, à vérifier), plan de sortie, second prestataire activable | Registre des prestataires dans le cadre ; clauses non rédigées |
| Hébergement | Second site ou cloud pour le PRA | Non démontrable en 4 jours |

---

## Atelier 4 — Scénarios opérationnels

Mode opératoire décrit en quatre temps : **connaître**, **entrer**, **trouver**, **exploiter**.
La vraisemblance **actuelle** tient compte des mesures en place.

**SO1 — Déni de service applicatif, rafale de paiements** *(attaque de notre démonstration ; SS1)*

- Mode opératoire : repérage de l'URL publique et de l'API de paiement → envoi massif de
  requêtes `POST /api/payment_intents` depuis une ou plusieurs IP → saturation de
  `payment-api` (une réplica) → paiements refusés ou trop lents.
- Biens supports : WAF, frontal, `payment-api`, base.
- Ce qui se passe aujourd'hui : rafale de 40 requêtes parallèles, **0 s de panne**, anomalie
  vue à +4 s, redémarrage en 13,8 s [TR § 3.1]. API arrêtée : reprise en **10 à 16 s**. Source
  unique au-delà de 1 200 requêtes par minute : bannie au WAF (`WafSourceFlood`) [WAF § 5].
- Reste ouvert : une attaque distribuée sous les seuils (20 IP bannies au plus) n'est pas
  arrêtée, et un DDoS volumétrique sature le lien avant le WAF.
- Vraisemblance : **V4 → V3**.

**SO2 — Force brute et bourrage d'identifiants sur la connexion** *(SS2)*

- Mode opératoire : listes d'identifiants fuités → `POST /auth/login` ou `/auth/token` en série
  → comptes clients dont le mot de passe est réutilisé.
- Mesures en place [AUTH] :
  - argon2id ; même réponse pour un compte inconnu ou un mauvais mot de passe ;
  - réponse 429 après 5 échecs sur un même identifiant, ou 20 échecs depuis une même adresse ;
  - **IP bannie au WAF en 27 s** [WAF § 5, test du 21/10].
- Reste ouvert : le bourrage distribué (une tentative par compte et par IP) passe sous tous les
  seuils. Les payeurs n'ont pas de second facteur.
- Vraisemblance : **V4 → V3**.

**SO3 — PC d'administrateur compromis sur le VPN** *(scénario red team ; SS3)*

- Mode opératoire : hameçonnage ou maliciel sur le poste d'un administrateur → accès au VPN
  EPSI-WG → reconnaissance du réseau → tentative sur les interfaces d'administration, ou
  attaque de l'application par l'intérieur.
- Mesures en place :
  - depuis le VPN, seules les interfaces web sont ouvertes ; le SSH passe par le poste de
    contrôle [`architecture.md` D8] ;
  - SSO Keycloak avec TOTP ;
  - aucune ouverture vers l'application qui ne passe par le WAF ;
  - le VPN n'est **volontairement pas** en liste blanche du bannissement : le poste compromis
    est banni comme une IP publique [WAF § 5].
- Reste ouvert : un poste compromis peut voler une session déjà ouverte (Grafana en HTTP,
  cookie lisible sur le LAN [ID § 10]) ou capter un code TOTP en temps réel. Aucun EDR, aucun
  bastion avec enregistrement des sessions.
- Vraisemblance : **V3 → V2**.

**SO4 — Injection SQL ou XSS** *(SS4 côté application)*

- Mode opératoire : scanner public → paramètres de l'API et du frontal → injection → lecture de
  la base (comptes, transactions) ou vol de session.
- Mesures en place :
  - ModSecurity + OWASP CRS en mode blocage : injection SQL et XSS en **403** sur l'URL publique
    [WAF § 4] ;
  - au-delà de 10 refus en 2 min, l'IP est bannie (`WafSourceAttacks`) ;
  - cookie de session `HttpOnly` et `SameSite=Strict` ; algorithme JWT figé [AUTH] ;
  - accès à la base par SQLAlchemy Core, donc par requêtes paramétrées : aucune requête
    construite par concaténation ou f-string dans `backend/` et `auth/` (vérifié par lecture
    du code, sans audit exhaustif).
- Reste ouvert : contournement possible d'un CRS au niveau de paranoïa 1. Pas de SAST ni de
  DAST, pas d'audit de code complet.
- Vraisemblance : **V3 → V1**.

**SO5 — Usurpation d'un opérateur du back-office** *(SS7)*

- Mode opératoire : photo de l'opérateur (réseaux sociaux) et mot de passe volé (hameçonnage) →
  photo présentée à la caméra → mot de passe saisi dans la fenêtre de 120 s → accès à toutes
  les transactions, aux soldes et aux habilitations.
- Mesures en place [AUTH] :
  - trois facteurs successifs : identifiant, visage (SFace, seuil 0,363), mot de passe ;
  - blocage de l'identifiant 5 min après deux cycles ratés ;
  - `/auth/token` et réinitialisation par e-mail refusés aux opérateurs ;
  - compte de service dispensé de visage **depuis le réseau interne seulement** ;
  - journal des accès du back-office.
- Reste ouvert : **pas de détection du vivant**. Une photo suffit pour le facteur visage, il ne
  reste alors que le mot de passe.
- Vraisemblance : **V3 → V2**.

**SO6 — Abus du moteur de remédiation** *(SS6, ER7)*

- Mode opératoire, deux variantes :
  - un conteneur compromis tente d'utiliser la clé SSH du moteur pour arrêter ou réduire des
    services ;
  - un attaquant provoque volontairement des anomalies pour faire redémarrer le service en
    boucle (déni de service auto-infligé).
- Mesures en place [REM] :
  - passerelle à liste fermée : `list`, `status`, `restart`, `rollback`, `scale` 1 à 6, sur les
    stacks autorisées seulement ;
  - commande forcée, sans shell ; clé utilisable depuis les workers seulement, par le seul
    service qui détient le secret ;
  - 60 s entre deux actions sur un service, 10 actions par 10 min ;
  - interrupteur d'arrêt ; chaque appel tracé dans Loki ;
  - **11 cas sur 11 conformes**, injections (`status demo_web;id`, `restart ../../etc`) refusées.
- Reste ouvert : limites comptées par manager (jusqu'à 3 fois la limite). Le pire effet est une
  série de redémarrages, pas une prise de contrôle.
- Vraisemblance : **V2 → V2** (gravité ramenée de G4 à G2).

**SO7 — Rançongiciel sur le socle et les sauvegardes** *(SS5)*

- Mode opératoire : accès administrateur (SO3 ou SO9) → découverte de Proxmox et de PBS →
  suppression des sauvegardes → chiffrement des disques Ceph → demande de rançon.
- Mesures en place :
  - PBS externe au lab ; `pg_dump` toutes les 15 min ;
  - restaurations testées : machine en **40 s**, base de **423 paiements en 0,7 s** ;
  - toute l'infrastructure décrite en code (reconstruction depuis Git) ;
  - segmentation : RA-APP ne joint ni Proxmox ni le SSH de MANAGEMENT [RES § 3].
- Reste ouvert :
  - un seul serveur de sauvegarde, sans copie immuable démontrée ;
  - les dumps restent sur le poste de contrôle et ne quittent le lab qu'une fois par jour
    (job PBS de 21h00) : si le poste est chiffré, jusqu'à **24 h** de paiements à reconstituer ;
  - un seul site ; Vault redémarre scellé.
- Vraisemblance : **V3 → V2**.

**SO8 — Compromission de la chaîne d'approvisionnement** *(SS4)*

- Mode opératoire : compte d'un contributeur GitHub compromis, ou dépendance publique piégée →
  code malveillant fusionné → image construite et déployée → exfiltration des secrets Swarm et
  des données.
- Mesures en place :
  - build depuis un **commit complet figé**, jamais une branche ;
  - tags d'images immuables, révision du commit inscrite dans chaque image ;
  - registre privé authentifié ;
  - scan anti-secrets du diff avant chaque envoi [`application.md`, DOS § 4].
- Reste ouvert : pas de protection de branche démontrée (**à vérifier**), pas de signature
  d'image, pas d'analyse des dépendances ni de SBOM. Dépôt public.
- Vraisemblance : **V2 → V2**.

**SO9 — Vol de secrets** *(SS6)*

- Mode opératoire : compromission du poste de contrôle 10.0.1.110 → lecture de `init.json`
  (token root de Vault, clés de descellement), de la clé de la CA et des identifiants de
  l'AppRole → tous les secrets, et des certificats valides à volonté.
- Mesures en place [ID] :
  - plus aucun fichier `.env` ; secrets lus à chaque exécution par `vault-env`, puis le jeton
    est révoqué ;
  - AppRole limité à l'adresse de .110 : refus 400 depuis une autre machine (testé) ;
  - audit de chaque lecture dans Loki ; fichiers en 0600 ;
  - secrets renouvelés le 20/10, sauf 7 qui ne peuvent l'être que chez le fournisseur ou
    après la démo (token root, clés de descellement, clé du moteur, UniFi, webhook Discord,
    healthchecks.io, S3 : `comptes-et-rotation.md`).
- Reste ouvert : token root et clé de la CA sur .110. Leur suppression est **planifiée après la
  démo du 23/10**.
- Vraisemblance : **V3 → V2**.

**SO10 — Injection de consignes dans l'assistant des opérateurs** *(complémentaire)*

- Mode opératoire : texte piégé dans une requête, journalisé, puis lu par l'assistant RAG → la
  réponse pousse l'opérateur à une mauvaise action.
- Mesures en place [RAG § 2 et § 7] :
  - VM hors du Swarm ; aucun secret d'administration ;
  - comptes de supervision en lecture seule ;
  - l'assistant ne déclenche aucune action ;
  - le prompt système traite les résultats d'outils comme des données.
- Reste ouvert : une réponse erronée reste possible. L'opérateur décide.
- Vraisemblance : **V3 → V2**.

---

## Atelier 5 — Traitement du risque

### 5.1 Synthèse : mesures existantes, risque initial, actuel et cible

| Risque | Scénario | Initial | Mesures existantes et preuve | Actuel | Mesures complémentaires (PACS) | Cible |
|---|---|---|---|---|---|---|
| R1 | SO1 Déni de service | G3/V4 **Critique** | Rafale 0 s ; API rétablie en 10–16 s ; frontal à 3 réplicas (11 s → 0 s) ; perte d'un hyperviseur sans arrêt ; flood mono-source banni | G3/V3 **Élevé** | Protection anti-DDoS en amont (CDN ou opérateur) ; limitation de débit par client ; `payment-api` à 2 réplicas ou plus | G2/V2 Faible |
| R2 | SO2 Bourrage d'identifiants | G3/V4 **Critique** | argon2id ; 429 après 5/20 échecs ; **ban en 27 s** ; visage obligatoire pour les opérateurs | G2/V3 **Moyen** | MFA ou passkeys pour les payeurs ; détection des identifiants fuités ; freinage partagé entre réplicas | G2/V2 Faible |
| R3 | SO3 PC admin compromis | G4/V3 **Critique** | VLAN + nftables `drop` ; seulement les interfaces web depuis le VPN ; TOTP ; VPN non protégé du ban | G4/V2 **Élevé** | Postes d'administration dédiés ; FIDO2 ; bastion avec enregistrement ; EDR ; Grafana en HTTPS | G4/V1 Moyen |
| R4 | SO4 Injection SQL / XSS | G4/V3 **Critique** | CRS en blocage, SQLi et XSS en 403 ; ban après 10 refus ; cookie `HttpOnly` / `SameSite=Strict` ; requêtes paramétrées (SQLAlchemy Core, vérifié par lecture du code) | G4/V1 **Moyen** | Revue de code et SAST ; DAST en CI ; test d'intrusion annuel ; chiffrement des champs sensibles | G3/V1 Moyen |
| R5 | SO5 Usurpation d'opérateur | G4/V3 **Critique** | Visage + mot de passe ; blocage 5 min ; pas de jeton ni de réinitialisation par e-mail pour les opérateurs | G4/V2 **Élevé** | Détection du vivant ; FIDO2 ; double validation des actions sensibles (habilitations, soldes) ; AIPD | G4/V1 Moyen |
| R6 | SO6 Abus de la remédiation | G4/V2 **Élevé** (socket Docker = root du cluster) | Passerelle à liste fermée, **11/11 conformes** ; limites de débit ; interrupteur ; traces | G2/V2 **Faible** | Limite de débit partagée entre managers ; alerte sur refus répétés | G2/V1 Faible |
| R7 | SO7 Rançongiciel | G4/V3 **Critique** | PBS externe ; dumps toutes les 15 min (hors du lab une fois par jour : RPO 24 h si le poste de contrôle est touché) ; restauration en 40 s / 0,7 s ; IaC ; segmentation | G4/V2 **Élevé** | Copie immuable hors site (3-2-1-1-0) ; comptes PBS séparés avec MFA ; dumps exportés à chaque exécution ; second site | G3/V1 Moyen |
| R8 | SO8 Chaîne d'approvisionnement | G4/V2 **Élevé** | Commit figé ; tags immuables ; registre authentifié ; scan anti-secrets | G4/V2 **Élevé** | Protection des branches et revue à deux ; commits et images signés ; SBOM et analyse des dépendances | G4/V1 Moyen |
| R9 | SO9 Vol de secrets | G4/V3 **Critique** (`.env` en clair) | Vault ; AppRole limité à .110 ; audit ; rotation du 20/10 (7 secrets jamais renouvelés) | G4/V2 **Élevé** | Révocation du token root et suppression d'`init.json` (planifiées le 23/10) ; CA hors ligne ; Vault à 3 nœuds avec auto-unseal | G4/V1 Moyen |
| R10 | SO10 Assistant manipulé | G2/V3 **Moyen** | Lecture seule ; aucun secret ; aucune action automatique | G1/V2 **Faible** | Citer la source de chaque réponse | G1/V2 Faible |

### 5.2 Cartographie avant / après

**Risque initial** (lundi, avant les mesures du workshop)

| | G1 | G2 | G3 | G4 |
|---|---|---|---|---|
| **V4** | | | R1, R2 | |
| **V3** | | R10 | | R3, R4, R5, R7, R9 |
| **V2** | | | | R6, R8 |
| **V1** | | | | |

**Risque actuel** (jeudi, mesures prouvées)

| | G1 | G2 | G3 | G4 |
|---|---|---|---|---|
| **V4** | | | | |
| **V3** | | R2 | R1 | |
| **V2** | R10 | R6 | | R3, R5, R7, R8, R9 |
| **V1** | | | | R4 |

**Risque cible** (après le PACS)

| | G1 | G2 | G3 | G4 |
|---|---|---|---|---|
| **V4** | | | | |
| **V3** | | | | |
| **V2** | R10 | R1, R2 | | |
| **V1** | | R6 | R4, R7 | R3, R5, R8, R9 |

**Lecture pour la direction.** Le workshop fait passer 7 risques critiques à zéro. Les mesures
ont surtout réduit la **vraisemblance** : filtrage, segmentation, bannissement, secrets dans
Vault. Elles ont aussi réduit la **durée d'un arrêt**, grâce à la reprise automatique.

Cinq risques restent élevés en gravité G4 : R3, R5, R7, R8 et R9. Ils ont un point commun :
**un compte privilégié ou la chaîne de production compromis**. Pour ces cas, la reprise
automatique ne sert à rien, car elle redémarre ce que l'attaquant contrôle déjà.

### 5.3 Restauration de la disponibilité et traitement d'une compromission

| Situation | Ce qui est automatique (démontré) | Ce qui reste humain | Décideur |
|---|---|---|---|
| Panne ou saturation (R1, R6) | Détection 2–4 s, `restart` par la passerelle, reprise 10–16 s ; ban de la source | Analyse a posteriori, réglage des seuils | Astreinte, DSI |
| Force brute (R2) | Ban en 27 s pendant 15 min | Débannissement d'une IP partagée à tort (`waf-ban unban`) ; information des comptes visés | Astreinte, RSSI |
| Injection ou fuite de données (R4, R9, ER4, ER6) | Blocage 403 et ban ; **aucune restauration de la confidentialité** | Qualification de l'incident ; gel des preuves (journaux Loki, audit Vault) ; rotation des secrets (procédure écrite, `comptes-et-rotation.md`) ; notification CNIL sous 72 h (art. 33) et ACPR (DORA art. 19) | RSSI, DPO, DG |
| Données altérées (ER3) | `restart` et `rollback` rétablissent le service, **pas les données** | Restauration de la base depuis un dump : 15 min de données perdues au plus, pour une cible de 5 min fixée par le BIA (écart à combler, PACS P1) ; rapprochement avec Stripe et PayPal | DSI sur décision de la DG |
| Socle compromis ou chiffré (R7) | Aucun | Isolement, reconstruction depuis Git (Terraform, Ansible) sur un socle sain, restauration PBS, rotation complète | DG (cellule de crise) |
| Service compromis | **Isolement automatique non implémenté** (action `isolate` prévue [REM § 7]) | Retrait manuel du service, conservation pour l'enquête | RSSI |

Redémarrer un conteneur compromis le relance depuis une image saine. L'attaquant ne revient que
si la faille est encore ouverte, ou si les secrets volés restent valides. **Une compromission
se termine donc par la rotation des secrets, pas par un redémarrage.**

### 5.4 Risques résiduels et acceptation

| Risque résiduel | Niveau actuel | Justification | Accepté par | Condition |
|---|---|---|---|---|
| R1 DDoS distribué ou volumétrique | Élevé | Hors de portée d'un lab ; mono-source traité | DG, sur proposition du RSSI | **Temporaire** : contrat anti-DDoS avant la mise en production |
| R3, R5 Comptes privilégiés usurpés | Élevé | TOTP et visage en place ; FIDO2 et détection du vivant non disponibles en 4 jours | DG | Temporaire, 3 mois ; journal du back-office revu chaque semaine |
| R7 Rançongiciel | Élevé | Sauvegardes externes testées ; immuabilité et second site non démontrés | DG | Temporaire, 3 mois |
| R8 Chaîne d'approvisionnement | Élevé | Build reproductible ; signature absente | DSI et RSSI, validé par la DG | Temporaire, 3 mois |
| R9 Secrets sur le poste de contrôle | Élevé | Gardés **volontairement** jusqu'à la démo pour desceller sans saisie | Équipe du workshop (lab) ; DG (organisation fictive) | **Échéance : 23/10, après la démo** |
| R2, R4 | Moyen | Mesures prouvées ; le résiduel tient à des attaques distribuées ou à un contournement du WAF | RSSI, avec revue trimestrielle | Indicateurs : `auth_login_total{result="failure"}`, 403 du WAF |
| R6, R10 | Faible | Dans le seuil d'acceptation | Accepté d'office | Revue annuelle |

Aucun risque de gravité G4 n'est accepté durablement. Selon le cadre, l'acceptation d'un risque
hors de la zone Faible relève de la direction générale.

### 5.5 PACS — Plan d'amélioration continue de la sécurité

Priorités :

- **P0** : avant la fin de la démonstration ;
- **P1** : avant toute mise en production ;
- **P2** : sous 3 mois ;
- **P3** : sous 12 mois.

| Prio. | Mesure | Risques | Porteur | Effort | Preuve attendue (vérifiable) |
|---|---|---|---|---|---|
| P0 | Révoquer le token root de Vault, supprimer `init.json`, répartir les clés de descellement entre 3 détenteurs | R9 | Infra | Faible | Token refusé (403) ; fichier absent ; `vault-unseal` en saisie manuelle testé |
| P1 | Protection anti-DDoS en amont, limitation de débit par client | R1 | DSI | Moyen | Test de charge distribué : moins de 1 % d'échecs de la sonde |
| P1 | Détection du vivant et AIPD de la reconnaissance faciale | R5, ER6 | Dev, DPO | Moyen | Photo refusée en test ; AIPD signée |
| P1 | Copie de sauvegarde immuable hors site ; dumps exportés à chaque exécution ; archivage continu des journaux PostgreSQL (WAL) pour tenir le RPO cible de 5 min | R7, ER3 | DSI | Moyen | Restauration complète depuis la copie immuable, chronométrée ; perte de données mesurée ≤ 5 min |
| P1 | Protection des branches, revue à deux, analyse des dépendances | R8 | Dev | Faible | Fusion directe refusée ; rapport d'analyse dans la CI |
| P1 | Supprimer le moteur de paiement de démonstration (`ownEngine.ts`) : seul Stripe Elements (ou PayPal) reçoit le numéro de carte | Conformité PCI DSS, ER4 | Dev | Faible | Aucune route de notre API n'accepte un numéro de carte ; périmètre de type SAQ A confirmé |
| P1 | `payment-api` et `auth` à 2 réplicas ou plus ; freinage anti force brute partagé ; `/api/health` qui teste la base | R1, R2 | Dev | Moyen | `kill-payment-api` : 17,4 s → 0 s ; `kill-auth` : 21,9 s → 0 s |
| P2 | FIDO2 pour les administrateurs et les opérateurs ; postes d'administration dédiés ; bastion avec enregistrement | R3, R5 | RSSI | Moyen | Connexion sans clé refusée ; sessions rejouables |
| P2 | Action `isolate` de la passerelle ; rotation des secrets automatisée | R4, R9, R6 | Infra, Cyber | Moyen | Exercice : service compromis isolé et secrets changés en moins de 15 min |
| P2 | Signature des images et des commits ; SBOM | R8 | Dev, Infra | Moyen | Déploiement refusé pour une image non signée |
| P2 | CA hors ligne, CA intermédiaire dans Vault ; Vault à 3 nœuds avec auto-unseal | R9 | Infra | Moyen | Perte d'un nœud Vault sans descellement manuel |
| P3 | Second site ou cloud pour le PRA ; supervision et WAF redondés ; VLAN dédiés à la supervision et à l'identité | R7, R1, ER8 | DG, DSI | Élevé | Bascule de site testée une fois par an |
| P3 | Test d'intrusion annuel, puis TLPT si l'ACPR le demande (DORA art. 26, à vérifier) | Tous | RSSI | Moyen | Rapport et plan de correction suivi |

**Suivi.** Revue trimestrielle du PACS en comité des risques (RSSI, DSI, conformité, DPO). Les
indicateurs viennent de la supervision existante :

- délai de reprise vu par la sonde de transaction ;
- délai de bannissement ;
- refus de la passerelle `remediate` ;
- lectures de l'audit Vault.

Chaque test de chaos rejoué (`chaos.sh`) met à jour la cartographie.

### 5.6 Ce qui est démontré, et ce qui ne l'est pas

| Statut | Éléments |
|---|---|
| **Démontré** | Reprise sans humain (10–16 s), rafale absorbée (0 s), ban en 27 s, SQLi/XSS en 403, passerelle 11/11, base répliquée (92 s → 0 s), perte d'un hyperviseur sans arrêt, restaurations (40 s, 0,7 s), segmentation testée depuis un worker |
| **Partiellement démontré** | Scénario red team (le poste compromis passe par le WAF, la compromission du poste n'est pas simulée) ; rotation des secrets (faite une fois, à la main) ; usurpation d'opérateur (limite connue, non testée par une photo) |
| **Non démontrable en 4 jours** | DDoS volumétrique, rançongiciel réel, compromission de GitHub, second site, TLPT, notifications réglementaires réelles |
