"""Bounded, reproducible WAF tests for the explicitly scoped workshop lab."""
import argparse
import datetime as dt
import hashlib
import getpass
import http.client
import ipaddress
import json
import os
import pathlib
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


ROOT = pathlib.Path(__file__).resolve().parent


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def validate_origin(value, allowed):
    p = urllib.parse.urlsplit(value)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("Cible HTTPS sans identifiants requise")
    if p.path not in ("", "/") or p.query or p.fragment:
        raise ValueError("La cible doit être une origine, sans chemin ni paramètres")
    if not ipaddress.ip_address(p.hostname).is_private:
        raise ValueError("Seules les IP littérales privées du laboratoire sont acceptées")
    normalized = value.rstrip("/")
    if normalized not in allowed:
        raise ValueError("Cible absente du périmètre scope.json")
    return normalized


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_opener(ca, relay_port=None):
    context = ssl.create_default_context(cafile=str(ca))
    if relay_port is None:
        handler = urllib.request.HTTPSHandler(context=context)
    else:
        class Connection(http.client.HTTPSConnection):
            def connect(self):
                raw = socket.create_connection(("127.0.0.1", relay_port), timeout=self.timeout)
                self.sock = context.wrap_socket(raw, server_hostname=self.host)
        class Handler(urllib.request.HTTPSHandler):
            def https_open(self, request):
                return self.do_open(Connection, request)
        handler = Handler()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        handler,
        NoRedirect(),
    )


def make_plan(scenario, run_id):
    if scenario in ["ml", "ml-auth"]:
        if scenario == "ml-auth":
            return [("mode_check", "/api/health", 200)] + [("invalid_payment", "/api/payment_intents", 422)] * 100 + [("recovery", "/", 200)]
        return [("mode_check", "/api/health", 200)] + [
            ("traffic", "/api/health" if i % 2 else "/api/status", [200, 401]) for i in range(100)
        ] + [("recovery", "/", 200)]
    if scenario == "all":
        return make_plan("waf", run_id) + make_plan("soc", run_id)
    normal = ("baseline", "/?" + urllib.parse.urlencode({"redteam_run": run_id}), 200)
    sql = "/?" + urllib.parse.urlencode({"id": "1' OR '1'='1' -- ", "redteam_run": run_id})
    xss = "/?" + urllib.parse.urlencode({"q": "<script>alert(1)</script>", "redteam_run": run_id})
    if scenario == "preflight":
        return [normal]
    if scenario == "waf":
        return [normal] * 3 + [("sql", sql, 403), ("xss", xss, 403)] * 3 + [("recovery", normal[1], 200)] * 3
    if scenario == "soc":
        return [normal] * 3 + [("xss", xss, 403)] * 20 + [("containment", normal[1], 403)] * 3
    raise ValueError("Scénario inconnu")


def send(opener, origin, case, run_id, timeout):
    name, path, expected = case
    started = utc()
    begin = time.monotonic()
    headers = {
        "User-Agent": "RESILIENCE-RedTeam/1.0 run=" + run_id,
        "X-Redteam-Run": run_id,
        "Accept": "text/html,application/json",
    }
    cookie = os.environ.get("REDTEAM_SESSION_COOKIE")
    if cookie:
        if "\r" in cookie or "\n" in cookie:
            raise ValueError("Cookie de session invalide")
        headers["Cookie"] = cookie
    data = None
    if name == "invalid_payment":
        headers["Content-Type"] = "application/json"
        data = b'{"amount":-1,"holder":"RedTeam-laboratoire"}'
    request = urllib.request.Request(origin + path, headers=headers, data=data)
    result = {"at": started, "case": name, "path": path, "expected": expected}
    try:
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            result["status"] = response.code
            result["request_id"] = response.headers.get("X-Request-ID")
            # Only retain a digest; pages, credentials and log contents are not exported.
            body = response.read(4096)
            result["body_prefix_sha256"] = hashlib.sha256(body).hexdigest()
            if name == "mode_check":
                try:
                    mode = json.loads(body).get("mode")
                    result["payment_mode"] = mode if mode in ["test", "live", "none"] else "unknown"
                except (ValueError, AttributeError):
                    result["payment_mode"] = "unknown"
        result["pass"] = result["status"] in expected if isinstance(expected, list) else result["status"] == expected
        if name == "mode_check" and result.get("payment_mode") != "test":
            result["pass"] = False
            result["error"] = "Le mode TEST de paiement n'est pas confirmé : stimulus annulé"
    except (OSError, urllib.error.URLError, ssl.SSLError) as error:
        result.update({"pass": False, "error": str(error)})
    result["duration_ms"] = round((time.monotonic() - begin) * 1000, 2)
    return result


def execute(opener, origin, plan, run_id, timeout, rate, log):
    results = []
    reason = None
    for index, case in enumerate(plan):
        if case[0] == "containment" and (index == 0 or plan[index - 1][0] != "containment"):
            # Let the 15 s alert evaluation and automated ban finish, below the 1 min window.
            time.sleep(20)
        before = time.monotonic()
        result = send(opener, origin, case, run_id, timeout)
        results.append(result)
        log.write(json.dumps(result, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps({k: result.get(k) for k in ["case", "status", "pass", "error"]}), flush=True)
        if not result["pass"]:
            reason = "Arrêt au premier résultat inattendu ; aucune hausse automatique du débit"
            break
        if index + 1 < len(plan):
            time.sleep(max(0, 1 / rate - (time.monotonic() - before)))
    return results, reason


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["preflight", "waf", "soc", "all", "ml", "ml-auth"], default="waf")
    parser.add_argument("--ssh-relay", action="store_true", help="Relais administrateur temporaire, local uniquement")
    parser.add_argument("--ssh-user", help="Compte dédié autorisé sur le relais")
    parser.add_argument("--session-cookie", action="store_true", help="Saisir en masqué la session d'un compte client TEST")
    parser.add_argument("--target")
    parser.add_argument("--scope", type=pathlib.Path, default=ROOT / "scope.json")
    parser.add_argument("--rate", type=float)
    parser.add_argument("--execute", action="store_true", help="Sans ce drapeau : plan uniquement")
    parser.add_argument("--output", type=pathlib.Path, default=ROOT / "evidence")
    args = parser.parse_args(argv)
    if not args.scope.is_file():
        raise ValueError("Copier scope.example.json en scope.json et renseigner le périmètre autorisé (voir README.md)")
    scope = json.loads(args.scope.read_text(encoding="utf-8"))
    origin = validate_origin(args.target or scope["default_origin"], scope["allowed_origins"])
    is_ml = args.scenario.startswith("ml")
    if args.execute and args.session_cookie:
        os.environ['REDTEAM_SESSION_COOKIE'] = getpass.getpass('Cookie du compte client TEST (saisie masquée) : ')
    if args.execute and args.scenario == 'ml-auth' and not os.environ.get('REDTEAM_SESSION_COOKIE'):
        raise ValueError('ml-auth exige une session de compte client TEST dans REDTEAM_SESSION_COOKIE')
    args.rate = args.rate if args.rate is not None else (5 if is_ml else 1)
    rate_limit = 5 if is_ml else min(2, scope["max_rate"])
    if not 0 < args.rate <= rate_limit:
        raise ValueError("Débit hors limite du scénario : " + str(rate_limit) + " requêtes/s maximum")
    run_id = str(uuid.uuid4())
    plan = make_plan(args.scenario, run_id)
    budget = 110 if is_ml else min(scope["max_requests"], 40)
    if len(plan) > budget:
        raise ValueError("Budget de requêtes dépassé")
    print(json.dumps({"run_id": run_id, "target": origin, "scenario": args.scenario,
                      "requests": len(plan), "rate": args.rate, "execute": args.execute}), flush=True)
    if not args.execute:
        return 0
    ca = args.scope.parent / scope["ca_file"]
    relay = None
    relay_host = None
    build_opener(ca)  # Validate trust before requesting any SSH credentials.
    if args.ssh_relay:
        from ssh_relay import SSHRelay
        host = urllib.parse.urlsplit(origin)
        config = scope.get("ssh_relay", {})
        relay_host = config.get("host")
        user = args.ssh_user or config.get("user")
        if not relay_host or not user or not ipaddress.ip_address(relay_host).is_private:
            raise ValueError("Renseigner ssh_relay.host (IP privée) et ssh_relay.user dans scope.json")
        relay = SSHRelay(relay_host, user, (host.hostname, host.port or 443), args.scope.parent / config.get("known_hosts", "ssh-known-hosts"))
    opener = build_opener(ca, relay.port if relay else None)
    dest = args.output / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + run_id)
    dest.mkdir(parents=True, exist_ok=False)
    summary = {"run_id": run_id, "started_at": utc(), "source_hostname": socket.gethostname(),
               "target": origin, "scenario": args.scenario, "rate": args.rate,
               "planned_requests": len(plan), "scope_sha256": hashlib.sha256(args.scope.read_bytes()).hexdigest(),
               "ca_sha256": hashlib.sha256(ca.read_bytes()).hexdigest(),
               "soc_alert": "not_verified", "ml_detection": "not_verified",
               "automatic_remediation": "not_verified", "new_business_transaction": "not_verified"}
    summary["transport"] = {"type": "ssh_relay" if relay else "direct_vpn", "relay": relay_host,
                            "note": "L'adresse source vue par le WAF est celle du relais" if relay else "Connexion directe"}
    results = []
    reason = None
    interrupted = False
    try:
        with (dest / "requests.jsonl").open("w", encoding="utf-8") as log:
            results, reason = execute(opener, origin, plan, run_id,
                                      min(10, max(1, scope["timeout_seconds"])), args.rate, log)
    except KeyboardInterrupt:
        interrupted = True
        reason = "Interruption opérateur"
        # Preserve completed requests even when interrupted during a sleep.
        results = [json.loads(line) for line in (dest / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
    finally:
        if relay:
            relay.close()
        if args.session_cookie:
            os.environ.pop('REDTEAM_SESSION_COOKIE', None)
    ok = not interrupted and len(results) == len(plan) and all(x["pass"] for x in results)
    summary.update({"finished_at": utc(), "sent": len(results), "passed": sum(x["pass"] for x in results),
                    "waf_test_passed": ok if not is_ml else None, "stop_reason": reason,
                    "scenario_passed": ok,
                    "attacker_ban_observed": any(x['case']=='containment' and x.get('status')==403 for x in results),
                    "full_subject_sequence_passed": False})
    (dest / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (dest / "SHA256SUMS.txt").write_text("\n".join(
        hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name
        for p in [dest / "requests.jsonl", dest / "summary.json"]) + "\n", encoding="ascii")
    print("PREUVES: " + str(dest), flush=True)
    return 0 if ok else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError) as exc:
        print("ERREUR: " + str(exc), file=sys.stderr)
        sys.exit(2)
