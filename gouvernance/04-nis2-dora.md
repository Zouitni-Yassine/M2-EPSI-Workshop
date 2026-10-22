# 04 — NIS2 et DORA : ce qui s'applique, ce que le démonstrateur prouve

Ce document répond à la consigne du sujet (§ 3.5) : analyser les enjeux NIS2 et DORA de
Resilience Pay, **en distinguant les exigences pertinentes des obligations qu'un prototype de
quatre jours ne peut pas démontrer**. Il s'appuie sur l'organisation fictive du
[cadre commun](00-cadre.md) et sur les essais mesurés du démonstrateur
([`tests-resilience.md`](../infra/docs/tests-resilience.md),
[`pca-pra-technique.md`](../infra/docs/pca-pra-technique.md)). Ce n'est pas un avis juridique :
les références sont citées avec prudence, et tout point non vérifié est marqué « à vérifier ».

Statuts utilisés :

| Statut | Sens |
|---|---|
| **Démontré** | Mécanisme en place et mesuré sur le démonstrateur, avec un chiffre et un document |
| **Partiel** | Mécanisme en place, mais incomplet, non mesuré ou sans le volet organisationnel |
| **Non démontrable en 4 jours** | Obligation de gouvernance, de contrat ou de durée : un prototype ne peut pas la prouver |

## 1. Quel texte s'applique à Resilience Pay ?

### 1.1 DORA s'applique directement

| Question | Réponse | Référence |
|---|---|---|
| Resilience Pay est-elle dans le champ ? | **Oui.** Les établissements de paiement sont des entités financières au sens de DORA | Règlement (UE) 2022/2554, art. 2(1)(b) |
| Depuis quand ? | 17 janvier 2025. Un règlement : applicable sans transposition | Art. 64 |
| Régime complet ou simplifié ? | **Complet.** Le cadre simplifié de l'art. 16 vise les établissements de paiement *exemptés* ; Resilience Pay est agréée (hypothèse du cadre). Elle n'est pas une microentreprise (85 salariés, 9 M€) | Art. 16(1), art. 3 |
| Proportionnalité | Oui : les exigences s'appliquent selon la taille, le profil de risque, la nature et la complexité de l'activité. 2 400 commerçants, 470 M€ de flux par an : établissement de taille modeste, sans caractère systémique | Art. 4 |
| Autorité compétente | ACPR (contrôle des établissements de paiement en France) | Art. 46 ; canal de déclaration ACPR **à vérifier** |
| Textes de niveau 2 utiles | RTS gestion du risque TIC (règlement délégué (UE) 2024/1774) ; RTS classification des incidents (2024/1772) ; RTS et ITS sur la notification (2025/301 et 2025/302) ; ITS registre d'information (2024/2956) ; RTS TLPT (numéro **à vérifier**) | — |

DORA remplace aussi, pour un établissement de paiement, l'ancienne déclaration des incidents
opérationnels et de sécurité de la DSP2 : l'art. 23 de DORA rattache ces incidents à son propre
régime de notification.

### 1.2 NIS2 : peu d'effet direct, mais trois raisons de s'y intéresser

**Constat vérifié dans le texte** : l'annexe I de la directive (UE) 2022/2555 (NIS2) ne cite,
pour le secteur bancaire, que les **établissements de crédit** (et, pour les infrastructures de
marchés financiers, les plates-formes de négociation et les contreparties centrales). Les
établissements de paiement n'y figurent pas, ni à l'annexe II. Resilience Pay n'est donc pas, par
son activité, une entité essentielle ou importante au sens de NIS2.

Même pour une banque, NIS2 s'efface devant DORA : l'art. 4 de NIS2 écarte ses dispositions
(mesures de l'art. 21, notification de l'art. 23, supervision) lorsqu'un acte sectoriel de l'Union
impose des obligations au moins équivalentes. C'est le cas de DORA, que les textes présentent
comme *lex specialis* (considérant de NIS2 relatif à DORA, numéro **à vérifier**).

NIS2 reste pertinente pour trois raisons :

1. **Les prestataires** : plusieurs fournisseurs de Resilience Pay sont, eux, dans le champ de NIS2
   (fournisseurs de cloud et de centres de données, fournisseurs de services gérés, opérateurs de
   communications électroniques, prestataires de confiance). Leur conformité NIS2 est un élément
   de la due diligence exigée par DORA (art. 28 et suivants).
2. **Une grille de lecture** : les dix mesures de l'art. 21 de NIS2 recoupent le cadre de DORA et
   sont plus lisibles pour une direction (§ 3).
3. **La transposition française** : le projet de loi « relatif à la résilience des infrastructures
   critiques et au renforcement de la cybersécurité » transpose NIS2, la directive REC (CER) et la
   directive (UE) 2022/2556 qui accompagne DORA. Adopté par le Sénat en mars 2025, il était inscrit
   à l'Assemblée nationale à partir du 7 octobre 2026. **Adoption définitive, promulgation et
   éventuelle extension du champ par le droit français : à vérifier** à la date du rendu. La
   Commission européenne aurait saisi la CJUE contre la France en juillet 2026 pour défaut de
   transposition (**à vérifier**).

### 1.3 En marge : RGPD et DSP2

| Texte | Point de contact avec le démonstrateur | Conséquence |
|---|---|---|
| RGPD, art. 9 | `auth` compare le visage des **opérateurs du back-office** à un gabarit (vecteur de 128 nombres, aucune image conservée, `auth/app/face.py`). Un gabarit biométrique servant à identifier une personne est une donnée sensible | Interdiction de principe sauf exception de l'art. 9(2) ; le consentement d'un salarié est rarement libre. Analyse d'impact (art. 35) obligatoire, alternative non biométrique à proposer, cadre de la CNIL sur la biométrie au travail (**à vérifier** : texte en vigueur) |
| RGPD, art. 33 | Fuite de données de payeurs ou de gabarits | Notification à la CNIL sous 72 h, en parallèle de DORA (rôle du DPO) |
| Règlement IA | Vérification biométrique « un pour un » destinée seulement à confirmer l'identité | Exclue *a priori* des systèmes à haut risque de l'annexe III (**à vérifier**) |
| DSP2 (directive (UE) 2015/2366) et RTS 2018/389 | Authentification forte des **payeurs** | Portée par le prestataire (Stripe, 3-D Secure) dans le démonstrateur, pas par Resilience Pay. La TOTP des administrateurs (Keycloak) relève de la sécurité interne, pas de la DSP2 |

Limite à signaler : la reconnaissance faciale n'a **pas de détection du vivant** (cadre § 6) ;
une photo pourrait suffire. C'est un facteur en plus du mot de passe, pas un facteur fort.

## 2. Matrice DORA : exigence, preuve, statut

Lecture : la colonne « Preuve » cite le chiffre mesuré et le document du dépôt. La dernière
colonne dit ce que l'entreprise réelle devrait ajouter.

### 2.1 Gouvernance et cadre de gestion du risque TIC (art. 5 à 16)

| Article | Exigence (résumé) | Ce que le démonstrateur prouve | Statut | En contexte réel |
|---|---|---|---|---|
| 5 | L'organe de direction définit, approuve, supervise le cadre et en porte la responsabilité finale ; il se forme | Rien : c'est une obligation de gouvernance. Rôles posés dans le [cadre](00-cadre.md) § 2 | Non démontrable | Délibération du conseil, budget TIC voté, formation annuelle des dirigeants (art. 5(4)) |
| 6 | Cadre de gestion du risque TIC documenté, revu chaque année, audité ; stratégie de résilience opérationnelle numérique | Analyse de risques ([EBIOS RM](02-ebios-rm.md)), [BIA](01-bia.md), objectifs RTO/RPO ([PCA/PRA](03-pca-pra.md)) ; architecture documentée (`infra/docs/architecture.md`, décisions D1 à D10) | Partiel | Politique formalisée, revue annuelle, audit interne indépendant (art. 6(6)), indicateurs de tolérance au risque |
| 7 | Systèmes TIC fiables, à jour, dimensionnés | Tout en code (Packer, Terraform, Ansible) ; playbooks idempotents (`changed=0` au second passage) ; rafale de 40 requêtes parallèles absorbée, **0 s** de panne | Partiel | Gestion de capacité, tests de charge au pic réel (6 transactions/s, soldes) |
| 8 | Identifier les fonctions, actifs, dépendances, risques ; inventaire | Chaîne de paiement et dépendances (`pca-pra-technique.md` § 1) ; inventaire des comptes et secrets (`comptes-et-rotation.md`) ; machines déclarées dans Terraform | Partiel | CMDB complète, cartographie des fonctions critiques ou importantes, revue annuelle |
| 9 | Protection et prévention : sécurité réseau, contrôle d'accès, authentification forte, chiffrement, gestion des changements et des correctifs | Segmentation en VLAN (RA-APP, RA-DMZ, MANAGEMENT) + nftables en politique `drop`, testée depuis un worker ; WAF seul point d'entrée ; SSO Keycloak + TOTP ; secrets dans Vault, aucun `.env` ; passerelle de remédiation à liste fermée (11 cas sur 11 conformes) ; rotation de tous les secrets le 20/10 | **Démontré** (technique) | Politique de correctifs, gestion des changements, chiffrement des flux internes (Grafana en HTTP, webhook en HTTP : `identites.md` § 10, `waf.md`) |
| 10 | Détecter rapidement les activités anormales, seuils d'alerte | Détecteur ML : anomalie en **2 à 4 s** (F1 0,86, rappel 0,92) ; règles vmalert et Loki ; journaux de 17 machines dans Loki ; Watchdog externe (healthchecks.io) qui détecte la mort de la chaîne d'alerte | **Démontré** | SOC ou service managé 24/7, rétention des journaux au-delà de 14 jours (`supervision.md` § 6) |
| 11 | Réponse et rétablissement : politique de continuité, plans testés au moins une fois par an, objectifs de reprise | API arrêtée : reprise en **10 à 16 s** sans humain ; base tuée : **7,5 s**, 0 paiement perdu ; perte d'un hyperviseur : application disponible ; force brute : IP bannie en **27 s** | **Démontré** (disponibilité) | Plan de continuité d'activité métier (pas seulement technique), cellule de crise, exercice annuel avec la direction |
| 11 (suite) | Traiter aussi la compromission, pas seulement la panne | `restart` et `rollback` rétablissent la disponibilité, pas l'intégrité ; isolement d'un service compromis **non implémenté** | Partiel | Procédure d'investigation, isolement, reconstruction depuis Git, rotation des secrets |
| 12 | Sauvegardes, restauration testée sur des systèmes séparés, redondance | PBS hors du lab (13h00, 21h00) : restauration en **40 s**, RTO ≈ 1 min ; `pg_dump` toutes les 15 min : **423 paiements restaurés en 0,7 s** (RPO mesuré 15 min, cible BIA 5 min : écart) ; base répliquée (Patroni) : perte du primaire **92 s → 0 s** | **Démontré** | Seconde copie hors site, rétention conforme aux obligations de conservation, reprise complète du site jamais testée (`pca-pra-technique.md` § 6) |
| 12 | Capacité redondante | 3 hyperviseurs, HA, Ceph, 3 réplicas du frontal ; **un seul site** sur un même hôte parent | Partiel | Second site ou cloud, PRA de site testé |
| 13 | Apprendre : analyse post-incident, veille, formation de tout le personnel | Les tests ont trouvé et fait corriger des défauts : bug `retry_in = 0` du moteur (72,5 s → réparation normale), `/api/health` aveugle à la base, base point unique (92 s) corrigée par la réplication | Partiel | Processus de retour d'expérience formel, programme de sensibilisation obligatoire (art. 13(6)) |
| 14 | Plans de communication interne et externe, en cas d'incident | Alertes vers Discord, chaque bannissement notifié aux humains | Partiel | Plan de communication commerçants, payeurs, presse ; porte-parole désigné ; messages préparés |
| 16 | Cadre simplifié | Sans objet (Resilience Pay est agréée, non exemptée) | — | — |

### 2.2 Incidents liés aux TIC (art. 17 à 23)

| Article | Exigence | Ce que le démonstrateur prouve | Statut | En contexte réel |
|---|---|---|---|---|
| 17 | Processus de gestion des incidents : détection, enregistrement, rôles, escalade | Chaque panne est horodatée (`/root/chaos/resultats.tsv`, annotations Grafana « Tests de chaos ») ; chaque action de la passerelle et chaque bannissement tracés dans Loki | Partiel | Outil de tickets, registre de tous les incidents, astreinte formalisée, critères d'escalade vers la direction |
| 18 | Classer les incidents selon les critères du RTS 2024/1772 | Les données existent : durée de panne vue par la sonde, transactions perdues (116 avant, 117 après `db-kill`), services touchés ; voir le cas pratique § 4 | Partiel | Grille de classification outillée, calcul automatique des seuils (clients, transactions, durée) |
| 19 | Notifier l'ACPR des incidents majeurs ; informer les clients touchés ; notification volontaire des cybermenaces importantes | Rien : aucune notification réelle | Non démontrable | Procédure, modèles de l'ITS 2025/302 pré-remplis, signataire (DG), astreinte conformité |
| 20 à 22 | Modèles harmonisés, centralisation, retour du superviseur | Sans objet pour un prototype | Non démontrable | Accès au portail de l'ACPR (**à vérifier**) |
| 23 | Incidents opérationnels ou de sécurité liés aux paiements | Le paiement est la fonction testée : la sonde fait un vrai paiement toutes les 30 s | Partiel | Rattachement de ces incidents au régime DORA |

### 2.3 Tests de résilience opérationnelle numérique (art. 24 à 27)

| Article | Exigence | Ce que le démonstrateur prouve | Statut | En contexte réel |
|---|---|---|---|---|
| 24 | Programme de tests, proportionné, au moins une fois par an sur les systèmes qui soutiennent des fonctions critiques ou importantes, par des testeurs indépendants | `infra/chaos/chaos.sh` : 14 tests en 3 couches (Appli, Conteneur, Virtualisation), garde-fous (état de départ sain, pas pendant une sauvegarde), résultats reproductibles. **14 pannes sur 14 réparées sans humain** | **Démontré** (programme technique) | Programme annuel validé par la direction ; indépendance des testeurs (art. 24(4)) ; suivi des correctifs |
| 25 | Types de tests : vulnérabilités, réseau, scénarios, performance, bout en bout, tests d'intrusion | Scénarios et bout en bout (sonde) : faits. Réseau : filtrage testé depuis un worker. Intrusion : red team de l'équipe cyber (PC admin compromis). Scans de vulnérabilités, revue de code : non faits | Partiel | Scans réguliers, revue de code, test d'intrusion externe annuel |
| 26, 27 | Tests de pénétration fondés sur la menace (TLPT) tous les 3 ans, par des testeurs qualifiés | Pas de TLPT. Le TLPT n'est dû que par les entités **désignées par l'autorité** (art. 26(8)), selon leur impact et leur caractère systémique | Non démontrable | Probablement non désignée vu sa taille (**à vérifier** auprès de l'ACPR) ; s'y préparer quand même |

### 2.4 Risque lié aux prestataires tiers de services TIC (art. 28 à 44)

| Article | Exigence | Ce que le démonstrateur prouve | Statut | En contexte réel |
|---|---|---|---|---|
| 28(2) | Stratégie et politique sur le risque prestataires | Liste des prestataires dans le [cadre](00-cadre.md) § 5 (Stripe, PayPal, GitHub, S3, Discord, healthchecks.io, Let's Encrypt, FAI) | Partiel | Politique écrite, classement des prestataires selon la fonction soutenue |
| 28(3) | **Registre d'information** de tous les contrats TIC, transmis à l'ACPR chaque année | Aucun registre au format de l'ITS 2024/2956 | Non démontrable | Registre tenu par la conformité, mis à jour à chaque contrat |
| 28(4) à (6) | Due diligence avant contrat, audits | Choix techniques argumentés (`architecture.md`), pas de due diligence contractuelle | Non démontrable | Questionnaires, certifications (ISO 27001, SOC 2, PCI DSS), conformité NIS2 du prestataire |
| 28(8) | **Stratégie de sortie** testée pour les fonctions critiques | PayPal intégré à côté de Stripe, mais **bascule non automatique** ; Stripe indisponible = pas de paiement (`pca-pra-technique.md` § 6) | Partiel | Second acquéreur actif, bascule testée, plan de transition documenté |
| 29 | Risque de concentration | Réduit sur l'hébergement (tout est auto-hébergé, en code), fort sur l'acquisition (Stripe) | Partiel | Analyse de substituabilité par prestataire |
| 30 | Clauses contractuelles minimales (niveaux de service, localisation des données, accès, audit, réversibilité) | Sans objet : comptes de test | Non démontrable | Revue juridique des contrats Stripe, PayPal, hébergeurs |
| 31 à 44 | Supervision des prestataires critiques par les autorités européennes | Concerne les prestataires désignés, pas Resilience Pay | Sans objet | Savoir si un prestataire est désigné critique (liste publiée par les AES) |

Point d'attention propre au démonstrateur : la chaîne d'alerte passe par **Discord** et
**healthchecks.io**, le code et le build par **GitHub**. Ce sont des prestataires TIC au sens de
DORA. En production, une alerte vitale ne devrait pas dépendre d'un service grand public sans
contrat.

### 2.5 Partage d'information (art. 45)

| Exigence | Démonstrateur | Statut | En contexte réel |
|---|---|---|---|
| Échange volontaire d'informations sur les cybermenaces au sein de communautés de confiance ; participation déclarée à l'autorité (art. 45(3)) | Les règles de détection (Loki, WAF) et les indicateurs (IP bannies) existent et pourraient être partagés | Non démontrable | Adhésion à une communauté sectorielle (CERT ou ISAC du secteur financier, **à vérifier**), déclaration à l'ACPR |

## 3. Grille NIS2 condensée

Pertinence : **indirecte**, Resilience Pay n'étant pas dans le champ de NIS2 (§ 1.2). La grille
sert à vérifier qu'aucune mesure de l'art. 21(2) n'est oubliée, et à évaluer les prestataires.

| Art. 21(2) | Mesure | Équivalent DORA | Démonstrateur | Statut |
|---|---|---|---|---|
| a | Analyse des risques, politiques de sécurité | Art. 6, 8 | EBIOS RM, BIA | Partiel |
| b | Gestion des incidents | Art. 17 à 19 | Détection 2–4 s, reprise 10–16 s, traces Loki ; pas de processus formel | Partiel |
| c | Continuité, sauvegardes, reprise, gestion de crise | Art. 11, 12 | PBS (40 s), `pg_dump` (0,7 s), réplication (0 s) ; cellule de crise non exercée | Démontré (technique) |
| d | Sécurité de la chaîne d'approvisionnement | Art. 28 à 30 | Liste des prestataires ; images construites depuis le dépôt, registre privé | Partiel |
| e | Sécurité de l'acquisition, du développement, de la maintenance ; vulnérabilités | Art. 9 | Tout en code, revue du diff avant chaque push (recherche de secrets) ; pas de scan de vulnérabilités | Partiel |
| f | Évaluer l'efficacité des mesures | Art. 24, 25 | Programme `chaos.sh`, 14/14 | Démontré |
| g | Hygiène informatique, formation | Art. 13(6) | — | Non démontrable |
| h | Cryptographie, chiffrement | Art. 9 | CA interne, TLS public (Let's Encrypt, HSTS) ; flux internes partiellement en clair | Partiel |
| i | Sécurité des ressources humaines, contrôle d'accès, gestion des actifs | Art. 8, 9 | Groupes Keycloak, comptes de secours dans Vaultwarden, inventaire des comptes | Partiel |
| j | Authentification multifacteur, communications sécurisées, communications d'urgence | Art. 9 | TOTP sur Grafana et Proxmox ; visage + mot de passe sur le back-office ; canal d'urgence = Discord | Partiel |

**Art. 20 (gouvernance)** : approbation des mesures par la direction et formation des
dirigeants. Même logique que l'art. 5 de DORA. Non démontrable.

**Art. 23 (notification)** : alerte précoce sous 24 h, notification sous 72 h, rapport final sous
un mois, vers le CSIRT ou l'autorité (ANSSI en France). Pour Resilience Pay, c'est le calendrier
DORA vers l'ACPR qui s'applique (§ 4.3). Une éventuelle copie à l'ANSSI prévue par le droit
français : **à vérifier**.

## 4. Cas pratique : deux incidents passés à la grille DORA

### 4.1 La règle (RTS 2024/1772, vérifiée)

Un incident est **majeur** s'il touche des **services critiques** (art. 6 du RTS) **et** soit
remplit le seuil « pertes de données » par accès malveillant réussi (art. 9(5)(b)), soit remplit
**au moins deux** des autres seuils de l'art. 9 :

| Critère | Seuil de matérialité (art. 9) | Valeur pour Resilience Pay |
|---|---|---|
| Clients, contreparties, transactions | > 10 % des clients du service, ou > 100 000 clients, ou > 10 % du nombre ou de la valeur des transactions quotidiennes moyennes | 10 % = 240 commerçants ; 10 % des transactions = **2 500 transactions** (≈ 130 000 €) |
| Réputation | Couverture médiatique, plaintes répétées, manquement réglementaire, perte probable de clients | — |
| Durée et indisponibilité | Incident > 24 h, ou indisponibilité > **2 h** d'un service soutenant une fonction critique | — |
| Étendue géographique | Au moins 2 États membres | Selon la clientèle des commerçants (payeurs étrangers) |
| Pertes de données | Atteinte à la disponibilité, l'authenticité, l'intégrité ou la confidentialité des données ; ou accès malveillant réussi pouvant entraîner une perte | — |
| Impact économique | Coûts et pertes > **100 000 €** | Atteint vers 4 h d'arrêt en pointe ([BIA](01-bia.md) : 1 h 16 k€, 4 h 103 k€, 24 h 463 k€, 72 h 1,3 M€) |

Le service « encaisser un paiement » (VM1) est un service financier soumis à agrément : tout
incident qui le touche touche un **service critique** (art. 6(b) du RTS). Un incident récurrent
(deux fois en six mois, même cause apparente) peut devenir majeur par cumul (art. 8(2) du RTS).

**Conséquence chiffrée** : en heure de pointe (3 000 transactions par heure), le seuil de 10 %
des transactions quotidiennes est atteint après **≈ 50 minutes** d'arrêt complet. Si l'on
considère, par prudence, que tous les commerçants sont touchés par un arrêt complet, le seuil
« clients » est atteint en même temps. **Un arrêt complet d'une heure en pointe serait donc
probablement majeur** (deux seuils), avant même le seuil de durée de 2 h, alors que son coût
reste modeste (16 k€, G2 au [BIA](01-bia.md)).

Hors pointe, le seuil est atteint vers **2 à 4 h** d'arrêt (seuil de durée de 2 h, puis
103 k€ à 4 h, au-dessus du seuil économique de 100 k€) : en journée (800 transactions par
heure), les 10 % de transactions ne sont atteints qu'en ≈ 3 h. **En pointe, il l'est dès
≈ 50 minutes.** Le BIA ([01-bia.md](01-bia.md) § 2.3 et 2.4) et le PCA/PRA
([03-pca-pra.md](03-pca-pra.md) § 2.1) retiennent ces deux lectures, avec une règle de
prudence : passer en niveau I3 et préparer la classification dès que la DMIA de l'encaissement
(15 min) est dépassée. La reprise mesurée (0 à 22 s selon la panne, cible
RTO 1 min) reste très loin de ces seuils.

### 4.2 Classification

| Critère | Cas A : rafale applicative (attaque de démonstration) | Cas A' : même attaque, sans parade, 3 h en pointe | Cas B : PC admin compromis (red team) |
|---|---|---|---|
| Ce qui se passe | 45 s, 40 requêtes parallèles ; anomalie vue à +4 s, redémarrage de payment-api en 13,8 s ; au-delà de 20 requêtes/s, IP bannie au WAF | Attaque distribuée sous les seuils de bannissement (limite connue, `waf.md`) ; API saturée | Poste d'un administrateur pris en main sur le VPN EPSI-WG ; la segmentation l'oblige à passer par le WAF |
| Service critique touché | Oui (paiement) | Oui | Oui si l'accès réussit : un accès malveillant réussi rend le service « critique » à lui seul (art. 6(c)) |
| Clients, transactions | **0** transaction perdue, **0 s** de panne vue par la sonde | ≈ 9 000 transactions (36 % de la moyenne) : **seuil atteint** | Dépend de l'action de l'attaquant |
| Durée, indisponibilité | 0 s | 3 h > 2 h : **seuil atteint** | — |
| Étendue géographique | Non | Possible | Non |
| Pertes de données | Non | Non | **Seuil atteint** si l'attaquant accède au back-office (historique des paiements, gabarits biométriques) ; non atteint s'il est arrêté au WAF |
| Impact économique | Négligeable | 3 × 3 000 € = 9 k€ de commissions, 468 k€ de ventes des commerçants bloquées ; coût total entre 16 k€ (1 h) et 103 k€ (4 h) au BIA : sous le seuil de 100 k€ | Investigation, rotation des secrets, notification : à chiffrer |
| Réputation | Non | Probable (plaintes de commerçants) | Probable si fuite |
| **Verdict** | **Non majeur.** Incident enregistré et classé (art. 17), pas de notification. Surveiller la récurrence (art. 8(2) du RTS) | **Majeur** (service critique + deux seuils) | **Deux branches** : arrêté au WAF et banni = non majeur, éventuellement notification **volontaire** d'une cybermenace importante (art. 19(2)) ; accès réussi au back-office = **majeur** par la seule règle des pertes de données, plus notification CNIL sous 72 h (RGPD art. 33) et information des clients (art. 19(3)) |

Ce que montre la comparaison A / A' : le démonstrateur rend **la disponibilité** réparable en
secondes, ce qui maintient un incident de type DoS sous les seuils. Il ne protège pas d'une
compromission : le cas B est majeur dès qu'un accès réussit, quelle que soit la durée de panne.
Les priorités de conformité diffèrent donc pour les deux familles d'incidents.

### 4.3 Calendrier de notification à l'ACPR (règlement délégué (UE) 2025/301, art. 5)

Exemple : cas A' commencé à 18h00, un vendredi.

| Étape | Délai réglementaire (vérifié) | Exemple | Qui |
|---|---|---|---|
| Détection | — | 18h00 : alerte `PaiementTransactionProbeFailing`, anomalie ML | Astreinte N1 |
| Classification comme majeur | Dès que possible | 19h00 (seuil de 10 % des transactions atteint vers 18h50) | RSSI + conformité, validée par la DG |
| **Notification initiale** | Dans les **4 h** suivant la classification, et au plus tard **24 h** après la prise de connaissance | Au plus tard vendredi 23h00 | Conformité, signée par la DG |
| **Rapport intermédiaire** | Au plus tard **72 h** après la notification initiale ; mis à jour quand l'activité normale reprend | Au plus tard lundi 23h00 | Conformité, DSI |
| **Rapport final** | Au plus tard **un mois** après le dernier rapport intermédiaire | Avec l'analyse des causes | Conformité, RSSI, DSI |
| Information des clients | Sans retard injustifié si leurs intérêts financiers sont touchés (art. 19(3) de DORA) | Message aux commerçants le soir même | Communication |

Aménagements pour les week-ends et jours fériés prévus par le RTS pour certaines entités :
**à vérifier**. Contenu et format des rapports : ITS 2025/302.

Le démonstrateur fournit déjà une bonne partie du contenu des rapports : heure de début et de
fin (sonde, annotations Grafana), services touchés, transactions perdues (comptage en base),
actions de remédiation (journal de la passerelle dans Loki), IP sources (journal du WAF). Il ne
fournit ni l'outil de classification ni le processus de décision.

## 5. Ce qu'un prototype ne peut pas démontrer, et comment y répondre

| Obligation | Pourquoi le prototype ne le prouve pas | Réponse de l'entreprise | Porteur |
|---|---|---|---|
| Responsabilité de l'organe de direction (DORA art. 5) | C'est une décision et un suivi dans la durée | Le conseil approuve le cadre et la tolérance au risque, reçoit un tableau de bord trimestriel (indicateurs du § 6) | DG |
| Formation des dirigeants et du personnel (art. 5(4), 13(6)) | Effet humain, sur la durée | Plan de formation annuel, exercice de crise sur table à partir des scénarios de ce dossier | RSSI |
| Cadre documenté, revu chaque année, audité (art. 6(5), 6(6)) | Un audit suppose de l'historique | Politique de risque TIC, revue annuelle, audit interne puis externe | Conformité |
| Registre d'information des prestataires (art. 28(3)) | Pas de contrat réel | Registre au format ITS 2024/2956, déclaration annuelle à l'ACPR | Conformité |
| Clauses contractuelles et stratégie de sortie (art. 28(8), 30) | Comptes de test | Revue des contrats Stripe, PayPal, hébergeur ; second acquéreur actif ; test de sortie annuel | Achats, DSI |
| TLPT (art. 26) | Exige des testeurs externes qualifiés et un cadre (TIBER) | Vérifier auprès de l'ACPR si l'établissement est désigné ; sinon test d'intrusion externe annuel | RSSI |
| Notification réelle (art. 19) | Aucun incident réel | Procédure écrite, modèles pré-remplis, exercice de notification à blanc | Conformité |
| Indépendance des tests (art. 24(4)) | Les tests sont faits par l'équipe qui a construit | Tests par une équipe distincte ou un prestataire | RSSI |
| Partage d'information (art. 45) | Pas de communauté | Adhésion à une communauté sectorielle | RSSI |
| Conformité RGPD de la biométrie | Analyse juridique et consultation des salariés | AIPD, alternative non biométrique, information du personnel, avis du DPO | DPO |
| Conservation des preuves | Journaux gardés 14 jours, lab éteint la nuit | Rétention alignée sur les obligations légales et le besoin d'enquête, stockage immuable | DSI |

## 6. Synthèse pour la direction : sept priorités

| # | Priorité | Pourquoi (élément vérifiable) | Indicateur de suivi |
|---|---|---|---|
| 1 | **Faire porter DORA par la direction** : cadre de risque TIC approuvé, rôle de la fonction de contrôle, budget | Obligation de l'art. 5, non démontrable par la technique ; c'est la première question d'un contrôle de l'ACPR | Délibération du conseil ; revue annuelle faite |
| 2 | **Outiller la classification et la notification des incidents** | Le cas pratique montre qu'un arrêt complet d'environ 50 min en pointe peut déjà devenir majeur ; la notification initiale tombe 4 h après la classification | Exercice de notification à blanc réussi en moins de 4 h |
| 3 | **Traiter la compromission comme la panne** : isolement d'un service, rotation des secrets, investigation | La disponibilité revient en 10 à 16 s, mais un accès malveillant réussi est majeur à lui seul ; l'isolement n'est pas implémenté | Procédure testée ; délai d'isolement mesuré |
| 4 | **Réduire la dépendance à Stripe** : second acquéreur actif, stratégie de sortie testée | Stripe indisponible = plus de paiement ; PayPal est intégré sans bascule automatique | Bascule testée chaque année |
| 5 | **Tenir le registre des prestataires** et requalifier les outils grand public (Discord, healthchecks.io, GitHub) | Art. 28(3) ; la chaîne d'alerte dépend de services sans contrat | Registre transmis à l'ACPR ; canal d'alerte contractuel |
| 6 | **Second site et sauvegardes hors site doublées** | Un seul site, un seul serveur PBS, reprise complète jamais testée ; RPO base hors site de 24 h (dumps copiés hors du lab une fois par jour : les copier à chaque exécution) | RTO de reprise de site mesuré ; RPO hors site ≤ 15 min |
| 7 | **Pérenniser le programme de tests** : `chaos.sh` chaque trimestre, test d'intrusion externe annuel, indépendance des testeurs | 14 pannes sur 14 réparées sans humain, et les tests ont trouvé des défauts réels (bug du moteur, base unique 92 s → 0 s) | Taux de tests réussis ; défauts trouvés et corrigés |

En résumé : le démonstrateur prouve la partie **technique** de DORA la plus difficile à obtenir
(détection en secondes, reprise sans humain, sauvegardes restaurées, tests reproductibles). Il
ne prouve pas la partie **organisationnelle** (gouvernance, contrats, notification, formation),
qui relève de décisions de direction et de la durée. Ce sont ces décisions que ce dossier
recommande de prendre en premier.

## Sources

| Source | Usage |
|---|---|
| Règlement (UE) 2022/2554 (DORA), art. 2, 4, 5, 6, 11, 12, 13, 16, 19, 23 à 30, 45 | Champ, exigences (texte consulté) |
| Directive (UE) 2022/2555 (NIS2), art. 4, 20, 21, 23 et annexes I et II | Articulation, mesures, notification (texte consulté) |
| Règlement délégué (UE) 2024/1772, art. 6, 8, 9 | Critères et seuils de classification (texte consulté) |
| Règlement délégué (UE) 2025/301, art. 5 | Délais de notification (texte consulté) |
| ITS (UE) 2025/302 ; ITS (UE) 2024/2956 ; RTS (UE) 2024/1774 | Modèles de rapport, registre, cadre de risque (cités, non relus) |
| Projet de loi relatif à la résilience des infrastructures critiques et au renforcement de la cybersécurité | Transposition française (état **à vérifier**) |
| Dépôt : `infra/docs/tests-resilience.md`, `pca-pra-technique.md`, `dossier/infra.md`, `identites.md`, `comptes-et-rotation.md`, `supervision.md`, `waf.md`, `remediation.md`, `auth/app/face.py` | Preuves techniques |
