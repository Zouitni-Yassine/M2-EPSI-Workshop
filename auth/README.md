# Resilience Pay — authentification

Service FastAPI qui vérifie un identifiant et un mot de passe, puis délivre un jeton
signé (JWT Ed25519) portant le rôle de l'utilisateur : `client` ou `operator`.

## Démarrer

```bash
cd auth
pip install -r requirements.txt
cp .env.example .env        # renseigner AUTH_PASSWORD_OPERATEUR et AUTH_PASSWORD_CLIENT
uvicorn app.main:app --port 8300
```

`GET http://localhost:8300/health` → `{"ok": true, "db": true}`. Sous Docker, le service ne publie
aucun port : on le joint par le relais du frontal, `http://localhost:5173/auth/...`.

## Routes

| Route | Usage |
| --- | --- |
| `POST /auth/login` | Navigateur. `{"username", "password"}` → cookie `rp_session` (`HttpOnly`, `SameSite=Strict`) et `{"expiresAt", "user"}` : jamais de jeton lisible par le JavaScript |
| `POST /auth/token` | Scripts et services (transaction de contrôle, Swagger). Mêmes entrées, même freinage → `{"token", "expiresAt", "user"}` à envoyer en `Authorization: Bearer` |
| `POST /auth/logout` | Efface le cookie (le JavaScript ne le peut pas) |
| `GET /auth/me` | Relit l'utilisateur de la session (cookie ou Bearer), en vérifiant qu'il n'est pas désactivé |
| `GET /auth/verify?role=operator` | Pour le relais nginx (`auth_request`) : 200, 401 sans session, 403 si le rôle manque |
| `GET /auth/docs` | Documentation OpenAPI, joignable par le relais |
| `GET /auth/jwks.json` | Clé publique de signature, pour que les autres services vérifient les jetons eux-mêmes |
| `GET /metrics` | `auth_login_total{result="success\|failure\|locked"}` et `auth_face_total{result}` au format Prometheus |
| `GET /health` | Vérifie la base |
| `POST /auth/identify` | Première étape de la connexion : `{"username"}` → `{"step": "password"}` (client, inconnu) ou `{"step": "face", "challenge", "frames"}` (back-office) ; `429` + `Retry-After` pendant un blocage |
| `POST /auth/identify/{challenge}/probe` | Guidage pendant la capture (multipart, champ `frame`) : position, repères et orientation du visage. Détection seule, aucun échec compté |
| `POST /auth/identify/{challenge}/frames` | Images de la caméra (multipart, champ `frames`) → `recognized`, `rejected` ou `locked` |
| `GET /auth/admin/accounts` | Habilitations (opérateur) : comptes, rôle, état, gabarits de visage, comptes de service |
| `POST /auth/admin/accounts` | Créer un compte nominatif |
| `POST /auth/admin/accounts/{id}` | Changer le rôle, désactiver ou réactiver, compte de service ou non |
| `POST /auth/admin/accounts/{id}/password` | Définir un mot de passe (le back-office ne se réinitialise pas par e-mail) |
| `POST /auth/admin/face/probe` | Guidage du scan d'enrôlement, image par image (opérateur) |
| `POST /auth/admin/accounts/{id}/face/scan` | Scan guidé sous trois angles (multipart `face`, `gauche`, `droite`) : remplace les gabarits du compte |
| `POST /auth/admin/accounts/{id}/face` | Ajouter un gabarit d'une seule prise (multipart `frames`) ; `…/face/delete` supprime les gabarits |
| `GET /auth/admin/events` | Journal des accès du back-office |

## Reconnaissance faciale du back-office (consigne additionnelle 1)

La connexion d'un **opérateur** se fait en trois temps : l'identifiant, puis la caméra du poste,
puis le mot de passe. Les clients de la boutique gardent identifiant puis mot de passe.

1. `POST /auth/identify` : pour un compte du back-office, le navigateur allume la caméra
   (webcam USB du PC hôte) et suit le visage (`…/probe`, détection seule) ; dès qu'il est bien
   placé dans l'ovale, de face, 5 images partent au jugement, puis la caméra s'éteint, quel que
   soit le résultat.
2. Le serveur compare le visage au gabarit du compte : **YuNet** trouve le visage, **SFace** en
   tire un vecteur de 128 nombres (deux modèles ONNX d'OpenCV Zoo, sur CPU). Similarité cosinus
   médiane ≥ `FACE_THRESHOLD` (0,363, valeur recommandée par OpenCV) : visage reconnu.
3. Reconnu : la saisie du mot de passe s'ouvre pour `FACE_PASSWORD_SECONDS` (120 s), et
   `POST /auth/login` exige ce `challenge`. Sans lui, le mot de passe n'est même pas vérifié (403).

| Situation | Effet |
| --- | --- |
| Visage refusé (ou aucun visage, ou plusieurs) | Identifiant vidé, caméra éteinte ; nouvel essai après 30 s |
| Mauvais mot de passe après un visage reconnu | Tout recommence (identifiant vidé) |
| Deux cycles ratés | Identifiant bloqué 5 min, puis de nouveau un essai et un seul nouvel essai |

- **Enrôlement par scan sous trois angles**, comme les applications d'identité : de face, puis la
  tête tournée d'un côté et de l'autre. Pas de minuteur : le navigateur envoie quelques images par
  seconde au guidage (`/auth/admin/face/probe`), affiche le cadre et les repères du visage, et ne
  garde une prise que lorsque la tête est bien placée, à l'angle voulu (mêmes seuils que le
  serveur, qu'il renvoie). L'angle de chaque prise se lit sur les repères de YuNet
  (décalage du nez par rapport au milieu des yeux, rapporté à leur écart) : de face sous
  `FACE_FRONT_MAX_YAW` (0,12), de côté au-delà de `FACE_SIDE_MIN_YAW` (0,18), un côté puis l'autre.
  Les trois prises doivent montrer la même personne. Sinon rien n'est enregistré, et le message
  dit quoi corriger. Les angles mesurés sont notés dans le journal des accès.
- **Aucune image n'est conservée** : seulement trois gabarits par scan (un par angle), en base
  (`face_templates`). Les données biométriques sont des données sensibles (RGPD, art. 9).
- **Comptes de service** : `FACE_EXEMPT_USERS` (par défaut `operateur`, utilisé par la sonde de
  transaction) est dispensé de visage **depuis le réseau interne seulement** (`FACE_SERVICE_NETS`).
  Depuis Internet, il doit passer la caméra. C'est ce compte qui enrôle les premiers visages.
- `/auth/token` est refusé aux comptes qui doivent passer la caméra ; la réinitialisation par
  e-mail aussi : un administrateur définit le mot de passe depuis les habilitations.
- La caméra n'est accessible au navigateur qu'en HTTPS (ou sur `localhost`).
- Modèles : `python scripts/fetch_models.py` (développement, dans `auth/models`) ; l'image Docker
  les télécharge au build. Sans modèles, l'identification d'un opérateur répond 503.
- Le guidage est borné à `FACE_MAX_PROBES` images par identification (8 par seconde de capture),
  et le navigateur s'arrête au premier refus : un éventuel faux positif du WAF ne coûte qu'un
  refus par essai, loin du bannissement automatique (10 refus en 2 minutes).
- Limites : pas de détection du vivant (une photo du visage peut tromper la caméra) ; l'état des
  identifications en cours est en mémoire (un redémarrage oblige seulement à recommencer).

## Rôles

| Rôle | Paiement | Transactions | Solde marchand | Supervision |
| --- | --- | --- | --- | --- |
| `client` | oui | les siennes | non | non |
| `operator` | oui | toutes | oui | oui |

## Choix de sécurité

- **Signature asymétrique (Ed25519).** La clé privée ne quitte pas ce service.
  `payment-api` récupère la clé publique et vérifie chaque jeton localement : compromis, il
  ne peut pas fabriquer un jeton d'opérateur. Si ce service tombe, les sessions ouvertes
  continuent de fonctionner.
- **Algorithme figé.** Un jeton `alg: none`, ou HS256 signé avec la clé publique, est refusé.
- **Mots de passe en argon2id**, jamais stockés ni journalisés en clair. Un identifiant
  inconnu prend le même temps qu'un mauvais mot de passe et reçoit la même réponse : on ne
  peut pas deviner quels comptes existent.
- **Force brute freinée.** Après 5 échecs en 5 minutes depuis une même adresse sur un même
  identifiant, ou 20 échecs depuis une adresse tous identifiants confondus, réponse `429`
  sans vérifier le mot de passe. Le blocage porte sur l'adresse, pas sur le compte : un
  attaquant ne peut pas enfermer l'opérateur dehors.
- **Traces exploitables.** Chaque tentative est une ligne JSON sur stdout (Loki, SIEM) et un
  compteur Prometheus. C'est le signal d'une attaque par force brute.
- **Aucun compte par défaut.** Un compte de démonstration n'est créé que si son mot de passe
  (8 caractères minimum) est fourni.

## Comptes

Les comptes de `AUTH_SEED_USERS` sont créés ou mis à jour à chaque démarrage. Pour en ajouter
un à la main :

```bash
python -m app.users add alice client          # en local
docker compose exec -it auth python -m app.users add alice client
python -m app.users list
```

## Données

Sous Docker (compose ou Swarm), le service est **sans état** :

- comptes dans PostgreSQL, base `auth` (`DATABASE_URL`, mot de passe dans `DB_PASSWORD_FILE`) ;
- clé de signature en secret Docker (`JWT_PRIVATE_KEY_FILE`), créée par
  `scripts/init-secrets.py`. Toutes les réplicas signent avec la même clé : un jeton émis par
  l'une est vérifiable partout, et un redémarrage ne déconnecte personne.

Au démarrage, le service attend la base jusqu'à une minute (Swarm ne garantit aucun ordre).
Lancé seul, sans ces variables, il retombe sur SQLite et une clé générée dans `AUTH_DATA_DIR`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```
