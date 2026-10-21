#!/usr/bin/env bash
# Tests de résilience de Resilience Pay : injecte une panne, puis mesure la reprise sans
# intervenir. Depuis le poste de contrôle (10.0.1.110), en root :
#
#   infra/chaos/chaos.sh list          liste des tests
#   infra/chaos/chaos.sh <test>        lance un test (demande confirmation)
#
# Pour chaque test :
#   1. vérifications préalables : application en bon état, aucune sauvegarde vzdump en cours
#      (une sauvegarde gèle les VM ~45 s et fausserait la mesure) ;
#   2. annotation « Tests de chaos » dans Grafana (zone sur le dashboard Démo / Remédiation) ;
#   3. panne ; pendant ce temps, GET /api/health sur l'adresse virtuelle toutes les secondes
#      (ce que voit un client) ;
#   4. attente du retour : API qui répond, puis transaction réussie de la sonde (preuve métier),
#      puis état nominal de l'infrastructure propre au test (VM relancée, nœud Swarm prêt...) ;
#   5. résultat : annotation fermée, ligne ajoutée à /root/chaos/resultats.tsv, journaux dans
#      /root/chaos/<date>-<test>/.
#
# Le script ne répare rien : il ne fait que casser et mesurer. La reprise est le travail de
# Swarm, du moteur de remédiation, de keepalived et de la HA Proxmox.
# Secrets (mot de passe admin Grafana) : lus dans Vault par vault-env, jamais écrits.
set -euo pipefail
[ -n "${VAULT_ENV_LOADED:-}" ] || exec vault-env "$0" "$@"

SSH_VM=(ssh -n -o BatchMode=yes -o ConnectTimeout=5 -i /root/.ssh/id_ed25519_infra)
SSH_PVE=(ssh -n -o BatchMode=yes -o ConnectTimeout=5 -i /root/.ssh/id_ed25519_proxmox)
MANAGERS=(10.30.1.211 10.30.1.212 10.30.1.213)
PVE_NODES=(10.0.1.100 10.0.1.101 10.0.1.102)
VIP=10.30.1.200
APP=http://$VIP:5173
GRAFANA=http://10.0.1.233:3000
OUT=/root/chaos
RESULTS=$OUT/resultats.tsv
TIMEOUT=${CHAOS_TIMEOUT:-900}
RESTORE_ID=9243          # test « restauration » : ID libre, supprimé après vérification
RESTORE_SRC=243          # vaultwarden01
RESTORE_STORAGE=vm-fastec
PBS_STORAGE=workshop-local-pbs

TESTS=(
  "api-stop|Appli|Arrêt propre de payment-api (code 0 : Swarm ne relance pas) : le détecteur et le moteur doivent agir"
  "burst|Appli|Rafale de requêtes sur l'API pendant 45 s : le détecteur ML doit voir l'anomalie"
  "db-kill|Appli|Arrêt brutal de PostgreSQL : Swarm relance, aucun paiement perdu"
  "kill-payment-api|Conteneur|Arrêt brutal (SIGKILL) de payment-api : Swarm relance"
  "kill-auth|Conteneur|Arrêt brutal du service d'authentification"
  "kill-frontend|Conteneur|Arrêt brutal du frontal"
  "kill-detector|Conteneur|Arrêt brutal du détecteur ML"
  "kill-remediation|Conteneur|Arrêt brutal du moteur de remédiation"
  "worker-crash|Conteneur|Arrêt brutal de la VM du worker qui porte l'adresse virtuelle"
  "leader-crash|Conteneur|Arrêt brutal de la VM du manager Swarm leader"
  "monitoring-crash|Virtualisation|Arrêt brutal du LXC monitoring01 (Loki, Grafana, alertes)"
  "node-loss|Virtualisation|Perte d'un hyperviseur entier, coupée à la main depuis l'hôte parent"
  "restore|Virtualisation|Restauration PBS de vaultwarden01 sur l'ID $RESTORE_ID, sans réseau"
)

# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #
now() { date +%s.%3N; }
say() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$DIR/journal.txt" >&2; }
die() { say "ERREUR : $*"; exit 1; }
elapsed() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f", b - a }'; }

# Commande sur le premier manager joignable (le leader peut être en panne)
mgr() {
  local m cmd
  cmd=$(printf '%q ' "$@")   # garde les arguments avec espaces (--format '{{.A}} {{.B}}')
  for m in "${MANAGERS[@]}"; do
    "${SSH_VM[@]}" "debian@$m" "sudo $cmd" 2>/dev/null && return 0
  done
  return 1
}
# Commande sur le premier hyperviseur joignable
pve() {
  local n
  for n in "${PVE_NODES[@]}"; do
    "${SSH_PVE[@]}" "root@$n" "$*" 2>/dev/null && return 0
  done
  return 1
}
host_ip() {  # dockerwrk02 -> 10.30.1.222, dockermgr03 -> 10.30.1.213
  case "$1" in
    dockerwrk0?) echo "10.30.1.22${1: -1}" ;;
    dockermgr0?) echo "10.30.1.21${1: -1}" ;;
    *) return 1 ;;
  esac
}
host_vmid() { host_ip "$1" | awk -F. '{ print $4 }'; }
pve_ip() { echo "10.0.1.10$(( ${1: -1} - 1 ))"; }   # ceph03 -> 10.0.1.102

# Nœud Proxmox et état d'une machine (VM ou LXC) : "ceph02 running"
guest_state() {
  pve "pvesh get /cluster/resources --type vm --output-format json" | python3 -c '
import json, sys
for r in json.load(sys.stdin):
    if r.get("vmid") == int(sys.argv[1]):
        print(r.get("node"), r.get("status"))' "$1"
}
service_node() {
  mgr docker service ps "$1" --filter desired-state=running --format '{{.Node}}' | head -1
}
task_container() {  # conteneur de la tâche d'un service sur un worker
  "${SSH_VM[@]}" "debian@$(host_ip "$1")" \
    "sudo docker ps -q --filter label=com.docker.swarm.service.name=$2" | head -1
}
replicas_ok() {  # « 1/1 » -> vrai
  local r
  r=$(mgr docker service ls --filter "name=$1" --format '{{.Replicas}}' | head -1)
  [ -n "$r" ] && [ "${r%%/*}" = "${r##*/}" ] && [ "${r%%/*}" != 0 ]
}
swarm_node_ready() {
  mgr docker node ls --format '{{.Hostname}}:{{.Status}}' | grep -qx "$1:Ready"
}
vip_holder() {
  local h
  for h in dockerwrk01 dockerwrk02 dockerwrk03; do
    "${SSH_VM[@]}" "debian@$(host_ip $h)" "ip -o addr" 2>/dev/null | grep -q " $VIP/" && echo $h
  done
}
leader() {
  mgr docker node ls --format '{{.Hostname}} {{.ManagerStatus}}' | awk '$2 == "Leader" { print $1 }'
}

# API Grafana : annotations (globales, tag chaos) et lecture de Loki
graf() { curl -sf -u "admin:$GRAFANA_ADMIN_PASSWORD" -H 'Content-Type: application/json' "$@"; }
annotate_start() {
  graf -X POST "$GRAFANA/api/annotations" -d "$(python3 -c '
import json, sys
print(json.dumps({"time": int(float(sys.argv[1]) * 1000), "tags": ["chaos", sys.argv[2]],
                  "text": f"Test {sys.argv[2]} : {sys.argv[3]}"}))' "$T0" "$TEST" "$DESC")" \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])' || true
}
annotate_end() {  # Grafana peut être en panne pendant le test : on réessaie à la fin
  local i
  [ -n "$ANN" ] || return 0
  for i in $(seq 1 30); do
    graf -X PATCH "$GRAFANA/api/annotations/$ANN" -d "$(python3 -c '
import json, sys
print(json.dumps({"timeEnd": int(float(sys.argv[1]) * 1000), "text": sys.argv[2]}))' "$(now)" "$1")" \
      >/dev/null && return 0
    sleep 10
  done
  say "annotation non fermée (Grafana injoignable)"
}
# Première transaction réussie de la sonde après $1 (secondes epoch), vide si aucune
probe_ok_after() {
  graf -G "$GRAFANA/api/datasources/proxy/uid/loki/loki/api/v1/query_range" \
    --data-urlencode 'query={stack="probe", service="probe_transactions"} |= "type=transaction" |= "result=ok"' \
    --data-urlencode "start=$(printf '%.0f' "$1")000000000" \
    --data-urlencode "direction=forward" --data-urlencode "limit=1" 2>/dev/null \
    | python3 -c '
import json, sys
vals = [int(v[0]) for s in json.load(sys.stdin)["data"]["result"] for v in s["values"]]
print("%.3f" % (min(vals) / 1e9) if vals else "")' 2>/dev/null || true
}

# Panne vue par la sonde (transactions complètes, à 5 s près) depuis $1 : somme des durées des
# incidents terminés. /api/health peut rester à 200 alors qu'un paiement échoue (base arrêtée).
probe_outage() {
  graf -G "$GRAFANA/api/datasources/proxy/uid/loki/loki/api/v1/query_range" \
    --data-urlencode 'query={stack="probe", service="probe_transactions"} |= "type=incident" |= "phase=fin"' \
    --data-urlencode "start=$(printf '%.0f' "$1")000000000" --data-urlencode "limit=100" 2>/dev/null \
    | python3 -c '
import json, re, sys
d = [float(m.group(1)) for s in json.load(sys.stdin)["data"]["result"] for v in s["values"]
     for m in [re.search(r"duree_s=([0-9.]+)", v[1])] if m]
print("%.1f" % sum(d))' 2>/dev/null || echo -
}

# Ce que voit un client : GET /api/health par l'adresse virtuelle, toutes les secondes
poll_start() {
  ( while :; do
      printf '%s %s\n' "$(now)" \
        "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$APP/api/health" || true)"
      sleep 1
    done ) >> "$DIR/sonde-http.log" &
  POLL=$!
}
health_ok() { [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$APP/api/health")" = 200 ]; }

wait_until() {  # wait_until <description> <commande...> : vrai si la condition est remplie à temps
  local what=$1; shift
  local start; start=$(now)
  while ! "$@" >/dev/null 2>&1; do
    if [ "$(elapsed "$start" "$(now)" | cut -d. -f1)" -ge "$TIMEOUT" ]; then
      say "délai dépassé ($TIMEOUT s) : $what"
      return 1
    fi
    sleep 2
  done
  say "OK : $what (+$(elapsed "$T0" "$(now)") s)"
}

# --------------------------------------------------------------------------- #
# Vérifications préalables
# --------------------------------------------------------------------------- #
preflight() {
  local n busy=""
  for n in "${PVE_NODES[@]}"; do
    "${SSH_PVE[@]}" "root@$n" "pgrep -x vzdump" >/dev/null 2>&1 && busy="$busy $n"
  done
  [ -z "$busy" ] || die "sauvegarde vzdump en cours sur$busy : attendre la fin"
  health_ok || die "l'application ne répond pas avant le test ($APP/api/health)"
  [ -n "$(probe_ok_after "$(( $(date +%s) - 120 ))")" ] \
    || die "aucune transaction réussie de la sonde depuis 2 min : état de départ non nominal"
  say "état de départ : API 200, sonde OK, aucune sauvegarde en cours"
}

# --------------------------------------------------------------------------- #
# Pannes
# --------------------------------------------------------------------------- #
crash_vm() {  # kill -9 du processus KVM : une panne, pas un arrêt demandé (que la HA respecterait)
  local id=$1 node; node=$(guest_state "$id" | awk '{ print $1 }')
  say "panne : kill -9 de la VM $id sur $node"
  "${SSH_PVE[@]}" "root@$(pve_ip "$node")" "kill -9 \$(cat /var/run/qemu-server/$id.pid)"
}
guest_running() { [ "$(guest_state "$1" | awk '{ print $2 }')" = running ]; }

inject() {
  case "$TEST" in
    api-stop)
      local node; node=$(service_node paiement_payment-api)
      say "panne : docker stop de payment-api sur $node"
      "${SSH_VM[@]}" "debian@$(host_ip "$node")" "sudo docker stop $(task_container "$node" paiement_payment-api)" >/dev/null
      ;;
    burst)
      say "panne : 45 s de rafale (40 requêtes en parallèle) sur POST /api/payment_intents"
      local end=$(( $(date +%s) + 45 ))
      while [ "$(date +%s)" -lt "$end" ]; do
        seq 1 200 | xargs -P 40 -I{} curl -s -o /dev/null --max-time 3 -X POST \
          -H 'Content-Type: application/json' -d '{"amount":100}' "$APP/api/payment_intents" || true
      done
      ;;
    db-kill|kill-*)
      local svc=paiement_db node
      [ "$TEST" = db-kill ] || svc=paiement_${TEST#kill-}
      node=$(service_node "$svc")
      [ "$TEST" != db-kill ] || PAY_BEFORE=$(payments_count)
      say "panne : docker kill (SIGKILL) de $svc sur $node"
      "${SSH_VM[@]}" "debian@$(host_ip "$node")" "sudo docker kill $(task_container "$node" "$svc")" >/dev/null
      ;;
    worker-crash)
      TARGET=$(vip_holder | head -1)
      [ -n "$TARGET" ] || die "aucun worker ne porte $VIP"
      say "porteur de l'adresse virtuelle : $TARGET ; base sur $(service_node paiement_db), payment-api sur $(service_node paiement_payment-api)"
      crash_vm "$(host_vmid "$TARGET")"
      ;;
    leader-crash)
      TARGET=$(leader)
      [ -n "$TARGET" ] || die "leader Swarm introuvable"
      say "leader Swarm : $TARGET"
      crash_vm "$(host_vmid "$TARGET")"
      ;;
    monitoring-crash)
      local node; node=$(guest_state 233 | awk '{ print $1 }')
      say "panne : lxc-stop -k de monitoring01 (233) sur $node"
      "${SSH_PVE[@]}" "root@$(pve_ip "$node")" "lxc-stop -n 233 -k"
      ;;
    node-loss)
      say "panne : COUPER MAINTENANT l'hyperviseur choisi depuis l'hôte parent (arrêt brutal)"
      say "le chronomètre court depuis l'annotation ; le script attend la perte du nœud"
      wait_until "un hyperviseur ne répond plus" node_lost || exit 1
      ;;
    restore) do_restore ;;
  esac
}

node_lost() {
  local n
  for n in "${PVE_NODES[@]}"; do
    ping -c1 -W1 "$n" >/dev/null 2>&1 || { LOST=$n; return 0; }
  done
  return 1
}
payments_count() {
  local node; node=$(service_node paiement_db)
  "${SSH_VM[@]}" "debian@$(host_ip "$node")" \
    "sudo docker exec \$(sudo docker ps -q --filter label=com.docker.swarm.service.name=paiement_db) psql -U postgres -d payments -tAc 'select count(*) from payments'"
}

do_restore() {
  local backup start
  [ -z "$(guest_state $RESTORE_ID)" ] || die "l'ID $RESTORE_ID existe déjà"
  backup=$(pve "pvesh get /nodes/ceph01/storage/$PBS_STORAGE/content --content backup --output-format json" \
    | python3 -c '
import json, sys
b = [x for x in json.load(sys.stdin) if x.get("vmid") == int(sys.argv[1])]
b.sort(key=lambda x: x["ctime"])
print(b[-1]["volid"], b[-1]["ctime"]) if b else None' $RESTORE_SRC)
  [ -n "$backup" ] || die "aucune sauvegarde de $RESTORE_SRC sur $PBS_STORAGE"
  RPO=$(( $(date +%s) - ${backup##* } ))
  say "sauvegarde la plus récente : ${backup%% *} (âge $(( RPO / 60 )) min = perte de données maximale)"
  start=$(now)
  "${SSH_PVE[@]}" root@10.0.1.100 "pct restore $RESTORE_ID ${backup%% *} --storage $RESTORE_STORAGE --unique 1 --start 0 >/dev/null \
    && pct set $RESTORE_ID --delete net0 --onboot 0 --hostname restore-test-$RESTORE_SRC && pct start $RESTORE_ID"
  say "restauré et démarré sans réseau en $(elapsed "$start" "$(now)") s"
}

# --------------------------------------------------------------------------- #
# Attente du retour à l'état nominal
# --------------------------------------------------------------------------- #
wait_back() {
  local ok=1
  case "$TEST" in
    restore)
      wait_until "vaultwarden démarré dans la copie restaurée" \
        "${SSH_PVE[@]}" root@10.0.1.100 "pct exec $RESTORE_ID -- systemctl is-active --quiet vaultwarden" || ok=0
      wait_until "données présentes (base SQLite de Vaultwarden)" \
        "${SSH_PVE[@]}" root@10.0.1.100 "pct exec $RESTORE_ID -- sh -c 'test -s /var/lib/vaultwarden/db.sqlite3 || test -s /var/lib/vaultwarden/data/db.sqlite3'" || ok=0
      say "suppression de la copie $RESTORE_ID"
      "${SSH_PVE[@]}" root@10.0.1.100 "pct stop $RESTORE_ID >/dev/null 2>&1; pct destroy $RESTORE_ID --purge 1" >/dev/null
      return $(( 1 - ok ))
      ;;
  esac
  wait_until "l'API répond par l'adresse virtuelle" health_ok || ok=0
  # Transaction commencée après la panne effective (docker stop laisse finir les requêtes en cours)
  probe_back() { [ -n "$(probe_ok_after "$T_FAULT")" ]; }
  wait_until "transaction de la sonde réussie après la panne" probe_back || ok=0
  case "$TEST" in
    db-kill)
      wait_until "PostgreSQL relancé" replicas_ok paiement_db || ok=0
      PAY_AFTER=$(payments_count)
      say "paiements en base : $PAY_BEFORE avant, $PAY_AFTER après (les nouveaux sont ceux de la sonde)"
      [ "$PAY_AFTER" -ge "$PAY_BEFORE" ] || { say "PERTE DE DONNÉES"; ok=0; }
      ;;
    api-stop|kill-*)
      local svc=paiement_payment-api
      [ "$TEST" = api-stop ] || svc=paiement_${TEST#kill-}
      wait_until "$svc de nouveau 1/1" replicas_ok "$svc" || ok=0
      ;;
    worker-crash|leader-crash)
      local id; id=$(host_vmid "$TARGET")
      wait_until "VM $TARGET relancée par la HA Proxmox" guest_running "$id" || ok=0
      wait_until "$TARGET de nouveau Ready dans Swarm" swarm_node_ready "$TARGET" || ok=0
      for s in paiement_db paiement_auth paiement_payment-api paiement_frontend paiement_detector paiement_remediation; do
        wait_until "$s 1/1" replicas_ok "$s" || ok=0
      done
      [ "$TEST" = worker-crash ] || say "nouveau leader : $(leader)"
      ;;
    monitoring-crash)
      wait_until "monitoring01 relancé par la HA Proxmox" guest_running 233 || ok=0
      gr() { curl -sf "$GRAFANA/api/health" >/dev/null; }
      wait_until "Grafana répond" gr || ok=0
      ;;
    node-loss)
      say "nœud perdu : $LOST. Après son retour : vault-unseal si Vault est scellé (attendu)"
      for id in 211 212 213 221 222 223 231 232 233 241 242 243; do
        wait_until "machine $id en marche" guest_running "$id" || ok=0
      done
      ;;
  esac
  return $(( 1 - ok ))
}

# Coupure vue par le client : du premier échec au premier succès qui suit (à 1 s près)
outage() {
  awk -v t0="$T0" '$1 >= t0 {
      if ($2 != 200 && !f) { f = $1 }
      if ($2 == 200 && f && !b) { b = $1 }
      if ($2 != 200) n++
    }
    END {
      if (!f) { print "0 0"; exit }
      if (!b) { print "-1 " n; exit }
      printf "%.1f %d\n", b - f, n
    }' "$DIR/sonde-http.log"
}

# --------------------------------------------------------------------------- #
case "${1:-list}" in
  list|-h|--help)
    printf '%-18s %-15s %s\n' TEST COUCHE DESCRIPTION
    for t in "${TESTS[@]}"; do IFS='|' read -r n c d <<<"$t"; printf '%-18s %-15s %s\n' "$n" "$c" "$d"; done
    exit 0 ;;
esac

TEST=$1 DESC="" LAYER=""
for t in "${TESTS[@]}"; do
  IFS='|' read -r n c d <<<"$t"
  [ "$n" = "$TEST" ] && { LAYER=$c DESC=$d; }
done
[ -n "$DESC" ] || { echo "test inconnu : $TEST (voir : $0 list)" >&2; exit 2; }

mkdir -p "$OUT"
DIR=$OUT/$(date +%Y%m%d-%H%M%S)-$TEST
mkdir -p "$DIR"
say "test $TEST ($LAYER) : $DESC"
if [ "${2:-}" != "--yes" ]; then
  read -r -p "Lancer cette panne ? (oui/non) " r
  [ "$r" = oui ] || { say "annulé"; exit 0; }
fi

PAY_BEFORE="" TARGET="" LOST="" RPO="" ANN="" POLL="" T_FAULT=""
[ "$TEST" = restore ] || preflight
T0=$(now)
ANN=$(annotate_start)
trap '[ -z "$POLL" ] || kill "$POLL" 2>/dev/null || true' EXIT
[ "$TEST" = restore ] || poll_start

inject
T_FAULT=$(now)
if wait_back; then verdict=OK; else verdict=ECHEC; fi
T1=$(now)
[ -z "$POLL" ] || { kill "$POLL" 2>/dev/null || true; POLL=""; }

read -r cut fails < <( [ "$TEST" = restore ] && echo "- -" || outage )
tx=$(probe_ok_after "${T_FAULT:-$T0}")
tx_s=$( [ -n "$tx" ] && elapsed "$T0" "$tx" || echo - )
total=$(elapsed "$T0" "$T1")
probe_cut=-
if [ "$TEST" != restore ]; then
  sleep 6   # la sonde écrit la fin d'incident à sa vérification suivante (5 s)
  probe_cut=$(probe_outage "$T0")
fi
summary="$verdict - panne vue par la sonde ${probe_cut} s, /api/health en échec ${cut} s, transaction OK à +${tx_s} s, état nominal à +${total} s"
[ -z "$RPO" ] || summary="$summary, âge de la sauvegarde $(( RPO / 60 )) min"
say "RÉSULTAT $TEST : $summary"
annotate_end "Test $TEST : $summary"

[ -f "$RESULTS" ] || printf 'date\ttest\tcouche\tverdict\tpanne_sonde_s\tcoupure_health_s\techecs_http\ttransaction_ok_s\tnominal_s\trpo_s\tcible\n' > "$RESULTS"
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -d @"${T0%.*}" '+%F %T')" "$TEST" "$LAYER" \
  "$verdict" "$probe_cut" "$cut" "$fails" "$tx_s" "$total" "${RPO:--}" "${TARGET:-${LOST:--}}" >> "$RESULTS"
[ "$verdict" = OK ]
