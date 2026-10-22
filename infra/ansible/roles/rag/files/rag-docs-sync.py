"""Synchronisation de la documentation de l'assistant avec GitHub (service rag-docs-sync).

Le CODE de l'assistant reste figé (rag_git_ref) ; seule sa CONNAISSANCE suit le dépôt :
  1. récupère les documents des branches configurées (clone superficiel et partiel, extraction
     limitée aux dossiers utiles, dépôt public : aucun jeton) ;
  2. rassemble les fichiers retenus (Markdown et PDF uniquement, exclusions) dans un répertoire
     neuf et calcule l'empreinte du corpus (contenu, modèle d'embeddings, ingest.py) ;
  3. empreinte identique à l'index en place : rien à faire ;
  4. sinon : ingest.py de l'équipe IA dans ce répertoire neuf (il lit docs/ et écrit chroma_db/
     relativement au répertoire courant), contrôle du nombre de morceaux, bascule atomique du lien
     /var/lib/rag/chroma_db, redémarrage de l'API entre deux questions, contrôle de /health
     (retour à l'index précédent en cas d'échec). Une génération précédente est gardée.

Une ligne de journal par passage : « sync ok inchange », « sync ok reindexe … » ou
« sync echec cause=… ». État lisible par la supervision : /var/lib/rag/sync-state.json.

  rag-docs-sync.py [--config FICHIER] [--force] [--repo-url URL]
"""

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

EXTENSIONS = (".md", ".pdf")  # jamais d'autre type de fichier, quelle que soit la configuration


class Echec(Exception):
    def __init__(self, cause, detail=""):
        super().__init__(cause)
        self.cause = cause
        self.detail = detail


def maintenant():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def propre(texte, n=160):
    """Détail d'erreur sur une ligne, sans caractère gênant pour le journal."""
    return re.sub(r"[^\w .:/@=+,()'-]", "_", " ".join(str(texte).split()))[:n]


def git(args, cwd=None, timeout=180):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_ASKPASS="/bin/false")
    cmd = ["git", "-c", "core.symlinks=false", "-c", "core.hooksPath=/dev/null",
           "-c", "protocol.allow=never", "-c", "protocol.https.allow=always"] + args
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Echec("github", f"git {args[0]} : délai dépassé")
    if r.returncode != 0:
        erreur = (r.stderr.strip().splitlines() or [f"code {r.returncode}"])[-1]
        raise Echec("github", f"git {args[0]} : {erreur}")
    return r.stdout.strip()


def recuperer(depot, branche, chemins, url):
    """Clone superficiel et partiel (sans contenu hors des chemins utiles), puis mise à jour."""
    if not os.path.isdir(os.path.join(depot, ".git")):
        shutil.rmtree(depot, ignore_errors=True)
        git(["clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout",
             "--branch", branche, url, depot])
    else:
        git(["remote", "set-url", "origin", url], cwd=depot)
        git(["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin",
             f"+refs/heads/{branche}:refs/remotes/origin/{branche}"], cwd=depot)
    git(["sparse-checkout", "set", "--cone"] + sorted(chemins), cwd=depot)
    git(["checkout", "-q", "-f", "--detach", f"origin/{branche}"], cwd=depot)
    return git(["rev-parse", "HEAD"], cwd=depot)


def rassembler(conf, depots, docs):
    """Copie les fichiers retenus dans docs/ ; renvoie [(chemin dans docs, empreinte)]."""
    retenus, exclusions = {}, conf.get("exclude", [])
    for src in conf["sources"]:
        racine = os.path.join(depots[src["branch"]], src["path"])
        if not os.path.isdir(racine):
            raise Echec("source_absente", f"{src['branch']}:{src['path']}")
        for dossier, sous, fichiers in os.walk(racine):
            sous[:] = sorted(d for d in sous if not d.startswith(".")) if src.get("recursive") else []
            for nom in sorted(fichiers):
                chemin = os.path.join(dossier, nom)
                rel_depot = os.path.relpath(chemin, depots[src["branch"]])
                if not nom.lower().endswith(EXTENSIONS) or nom.startswith("."):
                    continue
                if any(fnmatch.fnmatch(rel_depot, motif) for motif in exclusions):
                    continue
                # Fichiers ordinaires seulement (un lien du dépôt ne fait pas lire la machine)
                if os.path.islink(chemin) or not os.path.isfile(chemin):
                    continue
                if os.path.getsize(chemin) > conf["max_file_bytes"]:
                    raise Echec("fichier_trop_gros", rel_depot)
                dest = os.path.normpath(os.path.join(src.get("dest", ""), os.path.relpath(chemin, racine)))
                if dest.startswith("..") or os.path.isabs(dest):
                    continue
                if dest in retenus:
                    raise Echec("collision", dest)
                cible = os.path.join(docs, dest)
                os.makedirs(os.path.dirname(cible), exist_ok=True)
                shutil.copyfile(chemin, cible)
                with open(cible, "rb") as f:
                    retenus[dest] = hashlib.sha256(f.read()).hexdigest()
    if not retenus:
        raise Echec("corpus_vide")
    if len(retenus) > conf["max_files"]:
        raise Echec("trop_de_fichiers", str(len(retenus)))
    return sorted(retenus.items())


def empreinte(conf, fichiers):
    h = hashlib.sha256()
    h.update(f"modele={conf['embed_model']}\n".encode())
    with open(conf["ingest"], "rb") as f:
        h.update(f"ingest={hashlib.sha256(f.read()).hexdigest()}\n".encode())
    for chemin, somme in fichiers:
        h.update(f"{chemin}\0{somme}\n".encode())
    return h.hexdigest()


def compter(conf, base):
    """Nombre de morceaux de l'index (processus séparé : aucun fichier de Chroma gardé ouvert)."""
    code = ("import sys, chromadb; c = chromadb.PersistentClient(path=sys.argv[1]); "
            "print(sum(x.count() for x in c.list_collections()))")
    r = subprocess.run([conf["python"], "-I", "-c", code, base], capture_output=True, text=True,
                       timeout=120, cwd=os.path.dirname(base))
    if r.returncode != 0:
        raise Echec("comptage", (r.stderr.strip().splitlines() or ["?"])[-1])
    return int(r.stdout.strip().splitlines()[-1])


def connexions_api(port):
    """Connexions établies sur le port de l'API (une question en cours)."""
    n, local = 0, f":{port:04X}"
    for fichier in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(fichier) as f:
                next(f)
                for ligne in f:
                    champs = ligne.split()
                    if champs[1].endswith(local) and champs[3] == "01":
                        n += 1
        except OSError:
            pass
    return n


def api_saine(url, delai):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


def redemarrer(conf):
    """Redémarre les services actifs qui lisent l'index ; vrai si l'API répond (ou est arrêtée)."""
    api_active = subprocess.run(["systemctl", "is-active", "--quiet", conf["restart_units"][0]],
                                timeout=30).returncode == 0
    for unite in conf["restart_units"]:
        r = subprocess.run(["systemctl", "--no-ask-password", "try-restart", unite],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise Echec("redemarrage", f"{unite} : {r.stderr.strip()}")
    # API arrêtée (premier déploiement) : elle ouvrira le nouvel index à son démarrage
    return not api_active or api_saine(conf["api_health_url"], conf["api_health_timeout"])


def basculer(lien, cible):
    """Remplacement atomique du lien (rename(2)) : l'index lu est l'ancien ou le nouveau."""
    tmp = f"{lien}.tmp-{os.getpid()}"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    os.symlink(cible, tmp)
    os.replace(tmp, lien)


def ecrire_etat(chemin, etat):
    tmp = f"{chemin}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, chemin)


def synchroniser(conf, args, etat):
    data = conf["data_dir"]
    index_dir = os.path.join(data, "index")
    lien = os.path.join(data, "chroma_db")
    os.makedirs(index_dir, exist_ok=True)

    # Index en place : lien vers index/<nom>/chroma_db, ou ancien répertoire (avant la synchro)
    actuel = None
    if os.path.islink(lien):
        actuel = os.path.dirname(os.path.realpath(lien))
    fp_actuel = ""
    if actuel and os.path.isfile(os.path.join(actuel, "fingerprint")):
        with open(os.path.join(actuel, "fingerprint")) as f:
            fp_actuel = f.read().strip()

    # Répertoires de construction laissés par un passage interrompu
    for nom in os.listdir(index_dir):
        if nom.startswith(".build-"):
            shutil.rmtree(os.path.join(index_dir, nom), ignore_errors=True)

    debut = time.monotonic()
    url = args.repo_url or conf["repo_url"]
    if not url.startswith("https://"):
        raise Echec("configuration", "repo_url doit être en https://")
    chemins = {}
    for src in conf["sources"]:
        chemins.setdefault(src["branch"], set()).add(src["path"])
    depots, commits = {}, {}
    for branche, ch in sorted(chemins.items()):
        depots[branche] = os.path.join(data, "sync", "git-" + re.sub(r"[^\w.-]", "_", branche))
        commits[branche] = recuperer(depots[branche], branche, ch, url)
    etat["commits"] = commits

    build = os.path.join(index_dir, f".build-{os.getpid()}")
    os.makedirs(os.path.join(build, "docs"))
    try:
        fichiers = rassembler(conf, depots, os.path.join(build, "docs"))
        fp = empreinte(conf, fichiers)
        if fp == fp_actuel and not args.force:
            shutil.rmtree(build, ignore_errors=True)
            return "inchange", fichiers, etat.get("chunks"), time.monotonic() - debut, fp

        # Indexation : même procédure qu'au déploiement (ingest.py), dans le répertoire neuf
        try:
            r = subprocess.run([conf["python"], conf["ingest"]], cwd=build, capture_output=True,
                               text=True, timeout=conf["ingest_timeout"])
        except subprocess.TimeoutExpired:
            raise Echec("indexation", "délai dépassé")
        if r.returncode != 0:
            raise Echec("indexation", (r.stderr.strip().splitlines() or ["?"])[-1])
        morceaux = compter(conf, os.path.join(build, "chroma_db"))
        precedent = etat.get("chunks") or 0
        seuil = max(conf["min_chunks"], int(precedent * conf["min_ratio"]))
        if morceaux < seuil:
            raise Echec("index_trop_petit", f"morceaux={morceaux} seuil={seuil}")

        with open(os.path.join(build, "fingerprint"), "w") as f:
            f.write(fp + "\n")
        with open(os.path.join(build, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"date": maintenant(), "commits": commits, "chunks": morceaux,
                       "files": [c for c, _ in fichiers]}, f, ensure_ascii=False, indent=2)
        nom = f"{fp[:12]}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        nouveau = os.path.join(index_dir, nom)
        os.rename(build, nouveau)
    except BaseException:
        shutil.rmtree(build, ignore_errors=True)
        raise

    # Bascule entre deux questions : on attend que l'API n'ait plus de connexion en cours
    fin = time.monotonic() + conf["idle_wait"]
    while connexions_api(conf["api_port"]) and time.monotonic() < fin:
        time.sleep(1)

    if os.path.isdir(lien) and not os.path.islink(lien):
        # Première synchro : l'index construit par Ansible devient la génération précédente
        actuel = os.path.join(index_dir, f"ancien-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
        os.makedirs(actuel)
        os.rename(lien, os.path.join(actuel, "chroma_db"))
    basculer(lien, os.path.join(nouveau, "chroma_db"))
    if not redemarrer(conf):
        if actuel:
            basculer(lien, os.path.join(actuel, "chroma_db"))
            redemarrer(conf)
        raise Echec("api_ko", f"/health en échec après bascule vers {nom}, retour à l'index précédent")

    # Rétention : index en place + une génération précédente
    garder = {nom, os.path.basename(actuel) if actuel else ""}
    for ancien in os.listdir(index_dir):
        if ancien not in garder and not ancien.startswith("."):
            shutil.rmtree(os.path.join(index_dir, ancien), ignore_errors=True)
    etat["index"] = nom
    etat["previous_index"] = os.path.basename(actuel) if actuel else None
    etat["last_reindex"] = maintenant()
    return "reindexe", fichiers, morceaux, time.monotonic() - debut, fp


def main():
    p = argparse.ArgumentParser(description="Synchronise la documentation de l'assistant avec GitHub")
    p.add_argument("--config", default="/etc/rag/docs-sync.json")
    p.add_argument("--force", action="store_true", help="réindexer même si le corpus est inchangé")
    p.add_argument("--repo-url", help="dépôt à utiliser à la place de celui de la configuration")
    args = p.parse_args()
    with open(args.config, encoding="utf-8") as f:
        conf = json.load(f)

    data = conf["data_dir"]
    os.makedirs(os.path.join(data, "sync"), exist_ok=True)
    verrou = open(os.path.join(data, "sync", "lock"), "w")
    try:
        fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Un passage est déjà en cours (lancement manuel) : pas une erreur, l'état n'est pas touché
        print("sync ignore deja_en_cours", flush=True)
        return 0

    chemin_etat = os.path.join(data, "sync-state.json")
    try:
        with open(chemin_etat, encoding="utf-8") as f:
            etat = json.load(f)
    except (OSError, ValueError):
        etat = {}
    etat["last_run"] = maintenant()
    ia, infra = (conf.get("log_branches", ["IA", "INFRA"]) + ["", ""])[:2]
    try:
        resultat, fichiers, morceaux, duree, fp = synchroniser(conf, args, etat)
    except Exception as e:
        cause = e.cause if isinstance(e, Echec) else "interne"
        detail = e.detail if isinstance(e, Echec) else f"{e.__class__.__name__}: {e}"
        etat.update(last_result="echec", last_error=f"{cause} {propre(detail)}".strip(),
                    last_failure=etat["last_run"])
        ecrire_etat(chemin_etat, etat)
        print(f"sync echec cause={cause} detail=\"{propre(detail)}\"", flush=True)
        return 1

    commits = etat.get("commits", {})
    etat.update(last_result=resultat, last_success=etat["last_run"], last_error=None,
                fingerprint=fp, files=len(fichiers), chunks=morceaux)
    ecrire_etat(chemin_etat, etat)
    ligne = f"sync ok {resultat}"
    if resultat == "reindexe":
        ligne += f" fichiers={len(fichiers)} morceaux={morceaux} duree={duree:.1f}s"
    ligne += f" commit_ia={commits.get(ia, '?')[:7]} commit_infra={commits.get(infra, '?')[:7]}"
    print(ligne, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
