# Procédures d'incident — RESILIENCE-ALPHA

Fiches courtes pour les opérateurs. Les procédures détaillées de l'infrastructure (adresses,
commandes, alertes) sont dans les fiches infra-*.md ajoutées au corpus lors du déploiement.

## Incident : l'API de paiement ne répond plus

Symptôme : les transactions échouent, /api/health renvoie une erreur ou ne répond plus.
Procédure :
1. Ne pas intervenir pendant les deux premières minutes : la reprise est automatique.
2. Le détecteur ML signale l'anomalie en 2 à 4 s ; le moteur de remédiation fait redémarrer
   payment-api par la passerelle des managers (environ 13 s), puis passe une transaction de
   contrôle.
3. Vérifier sur le dashboard Grafana « Démo / Remédiation » : Paiements revenu à OK,
   événement « Service rétabli », nouvelle transaction de la sonde réussie.

## Services critiques

payment-api (API de paiement), auth (authentification), le frontal et la base PostgreSQL.
La base est répliquée sur trois nœuds (Patroni) : la perte du primaire déclenche une bascule
automatique, sans perte de paiement confirmé.

## Incident : pic d'erreurs 5xx ou rafale de requêtes

Symptôme : taux d'erreurs HTTP élevé, score du détecteur au-dessus du seuil 0,55.
Cause probable : attaque par déni de service ou force brute.
Réponse automatique, en deux temps :
1. Disponibilité : le moteur de remédiation redémarre payment-api.
2. Attaque : le WAF bannit l'adresse IP source pendant 15 minutes (règles de détection sur
   les journaux du WAF, environ 30 s). Débannir à la main : `sudo waf-ban unban <ip>` sur waf01.
Redémarrer le service ne bloque pas l'attaquant : c'est le bannissement au WAF qui le fait.
