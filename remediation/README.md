# Resilience Pay — moteur de remédiation

Le composant qui fait la différence entre une panne réparée par un humain (0/5) et
une reprise autonome. Il écoute le détecteur, décide, agit sur le conteneur visé,
puis vérifie que le métier répond avant de déclarer la reprise.

## Ce qu'il fait, dans l'ordre

| Étape | Action | Événement publié |
| --- | --- | --- |
| 1 | Lit `GET /score` du détecteur chaque seconde | — |
| 2 | `over = true` et pas de remédiation en cours → décision | « Anomalie confirmée par le détecteur » · « Décision : recréer payment-api » |
| 3 | `POST /containers/payment-api/restart` via le proxy Docker | « payment-api redémarré via le proxy Docker » |
| 4 | Attend que `GET /api/status` réponde **et** que la sonde Stripe passe (40 s max) | « Transaction de contrôle passée » |
| 5 | Attend que le détecteur retire son verdict (30 s max) | « Service rétabli en N s — 0 intervention humaine » |
| 6 | Temporisation de 45 s avant toute nouvelle action | — |

La reprise est jugée sur le **métier** (API + Stripe), pas sur l'état du conteneur.
C'est la distinction que le sujet impose : un conteneur qui redémarre ne prouve rien.

## Ce qu'il ne peut pas faire — par construction

Le sujet prévient (§3.4) : un moteur de remédiation a des droits élevés et ne doit pas
devenir une porte d'entrée. Trois garde-fous :

- **Il ne voit jamais le socket Docker.** Il parle à `docker-socket-proxy`, un nginx à liste
  blanche de deux requêtes : `GET /containers/json` et `POST /containers/payment-api/restart`
  (`proxy/nginx.conf`). Tout le reste répond 403 — pas d'`exec`, pas de création, pas d'arrêt,
  pas d'images. Vérifié depuis le conteneur du moteur. Le proxy tourne en lecture seule, sans
  capacité, sur un réseau Docker `internal` injoignable de l'extérieur.
- **Il ne redémarre que sa liste.** `TARGETS=payment-api`. Toute autre cible lève `PermissionError`.
- **Il n'expose aucune route d'écriture.** `GET /health`, `GET /state`, c'est tout. Personne ne peut
  lui demander d'agir ; seul le verdict du détecteur le déclenche.

## Routes

| Route | Rôle |
| --- | --- |
| `GET /health` | état et cibles autorisées |
| `GET /state` | `idle` ou `remediating`, journal des actions, compteur d'interventions humaines (0), durée de la dernière reprise |

La supervision lit `/state` chaque seconde : l'état bleu « Remédiation en cours » et les
événements de la chronologie viennent de là.

## Variables

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `DETECTOR_URL` | `http://detector:8100` | d'où vient le verdict |
| `API_URL` | `http://payment-api:8000/api` | ce qu'on vérifie après l'action |
| `DOCKER_URL` | `http://docker-socket-proxy:2375` | le seul chemin vers Docker |
| `TARGETS` | `payment-api` | conteneurs qu'on a le droit de redémarrer |
| `COOLDOWN_SECONDS` | `45` | délai minimal entre deux actions |
| `VERIFY_TIMEOUT` | `40` | temps accordé au service pour revenir |

## Limites, à dire au jury

- Une seule action possible : redémarrer. Bannir une IP au WAF, restaurer une base, basculer
  sur une réplique — ce sont les playbooks suivants, et ils demandent un WAF et une base.
- Si le service ne revient pas en 40 s, le moteur le dit (« escalade nécessaire ») et s'arrête.
  Il ne boucle pas : relancer à l'infini un conteneur qui ne revient pas, c'est aggraver la panne.
