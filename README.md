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
cp backend/.env.example backend/.env         # STRIPE_SECRET_KEY, PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET
cp detector/.env.example detector/.env       # DETECTOR_ADMIN_TOKEN
echo "VITE_STRIPE_PUBLISHABLE_KEY=pk_test_..." > .env
echo "VITE_PAYPAL_CLIENT_ID=..." >> .env     # facultatif : même client ID que dans backend/.env

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

## Séquence mesurée pendant le développement

Panne provoquée par `docker stop payment-api` à 14:35:02, puis plus aucune action humaine :

| Délai | Événement | Acteur |
| --- | --- | --- |
| +12 s | Anomalie confirmée par le détecteur (score 0.78 ≥ 0.55) | détecteur ML |
| +12 s | Décision : recréer payment-api → échec, proxy trop restrictif (403) | moteur |
| +1 min 42 | Deuxième tentative → échec, proxy mal configuré (502), « escalade nécessaire » | moteur |
| +3 min 13 | Troisième tentative : redémarrage via le proxy Docker | moteur |
| +3 min 15 | Transaction de contrôle passée — API et Stripe joignables | moteur |
| +3 min 19 | **Service rétabli en 5 s — 0 intervention humaine** | moteur |

Les deux premiers échecs venaient du proxy Docker, corrigé entre-temps. Le moteur ne les a
pas cachés et n'a pas bouclé : il a attendu sa temporisation et réessayé tant que le verdict
du détecteur persistait. Détecteur seul, avant la distance robuste : une panne totale obtenait
0.50, à la frontière du seuil — voir `detector/README.md`.

## Sécurité vérifiée

Depuis le conteneur du moteur de remédiation, vers le proxy Docker :

| Requête | Réponse |
| --- | --- |
| `GET /containers/json` | 200 |
| `POST /containers/payment-api/restart` | autorisé |
| `POST /containers/create` | 403 |
| `POST /containers/payment-api/exec` | 403 |
| `POST /containers/payment-api/stop` | 403 |
| `POST /containers/detector/restart` | 403 |
| `GET /images/json` | 403 |

- Le proxy (`proxy/nginx.conf`) n'accepte que ces deux requêtes, en lecture seule, sans
  capacité, sur un réseau Docker interne.
- Le moteur n'expose aucune route d'écriture ; seul le verdict du détecteur le déclenche.
- `POST /reset` du détecteur exige un jeton (`DETECTOR_ADMIN_TOKEN`), CORS limité en `GET`.
- Un détecteur injoignable **dégrade** l'état (« Surveillance interrompue ») au lieu de laisser
  le bandeau vert.
- Les clés Stripe ne sont lues que depuis l'environnement ; aucun `.env` n'est commité.

## État par pilier

| Pilier | Fait | Reste à faire |
| --- | --- | --- |
| **DEV** | Tunnel Stripe test, journal, dashboard, moteur de remédiation | Playbooks supplémentaires (bannir une IP, restaurer la base) |
| **IA** | Détecteur IsolationForest + distance robuste, verdict qui déclenche l'action | Assistant RAG Ollama + LangChain, réapprentissage continu, variables CPU/RAM |
| **INFRA** | `docker compose` complet, proxy Docker à liste blanche | Ansible, Prometheus, Grafana, Loki, PostgreSQL |
| **CYBER** | Droits du moteur réduits, `/reset` protégé, état dégradé si aveugle | WAF, SIEM/SOC, Vault ou SOPS, scénario d'attaque depuis le PC attaquant |
| **GOUV** | — | EBIOS RM, PCA/PRA, analyse NIS2/DORA |

## Développer sans Docker

Chaque service se lance seul (voir son README). Le frontend fonctionne même sans
backend : il bascule sur une simulation locale et l'affiche.
