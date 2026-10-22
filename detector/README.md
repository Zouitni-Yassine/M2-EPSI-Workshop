# Resilience Pay — détecteur d'anomalies

Service Python qui attribue chaque seconde un score d'anomalie à `payment-api`.
Pas de règle codée en dur : le modèle apprend la normale et mesure l'écart.

## Démarrer

```bash
cd detector
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --port 8100
```

`GET http://localhost:8100/score` → `{"status": "learning", "progress": 0.42, ...}` puis
`{"status": "ready", "current": 0.11, "over": false, "points": [...]}`.

## Comment il décide

| Étape | Ce qui se passe |
| --- | --- |
| Échauffement | `WARMUP_SECONDS` observations de `GET /api/status`, en ne retenant que celles où l'API répond |
| Apprentissage | un `IsolationForest` (200 arbres) **et** une normale robuste (médiane, MAD) sur six variables |
| Scoring | score = max(forêt, distance robuste), ramené sur [0, 1], 0.5 à la frontière |
| Lissage | moyenne mobile exponentielle (α = 0.5) pour l'affichage |
| Confirmation | `PERSISTENCE` secondes consécutives au-dessus de `THRESHOLD` avant `over = true` |

Les six variables, toutes réellement mesurées : débit, taux de 5xx, latence p95,
latence de la sonde Stripe, disponibilité de l'API, disponibilité de Stripe.

### Pourquoi deux modèles

Une plateforme calme a des variables quasi constantes. Sur ce régime, une forêt
d'isolation seule ne distingue plus rien : testé sur 30 secondes de calme, une panne
totale de l'API obtenait un score de 0.50 — à la frontière. La distance robuste à la
normale (en unités d'écart-type, avec un plancher d'échelle par variable) tranche ce
cas : la même panne monte à 0.87 en trois secondes.

Dès que le trafic a de la variance (utilisateurs réels, charge d'attaque), la forêt
reprend l'avantage sur les anomalies subtiles. Le `max` des deux garde le meilleur
des deux régimes.

### Mesuré pendant le développement

| Situation | Score | `over` |
| --- | --- | --- |
| 20 s de calme après apprentissage | 0.00 – 0.31 | non |
| Backend arrêté | 0.76 → 0.87 | oui, après 3 s |
| Backend relancé | retour sous 0.55 | non |

## Routes

| Route | Rôle |
| --- | --- |
| `GET /health` | état et nombre d'échantillons appris |
| `GET /score` | score courant, verdict `over`, 120 derniers points, seuil, dernières variables |
| `POST /reset` | réapprend la normale à partir de maintenant |
| `GET /metrics` | métriques Prometheus, collectées par le vmagent du Swarm (non relayé par le frontal) |

Métriques : `detector_anomaly_score` (score lissé), `detector_threshold`, `detector_anomaly`
(1 = anomalie confirmée), `detector_ready`, `detector_training_samples`,
`detector_feature{feature}` (les 6 variables), et les compteurs `detector_observations_total`,
`detector_over_threshold_seconds_total`, `detector_anomalies_total`. La collecte a lieu toutes
les 30 s : les compteurs gardent la trace d'une anomalie plus courte que cet intervalle.

## Limites, à dire au jury

- La normale est apprise au démarrage : si le trafic change de régime (plus d'utilisateurs),
  il faut `POST /reset`. Un vrai système réapprendrait en continu.
- Les planchers d'échelle (`SCALE_FLOOR`) sont des unités physiques choisies à la main —
  1 req/s, 100 ms, 5 % d'erreurs. Ce ne sont pas des seuils de détection, mais il faut
  pouvoir les justifier.
- Six variables, pas de CPU/RAM : elles viendront de cAdvisor quand l'infra sera en place.
- Le modèle est en mémoire, perdu au redémarrage du conteneur. Pour la démo c'est voulu :
  le détecteur ne doit pas être ce qu'on recrée pendant la remédiation.
