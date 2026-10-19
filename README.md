# M2 EPSI Workshop — Project RESILIENCE-ALPHA

Démonstrateur de cyber-résilience : une plateforme de paiement qui détecte une
anomalie et se répare seule, sans intervention humaine.

```
navigateur ──► frontend (React + Tailwind) ──► payment-api (FastAPI) ──► Stripe (mode test)
                    │                               ▲
                    │ supervision                   │ redémarrage, via proxy Docker à droits réduits
                    ▼                               │
               detector (IsolationForest) ──► remediation (décide, agit, vérifie)
```

| Dossier | Rôle | Doc |
| --- | --- | --- |
| `frontend/` | Tunnel de paiement, journal des transactions, dashboard de supervision | [README](frontend/README.md) |
| `backend/` | API de paiement, porte la clé Stripe, expose métriques et sonde | [README](backend/README.md) |
| `detector/` | Score d'anomalie chaque seconde, appris sur le trafic normal | [README](detector/README.md) |
| `remediation/` | Écoute le verdict, redémarre la cible, vérifie la reprise | [README](remediation/README.md) |

## Lancer le démonstrateur

```bash
# 1. Secrets, jamais commités
cp backend/.env.example backend/.env         # STRIPE_SECRET_KEY
cp detector/.env.example detector/.env       # DETECTOR_ADMIN_TOKEN
echo "VITE_STRIPE_PUBLISHABLE_KEY=pk_test_..." > .env

# 2. Tout monter
docker compose up --build
```

Puis http://localhost:5173. Le détecteur apprend la normale pendant `WARMUP_SECONDS`
(60 par défaut, réglable dans `.env`) avant de scorer.

## Rejouer la séquence de résilience

1. Onglet **Supervision** : bandeau vert, score d'anomalie bas.
2. Provoquer l'incident — par exemple arrêter le conteneur visé depuis le PC attaquant.
3. En quelques secondes : barres rouges, score qui franchit le seuil, « anomalie confirmée ».
4. Le bandeau passe au **bleu** : le moteur de remédiation redémarre `payment-api`.
5. Transaction de contrôle passée, bandeau **vert**, « Service rétabli en N s — 0 intervention humaine ».

Pendant toute la séquence, personne ne touche au clavier. C'est le point que le jury note.

## Développer sans Docker

Chaque service se lance seul (voir son README). Le frontend fonctionne même sans
backend : il bascule sur une simulation locale et l'affiche.
