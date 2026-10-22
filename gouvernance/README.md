# Gouvernance : PROJECT RESILIENCE-ALPHA

Volet gouvernance du workshop EPSI M2 (sujet § 3.5). Il traite de **Resilience Pay SAS**, un
établissement de paiement fictif qui exploite la plateforme du démonstrateur. Les données
d'entreprise sont fictives. Les chiffres techniques sont **mesurés** sur le démonstrateur les
20 et 21/10/2026 ; leur source est dans `../infra/docs/`.

## Documents

| Fichier | Contenu |
|---|---|
| [00-cadre.md](00-cadre.md) | Hypothèses communes : organisation fictive, rôles, valeurs métier VM1–VM5, échelles G1–G4 / V1–V4, biens supports, faits mesurés |
| [01-bia.md](01-bia.md) | Bilan d'impact : services critiques, dépendances, coût de l'arrêt par durée, DMIA / PDMA, RTO / RPO cibles comparés aux mesures, modes dégradés |
| [02-ebios-rm.md](02-ebios-rm.md) | Analyse de risques EBIOS RM en 5 ateliers : événements redoutés, sources de risque, scénarios, risques R1–R10 initial / actuel / cible, PACS P0–P3 |
| [03-pca-pra.md](03-pca-pra.md) | PCA/PRA organisationnel : niveaux d'incident I1–I4, astreinte, cellule de crise, RACI, scénarios S1–S11, choix de restauration, communication, risques après reprise |
| [04-nis2-dora.md](04-nis2-dora.md) | Applicabilité de DORA et NIS2, matrice exigence / preuve / statut, cas pratique de classification d'incident, ce qu'un prototype ne peut pas démontrer |
| [05-arbitrages-recommandations.md](05-arbitrages-recommandations.md) | Arbitrages A1–A14, indicateurs KPI / KRI, recommandations Rec1–Rec18, décisions D1–D5 demandées à la direction |
| [dossier-gouvernance.md](dossier-gouvernance.md) | Version condensée (3 à 4 pages) pour le dossier PDF |

## Comment lire

- **Direction, jury pressé** : la synthèse ci-dessous, puis `dossier-gouvernance.md`.
- **Vérifier un chiffre** : `00-cadre.md` § 6 (faits mesurés) renvoie aux documents de l'infra
  (`tests-resilience.md`, `waf.md`, `pca-pra-technique.md`, `dossier/infra.md`).
- **Ordre logique** : cadre → BIA (ce que coûte l'arrêt) → EBIOS RM (ce qui peut l'arrêter) →
  PCA/PRA (comment on continue et on reprend) → NIS2/DORA (ce que le régulateur attend) →
  arbitrages et recommandations (ce que l'on décide).
- **Identifiants** : VM = valeur métier ; ER = événement redouté ; R1–R10 = risques EBIOS ;
  P0–P3 = priorités du PACS ; S1–S11 = scénarios du PCA/PRA ; I1–I4 = niveaux d'incident ;
  A1–A14 = arbitrages ; Rec1–Rec18 = recommandations ; D1–D5 = décisions demandées.
- **Statuts** : démontré (mesuré), partiel, non démontrable en 4 jours ; « à vérifier » signale
  une référence réglementaire non relue.

## Synthèse pour la direction

1. Le service vital est l'**encaissement** : 3 000 € de commissions et 156 000 € de ventes des
   commerçants bloqués par heure de pointe ; 1 h d'arrêt ≈ 16 k€, 4 h ≈ 103 k€, 24 h ≈ 463 k€.
2. Le seuil réglementaire précède le seuil financier : un arrêt complet en pointe devient
   probablement un **incident majeur DORA dès ≈ 50 min**, à notifier à l'ACPR.
3. Sur les pannes courantes, la plateforme se rétablit **seule en 0 à 22 s** (14 pannes sur 14,
   0 intervention humaine, 0 paiement perdu), bien sous la DMIA de 15 min.
4. Les points uniques du paiement les plus graves ont été retirés et mesurés : base répliquée
   (92 s → 0 s), frontal à 3 réplicas (11 s → 0 s).
5. La résilience démontrée est une résilience de **disponibilité** : redémarrer ne chasse pas un
   attaquant ; isolement, rotation des secrets et restauration restent humains.
6. EBIOS RM : les 7 risques critiques de départ sont ramenés à « élevé » ou moins ; 5 risques G4
   restent élevés, tous liés à un compte privilégié ou à la chaîne de production compromis.
7. Écarts principaux : **un seul site** (sinistre non couvert), WAF et Stripe sans relève
   automatique, Vault descellé à la main.
8. RPO de la base : 15 min sur le lab, mais **24 h en cas de rançongiciel** : les dumps ne
   sortent du lab qu'une fois par jour. Les copier hors du lab à chaque exécution (Rec6).
9. DORA s'applique en entier ; NIS2 n'a d'effet qu'indirect. La partie technique est démontrée,
   la partie organisationnelle (gouvernance, contrats, notification) relève de la direction.
10. Cinq décisions demandées : second site, programme « zéro point unique », FIDO2 à la place
    de la biométrie, pilotage par indicateurs mesurés, exercices et gestion des prestataires.

## Correspondance avec le sujet (§ 3.5)

| Exigence du sujet | Document et section |
|---|---|
| Services jugés critiques | `01-bia.md` § 1 ; `02-ebios-rm.md` atelier 1 (§ 1.2) ; `00-cadre.md` § 3 |
| Coût de l'arrêt d'une fonction de paiement | `01-bia.md` § 2 (coût par heure, pénalités SLA, coûts indirects, total par durée) |
| Analyse structurée des risques (EBIOS RM) | `02-ebios-rm.md`, ateliers 1 à 5 ; cartographie avant / après § 5.2 |
| Objectifs de continuité et de reprise cohérents avec le démonstrateur | `01-bia.md` § 3 (DMIA, PDMA, RTO / RPO cibles et mesurés) |
| PCA/PRA : scénarios couverts | `03-pca-pra.md` § 3 (S1–S11, fiches) |
| PCA/PRA : responsabilités | `03-pca-pra.md` § 2 (niveaux, astreinte, cellule de crise, RACI) |
| PCA/PRA : choix de restauration | `03-pca-pra.md` § 4 (redémarrer, basculer, restaurer, reconstruire ; sauvegarde compromise) |
| PCA/PRA : risques qui subsistent après la reprise | `03-pca-pra.md` § 7 ; `02-ebios-rm.md` § 5.4 |
| NIS2 / DORA : exigences pertinentes | `04-nis2-dora.md` § 1 et § 2 (matrice DORA), § 3 (grille NIS2), § 4 (cas pratique) |
| NIS2 / DORA : obligations non démontrables par un prototype | `04-nis2-dora.md` § 5 ; `02-ebios-rm.md` § 5.6 |
| Arbitrages | `05-arbitrages-recommandations.md` § 1 et § 2 (A1–A14) |
| Recommandations à une direction | `05-arbitrages-recommandations.md` § 4 (Rec1–Rec18), § 6 (D1–D5) ; `04-nis2-dora.md` § 6 |
| Éléments vérifiables fondant les décisions | `05-arbitrages-recommandations.md` § 3 (KPI / KRI et leur source) ; `00-cadre.md` § 6 |

## Points « à vérifier »

Références réglementaires et hypothèses non confirmées, à relire avant toute utilisation hors
du workshop :

1. Canal et portail de déclaration des incidents majeurs à l'ACPR (`04` § 1.1, § 2.2).
2. Numéro du RTS sur les TLPT et désignation éventuelle de l'établissement par l'ACPR (art. 26)
   (`04` § 1.1, § 2.3 ; `02` § 5.5 ; `05` Rec15).
3. Numéro du considérant de NIS2 présentant DORA comme *lex specialis* (`04` § 1.2).
4. État de la transposition française de NIS2 (adoption, promulgation, extension éventuelle du
   champ) et recours de la Commission devant la CJUE (`04` § 1.2) ; copie éventuelle à l'ANSSI
   d'une notification (`04` § 3).
5. Aménagements de délai de notification pour les week-ends et jours fériés ; contenu exact des
   modèles de l'ITS 2025/302 (`04` § 4.3 ; `03` § 5.2).
6. Délais de notification DORA cités dans le BIA et le PCA/PRA (`01` § 2.3 ; `03` § 5.1),
   vérifiés dans `04` § 4.3 (règlement délégué 2025/301, art. 5).
7. Article de DORA sur les tests annuels des plans de continuité (`03` § 6.1).
8. Clauses contractuelles DORA avec les prestataires (art. 28 et suivants) (`02` § 3.3).
9. Cadre de la CNIL sur la biométrie au travail ; base légale et consentement des opérateurs ;
   chiffrement applicatif des gabarits (`04` § 1.3 ; `02` § 1.4).
10. Exclusion de la vérification biométrique « un pour un » des systèmes à haut risque du
    règlement IA (`04` § 1.3).
11. Communauté sectorielle de partage d'information (CERT ou ISAC financier) (`04` § 2.5).
12. Protection des branches du dépôt GitHub (`02` SO8).
13. Lien Internet unique de l'hébergeur (`01` § 1.2).
14. Hypothèses de calcul des pénalités SLA (tranche entamée due, plafond) à préciser au contrat
    (`01` § 2.2).
15. Mesure à refaire : perte d'un hyperviseur mesurée par la sonde (`node-loss`, déplacement des
    machines par la HA non chronométré) ; perte du WAF non mesurée (`01` § 3.2 ; `03` S5).
