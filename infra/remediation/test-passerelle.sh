#!/bin/sh
# Test de bout en bout de la passerelle de remédiation, par le chemin réel du moteur :
# conteneur sur un worker, clé lue depuis le secret Swarm, empreintes depuis la config Swarm.
# À lancer sur le poste de contrôle. Déploie la stack "demo" si elle est absente.
#   sh infra/remediation/test-passerelle.sh [ip-manager]
set -eu
MGR=${1:-10.30.1.211}
KEY=/root/.ssh/id_ed25519_infra
DIR=$(dirname "$0")
on_mgr() { ssh -n -i $KEY debian@$MGR "$@"; }

if ! on_mgr sudo docker stack ls --format '{{.Name}}' | grep -qx demo; then
  echo "== déploiement de la stack demo"
  ssh -i $KEY debian@$MGR 'cat > /tmp/demo-stack.yml' < "$DIR/demo-stack.yml"
  on_mgr sudo docker stack deploy -d -c /tmp/demo-stack.yml demo
  sleep 40
fi

# Script exécuté dans le conteneur. Chaque cas : code attendu|commande envoyée à la passerelle
INNER=$(cat <<EOS
apk add -q openssh-client >/dev/null
while IFS='|' read -r want cmd; do
  [ "\$want" = WAIT ] && { sleep 62; continue; }
  out=\$(ssh -T -i /run/secrets/id_ed25519 -o BatchMode=yes remediation@$MGR "\$cmd" </dev/null 2>&1) && rc=0 || rc=\$?
  [ "\$rc" = "\$want" ] && r=OK || r=ECHEC
  printf '%-5s attendu=%s obtenu=%s  %-26s %.160s\n' "\$r" "\$want" "\$rc" "[\$cmd]" "\$out"
done <<'CASES'
0|list
0|status demo_web
2|
2|status demo_web;id
2|restart ../../etc
3|status monitoring_vmagent
3|scale demo_web 99
0|restart demo_web
4|restart demo_web
WAIT|
0|scale demo_web 3
WAIT|
0|rollback demo_web
CASES
EOS
)
B64=$(printf '%s\n' "$INNER" | base64 -w0)

on_mgr sudo docker service rm remediation-test >/dev/null 2>&1 || true
echo "== job de test sur un worker (environ 3 min)"
on_mgr "sudo docker service create -q --name remediation-test --mode replicated-job \
  --constraint node.role==worker --restart-condition none \
  --secret source=remediation_ssh_key,target=id_ed25519,mode=0400 \
  --config source=remediation_known_hosts,target=/etc/ssh/ssh_known_hosts,mode=0444 \
  --env S=$B64 alpine:3.22 sh -c 'echo \"\$S\" | base64 -d | sh'" >/dev/null
on_mgr sudo docker service logs --raw remediation-test
on_mgr sudo docker service rm remediation-test >/dev/null
