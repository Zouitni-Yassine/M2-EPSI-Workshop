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
rôle `alloy` (groupe `waf`, adresse mise à jour dans l'inventaire).

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
