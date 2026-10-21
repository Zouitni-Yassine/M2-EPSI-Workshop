# Alertes et lecture du dashboard

## Alertes de l'application (envoyées sur Discord)

| Alerte | Signification | Action |
|---|---|---|
| PaiementTransactionProbeFailing | La sonde n'a réussi aucune transaction depuis 90 s | Vérifier que la remédiation est en cours (dashboard Démo) ; sinon prévenir l'équipe infra |
| PaiementApiDown | payment-api ne répond plus | Reprise automatique par le moteur |
| PaiementDatabaseDown | PostgreSQL injoignable | Swarm relance la base ; vérifier le retour |
| PaiementApiHighErrorRate / HighLatency | Erreurs 5xx ou lenteur de l'API | Surveiller le score du détecteur ; possible attaque |
| PaiementAuthBruteForce | Tentatives de connexion répétées | Rechercher la source dans Loki, bloquer au WAF |
| PaiementProviderDown | Stripe ou PayPal (bac à sable) injoignable | Problème externe, rien à redémarrer |

## Alertes d'infrastructure

| Alerte | Signification |
|---|---|
| VaultSealed | Vault scellé : lancer vault-unseal sur 10.0.1.110 |
| PveNodeDown | Un hyperviseur est hors ligne : la HA relance ses machines |
| CephHealthWarning / CephHealthError | Stockage dégradé / en erreur |
| SwarmNodeNotReady / SwarmNoLeader | Nœud Swarm perdu / plus de leader (quorum) |
| TargetDown | Une cible de supervision ne répond plus |
| Watchdog | Toujours active : prouve que la chaîne d'alerte fonctionne |

## Lire le dashboard « Démo / Remédiation »

- Bandeau : Paiements (OK ou EN PANNE vu par un vrai client), temps depuis la dernière
  transaction réussie, score d'anomalie du détecteur (seuil 0,55), état du moteur (EN VEILLE ou
  EN ACTION), dernier temps de reprise.
- Frise « Avant / pendant / après » : paiements, anomalie détectée, moteur.
- Chronologie de la remédiation : détection, décision, redémarrage, vérification, service rétabli.
- Section Infrastructure : worker qui porte l'adresse virtuelle, nœuds Swarm, leader, hyperviseurs,
  santé Ceph, état de Vault, placement des machines.
- Zones violettes « Tests de chaos » : tests de panne volontaires.
