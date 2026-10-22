# Procédures : incidents de l'application de paiement

## Incident : les paiements échouent ou payment-api ne répond plus

La reprise est automatique, ne pas intervenir pendant les deux premières minutes.
1. Le détecteur ML (IsolationForest) voit l'écart en 2 à 4 s (score au-dessus du seuil 0,55
   pendant 3 s).
2. Le moteur de remédiation demande à la passerelle des managers de redémarrer payment-api
   (environ 13 s), puis fait une transaction de contrôle.
3. Vérifier sur le dashboard « Démo / Remédiation » : bandeau Paiements revenu à OK, événement
   « Service rétabli », nouvelle transaction de la sonde en vert.
Temps mesurés le 20/10 : 10 à 16 s de panne vue par un client, 0 intervention humaine.

## Incident : le moteur ne relance pas tout de suite (« Action différée »)

La passerelle refuse deux actions sur un même service à moins de 60 s d'intervalle, et plus de
10 actions par fenêtre de 10 minutes. C'est un garde-fou volontaire : un moteur compromis ne
peut pas redémarrer les services en boucle. Le moteur réessaie seul après le délai. Attendre ;
si la limite globale est atteinte, prévenir l'équipe infra.

## Incident : base de données PostgreSQL arrêtée

Swarm relance la base seule en une dizaine de secondes. Aucun paiement n'est perdu : les données
sont sur un volume du worker dockerwrk01 (test du 20/10 : 116 paiements avant, 117 après).
Attention : /api/health peut répondre 200 alors que la base est arrêtée ; se fier à la sonde
de transaction (dashboard Démo) et au champ "db" de /api/health.
Limite : la base est épinglée sur dockerwrk01. Si ce worker tombe, la base attend son
redémarrage par la HA Proxmox (1 à 2 minutes).

## Incident : rafale de requêtes ou déni de service sur l'API

Le détecteur signale l'anomalie et le moteur redémarre payment-api pour rétablir la
disponibilité. Ce redémarrage NE bloque PAS la source de l'attaque : il n'y a pas aujourd'hui de
bannissement automatique d'adresse IP. Rechercher la source dans Loki (logs du frontal et du WAF)
et la bloquer au WAF (équipe cyber). Ne pas confondre rétablir le service et traiter l'attaque.

## Incident : un conteneur de l'application s'est arrêté brutalement

auth, frontend, detector, remediation et payment-api sont relancés par Swarm (politique de
redémarrage en cas d'échec). Vérifier dans Grafana que le service repasse à 1/1. Le moteur de
remédiation ne peut pas se réparer lui-même : c'est Swarm qui le relance.
