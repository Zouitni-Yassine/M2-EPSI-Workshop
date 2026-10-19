# Procédures d'incident — RESILIENCE-ALPHA

## Incident : l'API de paiement ne répond plus

Symptôme : les transactions échouent, le endpoint /health renvoie une erreur.
Procédure :
1. Vérifier l'état du conteneur api-paiement dans le dashboard.
2. Si le conteneur est tombé, le moteur de rémédiation le redéploie automatiquement.
3. Confirmer la reprise en lançant une transaction de test.

## Services critiques

Le service de paiement (api-paiement) et la base de données PostgreSQL
sont les deux services critiques. Leur indisponibilité stoppe toute l'activité.

## Incident : pic d'erreurs 5xx

Symptôme : taux d'erreurs HTTP élevé détecté par le modèle IA.
Cause probable : attaque par déni de service (DoS).
Procédure : le système isole la source et applique la limitation de débit.