# WAF : waf01 en RA-DMZ devant l'application

Le WAF de l'équipe cyber (`waf01`, ModSecurity + OWASP CRS) est le seul point d'entrée public de
Resilience Pay. Il a été déplacé de `MANAGEMENT` (10.0.1.251) vers `RA-DMZ` (**10.30.2.251**) et
branché sur l'application le 21/10/2026, avec l'accord de l'équipe cyber. Contexte complet de la
publication (NPM, frontal, règles UniFi) : [application.md](application.md#exposition-publique-de-lapplication).

## 1. Chaîne d'une requête

```text
Internet ── 443 TLS (Let's Encrypt, HSTS) ──> NPM 172.16.1.10 (géré par l'utilisateur)
         ── 8443 TLS (CA interne) ──────────> waf01 10.30.2.251 (RA-DMZ)
                                               ModSecurity + CRS, paranoïa 1, blocage
         ── 5173 HTTP ──────────────────────> adresse virtuelle 10.30.1.200 (keepalived, workers)
                                               frontal paiement_frontend -> /api, /auth
```

| Élément | Valeur |
|---|---|
| Règles UniFi | `ra-npm-to-waf` (NPM → RA-DMZ 8443), `ra-dmz-to-app` (RA-DMZ → RA-APP 5173), `ra-dmz-to-loki`, `ra-mgmt-to-dmz` (administration) |
| Firewall nftables du WAF (`/opt/resilience-waf/waf-firewall.nft`, copié dans `/etc/waf-firewall.nft`, chargé par `waf-firewall.service`) | 22 depuis 10.0.1.0/24 ; 8080/8443 depuis 10.0.1.0/24, 10.250.90.9 et **172.16.1.10 (NPM)**. Le fichier commence par `table inet waf_host` + `delete table inet waf_host` : un `systemctl restart waf-firewall` le recharge de façon atomique, sans doublon |
| Backend | `BACKEND` (compose.yml) et `proxy_pass` (`default.conf.template`) : `http://10.30.1.200:5173`. Le conteneur de démo `resilience-waf-demo` tourne encore mais n'est plus utilisé |
| IP réelle du client | `set_real_ip_from 172.16.1.10; real_ip_header X-Forwarded-For;` dans le serveur 8443 : seule l'adresse envoyée par NPM est crue, `$remote_addr` (journaux, règles ModSecurity) est celle du client. Le WAF la retransmet au frontal (`X-Forwarded-For $remote_addr`) |
| `server_name` (8443) | `waf01 waf01.epsi.lsn 10.30.2.251 app.slabreze.fr` |
| Certificat | Signé par la CA interne (EC P-256, 1 an, `serverAuth`) ; SAN `waf01`, `waf01.epsi.lsn`, `app.slabreze.fr`, IP 10.30.2.251, 127.0.0.1. Émis sur .110 dans `/root/.pki/issued/waf01/` (la clé de la CA ne quitte pas .110) |

Les fichiers modifiés de `/opt/resilience-waf` ont une copie `*.bak-20261021` (droits d'origine ;
anciens certificat et clé en 0600).

**Proxy host NPM** (fait par l'utilisateur) : `app.slabreze.fr` → scheme `https`, forward
`10.30.2.251`, port `8443`. NPM ne vérifie pas le certificat du WAF par défaut (lien interne).

Bascule faite le 21/10/2026 : règle temporaire `ra-npm-to-app-temp` (NPM directement vers le
frontal, sans WAF) **retirée** de la passerelle. Plus aucun accès à l'application depuis l'extérieur
ne contourne le WAF. Vérifié par l'URL publique : page 200, injection SQL 403, paiement complet
(connexion, création, confirmation carte de test) `succeeded`, IP réelle des clients dans les
journaux du WAF.

## 2. waf01 dans Terraform

La VM avait été créée à la main (clone du template). Elle est désormais décrite par
[`terraform/waf.tf`](../terraform/waf.tf) et **importée** (bloc `import`, id `ceph01/251`), sans
recréation :

- `lifecycle.prevent_destroy = true` : Terraform refuse tout plan qui la détruirait ;
- `ignore_changes = [clone, disk, node_name, description, initialization[0].user_account]` :
  attributs impossibles à décrire fidèlement pour une VM importée (pas de clone à rejouer, disque
  créé hors Terraform, compte cloud-init déjà en place) ou portés par la HA (nœud) ;
- import vérifié par un premier plan sans changement de réseau : seul `stop_on_destroy`
  (attribut propre à Terraform) apparaissait ;
- le passage en RA-DMZ est une **modification en place** : carte `net0` sur le vnet `radmz`
  (même MAC `BC:24:11:8C:9C:21`, que le netplan utilise pour reconnaître l'interface), cloud-init
  `10.30.2.251/24`, passerelle et DNS `10.30.2.254`, `ciupgrade` désactivé (`upgrade = false`).
  Le provider a redémarré la VM ; cloud-init a vu une nouvelle instance et régénéré
  `/etc/netplan/50-cloud-init.yaml`. Sans `upgrade = false`, ce premier démarrage rejoué aurait
  lancé un `apt upgrade` (Docker compris) ;
- **HA** : la VM n'avait pas de ressource HA. `proxmox_haresource.waf` (`vm:251`, `started`,
  2 redémarrages, 1 relocalisation) est créée à part, sans règle de nœud préféré : l'ajouter aux
  règles `home-*` de [`ha.tf`](../terraform/ha.tf) aurait modifié les règles du socle.

Le contenu du WAF (`/opt/resilience-waf`) reste à l'équipe cyber ; Ansible n'y applique que le
rôle `alloy` (groupe `waf`, adresse mise à jour dans l'inventaire) et les ajouts du
bannissement automatique (`waf-ban.yml`, section 5).

## 3. Retour arrière

Snapshots Proxmox de la VM 251 : `before-waf-20261020`, `waf-validated-20261020` (WAF validé,
page de démo), **`avant-dmz-20261021`** (juste avant le passage en RA-DMZ). Un retour à ce dernier
(`qm rollback 251 avant-dmz-20261021`) remet la configuration de la VM sur `vmbr0` / 10.0.1.251 :
il faut alors aussi revenir sur `waf.tf` (réseau) et l'inventaire, sinon le `tf plan` suivant
redéplace la VM. Pour le seul contenu du WAF, les copies `*.bak-20261021` suffisent.

## 4. Tests du 21/10/2026

Depuis le poste de contrôle (.110) :

| Test | Attendu | Obtenu |
|---|---|---|
| `ping 10.30.2.251`, SSH | répond | OK |
| `ip -4 addr`, route par défaut sur waf01 | 10.30.2.251/24, via 10.30.2.254 | OK, netplan régénéré |
| Accès Internet depuis waf01 (`apt-get update`, HTTPS) | OK | OK |
| `http://10.30.1.200:5173/` depuis waf01 | 200 | 200 |
| Conteneur `resilience-waf` | healthy | healthy, `nginx -t` OK |
| `https://10.30.2.251:8443/healthz` | 200 | 200 |
| `https://10.30.2.251:8443/` (vérifié avec la CA interne) | 200, frontal (`<div id="root">`) | 200, frontal |
| `/api/health` | JSON `ok` | `{"ok":true,…,"db":true}` |
| `/?id=1' OR 1=1--` (injection SQL) | 403 | 403 |
| `/?q=<script>alert(1)</script>` (XSS) | 403 | 403 |
| `http://10.30.2.251:8080/` | 301 vers 8443 | 301 |
| `--resolve app.slabreze.fr:8443:10.30.2.251` (SNI et nom du certificat) | 200 | 200 |
| Logs dans Loki (`{host="waf01"}`) | flux journal et `resilience-waf` | reçus après le changement d'IP, blocages 403 visibles |
| `tf plan` après l'apply | aucun changement | « No changes » |
| `monitoring.yml --limit waf01` (rôle alloy) | `changed=0` | `changed=0` |

Logs : `{host="waf01",container="resilience-waf"} | json | status="403"` pour les blocages.

## 5. Bannissement automatique

Réponse à l'attaque : la remédiation existante rétablit la disponibilité (redémarrage de
payment-api) mais ne bloque pas la source. Le bannissement contient l'attaquant au WAF, sans
intervention humaine, pour 15 minutes. Mis en place le 21/10/2026 avec l'accord de l'équipe
cyber.

```text
waf01 (nginx, journal JSON : source_ip = IP réelle derrière NPM)
  ── Alloy ──> Loki (monitoring01) : règles waf-ban.yml, évaluées toutes les 15 s
  ── alerte action="ban", source_ip ──> Alertmanager (group_wait 5 s)
        ├─> Discord (humains prévenus)
        └─> POST http://10.30.2.251:9095/alertmanager (jeton Bearer)
              waf-ban.service : contrôles, ajout à banned.conf, nginx -t, nginx -s reload
              ──> nginx : geo $waf_banned -> 403 pour cette IP (sauf /healthz), 15 min
```

### Règles et seuils (`monitoring/loki/rules/waf-ban.yml`)

| Alerte | Condition, par IP source | Pourquoi ce seuil |
|---|---|---|
| `WafSourceFlood` | plus de 1200 requêtes en 1 min (20/s en moyenne), hors `/healthz` | une page complète du site fait ~25 requêtes |
| `WafSourceBruteForce` | au moins 10 POST `/auth/login` ou `/auth/token` en 401 ou 429 en 2 min | l'application freine déjà (429) au bout de 5 échecs |
| `WafSourceAttacks` | au moins 10 réponses 403 en 2 min | blocages ModSecurity répétés (un refus applicatif compte aussi) |

Pas de `for` : l'alerte part à la première évaluation (15 s au plus). Les requêtes refusées
pour bannissement sont journalisées avec `event_type="waf_banned"` : elles ne comptent dans
aucune règle (ni dans `WAFRepeatedBlocks` de l'équipe cyber), l'alerte se résout donc une
fois l'IP bannie.

### Côté WAF

| Élément | Emplacement |
|---|---|
| Récepteur (Python standard, sans dépendance) | `/usr/local/sbin/waf-ban` ← [`waf/waf-ban.py`](../waf/waf-ban.py) |
| Service | `waf-ban.service` ← [`waf/waf-ban.service.j2`](../waf/waf-ban.service.j2), utilisateur `waf-ban` |
| Extraits nginx | `/opt/resilience-waf/waf-ban/{http,server}.conf` ← [`waf/nginx/`](../waf/nginx/), montés en lecture seule dans le conteneur (`/etc/nginx/waf-ban`) |
| Liste des IP bannies | `/opt/resilience-waf/waf-ban/banned/banned.conf` (format `geo`, une ligne `<ip> 1; # expire=… raison=…`), seul fichier écrit par le service |
| Jeton, liste blanche | `/etc/waf-ban/token`, `/etc/waf-ban/allowlist` (0640 root:waf-ban) |
| Ajouts aux fichiers de l'équipe cyber | `default.conf.template` : `include` du niveau http en tête et `include …/server.conf;` dans les serveurs 8080 et 8443 ; `compose.yml` : volume `./waf-ban` ; `waf-firewall.nft` et `/etc/waf-firewall.nft` : `ip saddr 10.0.1.233/32 tcp dport 9095 accept`. Copies d'origine `*.bak-20261021-ban` |

Déploiement idempotent (second passage `changed=0`) :

```bash
cd /srv/M2-EPSI-Workshop/infra/ansible
vault-env ansible-playbook waf-ban.yml                          # waf01
vault-env ansible-playbook monitoring.yml --limit monitoring01  # règles, route, jeton
```

Un changement de `default.conf.template` ou de `compose.yml` recrée le conteneur (templates
rendus au démarrage, ~15 s sans WAF) ; un changement des extraits ne fait qu'un `nginx -s
reload`.

**IP réelle** : `geo` lit l'adresse du client après réécriture par `realip`
(`set_real_ip_from 172.16.1.10`), donc l'IP du client et non celle de NPM. NPM ajoute l'adresse
qu'il voit en dernier dans `X-Forwarded-For` et nginx ne prend que celle-là : un attaquant ne
peut pas faire bannir une autre adresse en forgeant cet en-tête. Le bannissement est fait dans
nginx et non dans nftables, qui ne voit que NPM comme source du trafic public.

### Garde-fous

- **Authentification** : jeton Bearer de 43 caractères (Vault `secret/infra/waf-ban`,
  `WAF_BAN_TOKEN`), comparaison à temps constant ; sans jeton valide : 401 et ligne
  `refus_auth`. Le port 9095 n'est ouvert qu'à 10.0.1.233 (nftables), et le service lui-même
  n'accepte que cette adresse et l'hôte (`IPAddressAllow`).
- **Jamais bannies** : bouclage, adresses spéciales, NPM 172.16.1.10, supervision 10.0.1.233 et
  réseaux RA-* 10.30.0.0/16 (dans le code) ; liste blanche `waf_ban_allowlist` de
  `waf-ban.yml` (poste de contrôle 10.0.1.110), relue à chaque alerte. Les VPN d'administration
  ne sont volontairement pas protégés (scénario du « PC admin compromis »).
- **Plafonds** : 20 IP bannies au plus, 5 nouveaux bannissements par minute au plus ; au-delà,
  refus journalisé (`cause=plafond_…`).
- **Expiration** : 15 min, vérifiée toutes les 10 s par le service, suivie d'un rechargement.
- **Sûreté** : IP validée par `ipaddress` avant toute écriture ; fichier remplacé de façon
  atomique ; `nginx -t` avant chaque rechargement, retour à la liste précédente en cas
  d'échec ; aucune commande reçue n'est exécutée (seuls `nginx -t` et `nginx -s reload`, en
  dur). Service sans capacité, système en lecture seule sauf la liste
  (`systemd-analyze security` : 1.5 « OK »). Le groupe `docker`, nécessaire au rechargement,
  équivaut à root sur l'hôte : c'est la limite de ce durcissement.
- **Journal** (identifiant `waf-ban`, donc dans Loki) : une ligne par décision.

```text
ban ip=10.0.1.110 raison=WafSourceBruteForce duree_s=900 expire=10:50:20 actifs=1
refus ip=172.16.1.10 cause=adresse_protegee raison=TestManuel
expiration ip=203.0.113.7 raison=TestManuel actifs=0
deban ip=10.0.1.110 par=manuel actifs=0
```

Dashboard « Démo / Remédiation » : annotation **IP bannie au WAF**. Loki :
`{host="waf01",identifier="waf-ban"}` (décisions),
`{host="waf01",container="resilience-waf"} | json | event_type="waf_banned"` (requêtes refusées).

### Exploitation

```bash
ssh -i /root/.ssh/id_ed25519_infra debian@10.30.2.251
sudo waf-ban list                 # IP bannies, expiration (heure UTC de waf01), raison
sudo waf-ban unban 203.0.113.7    # débannir tout de suite (journalisé)
sudo waf-ban unban --all          # tout vider
sudo systemctl stop waf-ban       # suspendre le bannissement automatique
```

Ne pas éditer `banned.conf` à la main : passer par `waf-ban unban`, qui recharge nginx.
Un débannissement prend effet en 1 à 3 s (les connexions gardées ouvertes par NPM sont servies
par l'ancien processus nginx jusqu'à la fin du rechargement).

### Tests du 21/10/2026

| Test | Attendu | Obtenu |
|---|---|---|
| Webhook sans jeton / avec un mauvais jeton (depuis monitoring01) | 401 | 401, 401 (`refus_auth`) |
| Port 9095 depuis .110 | fermé | timeout (nftables) |
| Webhook authentifié, `source_ip=203.0.113.7` | ban, nginx rechargé | `ban`, ligne dans `banned.conf` visible dans le conteneur |
| Même alerte une seconde fois | pas de doublon | `deja_banni` |
| 172.16.1.10, 10.30.1.200, 10.0.1.110, `1.2.3.4; rm -rf /` | refus | `adresse_protegee`, `adresse_protegee`, `liste_blanche`, `ip_invalide` |
| Alerte `resolved` ou sans `action="ban"` | ignorée | ignorée |
| Expiration (date avancée) | retirée et journalisée | retirée en moins de 10 s, `expiration` |
| **Bout en bout** : 12 POST `/auth/login` erronés depuis .110 par l'URL publique (exception temporaire de la liste blanche) | IP réelle vue par le WAF, alerte, ban | WAF voit 10.0.1.110 ; `WafSourceBruteForce` → Alertmanager → `ban` ; `/` et `/api/health` en 403 |
| Délai attaque → bannissement | < 1 min | **27 s** (premier échec 10:34:55, `ban` 10:35:21, premier 403 10:35:22) |
| `/healthz` pendant le bannissement | 200 | 200 (public et direct) |
| Débannissement manuel, liste blanche rétablie | 200 | 200 en moins de 3 s |
| Second passage des deux playbooks | `changed=0` | `changed=0` |

Le délai se décompose ainsi : arrivée des logs dans Loki, évaluation du ruler (toutes les
15 s), `group_wait` de 5 s, rechargement de nginx (< 1 s).

### Limites

- Une IP partagée (NAT d'entreprise, opérateur mobile) est bannie pour tous ses utilisateurs ;
  les seuils restent volontairement élevés et la durée courte.
- IPv6 : géré par le récepteur et `geo`, mais la chaîne publique est en IPv4 seulement.
- Une attaque distribuée (beaucoup d'IP, chacune sous les seuils) n'est pas arrêtée ; le
  plafond de 20 IP limite aussi l'effet d'un emballement.
- Le webhook circule en HTTP entre MANAGEMENT et RA-DMZ (jeton lisible sur ce lien interne) ;
  il ne permet que de bannir 15 min une IP hors liste blanche.
- `WafSourceAttacks` compte aussi les 403 de l'application.
- Le bannissement ne remplace pas la remédiation de disponibilité : il contient la source,
  le moteur de remédiation rétablit le service.
- Les fichiers de `/opt/resilience-waf` restent ceux de l'équipe cyber : une réinstallation de
  leur côté doit être suivie de `waf-ban.yml`.

## 6. Routes de la caméra (reconnaissance faciale, 22/10/2026)

La connexion des opérateurs par visage (consigne additionnelle, voir
[application.md](application.md#reconnaissance-faciale-du-back-office-consigne-additionnelle))
envoie des images de la caméra à auth. Le WAF limitait tous les corps à 1 Mo : l'envoi des
5 images au jugement ne passait pas.

### Changement

Fichier versionné `infra/waf/nginx/site-8443.conf` (inclus dans le serveur 8443, déployé par
`waf-roadmap.yml`) : une `location` à expression régulière sur les 5 routes caméra, et
seulement elles.

```nginx
location ~ "^/auth/(identify/[A-Za-z0-9_-]+/(frames|probe)|admin/face/probe|admin/accounts/[^/]+/face(/scan)?)$" {
    client_max_body_size 4m;
    proxy_pass http://10.30.1.200:5173;
    # mêmes en-têtes que le relais principal (X-Forwarded-For $remote_addr, X-Request-ID…)
    proxy_connect_timeout 3s;
    proxy_read_timeout 30s;
    proxy_send_timeout 30s;
}
```

Le navigateur envoie au plus 8 images JPEG (400 ko chacune au plus). Le délai de 30 s couvre
le calcul des gabarits sur CPU. Le bloc reprend les en-têtes du relais principal : l'IP réelle
du client arrive toujours à auth. Pas d'`add_header` dans ce fichier : il annulerait les
en-têtes de sécurité définis au niveau du serveur.

| Route | Rôle | Corps accepté |
|---|---|---|
| `/auth/identify/<id>/probe` | Guidage pendant la capture (connexion) | 4 Mo |
| `/auth/identify/<id>/frames` | Images au jugement (connexion) | 4 Mo |
| `/auth/admin/face/probe` | Guidage du scan d'enrôlement | 4 Mo |
| `/auth/admin/accounts/<compte>/face` et `…/face/scan` | Enrôlement | 4 Mo |
| Toutes les autres routes | Pages, API, connexion classique | **1 Mo**, inchangé |

Le frontal applique la même expression régulière avec la même limite (`frontend/nginx.conf`,
16 ko ailleurs). Une route voisine hors de l'expression (par exemple `/auth/login`) garde la
limite basse.

### ModSecurity : aucune exclusion

Aucune exclusion de règle n'a été nécessaire :

- `SecRequestBodyLimit` est à 12,5 Mo : au-dessus des 4 Mo de nginx ;
- les images partent comme **fichiers** d'un formulaire multipart. Elles ne comptent pas dans
  `SecRequestBodyNoFilesLimit` (128 ko), qui ne mesure que les champs hors fichiers ;
- CRS 4.30 en paranoïa 1 n'inspecte que le nom des fichiers, pas leur contenu.

### Tests

Depuis le poste de contrôle, par le serveur 8443 :

| Test | Attendu | Obtenu |
|---|---|---|
| 5 JPEG de 352 ko (bruit aléatoire) sur chacune des 5 routes | Transmis, aucune règle déclenchée | OK |
| 8 images (2,8 Mo) en une requête | Transmis, aucune règle déclenchée | OK |
| Rafale de 40 `/probe` en 5 s | Transmis | OK |
| Témoin : 2 Mo sur `/auth/login` (route voisine, hors expression) | 413 | 413 |
| Témoin : 5 Mo sur `/frames` | 413 | 413 |
| Journaux du WAF pendant les tests | Aucun 403, aucun bannissement | Aucun 403, aucun bannissement |

Les 413 ne comptent pas dans les règles de bannissement, qui ne regardent que les 403
(section 5). Un opérateur qui envoie une image trop grande n'est donc pas banni.

### Limites

- Les données envoyées sur ces 5 routes ne sont pas inspectées au-delà de ce que fait CRS sur
  un fichier multipart : le contrôle du contenu (images valides, nombre d'images) est fait par
  auth.
- Le délai de 30 s laisse le temps à l'inférence sur CPU ; un client lent occupe une connexion
  pendant ce temps.

## Feuille de route publiée par le WAF

La feuille de route du projet (`infra/roadmap/index.html`) est servie par le WAF lui-même sur
https://app.slabreze.fr/roadmap/ (`infra/waf/nginx/site-8443.conf`, inclus dans le serveur 8443,
dossier `/opt/resilience-waf/site` monté en lecture seule). Publication et mise à jour :
`vault-env ansible-playbook waf-roadmap.yml`. Une mise à jour de la page n'est qu'une copie de
fichier, sans rechargement de nginx. La redirection `/roadmap` → `/roadmap/` est relative
(`absolute_redirect off`) : sinon nginx ajouterait son port interne 8443.
