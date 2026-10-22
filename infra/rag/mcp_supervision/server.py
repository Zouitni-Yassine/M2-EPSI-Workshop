"""Serveur MCP « supervision » de l'assistant RAG (rag01) : état réel du système, en LECTURE SEULE.

Outils exposés à l'agent de l'équipe IA (rag/agent.py, branche IA) :
  alertes_recentes, etat_plateforme, ip_bannies, evenements_remediation, requete_metrique.

Sources : VictoriaMetrics (API Prometheus, via vmauth) et Loki (via nginx), interrogés avec le
compte rag-readonly, limité par la supervision aux seules routes de requête (docs/rag.md) : même
un outil détourné ne peut ni écrire, ni supprimer, ni lire de secret. Aucun outil n'agit sur le
système (pas de redémarrage, pas de bannissement).

Transport streamable HTTP sur 127.0.0.1 uniquement (service rag-mcp). Configuration par
l'environnement (unité systemd) ; mots de passe lus dans des fichiers à chaque appel.
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

VM_URL = os.getenv("RAG_VM_URL", "http://10.0.1.233:8428").rstrip("/")
LOKI_URL = os.getenv("RAG_LOKI_URL", "http://10.0.1.233:3100").rstrip("/")
USER = os.getenv("RAG_READONLY_USER", "rag-readonly")
VM_PASSWORD_FILE = os.getenv("RAG_VM_PASSWORD_FILE", "/etc/rag/vm_password")
LOKI_PASSWORD_FILE = os.getenv("RAG_LOKI_PASSWORD_FILE", "/etc/rag/loki_password")
HOST = os.getenv("RAG_MCP_HOST", "127.0.0.1")
PORT = int(os.getenv("RAG_MCP_PORT", "8610"))

TZ = ZoneInfo("Europe/Paris")
TIMEOUT = 10.0                  # délai par requête HTTP
MAX_BYTES = 2 * 1024 * 1024     # réponse brute maximale acceptée d'une source
MAX_CHARS = 3000                # sortie maximale d'un outil (lisible par le modèle)

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
log = logging.getLogger("mcp-supervision")
for bruyant in ("httpx", "mcp", "uvicorn.access"):
    logging.getLogger(bruyant).setLevel(logging.WARNING)

LECTURE = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                          openWorldHint=False)

mcp = FastMCP(
    "supervision",
    instructions="État réel de la plateforme RESILIENCE-ALPHA (supervision), en lecture seule.",
    host=HOST, port=PORT, stateless_http=True, json_response=True, log_level="WARNING",
)


# --- Accès aux sources -------------------------------------------------------------------

def _mot_de_passe(chemin):
    with open(chemin, encoding="utf-8") as f:
        return f.read().strip()


async def _get(base, chemin, params, fichier_mdp):
    """GET authentifié, réponse bornée en taille et en temps. Erreur courte, sans secret."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            async with client.stream("GET", base + chemin, params=params,
                                     auth=(USER, _mot_de_passe(fichier_mdp))) as r:
                corps = bytearray()
                async for bloc in r.aiter_bytes():
                    corps += bloc
                    if len(corps) > MAX_BYTES:
                        raise ToolError("résultat trop volumineux : préciser la requête")
                if r.status_code != 200:
                    detail = corps[:200].decode("utf-8", "replace").strip()
                    raise ToolError(f"HTTP {r.status_code} sur {chemin} : {detail}")
                return json.loads(corps)
    except httpx.TimeoutException:
        raise ToolError(f"délai dépassé ({TIMEOUT:.0f} s) sur {chemin}") from None
    except httpx.HTTPError as e:
        raise ToolError(f"source injoignable ({e.__class__.__name__})") from None


async def vm_instant(expr):
    d = await _get(VM_URL, "/api/v1/query", {"query": expr, "timeout": "8s"}, VM_PASSWORD_FILE)
    return d["data"]["resultType"], d["data"]["result"]


async def vm_vecteur(expr):
    return (await vm_instant(expr))[1]


async def vm_plage(expr, debut, fin, pas):
    d = await _get(VM_URL, "/api/v1/query_range",
                   {"query": expr, "start": int(debut), "end": int(fin), "step": f"{int(pas)}s",
                    "timeout": "8s"}, VM_PASSWORD_FILE)
    return d["data"]["result"]


async def loki_lignes(requete, heures, limite):
    """Lignes de Loki sur la période, de la plus ancienne à la plus récente : [(ts, ligne, flux)]."""
    fin = time.time_ns()
    d = await _get(LOKI_URL, "/loki/api/v1/query_range",
                   {"query": requete, "start": fin - int(heures * 3600e9), "end": fin,
                    "limit": limite, "direction": "backward"}, LOKI_PASSWORD_FILE)
    lignes = [(int(ts) / 1e9, ligne, s["stream"]) for s in d["data"]["result"]
              for ts, ligne in s["values"]]
    return sorted(lignes, key=lambda x: x[0])


# --- Mise en forme -----------------------------------------------------------------------

def heure(ts):
    t = datetime.fromtimestamp(ts, TZ)
    return t.strftime("%H:%M:%S") if t.date() == datetime.now(TZ).date() else t.strftime("%d/%m %H:%M")


def duree(s):
    s = int(s)
    if s < 120:
        return f"{s} s"
    if s < 7200:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60:02d}"


def borne(n, mini, maxi):
    try:
        return max(mini, min(maxi, int(n)))
    except (TypeError, ValueError):
        return mini


def coupe(texte):
    return texte if len(texte) <= MAX_CHARS else texte[:MAX_CHARS - 30] + "\n… (sortie tronquée)"


def propre(valeur, n=60):
    """Valeur venant des journaux (donc potentiellement d'un attaquant) : une ligne, bornée."""
    return re.sub(r"[^\w.:/=@,+ -]", "?", str(valeur))[:n]


def journal(outil, args, debut, statut):
    log.info("outil=%s args=%s duree=%.2fs statut=%s", outil,
             json.dumps(args, ensure_ascii=False)[:200], time.monotonic() - debut, statut)


async def execute(outil, args, fonction):
    debut = time.monotonic()
    try:
        resultat = coupe(await fonction())
        journal(outil, args, debut, "ok")
        return resultat
    except ToolError as e:
        journal(outil, args, debut, f"erreur: {e}")
        raise
    except Exception as e:  # erreur inattendue : message court, pas de trace vers le modèle
        journal(outil, args, debut, f"erreur: {e.__class__.__name__}")
        raise ToolError(f"erreur interne de l'outil ({e.__class__.__name__})") from None


# --- Outils ------------------------------------------------------------------------------

@mcp.tool(annotations=LECTURE)
async def alertes_recentes(heures: int = 2) -> str:
    """Alertes de supervision déclenchées (firing) sur les N dernières heures (1 à 48) :
    nom, sévérité, service ou machine, début et fin approximatifs, encore active ou non.
    Source : série ALERTS de VictoriaMetrics (vmalert), alerte Watchdog exclue."""
    h = borne(heures, 1, 48)

    async def run():
        fin = time.time()
        pas = max(30, h * 3600 // 600)
        selecteur = 'ALERTS{alertstate="firing", alertname!="Watchdog"}'
        series, actives = await asyncio.gather(
            vm_plage(selecteur, fin - h * 3600, fin, pas), vm_vecteur(selecteur))
        cles_actives = {json.dumps(s["metric"], sort_keys=True) for s in actives}
        episodes = []
        for s in series:
            m = s["metric"]
            ts = [float(t) for t, _ in s["values"]]
            if not ts:
                continue
            # Plusieurs épisodes dans la période : coupure si l'alerte a disparu plus de 2 pas
            debut = prec = ts[0]
            morceaux = []
            for t in ts[1:]:
                if t - prec > 2 * pas + 1:
                    morceaux.append((debut, prec))
                    debut = t
                prec = t
            morceaux.append((debut, prec))
            cible = m.get("service") or m.get("host") or m.get("source_ip") or m.get("instance") or m.get("job") or ""
            for i, (d, f) in enumerate(morceaux):
                active = i == len(morceaux) - 1 and json.dumps(m, sort_keys=True) in cles_actives
                episodes.append((d, f, active, m.get("alertname", "?"), m.get("severity", "?"), cible))
        if not episodes:
            return (f"Aucune alerte déclenchée sur les {h} dernières heures "
                    "(source : VictoriaMetrics, série ALERTS, Watchdog exclu).")
        episodes.sort(key=lambda e: e[0], reverse=True)
        n_actives = sum(1 for e in episodes if e[2])
        lignes = [f"{len(episodes)} déclenchement(s) d'alerte sur les {h} dernières heures, "
                  f"{n_actives} encore active(s) (heure de Paris, précision ±{pas} s ; "
                  "source : VictoriaMetrics, série ALERTS) :"]
        compte = {}
        for e in episodes:
            compte[(e[3], e[4])] = compte.get((e[3], e[4]), 0) + 1
        lignes.append("Par alerte : " + ", ".join(
            f"{nom} [{sev}] ×{n}" for (nom, sev), n in sorted(compte.items(), key=lambda x: -x[1])))
        lignes.append("Les plus récentes :")
        for d, f, active, nom, sev, cible in episodes[:10]:
            quoi = f"{nom} [{sev}]" + (f" ({cible})" if cible else "")
            if active:
                lignes.append(f"- {quoi} : depuis {heure(d)}, ENCORE ACTIVE")
            else:
                lignes.append(f"- {quoi} : {heure(d)} → {heure(f)} (~{duree(f - d + pas)}), résolue")
        if len(episodes) > 10:
            lignes.append(f"… et {len(episodes) - 10} autre(s), plus ancienne(s)")
        return "\n".join(lignes)

    return await execute("alertes_recentes", {"heures": h}, run)


async def _ou_rien(coro):
    try:
        return await coro
    except ToolError:
        return None


@mcp.tool(annotations=LECTURE)
async def etat_plateforme() -> str:
    """Photographie de l'état actuel : services de la stack paiement vus par la supervision,
    base PostgreSQL (primaire, standbys, retard de réplication), score du détecteur d'anomalies
    et seuil, dernière transaction réussie de la sonde, alertes actives, Vault, Ceph,
    hyperviseurs Proxmox et nœuds Swarm. Source : VictoriaMetrics."""

    async def run():
        req = {
            "up": 'max by (service) (up{stack=~"paiement|probe"})',
            "vus": 'max by (service) (max_over_time(up{stack=~"paiement|probe"}[1h]))',
            "primaire": 'patroni_primary{stack="paiement"}',
            "replica": 'patroni_replica{stack="paiement"}',
            "streaming": 'patroni_postgres_streaming{stack="paiement"}',
            "wal": 'patroni_xlog_location{stack="paiement"}',
            "rejoue": 'patroni_xlog_replayed_location{stack="paiement"}',
            "score": "detector_anomaly_score",
            "seuil": "detector_threshold",
            "pret": "detector_ready",
            "sonde": 'paiement_probe_last_success_timestamp_seconds{check="transaction"}',
            "alertes": 'ALERTS{alertstate="firing", alertname!="Watchdog"}',
            "vault": "vault_core_unsealed",
            "ceph": "ceph_health_status",
            "pve": 'pve_up{id=~"node/.*"}',
            "docker": 'up{job="docker"}',
            "leader": "swarm_manager_leader == 1",
        }
        res = dict(zip(req, await asyncio.gather(*(_ou_rien(vm_vecteur(e)) for e in req.values()))))
        if all(v is None for v in res.values()):
            raise ToolError("VictoriaMetrics injoignable : état du système indisponible")
        val = lambda s: float(s["value"][1])  # noqa: E731
        nd = "indisponible"
        out = [f"État de la plateforme à {heure(time.time())} (heure de Paris ; source : VictoriaMetrics) :"]

        # Services (cibles scrapées de la stack paiement et de la sonde)
        if res["up"] is None or res["vus"] is None:
            out.append(f"- Services : {nd}")
        else:
            etat = {s["metric"].get("service", "?"): val(s) for s in res["up"]}
            vus = sorted(s["metric"].get("service", "?") for s in res["vus"])
            ok = [s for s in vus if etat.get(s) == 1]
            ko = [s for s in vus if etat.get(s) != 1]
            out.append(f"- Services supervisés : {len(ok)}/{len(vus)} up"
                       + (f" ; EN PANNE ou absents : {', '.join(ko)}" if ko else "")
                       + " (frontend et moteur de remédiation non scrapés : voir la sonde)")

        # Base PostgreSQL (Patroni)
        if res["primaire"] is None:
            out.append(f"- Base : {nd}")
        elif not res["primaire"]:
            out.append("- Base : aucune métrique Patroni (membres injoignables ?)")
        else:
            nom = lambda s: s["metric"].get("name") or s["metric"].get("service", "?")  # noqa: E731
            prim = [s for s in res["primaire"] if val(s) == 1]
            wal = {nom(s): val(s) for s in res["wal"] or []}
            rejoue = {nom(s): val(s) for s in res["rejoue"] or []}
            stream = {nom(s): val(s) for s in res["streaming"] or []}
            standbys = [nom(s) for s in res["replica"] or [] if val(s) == 1]
            if len(prim) == 1:
                p = nom(prim[0])
                details = []
                for r in sorted(standbys):
                    retard = wal.get(p, 0) - rejoue.get(r, 0)
                    flux = "en réplication" if stream.get(r) == 1 else "PAS en réplication"
                    details.append(f"{r} {flux}, retard {max(0, retard) / 1024:.0f} Kio")
                out.append(f"- Base : primaire {p} ; standbys : "
                           + ("; ".join(details) if details else "AUCUN"))
            elif not prim:
                out.append("- Base : AUCUN PRIMAIRE (bascule Patroni en cours ou bloquée)")
            else:
                out.append(f"- Base : {len(prim)} PRIMAIRES à la fois (split brain) : "
                           + ", ".join(nom(s) for s in prim))

        # Détecteur d'anomalies
        if res["score"]:
            score = val(res["score"][0])
            seuil = val(res["seuil"][0]) if res["seuil"] else None
            pret = res["pret"] and val(res["pret"][0]) == 1
            txt = f"- Détecteur : score {score:.2f}"
            if seuil is not None:
                txt += f", seuil {seuil:.2f} ({'ANOMALIE' if score >= seuil else 'normal'})"
            out.append(txt + ("" if pret else ", modèle pas encore prêt"))
        else:
            out.append(f"- Détecteur : {nd}")

        # Sonde de transaction (paiement de test périodique)
        if res["sonde"]:
            ts = max(val(s) for s in res["sonde"])
            out.append(f"- Dernière transaction de test réussie : {heure(ts)} (il y a {duree(time.time() - ts)})")
        else:
            out.append(f"- Sonde de transaction : {nd}")

        # Alertes actives
        if res["alertes"] is None:
            out.append(f"- Alertes actives : {nd}")
        else:
            noms = sorted({s["metric"].get("alertname", "?") for s in res["alertes"]})
            out.append(f"- Alertes actives : {len(res['alertes'])}"
                       + (f" ({', '.join(noms[:8])})" if noms else ""))

        # Socle
        if res["vault"] is None:
            out.append(f"- Vault : {nd}")
        elif not res["vault"]:
            out.append("- Vault : métrique absente (Vault scellé ou injoignable)")
        else:
            out.append("- Vault : " + ("descellé" if val(res["vault"][0]) == 1 else "SCELLÉ"))
        if res["ceph"]:
            out.append("- Ceph : " + {0: "HEALTH_OK", 1: "HEALTH_WARN", 2: "HEALTH_ERR"}.get(
                int(val(res["ceph"][0])), "inconnu"))
        else:
            out.append(f"- Ceph : {nd}")
        if res["pve"]:
            noeuds = sorted((s["metric"]["id"].split("/")[-1], val(s)) for s in res["pve"])
            out.append("- Hyperviseurs : " + ", ".join(f"{n} {'up' if v == 1 else 'DOWN'}" for n, v in noeuds))
        else:
            out.append(f"- Hyperviseurs : {nd}")
        if res["docker"]:
            joignables = sum(1 for s in res["docker"] if val(s) == 1)
            leader = ", ".join(s["metric"].get("host", "?") for s in res["leader"] or []) or "AUCUN"
            out.append(f"- Swarm : {joignables}/{len(res['docker'])} nœuds joignables, leader {leader}")
        else:
            out.append(f"- Swarm : {nd}")
        return "\n".join(out)

    return await execute("etat_plateforme", {}, run)


CLE_VALEUR = re.compile(r"(\w+)=('[^']*'|\"[^\"]*\"|\S+)")


def champs(ligne):
    return {k: v.strip("'\"") for k, v in CLE_VALEUR.findall(ligne)}


@mcp.tool(annotations=LECTURE)
async def ip_bannies(heures: int = 24) -> str:
    """Bannissements automatiques au WAF sur les N dernières heures (1 à 168) : IP bannies,
    raison (règle d'alerte), heure, expiration, IP encore bannies maintenant, débannissements
    et demandes refusées. Source : journal du service waf-ban de waf01 dans Loki."""
    h = borne(heures, 1, 168)

    async def run():
        lignes = await loki_lignes('{identifier="waf-ban"} |~ "^(ban|expiration|deban|refus) "', h, 1000)
        maintenant = time.time()
        bans, fins, refus = [], [], []
        expire_a = {}
        for ts, ligne, _ in lignes:
            kind = ligne.split(" ", 1)[0]
            c = champs(ligne)
            ip = propre(c.get("ip", "?"), 45)
            if kind == "ban":
                try:
                    duree_s = int(c.get("duree_s", "0"))
                except ValueError:
                    duree_s = 0
                bans.append((ts, ip, propre(c.get("raison", "?")), duree_s))
                expire_a[ip] = ts + duree_s
            elif kind in ("expiration", "deban"):
                fins.append((ts, ip, "débannie manuellement" if kind == "deban" else "expirée"))
                expire_a.pop(ip, None)
            elif kind == "refus":
                refus.append((ts, ip, propre(c.get("cause", "?"))))
        actives = sorted(ip for ip, t in expire_a.items() if t > maintenant)
        src = "source : Loki, journal waf-ban de waf01"
        if not bans and not fins and not refus:
            return f"Aucun bannissement au WAF sur les {h} dernières heures ({src})."
        out = [f"WAF, {h} dernières heures (heure de Paris ; {src}) : {len(bans)} bannissement(s), "
               f"{len(actives)} IP encore bannie(s) maintenant"
               + (f" : {', '.join(actives)}" if actives else "") + "."]
        for ts, ip, raison, d in bans[-12:][::-1]:
            out.append(f"- {heure(ts)} ban {ip}, raison {raison}, {duree(d)} (jusqu'à {heure(ts + d)})")
        if len(bans) > 12:
            out.append(f"… et {len(bans) - 12} bannissement(s) plus ancien(s)")
        for ts, ip, quoi in fins[-6:][::-1]:
            out.append(f"- {heure(ts)} {ip} {quoi}")
        if refus:
            out.append(f"- {len(refus)} demande(s) de bannissement refusée(s) (liste blanche, adresse "
                       f"protégée ou invalide), dernière : {refus[-1][1]} ({refus[-1][2]})")
        return "\n".join(out)

    return await execute("ip_bannies", {"heures": h}, run)


@mcp.tool(annotations=LECTURE)
async def evenements_remediation(heures: int = 2) -> str:
    """Chronologie des événements du moteur de remédiation sur les N dernières heures (1 à 48) :
    incident détecté, décision, action (redémarrage par la passerelle), vérification, service
    rétabli avec sa durée. Source : événements republiés par la sonde de transaction (Loki)."""
    h = borne(heures, 1, 48)

    async def run():
        lignes = await loki_lignes('{stack="probe"} |= "type=evenement"', h, 500)
        vus, evts = set(), []
        for ts, ligne, _ in lignes:
            c = champs(ligne)
            cle = (c.get("at"), c.get("kind"), c.get("texte"))
            if cle in vus:
                continue
            vus.add(cle)
            try:
                quand = datetime.fromisoformat(c["at"].replace("Z", "+00:00")).timestamp()
            except (KeyError, ValueError):
                quand = ts
            evts.append((quand, propre(c.get("kind", "?"), 20), c.get("etape", "")[:40],
                         c.get("texte", "")[:200]))
        if not evts:
            return (f"Aucun événement du moteur de remédiation sur les {h} dernières heures "
                    "(source : Loki, sonde de transaction).")
        # Tri stable sur l'heure : à seconde égale, l'ordre d'émission (Loki) est conservé
        evts.sort(key=lambda e: e[0])
        incidents = sum(1 for e in evts if e[1] == "detect")
        retablis = sum(1 for e in evts if e[1] == "restore")
        out = [f"{len(evts)} événement(s) du moteur sur les {h} dernières heures : {incidents} incident(s) "
               f"détecté(s), {retablis} rétablissement(s) (heure de Paris ; source : Loki, sonde) :"]
        for quand, kind, etape, texte in evts[-20:]:
            out.append(f"- {heure(quand)} [{kind}] {etape} : {texte}")
        if len(evts) > 20:
            out.insert(1, f"(les {len(evts) - 20} plus anciens sont omis)")
        return "\n".join(out)

    return await execute("evenements_remediation", {"heures": h}, run)


# Nature de chaque machine, d'après le label role posé par la collecte (job node)
TYPES = {
    "pve": "serveur physique (hyperviseur Proxmox + Ceph)",
    "swarm_manager": "VM (manager Swarm)",
    "swarm_worker": "VM (worker Swarm)",
    "rag": "VM (assistant)",
    "control": "VM (poste de contrôle)",
    "waf": "VM (WAF)",
    "monitoring": "LXC (supervision)",
    "identity": "LXC (identité)",
}
FILTRES = {"physique": {"pve"}, "pve": {"pve"}, "hyperviseur": {"pve"},
           "vm": {"swarm_manager", "swarm_worker", "rag", "control", "waf"},
           "lxc": {"monitoring", "identity"}}


@mcp.tool(annotations=LECTURE)
async def charge_machines(type_machine: str = "") -> str:
    """Charge actuelle de chaque machine : CPU (moyenne 5 min), RAM utilisée, disque racine
    utilisé, état. À utiliser pour toute question CPU / RAM / disque / charge des serveurs.
    type_machine : "physique" (= les serveurs physiques : les 3 hyperviseurs Proxmox
    ceph01, ceph02, ceph03), "vm", "lxc", ou vide pour toutes les machines.
    Seuls ceph01-03 sont des serveurs physiques ; toutes les autres machines sont des VM ou
    des LXC hébergées sur eux."""
    filtre = (type_machine or "").strip().lower()

    async def run():
        if filtre and filtre not in FILTRES:
            raise ToolError('type_machine attendu : "physique", "vm", "lxc" ou vide')
        cpu, ram, disque, up = await asyncio.gather(
            vm_vecteur('100 * (1 - avg by (host, role, instance) '
                       '(rate(node_cpu_seconds_total{job="node", mode="idle"}[5m])))'),
            vm_vecteur('100 * (1 - node_memory_MemAvailable_bytes{job="node"} '
                       '/ node_memory_MemTotal_bytes{job="node"})'),
            vm_vecteur('100 * (1 - node_filesystem_avail_bytes{job="node", mountpoint="/"} '
                       '/ node_filesystem_size_bytes{job="node", mountpoint="/"})'),
            vm_vecteur('up{job="node"}'))
        machines = {}
        for nom, serie in (("cpu", cpu), ("ram", ram), ("disque", disque), ("up", up)):
            for s in serie:
                m = s["metric"]
                hote = m.get("host", m.get("instance", "?"))
                fiche = machines.setdefault(hote, {"role": m.get("role", "?"),
                                                    "ip": m.get("instance", "?").split(":")[0]})
                fiche[nom] = float(s["value"][1])
        roles = FILTRES.get(filtre)
        lignes = []
        for hote, f in sorted(machines.items(), key=lambda x: (x[1]["role"] != "pve", x[0])):
            if roles and f["role"] not in roles:
                continue
            if f.get("up", 0) < 1:
                lignes.append(f"- {hote} ({f['ip']}, {TYPES.get(f['role'], f['role'])}) : INJOIGNABLE")
                continue
            val = lambda k: f"{f[k]:.0f} %" if k in f else "n/d"
            lignes.append(f"- {hote} ({f['ip']}, {TYPES.get(f['role'], f['role'])}) : "
                          f"CPU {val('cpu')} · RAM {val('ram')} · disque / {val('disque')}")
        if not lignes:
            return "Aucune machine trouvée pour ce filtre (source : VictoriaMetrics)."
        titre = {"": "Toutes les machines", "vm": "VM", "lxc": "LXC"}.get(
            filtre, "Serveurs physiques (hyperviseurs Proxmox ceph01-03)")
        return (f"{titre}, {len(lignes)} machine(s) (source : VictoriaMetrics, node_exporter) :\n"
                + "\n".join(lignes))

    return await execute("charge_machines", {"type_machine": filtre[:20]}, run)


@mcp.tool(annotations=LECTURE)
async def requete_metrique(promql: str) -> str:
    """Requête PromQL/MetricsQL instantanée (lecture seule, 300 caractères max, 8 s max,
    20 séries affichées au plus) pour une question non couverte par les autres outils (CPU / RAM / disque : utiliser
    charge_machines).
    Exemples : up{job="node"} == 0, detector_anomaly_score, rate(http_requests_total[5m])."""
    expr = (promql or "").strip()

    async def run():
        if not expr:
            raise ToolError("requête vide")
        if len(expr) > 300:
            raise ToolError("requête trop longue (300 caractères maximum)")
        type_res, res = await vm_instant(expr)
        if type_res == "scalar" or type_res == "string":
            return f"{expr} = {res[1]} (source : VictoriaMetrics)"
        if not res:
            return f"Aucun résultat pour {expr} (source : VictoriaMetrics)."
        out = [f"{len(res)} série(s) pour {expr} (source : VictoriaMetrics) :"]
        for s in res[:20]:
            labels = ", ".join(f"{k}={v}" for k, v in sorted(s["metric"].items()))
            if "value" in s:
                out.append(f"- {{{labels}}} = {s['value'][1]}")
            else:  # vecteur de plage : dernière valeur seulement
                derniere = s["values"][-1] if s.get("values") else [0, "?"]
                out.append(f"- {{{labels}}} = {derniere[1]} (dernier point de {len(s.get('values', []))})")
        if len(res) > 20:
            out.append(f"… et {len(res) - 20} autre(s) série(s)")
        return "\n".join(out)

    return await execute("requete_metrique", {"promql": expr[:300]}, run)


if __name__ == "__main__":
    log.info("serveur MCP supervision : http://%s:%d/mcp (lecture seule)", HOST, PORT)
    mcp.run(transport="streamable-http")
