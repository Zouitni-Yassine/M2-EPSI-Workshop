#!/usr/bin/env bash
# Vérification d'avant démonstration (et d'avant tournage du clip) : tout ce qui doit être vrai pour
# que l'attaque soit détectée et réparée sans intervention humaine. Lecture seule : ne modifie rien.
#
#   infra/demo/demo-check.sh          depuis le poste de contrôle (10.0.1.110), en root
#
# Code de sortie : 0 = prêt, 1 = au moins un point bloquant (KO). Les avertissements (ATTENTION)
# ne bloquent pas mais sont à lire : sauvegarde imminente, quota de la passerelle entamé...
set -uo pipefail
[ -n "${VAULT_ENV_LOADED:-}" ] || exec vault-env "$0" "$@"

SSH_VM=(ssh -n -o BatchMode=yes -o ConnectTimeout=5 -i /root/.ssh/id_ed25519_infra)
SSH_PVE=(ssh -n -o BatchMode=yes -o ConnectTimeout=5 -i /root/.ssh/id_ed25519_proxmox)
MANAGERS=(10.30.1.211 10.30.1.212 10.30.1.213)
VIP=10.30.1.200
APP=http://$VIP:5173
WAF=https://10.30.2.251:8443
NPM=172.16.1.10
PUBLIC=app.slabreze.fr
GRAFANA=http://10.0.1.233:3000
VAULT=https://10.0.1.242:8200

KO=0 WARN=0
ok()   { printf '  \033[32mOK\033[0m        %s\n' "$*"; }
warn() { printf '  \033[33mATTENTION\033[0m %s\n' "$*"; WARN=$((WARN + 1)); }
ko()   { printf '  \033[31mKO\033[0m        %s\n' "$*"; KO=$((KO + 1)); }
section() { printf '\n\033[1m%s\033[0m\n' "$*"; }

mgr() {
  local m cmd
  cmd=$(printf '%q ' "$@")
  for m in "${MANAGERS[@]}"; do
    "${SSH_VM[@]}" "debian@$m" "sudo $cmd" 2>/dev/null && return 0
  done
  return 1
}
graf() { curl -sf --max-time 10 -u "admin:$GRAFANA_ADMIN_PASSWORD" "$@"; }
# Valeur d'une requête instantanée VictoriaMetrics (premier résultat), vide si aucun
vm() {
  graf -G "$GRAFANA/api/datasources/proxy/uid/victoriametrics/api/v1/query" --data-urlencode "query=$1" \
    | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else "")' 2>/dev/null
}
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$@"; }

# --------------------------------------------------------------------------- #
section "Créneaux"
now_paris=$(TZ=Europe/Paris date +%H:%M)
min_paris=$(( 10#$(TZ=Europe/Paris date +%H) * 60 + 10#$(TZ=Europe/Paris date +%M) ))
# Sauvegardes PBS 21h00 et 22h30, gel par la sauvegarde de l'hôte parent vers 15h36 (heure de Paris)
for slot in "15:36 sauvegarde de l'hôte parent (gel ~45 s des VM de ceph01)" \
            "21:00 sauvegarde PBS (contrôle, collecteurs, supervision)" \
            "22:30 sauvegarde PBS (Swarm, identité, WAF)"; do
  h=${slot%% *}; m=$(( 10#${h%%:*} * 60 + 10#${h##*:} ))
  d=$(( m - min_paris ))
  if [ "$d" -ge -10 ] && [ "$d" -le 20 ]; then warn "il est $now_paris : $slot à $h"; fi
done
busy=""
for n in 10.0.1.100 10.0.1.101 10.0.1.102; do
  "${SSH_PVE[@]}" "root@$n" "pgrep -x vzdump" >/dev/null 2>&1 && busy="$busy $n"
done
[ -z "$busy" ] && ok "aucune sauvegarde vzdump en cours ($now_paris)" || ko "sauvegarde vzdump en cours sur$busy"

# --------------------------------------------------------------------------- #
section "Socle"
quorum=$("${SSH_PVE[@]}" root@10.0.1.100 "pvecm status 2>/dev/null | awk '/^Quorate:/ {print \$2}'")
[ "$quorum" = Yes ] && ok "cluster Proxmox : quorum" || ko "cluster Proxmox : quorum absent ou injoignable"
ha_bad=$("${SSH_PVE[@]}" root@10.0.1.100 "ha-manager status | grep '^service' | grep -vc 'started)'")
[ "${ha_bad:-1}" = 0 ] && ok "HA Proxmox : toutes les machines started" || ko "HA Proxmox : $ha_bad machine(s) pas started"
ceph=$("${SSH_PVE[@]}" root@10.0.1.100 "ceph health 2>/dev/null")
case "$ceph" in
  HEALTH_OK*) ok "Ceph : HEALTH_OK" ;;
  HEALTH_WARN*) warn "Ceph : $ceph" ;;
  *) ko "Ceph : ${ceph:-injoignable}" ;;
esac
sealed=$(curl -sk --max-time 5 "$VAULT/v1/sys/seal-status" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sealed"])' 2>/dev/null)
case "$sealed" in
  False) ok "Vault descellé" ;;
  True) ko "Vault scellé : lancer vault-unseal (l'application tourne, mais aucun déploiement possible)" ;;
  *) ko "Vault injoignable" ;;
esac

# --------------------------------------------------------------------------- #
section "Swarm et application"
ready=$(mgr docker node ls --format '{{.Status}}' | grep -c '^Ready$')
[ "$ready" = 6 ] && ok "Swarm : 6 / 6 nœuds Ready" || ko "Swarm : $ready / 6 nœuds Ready"
leader=$(mgr docker node ls --format '{{.Hostname}} {{.ManagerStatus}}' | awk '$2 == "Leader" { print $1 }')
[ -n "$leader" ] && ok "Swarm : leader $leader" || ko "Swarm : aucun leader"
bad=$(mgr docker service ls --format '{{.Name}} {{.Replicas}}' | awk '$1 ~ /^(paiement|probe)_/ { split($2, r, "/"); if (r[1] != r[2] || r[1] == 0) print $1 " " $2 }')
[ -z "$bad" ] && ok "services paiement_* et sonde : toutes les réplicas en marche" || ko "services incomplets : $(echo $bad)"
holder=""
for h in 10.30.1.221 10.30.1.222 10.30.1.223; do
  "${SSH_VM[@]}" "debian@$h" "ip -o addr" 2>/dev/null | grep -q " $VIP/" && holder="$holder $h"
done
case $(echo $holder | wc -w) in
  1) ok "adresse virtuelle $VIP portée par$holder" ;;
  0) ko "adresse virtuelle $VIP portée par personne" ;;
  *) ko "adresse virtuelle $VIP portée par plusieurs nœuds :$holder" ;;
esac
health=$(curl -s --max-time 5 "$APP/api/health")
echo "$health" | grep -q '"ok":true' && echo "$health" | grep -q '"db":true' \
  && ok "API par l'adresse virtuelle : ok, base joignable" || ko "API par l'adresse virtuelle : ${health:-pas de réponse}"
echo "$health" | grep -q '"stripe":true' && ok "Stripe (mode test) joignable" || warn "Stripe injoignable : les paiements échoueront"

# --------------------------------------------------------------------------- #
section "Chaîne publique (NPM -> WAF -> application)"
[ "$(code -k "$WAF/healthz")" = 200 ] && ok "WAF : healthz 200" || ko "WAF : healthz en échec"
c=$(code --resolve "$PUBLIC:443:$NPM" "https://$PUBLIC/")
[ "$c" = 200 ] && ok "https://$PUBLIC/ : 200 (certificat valide)" || ko "https://$PUBLIC/ : $c"
c=$(code --resolve "$PUBLIC:443:$NPM" "https://$PUBLIC/?id=1%27%20OR%201=1--")
[ "$c" = 403 ] && ok "WAF : injection SQL bloquée (403)" || ko "WAF : injection SQL non bloquée ($c)"

# --------------------------------------------------------------------------- #
section "Détection et remédiation"
[ "$(vm 'max(detector_ready)')" = 1 ] && ok "détecteur ML : normale apprise" \
  || ko "détecteur ML : en apprentissage (60 s après un redémarrage) ou injoignable"
an=$(vm 'max(detector_anomaly)')
[ "$an" = 0 ] && ok "détecteur ML : aucune anomalie en cours (score $(vm 'max(detector_anomaly_score)' | cut -c1-4))" \
  || warn "détecteur ML : anomalie en cours ou inconnue ($an)"
busy=$(vm 'max(paiement_probe_remediation_in_progress)')
[ "$busy" = 0 ] && ok "moteur de remédiation : en veille" || warn "moteur de remédiation : en action ou inconnu ($busy)"
# Quota de la passerelle : 10 actions par fenêtre de 10 min, 60 s entre deux actions sur un service
recent=0
for m in "${MANAGERS[@]}"; do
  n=$("${SSH_VM[@]}" "debian@$m" "sudo cat /var/lib/remediation/state.json 2>/dev/null" | python3 -c '
import json, sys, time
try:
    s = json.load(sys.stdin)
except ValueError:
    print(0); sys.exit()
print(sum(1 for t in s.get("actions", []) if time.time() - t < 600))' 2>/dev/null)
  recent=$((recent + ${n:-0}))
done
if [ "$recent" -eq 0 ]; then ok "passerelle : aucune action dans les 10 dernières minutes (quota plein)"
elif [ "$recent" -lt 7 ]; then warn "passerelle : $recent action(s) dans les 10 dernières minutes (10 au plus)"
else ko "passerelle : $recent actions dans les 10 dernières minutes : quota presque épuisé, attendre"; fi

# --------------------------------------------------------------------------- #
section "Supervision"
since=$(vm 'min(paiement_probe_seconds_since_success{check="transaction"})')
if [ -n "$since" ] && [ "${since%.*}" -lt 60 ]; then ok "sonde : dernière transaction réussie il y a ${since%.*} s"
else ko "sonde : pas de transaction réussie récente (${since:-inconnu})"; fi
alerts=$(graf -G "$GRAFANA/api/datasources/proxy/uid/victoriametrics/api/v1/query" \
  --data-urlencode 'query=ALERTS{alertstate="firing", alertname!="Watchdog"}' \
  | python3 -c 'import json,sys; print(" ".join(sorted({r["metric"]["alertname"] for r in json.load(sys.stdin)["data"]["result"]})))' 2>/dev/null)
[ -z "$alerts" ] && ok "aucune alerte active (hors Watchdog)" || warn "alertes actives : $alerts"
[ "$(code "$GRAFANA/api/health")" = 200 ] && ok "Grafana : dashboard Démo / Remédiation disponible" || ko "Grafana injoignable"

# --------------------------------------------------------------------------- #
printf '\n'
if [ "$KO" -eq 0 ]; then
  printf '\033[32mPRÊT\033[0m pour la démonstration (%d avertissement(s))\n' "$WARN"
else
  printf '\033[31mPAS PRÊT\033[0m : %d point(s) bloquant(s), %d avertissement(s)\n' "$KO" "$WARN"
fi
[ "$KO" -eq 0 ]
