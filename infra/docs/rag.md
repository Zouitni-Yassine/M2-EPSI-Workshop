# Assistant RAG des opérateurs (rag01)

L'équipe IA a écrit un assistant local qui répond aux questions des opérateurs à partir des
procédures et des documents du projet (Ollama + LangChain + ChromaDB + Streamlit, code dans le
dossier `rag/` de la branche `IA`). L'infra l'héberge sur une VM dédiée, `rag01`, créée et
configurée entièrement en code (21/10/2026).

L'assistant aide à comprendre et à retrouver une procédure. Il **n'agit sur rien** : ce n'est pas
le moteur de remédiation.

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
| Aucun secret sur la machine | Ni clé SSH, ni jeton Vault, ni mot de passe : le seul secret déployé est celui de Loki, lisible par Alloy uniquement (`/etc/alloy/loki_password`, 0640 root:alloy) |
| Utilisateurs système dédiés | `rag` et `ollama`, sans shell ni sudo |
| Code en lecture seule | Code et venv appartiennent à root ; le service n'écrit que dans `/var/lib/rag` |
| Services durcis (systemd) | `NoNewPrivileges`, `ProtectSystem=strict` + `ReadWritePaths`, `ProtectHome`, `PrivateTmp`, `PrivateDevices`, aucune capacité |
| Ollama local uniquement | API sur **127.0.0.1:11434** : ni le réseau ni les autres VM ne parlent aux modèles |
| Pas d'appel sortant de l'appli | Télémétrie de ChromaDB et de Streamlit coupée |

## 3. Composants

| Composant | Version | Détail |
|---|---|---|
| Ollama | **v0.35.1** (29/09/2026) | Archive officielle `ollama-linux-amd64.tar.zst` de la release GitHub, sha256 vérifié, `/opt/ollama/v0.35.1`, service `ollama`, données `/var/lib/ollama` |
| Modèle de génération | `llama3.2:3b` (2,0 Go) | Choix de l'équipe IA (≤ 8 milliards de paramètres) |
| Modèle d'embeddings | `nomic-embed-text` (274 Mo) | |
| Code de l'assistant | branche `IA`, commit **`1b7f20b`** (`rag_git_ref`) | `/opt/rag/releases/<commit>`, lien `/opt/rag/app` |
| Dépendances Python | venv `/opt/rag/venv` | Versions figées par `roles/rag/files/constraints.txt` (le `requirements.txt` de l'équipe IA n'en fixe aucune) : langchain 1.4.6, langchain-community 0.4.2, langchain-ollama 1.1.0, chromadb 1.5.9, streamlit 1.66.0, pypdf 6.21.1 |
| Base vectorielle | ChromaDB | `/var/lib/rag/chroma_db` (lien `chroma_db` dans le code, qui utilise un chemin relatif) |
| Interface | Streamlit, service `rag-assistant` | `0.0.0.0:8501`, `--server.headless true` |

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
| LAN d'administration (10.0.1.0/24) et VPN admin (`LSN - UGC`, `EPSI-WG`) | **http://10.30.1.230:8501** |
| PC de délestage IA (VPN `EPSI-WS-IA`, 192.168.2.0/24) | 8501 et SSH (tunnel vers Ollama ; compte de tunnel pas encore créé) |
| Poste de contrôle | SSH `debian@10.30.1.230` (clé `id_ed25519_infra`) |
| Supervision | node_exporter (9100) depuis les vmagents uniquement ; logs par Alloy vers Loki |

Firewall nftables de rag01 (`roles/rag/templates/nftables.conf.j2`) : politique `drop`, SSH depuis
`fw_ssh_allowed`, 8501 depuis `fw_monitoring_allowed` et `fw_admin_web_allowed`, 9100 depuis les
vmagents, 22 et 8501 depuis `rag_gpu_vpn_cidr`. 11434 n'est jamais ouvert.

## 5. Déploiement

```bash
# VM et HA
tf plan && tf apply

# Configuration (idempotente)
cd /srv/M2-EPSI-Workshop/infra/ansible
vault-env ansible-playbook rag.yml

# Collecte node_exporter (cible ajoutée au job "node" depuis l'inventaire)
vault-env ansible-playbook monitoring.yml --limit vmagents
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
| Pas d'authentification sur l'interface Streamlit (filtrée par IP seulement) | Reverse proxy avec SSO Keycloak |
| La pertinence dépend du corpus et de la recherche (4 segments) : sur payment-api, les documents du backend passent avant la fiche infra | Métadonnées par type de document, re-classement, plus de segments |
| Une seule instance (HA Proxmox, pas de redondance applicative) | Acceptable : l'assistant n'est pas sur le chemin critique du paiement |
| `RA-APP` peut joindre Vault (8200) et Keycloak (443) au niveau réseau (règles du Swarm) | Segment dédié ou règles par adresse source ; rag01 n'a de toute façon aucun identifiant |
