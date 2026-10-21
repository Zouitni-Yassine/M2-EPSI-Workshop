# Assistant RAG des opérateurs (rag01)

L'équipe IA a écrit un assistant local qui répond aux questions des opérateurs à partir des
procédures et des documents du projet (Ollama + LangChain + ChromaDB + Streamlit, code dans le
dossier `rag/` de la branche `IA`). L'infra l'héberge sur une VM dédiée, `rag01`, créée et
configurée entièrement en code (21/10/2026).

L'assistant aide à comprendre et à retrouver une procédure. Il **n'agit sur rien** : ce n'est pas
le moteur de remédiation.

Depuis le 21/10/2026 au soir, il répond aussi sur **l'état réel du système** (alertes, services,
base, détecteur, bannissements au WAF, événements du moteur) grâce à des **outils MCP en lecture
seule** (section 8), et il est utilisé par le **bot Discord** de l'équipe (sections 9 et 10).
L'**interface web Streamlit est désactivée** : le bot et l'API sont le seul accès
(réactivable par `-e rag_ui_enabled=true`).

## 1. Machine

| | |
|---|---|
| VM | `rag01`, VMID **230**, nœud d'origine `ceph02`, HA Proxmox (règle `home-rag01`, failback) |
| Réseau | **10.30.1.230/24**, VLAN 301 `RA-APP` (vnet `raapp`), passerelle et DNS 10.30.1.254 |
| Dimensionnement | 8 vCPU `x86-64-v3` (AVX2, FMA), 16 Go de RAM, disque 60 Go sur `vm-fastec` (Ceph) |
| Système | Clone du template `debian13-docker` (9100) : agent QEMU et durcissement SSH/sysctl de base. Docker y est **arrêté et désactivé** |
| Code Terraform | [`terraform/rag.tf`](../terraform/rag.tf), HA dans [`terraform/ha.tf`](../terraform/ha.tf) |
| Code Ansible | [`ansible/rag.yml`](../ansible/rag.yml), rôles `rag` puis `alloy` ; groupe d'inventaire `rag_servers` |

**Pourquoi 8 vCPU x86-64-v3 et 16 Go.** L'inférence tourne sur CPU (pas de GPU dans le lab).
llama.cpp, utilisé par Ollama, a besoin d'AVX2 pour être utilisable ; le type `x86-64-v2-AES` des
autres VM ne l'offre pas. Les 3 hyperviseurs ont le même processeur : la VM reste migrable. Les
deux modèles chargés en permanence occupent ~3 Go ; 16 Go laissent la place au cache de pages et à
ChromaDB.

**Pourquoi une règle HA à part.** rag01 n'est pas dans la règle `home-ceph02` du socle : on peut
l'ajouter ou la retirer sans modifier les règles existantes. Le comportement est le même (nœud
préféré non strict, retour automatique).

## 2. Pourquoi RA-APP, et aucun accès privilégié

Le sujet (§3.3) demande que l'assistant ne soit pas confondu avec l'automate de remédiation et ne
dispose pas, sans contrôle, d'accès privilégiés au système. D'où :

| Mesure | Effet |
|---|---|
| VM à part, hors du Swarm | Aucun accès au socket Docker, à la passerelle `remediate` ni aux secrets Swarm |
| VLAN `RA-APP`, pas `MANAGEMENT` | La passerelle UniFi lui refuse le SSH et les interfaces web des hyperviseurs, de Vault et de la supervision ; seuls les flux `ra-app-to-*` existent (Loki pour ses logs) |
| Aucun secret d'administration | Ni clé SSH, ni jeton Vault, ni mot de passe d'un compte complet. Secrets déployés, chacun lisible par un seul service : Loki pour Alloy (`/etc/alloy/loki_password`, 0640 root:alloy) ; comptes **lecture seule** de la supervision et jeton de l'API (`/etc/rag/*`, 0640 root:rag) ; jeton Discord (`/etc/discord-bot/discord_token`, 0600 qwen-bot) |
| Supervision en lecture seule | Compte `rag-readonly` limité par la supervision elle-même aux routes de requête (section 8) : même un outil détourné ne peut ni écrire, ni supprimer, ni lire un secret |
| Utilisateurs système dédiés | `rag`, `ollama` et `qwen-bot` (bot Discord), sans shell ni sudo |
| Code en lecture seule | Code et venv appartiennent à root ; le service n'écrit que dans `/var/lib/rag` |
| Services durcis (systemd) | `NoNewPrivileges`, `ProtectSystem=strict` + `ReadWritePaths`, `ProtectHome`, `PrivateTmp`, `PrivateDevices`, aucune capacité |
| Ollama local uniquement | API sur **127.0.0.1:11434** : ni le réseau ni les autres VM ne parlent aux modèles |
| Pas d'appel sortant de l'appli | Télémétrie de ChromaDB et de Streamlit coupée. Seul le bot sort vers Internet (Discord) |

## 3. Composants

| Composant | Version | Détail |
|---|---|---|
| Ollama | **v0.35.1** (29/09/2026) | Archive officielle `ollama-linux-amd64.tar.zst` de la release GitHub, sha256 vérifié, `/opt/ollama/v0.35.1`, service `ollama`, données `/var/lib/ollama` |
| Modèle de génération | `qwen3.8:27b` sur le GPU de délestage ; `llama3.2:3b` (2,0 Go) en secours CPU, sous un alias du même nom | `RAG_LLM_MODEL` ; dérogation au §3.3 validée par le coach (voir `rag_gpu_llm_model`) |
| Modèle d'embeddings | `nomic-embed-text` (274 Mo) | |
| Code de l'assistant | branche `IA`, commit **`2e3c0c2`** (`rag_git_ref`) | `/opt/rag/releases/<commit>`, lien `/opt/rag/app` : `chain.py`, `agent.py`, `api.py`, `ingest.py`, `app.py` |
| Dépendances Python | venv `/opt/rag/venv` | Versions figées par `roles/rag/files/constraints.txt` (le `requirements.txt` de l'équipe IA n'en fixe aucune) : langchain 1.4.6, langchain-community 0.4.2, langchain-ollama 1.1.0, chromadb 1.5.9, streamlit 1.66.0, pypdf 6.21.1 ; ajoutés le 21/10 : mcp 1.30.0, langchain-mcp-adapters 0.3.2, fastapi 0.156.8, uvicorn 0.54.0 |
| Outils de supervision | serveur MCP, service `rag-mcp` | `infra/rag/mcp_supervision/server.py` (dépôt INFRA) → `/opt/rag/mcp_supervision`, **127.0.0.1:8610** (section 8) |
| API du bot | FastAPI, service `rag-api` | `api.py` de l'équipe IA, **0.0.0.0:8600** filtré par nftables (section 9) |
| Bot Discord | discord.py 2.7.1, service `discord-bot` | `infra/rag/discord_bot/` → `/opt/discord-bot` (venv dédié), utilisateur `qwen-bot` (section 10) |
| Base vectorielle | ChromaDB | `/var/lib/rag/chroma_db` (lien `chroma_db` dans le code, qui utilise un chemin relatif) |
| Interface web | Streamlit, service `rag-assistant` | **Désactivée** (`rag_ui_enabled: false` : service arrêté, 8501 fermé). Code installé ; l'index est construit par Ansible, pas par ce service |

Les modèles restent chargés en mémoire (`OLLAMA_KEEP_ALIVE=-1`) : pas de rechargement entre deux
questions.

### Corpus

`ingest.py` indexe tout `docs/**/*.md` et `docs/**/*.pdf` du code. Il contient :

- les documents de l'équipe IA (`rag/docs/` de la branche `IA`) ;
- les **fiches de procédures de l'infra**, rangées dans
  [`infra/rag/corpus/`](../rag/corpus/) et copiées dans `docs/infra/` de l'appli.

L'index est reconstruit **seulement si le corpus change** : empreinte de l'arbre `rag/docs` du
commit, des fiches de l'infra et du modèle d'embeddings, comparée à `/var/lib/rag/corpus.id`.
`ingest.py` ajoute à la base existante, la base est donc vidée avant chaque indexation.

## 4. Accès

| Depuis | Accès |
|---|---|
| Discord (serveur « Workshop 2026 », salon #assistance-rag) | Bot « Qwen » : le mentionner (section 10). **Accès normal** |
| LAN d'administration (10.0.1.0/24) et VPN admin (`LSN - UGC`, `EPSI-WG`) | API **http://10.30.1.230:8600** (jeton Bearer, section 9) ; interface web 8501 fermée sauf `rag_ui_enabled=true` |
| PC de délestage IA (VPN `EPSI-WS-IA`, 192.168.2.0/24) | SSH (tunnel vers Ollama) ; 8501 seulement si l'interface est réactivée |
| Poste de contrôle | SSH `debian@10.30.1.230` (clé `id_ed25519_infra`) |
| Supervision | node_exporter (9100) depuis les vmagents uniquement ; logs par Alloy vers Loki |

Firewall nftables de rag01 (`roles/rag/templates/nftables.conf.j2`) : politique `drop`, SSH depuis
`fw_ssh_allowed`, **8600 depuis `rag_api_allowed`** (par défaut LAN MANAGEMENT + VPN
d'administration ; le bot, local, passe par `lo`), 9100 depuis les vmagents, 22 depuis
`rag_gpu_vpn_cidr`. 8501 seulement si `rag_ui_enabled` (depuis `fw_monitoring_allowed`,
`fw_admin_web_allowed` et `rag_gpu_vpn_cidr`). 11434, 11430 et 8610 écoutent sur 127.0.0.1 et ne
sont jamais ouverts. Les règles de la passerelle UniFi sont gérées à part (`infra/unifi`).

## 5. Déploiement

```bash
# VM et HA
tf plan && tf apply

# Configuration (idempotente)
cd /srv/M2-EPSI-Workshop/infra/ansible
vault-env ansible-playbook rag.yml

# Collecte node_exporter (cible ajoutée au job "node" depuis l'inventaire)
vault-env ansible-playbook monitoring.yml --limit vmagents

# Comptes lecture seule de l'assistant sur la supervision (vmauth, nginx de Loki)
vault-env ansible-playbook monitoring.yml --limit monitoring01

# Interface web : réactiver (service + pare-feu) ou la laisser désactivée (défaut)
vault-env ansible-playbook rag.yml -e rag_ui_enabled=true
```

**Mettre à jour le code de l'équipe IA** :

```bash
git -C /srv/M2-EPSI-Workshop fetch origin
git -C /srv/M2-EPSI-Workshop rev-parse origin/IA          # sha complet
vault-env ansible-playbook rag.yml -e rag_git_ref=<sha>   # ou changer rag_git_ref dans roles/rag/defaults/main.yml
```

Le nouveau code est extrait dans un nouveau répertoire de `releases/`, le lien `app` bascule, le
service redémarre, et l'index est reconstruit si les documents ont changé. Si `requirements.txt`
ajoute une dépendance : déployer une fois avec `-e rag_pip_constraints=false`, puis régénérer
`constraints.txt` par `pip freeze` dans `/opt/rag/venv`.

**Ajouter une fiche infra** : la déposer dans `infra/rag/corpus/`, relancer `rag.yml` (réindexation
automatique).

## 6. Vérifications du 21/10/2026

| Vérification | Résultat |
|---|---|
| `tf plan` avant apply | 3 à créer (VM, ressource HA, règle `home-rag01`), 0 modification, 0 destruction |
| `tf plan` après apply | Aucun changement |
| Second passage de `rag.yml` | `changed=0` |
| `systemctl is-active ollama rag-assistant` | `active` `active` (Docker : `inactive`) |
| `ollama list` | `llama3.2:3b`, `nomic-embed-text:latest` |
| `curl http://10.30.1.230:8501/` depuis .110 | 200 |
| `curl 127.0.0.1:11434` sur rag01 / `10.30.1.230:11434` depuis .110 | 200 / refusé (filtré, et écoute locale seulement) |
| `up{job="node",host="rag01"}` | 1 |
| Logs dans Loki (`{host="rag01"}`) | Présents (`ollama.service`, `rag-assistant.service`, `alloy.service`...) |
| `nft list ruleset` | Contient la règle 192.168.2.0/24 → 22, 8501 |

**Test de bout en bout** (utilisateur `rag`, venv, `chain.ask()`) :

| Question | Temps | Réponse |
|---|---|---|
| « Que faire si payment-api ne répond plus ? » | 84 s (modèle froid), **30 s** ensuite | Répond à partir des documents du backend (mode hors ligne, journalisation) ; ne cite pas la fiche infra (redémarrage par le moteur) |
| « Que faire si Vault est scellé ? Sur quelle machine ? » | **17 s** | Lancer `vault-unseal` sur le poste de contrôle 10.0.1.110, puis vérifier la tuile Vault du dashboard Démo |

Chargement de la chaîne (import, ouverture de ChromaDB) : ~4 s.

## 7. Limites

| Limite | En production |
|---|---|
| Inférence sur CPU : 15 à 30 s par réponse | GPU (PC de délestage IA, tunnel SSH vers Ollama) |
| Pas d'authentification sur l'interface Streamlit (filtrée par IP seulement) : interface désactivée | Reverse proxy avec SSO Keycloak |
| La pertinence dépend du corpus et de la recherche (4 segments) : sur payment-api, les documents du backend passent avant la fiche infra | Métadonnées par type de document, re-classement, plus de segments |
| Une seule instance (HA Proxmox, pas de redondance applicative) | Acceptable : l'assistant n'est pas sur le chemin critique du paiement |
| `RA-APP` peut joindre Vault (8200) et Keycloak (443) au niveau réseau (règles du Swarm) | Segment dédié ou règles par adresse source ; rag01 n'a de toute façon aucun identifiant |
| Secours CPU (GPU absent) : le petit modèle n'appelle pas les outils ; l'agent répond avec la documentation seule (« Mode dégradé ») et peut présenter la doc comme des faits | GPU permanent, ou modèle local plus grand capable d'appeler des outils |
| Une question à la fois, 10 par minute pour tous : 20 à 80 s par réponse sur le GPU | File d'attente, plusieurs instances, réponse en flux |
| Les résultats d'outils contiennent des données venues de l'extérieur (IP, journaux) : injection de consignes possible | Outils et compte en lecture seule : l'effet se limite à une mauvaise réponse ; le prompt système traite ces résultats comme des données |
| Mots de passe lecture seule lisibles par tout service tournant en `rag` (API, interface) | Utilisateur dédié au serveur MCP, ou `LoadCredential=` de systemd |
| Métriques de vmauth non collectées (`/metrics` sur 127.0.0.1:8426) | Exposition sur le LAN pour les vmagents |
| Frontend et moteur de remédiation non scrapés : `etat_plateforme` les voit à travers la sonde de transaction | Métriques exposées par ces services |

## 8. Outils de supervision (MCP, lecture seule)

L'agent de l'équipe IA (`agent.py`) choisit lui-même ses outils : `chercher_documentation` (la
recherche de `chain.py`) et cinq outils du serveur MCP « supervision » de l'infra.

```text
bot / API ── agent.py (ChatOllama qwen3.8:27b, 4 appels d'outils max, 100 s)
               ├─ chercher_documentation ──> ChromaDB (procédures, docs)
               └─ MCP streamable HTTP 127.0.0.1:8610 (service rag-mcp, utilisateur rag)
                    ├─ VictoriaMetrics :8428 (vmauth, compte rag-readonly : requêtes uniquement)
                    └─ Loki :3100 (nginx, compte rag-readonly : requêtes uniquement)
```

| Outil | Ce qu'il renvoie | Source |
|---|---|---|
| `alertes_recentes(heures=2)` (1 à 48) | Synthèse par alerte et 10 déclenchements les plus récents : nom, sévérité, service ou machine, début et fin (à un pas près), encore active ou non. Watchdog exclu | `ALERTS{alertstate="firing"}` (query_range) |
| `etat_plateforme()` | Services de la stack paiement (up ou absents), base (primaire, standbys, retard en Kio), score du détecteur et seuil, dernière transaction réussie de la sonde, alertes actives, Vault, Ceph, hyperviseurs, nœuds et leader Swarm | 17 requêtes instantanées |
| `ip_bannies(heures=24)` (1 à 168) | Bannissements (IP, raison, durée, fin), IP encore bannies, expirations, débannissements, demandes refusées | Loki `{identifier="waf-ban"}` |
| `evenements_remediation(heures=2)` (1 à 48) | Chronologie du moteur : incident détecté, décision, action, vérification, rétabli (20 derniers) | Loki `{stack="probe"} \|= "type=evenement"` |
| `requete_metrique(promql)` | Requête instantanée : 300 caractères, 8 s, 20 séries affichées au plus | VictoriaMetrics |

Sorties en français, 3000 caractères au plus, heures de Paris, source citée ; réponses brutes des
sources limitées à 2 Mo. Les valeurs venues des journaux (IP...) sont nettoyées. Une ligne de
journal par appel (`outil=… duree=… statut=…`, unité `rag-mcp`). Aucun outil n'écrit, ne
redémarre, ne bannit ni ne lit un secret ; les outils sont annotés `readOnlyHint`.

**Comptes lecture seule** (`rag_readonly_user: rag-readonly`, secret Vault
`secret/infra/rag-readonly`, clés `RAG_VM_READ_PASSWORD` et `RAG_LOKI_READ_PASSWORD`) :

| Service | Mécanisme | Autorisé | Refusé (testé le 21/10) |
|---|---|---|---|
| VictoriaMetrics | **vmauth** sur :8428 ; VictoriaMetrics passe sur 127.0.0.1:8427 et garde son authentification derrière (rôle `vmsingle`, `tasks/vmauth.yml`). Le compte `monitoring` garde toute l'API : rien ne change pour vmagent, vmalert et Grafana | `/api/v1/query`, `query_range`, `series`, `labels`, `label/<nom>/values`, `status/buildinfo` ; 2 requêtes simultanées | import, `write`, `delete_series`, `export`, vmui, `/metrics`, `force_merge` : **400** ; mauvais mot de passe : 401 |
| Loki | Second utilisateur du `htpasswd` de nginx ; routes filtrées par un `map` sur `$remote_user:$uri` (`monitoring/loki/nginx-loki.conf.j2`) | `/loki/api/v1/query`, `query_range`, `labels`, `label/<nom>/values`, `series` | `push`, `tail`, `delete`, `rules`, `/ready`, `/metrics` : **403** |

Mots de passe dans des fichiers dédiés : `/etc/victoria-metrics/vmauth.env` (0600 root, lu par
systemd ; `vmauth.yml` ne contient que des `%{...}`), `/etc/nginx/loki.htpasswd` (hash SHA-512),
`/etc/rag/{vm,loki}_password` sur rag01 (0640 root:rag, relus à chaque appel). Pare-feu : le
nftables de monitoring01 et la passerelle UniFi (`ra-app-to-monitoring`) acceptent déjà RA-APP
sur 3100 et 8428.

**Repli.** Si le modèle servi ne sait pas appeler d'outils (moins de 7 milliards de paramètres
selon `ollama show` : c'est le secours CPU, `llama3.2:3b` sous l'alias du modèle du GPU), si le
serveur MCP est injoignable ou si un outil échoue, l'agent répond avec `chain.ask`
(documentation seule), précédé de « [Mode dégradé : raison. Réponse tirée de la documentation
seule : elle ne reflète PAS l'état réel du système.] ». Une requête PromQL refusée est rendue au
modèle pour qu'il la corrige.

## 9. API de l'assistant (bot Discord)

Service `rag-api` (`api.py` de l'équipe IA, uvicorn, utilisateur `rag`, même venv, unité durcie
comme les autres), **port 8600**.

| | |
|---|---|
| URL | `http://127.0.0.1:8600` (bot local) ; `http://10.30.1.230:8600` depuis `rag_api_allowed` |
| Authentification | `Authorization: Bearer <jeton>` ; jeton dans Vault **`secret/infra/rag-api`, clé `RAG_API_TOKEN`**, déployé dans `/etc/rag/api_token` (0640 root:rag) et `/etc/discord-bot/api_token` (0640 root:qwen-bot). Comparaison à temps constant |
| `POST /ask` | Corps JSON `{"question": "...", "user": "pseudo"}` (`user` facultatif, 100 caractères au plus) |
| Réponse 200 | `{"answer": str, "tools": [outils appelés], "model": "qwen3.8:27b (27.3B)", "mode": "agent" ou "documentation", "duration_s": 17.7}` ; `answer` fait 1500 caractères au plus |
| `GET /health` | `{"status": "ok"}`, sans authentification |
| Erreurs | 401 jeton absent ou faux ; 413 corps de plus de 8 Ko ; 422 question vide ou de plus de 1000 caractères ; 429 plus de 10 questions dans la minute, tous utilisateurs confondus (`Retry-After`) ; 503 une autre question occupe l'assistant depuis plus de 30 s (`Retry-After: 30`) ; 504 pas de réponse en 120 s ; 500 erreur interne. Corps : `{"detail": "..."}` |

Une question à la fois (un seul GPU). Une ligne de journal par question, sans la question ni la
réponse : `question utilisateur=… statut=… mode=… outils=… duree=…` (journald, donc Loki :
`{host="rag01", unit="rag-api.service"} |= "question"`).

**Tester depuis rag01** (jeton lu dans le fichier, jamais affiché) :

```bash
sudo sh -c 'curl -s -H "Authorization: Bearer $(cat /etc/rag/api_token)" \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"la base est-elle en bonne santé ?\"}" http://127.0.0.1:8600/ask'
```

## 10. Bot Discord (« Qwen »)

Code dans [`infra/rag/discord_bot/`](../rag/discord_bot/) (`bot.py` ; `requirements.txt` figé :
discord.py **2.7.1**, publiée le 03/03/2026, httpx 0.28.1), déployé par le rôle `rag`
(`tasks/discord_bot.yml`) dans `/opt/discord-bot` (code et venv à root), service
**`discord-bot`**, utilisateur système **`qwen-bot`** (ni root, ni `rag`, sans shell).

**Fonctionnement.**

- Intents par défaut, **aucun intent privilégié** : Discord fournit le contenu d'un message qui
  mentionne le bot.
- Répond **seulement** sur le serveur `discord_guild_id` (**1562456667138818081**, « Workshop
  2026 ») et dans le salon `discord_channel_id` (**1562456703012839575**, #assistance-rag) ou ses
  fils (bot Discord de l'équipe : seul serveur / salon autorisés, variables de
  `inventory/group_vars/rag_servers.yml`), et seulement quand il est **mentionné** ou qu'on
  **répond à l'un de ses messages**. Ignore les autres bots et lui-même.
- Retire la mention ; refuse poliment une question vide ou de plus de 1000 caractères.
- Indicateur « en train d'écrire » pendant le calcul, appel `POST http://127.0.0.1:8600/ask`
  (`user` = nom d'affichage, délai 150 s), réponse **en réponse au message**, découpée en
  morceaux de 2000 caractères, avec un pied discret : `-# qwen3.8:27b · etat_plateforme · 18 s`
  (plus « mode dégradé » si l'agent est retombé sur la documentation seule).
- 429, 503, 504 ou délai dépassé : message clair (« Je suis occupé avec une autre question :
  réessaie dans une minute », « La réponse prend trop de temps (GPU indisponible ?) »...), jamais
  de trace d'erreur.
- Une question à la fois par utilisateur, 10 s entre deux questions.
- Les réponses ne notifient que l'auteur de la question (ni `@everyone`, ni rôles).
- Au démarrage : vérifie le serveur, le salon et les permissions (Voir le salon, Envoyer des
  messages, Lire l'historique, Envoyer dans les fils) et journalise une erreur explicite sinon.
- Message « Qwen est en ligne… » posté une seule fois au démarrage si `discord_bot_announce: true`
  (marqueur `/var/lib/discord-bot/annonce-faite`) : **désactivé par défaut**.

**Sécurité.** Jeton Discord dans Vault (**`secret/infra/discord-bot`, clé
`DISCORD_BOT_TOKEN`**, rangé par l'utilisateur), lu par `vault-env` et déposé dans
`/etc/discord-bot/discord_token` (**0600 qwen-bot**) ; jeton de l'API dans une copie 0640
root:qwen-bot. Tâches en `no_log`. Le bot ne parle qu'à Discord et à l'API locale, elle-même en
lecture seule : un message Discord ne peut déclencher aucune action sur le système. Unité durcie
(`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `PrivateDevices`, aucune
capacité ; seul `/var/lib/discord-bot` est inscriptible). Sortie Internet de rag01 vers Discord
(RA-APP vers Internet) ; aucune règle nftables en sortie.

**Exploitation.**

```bash
# Journaux (une ligne par question : utilisateur, statut, outils, durées)
ssh -i /root/.ssh/id_ed25519_infra debian@10.30.1.230 sudo journalctl -u discord-bot -f
#   Loki : {host="rag01", unit="discord-bot.service"}
# Redémarrer
ssh -i /root/.ssh/id_ed25519_infra debian@10.30.1.230 sudo systemctl restart discord-bot
# Changer de serveur ou de salon : discord_guild_id / discord_channel_id dans
# inventory/group_vars/rag_servers.yml, puis :
vault-env ansible-playbook rag.yml
# Nouveau jeton Discord : le ranger dans Vault (secret/infra/discord-bot), puis rag.yml
# Couper le bot (discord_bot_enabled=false ne désinstalle pas un bot déjà en place) :
#   sudo systemctl disable --now discord-bot
```

Au démarrage, le journal doit afficher `prêt : serveur « Workshop 2026 », salon #assistance-rag,
permissions OK`. Sinon : bot pas invité (lien d'invitation OAuth2, scope `bot`, à générer par
l'utilisateur dans le portail développeur Discord) ou permissions manquantes (Voir le salon,
Envoyer des messages, Lire l'historique des messages, Envoyer des messages dans les fils).

**Tester** : dans #assistance-rag, écrire `@Qwen-RAG-Bot quelles alertes ces 2 dernières
heures ?` ; la réponse arrive en réponse au message, avec le pied modèle · outils · durée.

## 11. Vérifications des outils, de l'API et du bot (21/10/2026)

| Vérification | Résultat |
|---|---|
| `monitoring.yml --limit monitoring01`, second passage | `changed=0` ; vmagents, vmalert, Grafana inchangés (`up`=1, ~3 900 points/s écrits) |
| `rag.yml`, second passage | `changed=0` |
| Compte lecture seule : écriture | VictoriaMetrics 400 (import, write, delete_series, export...), Loki 403 (push, delete, tail...) ; aucune série écrite |
| Outils MCP appelés directement | Conformes aux requêtes manuelles (mêmes noms d'alertes, primaire db3, score 0,38 / seuil 0,55, 4 bannissements) ; 0,05 à 0,6 s par outil |
| API sans jeton / faux jeton / 1001 caractères / corps de 9 Ko | 401 / 401 / 422 / 413 |
| Rafale de 12 questions simultanées | 5 × 200, 4 × 503 (occupé), 3 × 429 (limite de débit) |
| Depuis .110 : 8600 / 8501 / 8610 | 200 / fermé / fermé |
| Bot | `prêt : serveur « Workshop 2026 », salon #assistance-rag, permissions OK` ; premières questions de l'équipe traitées |

| Question (API) | Outils | Durée | Extrait |
|---|---|---|---|
| « quelles alertes ont eu lieu ces 2 dernières heures ? » | `alertes_recentes` | 31 s | 31 déclenchements, 0 actif ; PaiementAnomalieDetectee ×12, TargetDown ×10... |
| « la base de données est-elle en bonne santé ? » | `etat_plateforme` | 18 s | Primaire db3, db1 et db2 en réplication, retard 0 Kio |
| « quelles IP ont été bannies au WAF aujourd'hui ? » | `ip_bannies` | 25 s | 10.0.1.100 (2 fois, WafSourceAttacks), 10.0.1.110 (débannie), 203.0.113.7 (test) ; aucune encore bannie |
| « que faire si Vault est scellé ? » | `chercher_documentation` | 41 s | `vault-unseal` sur 10.0.1.110, puis tuile Vault du dashboard Démo [doc : infra-20...] |
| Repli : modèle CPU (3,2 B) | aucun | 26 s | « [Mode dégradé : modèle de secours sans appel d'outils...] » |
| Repli : serveur MCP injoignable | aucun | 41 s | « [Mode dégradé : supervision ou outil en erreur...] » |
