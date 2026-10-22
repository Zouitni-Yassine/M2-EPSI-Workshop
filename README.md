<div align="center">

# 🛡️ PROJECT RESILIENCE-ALPHA

### Cyber-résilience et reprise autonome — Plateforme de paiement *Resilience Pay*

**Workshop National EPSI — BAC+5 — Session Octobre 2026**
Consortium **M2 · Groupe G\<n\>**

*« Un conteneur qui redémarre n'est pas une preuve : notre preuve, c'est un paiement réussi. »*

</div>

---

> **La mission.** Démontrer qu'un système d'information critique — ici une plateforme de paiement
> fictive — peut **encaisser un incident de sécurité et retrouver son fonctionnement sans qu'un
> opérateur intervienne pour le réparer**. Pas sur le papier : sur un environnement conçu,
> développé, installé et testé par l'équipe.

De l'attaque au paiement vérifié, **sans humain dans la boucle** :

```
Attaque ─▶ Collecte (métriques + journaux) ─▶ Détection ML (2–4 s) ─▶ Décision
   │                                                                      │
   │                                                       Moteur de remédiation
   │                                                   (passerelle à liste fermée)
   ▼                                                                      ▼
WAF : IP bannie (27 s)                         Service redémarré ─▶ Paiement de contrôle ✅
```

---

## Sommaire

- [Les cinq piliers](#les-cinq-piliers)
- [Démarrage rapide](#démarrage-rapide)
- [Architecture en bref](#architecture-en-bref)
- [Résultats mesurés](#résultats-mesurés)
- [Navigation du dépôt](#navigation-du-dépôt)
- [Documentation](#documentation)
- [Contributions de l'équipe](#contributions-de-léquipe)
- [Livrables & sécurité](#livrables--sécurité)

---

## Les cinq piliers

La solution réunit cinq domaines complémentaires, tous obligatoires.

| | Domaine | Ce qui a été construit | Dossier |
|---|---|---|---|
| 💻 | **Développement** | Microservices (auth, API de paiement, détecteur, moteur de remédiation), frontal React/Tailwind, reconnaissance faciale des opérateurs | [`auth/`](auth) · [`backend/`](backend) · [`frontend/`](frontend) · [`remediation/`](remediation) |
| 🏗️ | **Infrastructure** | Cluster Proxmox + Ceph (HA), Docker Swarm, tout en code (Packer/Terraform/Ansible), observabilité, base répliquée, chaos engineering | [`infra/`](infra) |
| 🤖 | **IA / Data** | Détecteur d'anomalies (IsolationForest), assistant RAG des opérateurs (Ollama + LangChain) | [`detector/`](detector) · [`rag/`](rag) · [`evaluation/`](evaluation) |
| 🔐 | **Cybersécurité** | WAF (ModSecurity + CRS), SIEM/SOC, bannissement automatique, Vault, SSO + TOTP, scénarios Red Team | [`cyber/`](cyber) · [`redteam/`](redteam) |
| 🧭 | **Gouvernance** | EBIOS RM, PCA/PRA, analyse NIS2/DORA, arbitrages et recommandations | [`gouvernance/`](gouvernance) |

---

## Démarrage rapide

> Le détail pas à pas, les prérequis et le dépannage sont dans
> [`infra/docs/deploiement.md`](infra/docs/deploiement.md).

**Application seule** (microservices, pour le développement) :

```bash
python scripts/init-secrets.py          # secrets locaux (jamais commités)
cp backend/.env.example backend/.env    # clés Stripe / PayPal (mode test)
cp auth/.env.example auth/.env          # mots de passe de départ
cp detector/.env.example detector/.env  # jeton d'administration du détecteur
docker compose up --build -d            # db, auth, payment-api, detector, remediation, frontend
```
Interface : http://localhost:5173 · API : http://localhost:5173/api

**Plateforme complète** (infrastructure reproductible) : chaîne *Packer → Terraform → Ansible*
depuis le poste de contrôle. Les applications restent décrites en fichiers Compose et sont
déployées sur Docker Swarm. Voir [`infra/README.md`](infra/README.md).

---

## Architecture en bref

Internet n'atteint **jamais** l'application en direct : tout passe par le reverse-proxy TLS,
le WAF en DMZ, puis l'adresse virtuelle du cluster.

```
Internet ─443─▶ NPM (TLS) ─8443─▶ WAF ModSecurity [DMZ] ─5173─▶ VIP keepalived
                                                                    │
                 ┌──────────────── Docker Swarm [VLAN applicatif] ──┴────────────────┐
                 │  frontal ×3 ─▶ auth ─▶ payment-api ─▶ PostgreSQL (Patroni ×3)      │
                 │  détecteur ML · moteur de remédiation · sonde de transaction       │
                 └────────────────────────────────────────────────────────────────────┘
```

- **Socle** : 3 hyperviseurs **Proxmox VE 9 + Ceph**, haute disponibilité avec fencing.
- **Orchestration** : **Docker Swarm** (3 managers drainés, 3 workers), secrets, mises à jour
  avec retour arrière.
- **Observabilité** : **VictoriaMetrics** (compatible Prometheus), vmalert, Alertmanager (Discord),
  **Loki**, **Grafana**, Alloy ; une sonde paie comme un vrai client toutes les 30 s.
- **Identités & secrets** : **Keycloak** (SSO + TOTP), **HashiCorp Vault**, Vaultwarden.

Décisions détaillées : [`infra/docs/architecture.md`](infra/docs/architecture.md) ·
Réseau et segmentation : [`infra/docs/reseau.md`](infra/docs/reseau.md).

---

## Résultats mesurés

Référence : la **panne vue par la sonde** (un vrai client qui paie), pas un simple
`/api/health`. Source : [`infra/docs/tests-resilience.md`](infra/docs/tests-resilience.md).

| Scénario provoqué | Qui répare | Panne vue par un client |
|---|---|---|
| API de paiement arrêtée | détecteur ML → moteur → passerelle | **10 à 16 s**, 0 intervention |
| Rafale (40 requêtes parallèles) | détecteur, moteur | **0 s** (anomalie à +4 s) |
| Force brute sur la connexion | bannissement au WAF | **IP bannie en 27 s** |
| PostgreSQL tué | Patroni / Swarm | **0 paiement perdu** |
| Perte de la VM portant la base | réplication Patroni | **92 s → 0 s** |
| Frontal tué (3 réplicas) | Swarm, maillage de routage | **0 s** |
| Hyperviseur entier coupé | quorum, Ceph, Swarm | application disponible |

> 15+ pannes provoquées, **toutes réparées sans intervention humaine** (hors restauration et
> descellement de Vault, manuels par nature). Détecteur ML : **F1 0,86 · rappel 0,92**.

---

## Navigation du dépôt

### Application (racine)

| Dossier | Rôle |
|---|---|
| [`auth/`](auth) | Service d'authentification (comptes, JWT, anti force brute, **reconnaissance faciale**) |
| [`backend/`](backend) | API de paiement (Stripe & PayPal en mode test) |
| [`detector/`](detector) | Détecteur d'anomalies ML (IsolationForest), exposé en `/metrics` |
| [`remediation/`](remediation) | Moteur de remédiation (décide, puis appelle la passerelle à liste fermée) |
| [`frontend/`](frontend) | Frontal React + Tailwind : boutique, back-office, supervision, scénario de démo |
| [`db/`](db) | Schéma et initialisation PostgreSQL |
| [`docker-compose.yml`](docker-compose.yml) | Définition des microservices (sert aussi au déploiement Swarm) |
| [`docs/`](docs) | Schémas d'architecture de référence (PDF, PPTX, PNG) |
| [`scripts/`](scripts) | Outils locaux (génération des secrets de développement) |

### Infrastructure — [`infra/`](infra)

| Dossier | Rôle |
|---|---|
| [`infra/packer/`](infra/packer) | Images de VM (Debian + Docker) |
| [`infra/terraform/`](infra/terraform) | VM, LXC, SDN, haute disponibilité Proxmox |
| [`infra/ansible/`](infra/ansible) | Configuration : Swarm, firewall, observabilité, application, assistant |
| [`infra/app/`](infra/app) | Stack Swarm `paiement`, base répliquée (Patroni + etcd) |
| [`infra/monitoring/`](infra/monitoring) | VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana, dashboards |
| [`infra/waf/`](infra/waf) | Configuration du WAF (ModSecurity) et bannissement automatique |
| [`infra/pki/`](infra/pki) | Autorité de certification interne |
| [`infra/chaos/`](infra/chaos) | Chaos engineering : injection de pannes, mesure de la reprise |
| [`infra/demo/`](infra/demo) | Scénario de démonstration et vérifications pré-démo |
| [`infra/rag/`](infra/rag) | Hébergement de l'assistant (relais Ollama, outils de supervision MCP, bot Discord) |
| [`infra/roadmap/`](infra/roadmap) | Feuille de route du projet |
| [`infra/unifi/`](infra/unifi) | Réseau déclaratif (VLAN, règles de filtrage) |
| [`infra/docs/`](infra/docs) | **Documentation technique complète** (voir ci-dessous) |

### IA, Cyber, Gouvernance

| Dossier | Rôle |
|---|---|
| [`rag/`](rag) | Assistant des opérateurs (Ollama + LangChain), corpus et chaîne de recherche |
| [`evaluation/`](evaluation) | Évaluation du détecteur : scénario, scores, notebook, courbes |
| [`cyber/`](cyber) | Dispositifs défensifs, exploitation, note pour le jury |
| [`redteam/`](redteam) | Scénarios d'attaque reproductibles (périmètre borné au SI fictif) |
| [`gouvernance/`](gouvernance) | BIA, EBIOS RM, PCA/PRA, NIS2/DORA, arbitrages |

---

## Documentation

Toute la documentation technique de l'infrastructure est dans [`infra/docs/`](infra/docs) :

| Document | Contenu |
|---|---|
| [`architecture.md`](infra/docs/architecture.md) | Décisions, alternatives écartées, limites |
| [`reseau.md`](infra/docs/reseau.md) | VLAN, flux autorisés, adresse virtuelle |
| [`application.md`](infra/docs/application.md) | Stack Swarm, exposition publique, sonde, reconnaissance faciale |
| [`supervision.md`](infra/docs/supervision.md) | Métriques, logs, alertes, dashboards |
| [`waf.md`](infra/docs/waf.md) | WAF en DMZ, bannissement automatique |
| [`remediation.md`](infra/docs/remediation.md) | Passerelle : actions, garde-fous, tests |
| [`identites.md`](infra/docs/identites.md) | Keycloak, Vault, Vaultwarden, CA interne |
| [`tests-resilience.md`](infra/docs/tests-resilience.md) | Méthode et résultats du chaos engineering |
| [`pca-pra-technique.md`](infra/docs/pca-pra-technique.md) | Services critiques, RTO/RPO, sauvegardes |
| [`rag.md`](infra/docs/rag.md) | Assistant des opérateurs, hébergement isolé |
| [`demo.md`](infra/docs/demo.md) | Scénario de démonstration, check-list, plan B |
| [`api/`](infra/docs/api) | Documentation des API (OpenAPI) |

Gouvernance : commencer par [`gouvernance/README.md`](gouvernance/README.md).

---

## Contributions de l'équipe

> Chaque membre assume une contribution clairement identifiable ; les décisions d'architecture
> sont restées partagées.

| Membre | Domaine | Apports principaux |
|---|---|---|
| **Samuel Labreze** | 🏗️ Infrastructure & 🧭 Gouvernance | Socle Proxmox/Ceph (HA), Swarm, IaC complet, observabilité, base répliquée, chaos engineering, WAF en DMZ, hébergement de l'assistant · EBIOS RM, PCA/PRA, analyse NIS2/DORA, arbitrages |
| **Grégoire Mouilleau** | 💻 Développement | Connecteur de paiement **PayPal**, **reconnaissance faciale** des opérateurs |
| **Yassine Zouitni** | 💻 Développement | Connecteur de paiement **Stripe**, **frontal** React / Tailwind |
| **Rémi Reze** | 🔐 Cybersécurité | WAF (ModSecurity + CRS), SIEM / SOC, bannissement automatique, durcissement, scénarios Red Team |
| **Nadège Matezere** | 🤖 IA / Data & RAG | Détecteur d'anomalies (IsolationForest, évaluation), assistant RAG des opérateurs |

---

## Livrables & sécurité

- **Déploiement reproductible** : la plateforme se réinstalle et se relance depuis ce dépôt ;
  les playbooks sont idempotents.
- **Aucun secret en clair** : tous les secrets sont dans HashiCorp Vault, lus à l'exécution ;
  aucun `.env` réel, aucune clé versionnée. Le diff sortant est scanné avant chaque *commit*.
- **Périmètre** : environnement, opérations et données **entièrement fictifs** ; aucune donnée
  bancaire réelle. Les actions offensives sont limitées au SI fictif de l'équipe.

<div align="center">

---

*EPSI — Direction Pédagogique Nationale — Workshop BAC+5 2026-27*

</div>
