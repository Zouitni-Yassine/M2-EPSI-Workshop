#!/usr/bin/env python3
"""Bannissement automatique d'adresses IP au WAF (waf01), déclenché par Alertmanager.

Service (waf-ban.service) :
    waf-ban serve
  reçoit les webhooks d'Alertmanager (JSON v4, jeton Bearer) sur POST /alertmanager ; pour chaque
  alerte "firing" portant action="ban" et source_ip, ajoute l'IP à la liste lue par nginx
  (geo $waf_banned, fichier banned.conf), vérifie la configuration puis recharge nginx sans
  coupure. Les bannissements expirent seuls (BAN_DURATION_S).

Exploitation (root, ou sudo -u waf-ban) :
    waf-ban list            IP bannies et expiration
    waf-ban unban <ip>      débannir tout de suite
    waf-ban unban --all     tout vider

Garde-fous : adresses protégées (bouclage, NPM, supervision, réseaux du lab) et liste blanche
(ALLOWLIST_FILE) jamais bannies, au plus MAX_ACTIVE IP bannies, au plus MAX_PER_MIN nouveaux
bannissements par minute. Chaque décision est une ligne du journal (identifiant waf-ban, donc
dans Loki). Le service ne fait rien d'autre : aucune commande reçue n'est exécutée.
"""
import contextlib
import fcntl
import hmac
import ipaddress
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer

LISTEN_ADDR = os.environ.get("LISTEN_ADDR", "10.30.2.251")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "9095"))
TOKEN_FILE = os.environ.get("TOKEN_FILE", "/etc/waf-ban/token")
ALLOWLIST_FILE = os.environ.get("ALLOWLIST_FILE", "/etc/waf-ban/allowlist")
BAN_FILE = os.environ.get("BAN_FILE", "/opt/resilience-waf/waf-ban/banned/banned.conf")
CONTAINER = os.environ.get("WAF_CONTAINER", "resilience-waf")
BAN_DURATION_S = int(os.environ.get("BAN_DURATION_S", "900"))
MAX_ACTIVE = int(os.environ.get("MAX_ACTIVE", "20"))
MAX_PER_MIN = int(os.environ.get("MAX_PER_MIN", "5"))
MAX_BODY = 1024 * 1024

# Jamais bannies, quelle que soit la liste blanche : bouclage, NPM (tout le trafic public passe
# par lui), supervision (Alertmanager) et réseaux RA-* du lab (frontal, workers, WAF)
PROTECTED = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "::1/128", "172.16.1.10/32", "10.0.1.233/32", "10.30.0.0/16")]

LINE = re.compile(r"^(?P<ip>[0-9a-fA-F:.]+) 1; # expire=(?P<exp>\d+) raison=(?P<why>\S+)$")
_tlock = threading.Lock()
recent = deque()  # dates des derniers bannissements (plafond par minute)


def log(msg):
    print(msg, flush=True)
    # Commande lancée à la main : la décision va aussi dans le journal (donc dans Loki)
    if "JOURNAL_STREAM" not in os.environ:
        subprocess.run(["logger", "-t", "waf-ban", msg], check=False)


@contextlib.contextmanager
def lock():
    """Exclusion entre le service et les commandes manuelles (fichier verrou à côté de la liste)."""
    with _tlock:
        fd = os.open(BAN_FILE + ".lock", os.O_RDONLY | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)


def hhmmss(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts))


def load():
    """IP bannies : {ip: (expiration, raison)}, lues dans le fichier de nginx."""
    bans = {}
    try:
        with open(BAN_FILE, encoding="utf-8") as f:
            for line in f:
                m = LINE.match(line.strip())
                if m:
                    bans[m["ip"]] = (int(m["exp"]), m["why"])
    except FileNotFoundError:
        pass
    return bans


def save(bans):
    tmp = BAN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# Généré par waf-ban (ne pas éditer à la main : waf-ban list|unban)\n")
        for ip, (exp, why) in sorted(bans.items()):
            f.write(f"{ip} 1; # expire={exp} raison={why}\n")
    os.chmod(tmp, 0o644)  # lu par nginx (uid 101) dans le conteneur
    os.replace(tmp, BAN_FILE)  # remplacement atomique : nginx ne lit jamais un fichier partiel


def docker(*args):
    return subprocess.run(["docker", "exec", CONTAINER, *args], capture_output=True,
                          text=True, timeout=30)


def apply(bans, previous):
    """Écrit la liste, vérifie la configuration de nginx et recharge ; sinon revient en arrière."""
    save(bans)
    test = docker("nginx", "-t", "-q")
    if test.returncode != 0:
        save(previous)
        log(f"erreur cause=nginx_t_echoue detail={test.stderr.strip()[:200]!r}")
        return False
    reload = docker("nginx", "-s", "reload")
    if reload.returncode != 0:
        log(f"erreur cause=reload_echoue detail={reload.stderr.strip()[:200]!r}")
        return False
    return True


def allowlist():
    nets = []
    try:
        with open(ALLOWLIST_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    try:
                        nets.append(ipaddress.ip_network(line, strict=False))
                    except ValueError:
                        log(f"erreur cause=liste_blanche_invalide valeur={line[:60]!r}")
    except FileNotFoundError:
        pass
    return nets


def refusal(ip):
    """Cause du refus de bannir cette IP, ou None si elle peut l'être."""
    if ip.is_unspecified or ip.is_multicast or ip.is_loopback or ip.is_link_local:
        return "adresse_speciale"
    if any(ip in n for n in PROTECTED):
        return "adresse_protegee"
    if any(ip.version == n.version and ip in n for n in allowlist()):
        return "liste_blanche"
    return None


def ban(raw_ip, why):
    why = re.sub(r"[^A-Za-z0-9_.-]", "_", why or "inconnue")[:60]
    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        log(f"refus ip={str(raw_ip)[:60]!r} cause=ip_invalide raison={why}")
        return "refus"
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    cause = refusal(ip)
    if cause:
        log(f"refus ip={ip} cause={cause} raison={why}")
        return "refus"
    now = time.time()
    with lock():
        bans = load()
        if str(ip) in bans:
            log(f"deja_banni ip={ip} raison={why} expire={hhmmss(bans[str(ip)][0])}")
            return "deja"
        while recent and recent[0] < now - 60:
            recent.popleft()
        if len(bans) >= MAX_ACTIVE:
            log(f"refus ip={ip} cause=plafond_actifs max={MAX_ACTIVE} raison={why}")
            return "refus"
        if len(recent) >= MAX_PER_MIN:
            log(f"refus ip={ip} cause=plafond_par_minute max={MAX_PER_MIN} raison={why}")
            return "refus"
        previous = dict(bans)
        exp = int(now) + BAN_DURATION_S
        bans[str(ip)] = (exp, why)
        if not apply(bans, previous):
            return "erreur"
        recent.append(now)
        log(f"ban ip={ip} raison={why} duree_s={BAN_DURATION_S} expire={hhmmss(exp)} "
            f"actifs={len(bans)}")
        return "ban"


def expire_loop():
    while True:
        time.sleep(10)
        try:
            with lock():
                bans = load()
                now = time.time()
                gone = [ip for ip, (exp, _) in bans.items() if exp <= now]
                if gone:
                    previous = dict(bans)
                    for ip in gone:
                        del bans[ip]
                    if apply(bans, previous):
                        for ip in gone:
                            log(f"expiration ip={ip} raison={previous[ip][1]} actifs={len(bans)}")
        except Exception as exc:  # la boucle ne doit jamais s'arrêter
            log(f"erreur cause=expiration detail={exc!r}")


class Handler(BaseHTTPRequestHandler):
    server_version = "waf-ban"
    sys_version = ""

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # pas de journal d'accès : seules les décisions comptent
        pass

    def do_GET(self):
        if self.path == "/healthz":
            self.reply(200, {"ok": True, "actifs": len(load())})
        else:
            self.reply(404, {"erreur": "inconnu"})

    def do_POST(self):
        if self.path != "/alertmanager":
            return self.reply(404, {"erreur": "inconnu"})
        auth = self.headers.get("Authorization", "")
        if not hmac.compare_digest(auth.encode(), b"Bearer " + self.server.token):
            log(f"refus_auth source={self.client_address[0]}")
            return self.reply(401, {"erreur": "authentification"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY:
                raise ValueError("taille")
            payload = json.loads(self.rfile.read(size))
            alerts = payload["alerts"]
        except (ValueError, KeyError, TypeError):
            return self.reply(400, {"erreur": "format"})
        results = []
        for alert in alerts if isinstance(alerts, list) else []:
            if not isinstance(alert, dict):
                continue
            labels = alert.get("labels") or {}
            if alert.get("status") != "firing" or labels.get("action") != "ban":
                continue
            if "source_ip" not in labels:
                continue
            results.append(ban(str(labels["source_ip"]), str(labels.get("alertname", ""))))
        self.reply(200, {"resultats": results})


def serve():
    with open(TOKEN_FILE, "rb") as f:
        token = f.read().strip()
    if len(token) < 32:
        sys.exit("waf-ban : jeton absent ou trop court")
    if not os.path.exists(BAN_FILE):
        save({})
    threading.Thread(target=expire_loop, daemon=True).start()
    srv = HTTPServer((LISTEN_ADDR, LISTEN_PORT), Handler)
    srv.token = token
    log(f"demarrage ecoute={LISTEN_ADDR}:{LISTEN_PORT} duree_s={BAN_DURATION_S} "
        f"max_actifs={MAX_ACTIVE} max_par_minute={MAX_PER_MIN}")
    srv.serve_forever()


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "serve":
        return serve()
    if cmd == "list":
        bans = load()
        for ip, (exp, why) in sorted(bans.items()):
            print(f"{ip}\texpire {hhmmss(exp)}\t{why}")
        print(f"{len(bans)} IP bannie(s)")
        return 0
    if cmd == "unban" and len(argv) == 3:
        with lock():
            bans = load()
            previous = dict(bans)
            gone = list(bans) if argv[2] == "--all" else [argv[2]] if argv[2] in bans else []
            if not gone:
                print(f"{argv[2]} n'est pas bannie")
                return 1
            for ip in gone:
                del bans[ip]
            if not apply(bans, previous):
                return 1
            for ip in gone:
                log(f"deban ip={ip} par=manuel actifs={len(bans)}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
