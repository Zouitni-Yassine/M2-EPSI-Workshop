"""Bot Discord de l'équipe (« Qwen ») : relaie les questions vers l'assistant opérateur de rag01.

Répond seulement sur le serveur et le salon configurés (et les fils de ce salon), seulement
quand il est mentionné ou qu'on répond à l'un de ses messages. Chaque question part vers
l'API locale de l'assistant (POST http://127.0.0.1:8600/ask, jeton Bearer) ; la réponse est
donnée en réponse au message, en morceaux de 2000 caractères au plus.

Aucun droit sur le système : le bot ne parle qu'à l'API de l'assistant, elle-même en lecture
seule. Intents par défaut (pas d'intent privilégié) : Discord fournit le contenu des messages
qui mentionnent le bot.

Configuration par l'environnement (unité systemd discord-bot, rôle Ansible rag) ; jetons lus
dans des fichiers, jamais journalisés.
"""

import logging
import os
import re
import sys
import time

import discord
import httpx

GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])
CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8600/ask")
DISCORD_TOKEN_FILE = os.getenv("DISCORD_TOKEN_FILE", "/etc/discord-bot/discord_token")
API_TOKEN_FILE = os.getenv("RAG_API_TOKEN_FILE", "/etc/discord-bot/api_token")
# Message d'annonce, posté une seule fois (marqueur dans le répertoire d'état) si activé
ANNONCE = os.getenv("DISCORD_ANNOUNCE", "0") == "1"
MARQUEUR = os.path.join(os.getenv("STATE_DIRECTORY", "/var/lib/discord-bot"), "annonce-faite")
DELAI_API = 150.0
PAUSE_UTILISATEUR = 10.0
MAX_QUESTION = 1000

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(levelname)s %(message)s")
for bruyant in ("discord", "httpx"):
    logging.getLogger(bruyant).setLevel(logging.WARNING)
log = logging.getLogger("discord-bot")


def lire(chemin):
    with open(chemin, encoding="utf-8") as f:
        return f.read().strip()


client = discord.Client(
    intents=discord.Intents.default(),
    # Une réponse ne notifie que l'auteur de la question (jamais @everyone, rôles ou autres)
    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False,
                                             replied_user=True),
)
en_cours = set()
derniere = {}


def salon_autorise(canal):
    if getattr(canal, "id", None) == CHANNEL_ID:
        return True
    return isinstance(canal, discord.Thread) and canal.parent_id == CHANNEL_ID


def morceaux(texte, taille=2000):
    """Découpe en morceaux de `taille` caractères au plus, de préférence aux fins de ligne."""
    while texte:
        if len(texte) <= taille:
            yield texte
            return
        coupe = texte.rfind("\n", 0, taille)
        coupe = coupe if coupe > taille // 2 else taille
        yield texte[:coupe]
        texte = texte[coupe:].lstrip("\n")


@client.event
async def on_ready():
    log.info("connecté à Discord en tant que %s (id %s)", client.user, client.user.id)
    serveur = client.get_guild(GUILD_ID)
    if serveur is None:
        log.error("serveur %s introuvable : le bot n'y est pas invité (lien d'invitation OAuth2 "
                  "avec le scope bot à générer dans le portail développeur)", GUILD_ID)
        return
    canal = serveur.get_channel(CHANNEL_ID)
    if canal is None:
        log.error("serveur « %s » : salon %s introuvable ou invisible pour le bot "
                  "(permission Voir le salon)", serveur.name, CHANNEL_ID)
        return
    droits = canal.permissions_for(serveur.me)
    manque = [nom for nom, ok in (("Voir le salon", droits.view_channel),
                                  ("Envoyer des messages", droits.send_messages),
                                  ("Lire l'historique des messages", droits.read_message_history),
                                  ("Envoyer des messages dans les fils", droits.send_messages_in_threads))
              if not ok]
    if manque:
        log.error("serveur « %s », salon #%s : permissions manquantes : %s",
                  serveur.name, canal.name, ", ".join(manque))
        return
    log.info("prêt : serveur « %s », salon #%s, permissions OK", serveur.name, canal.name)
    if ANNONCE and not os.path.exists(MARQUEUR):
        await canal.send("Qwen est en ligne : mentionnez-moi pour poser une question sur la plateforme.")
        with open(MARQUEUR, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%dT%H:%M:%S\n"))
        log.info("annonce postée dans #%s", canal.name)


async def vise_le_bot(message):
    if client.user in message.mentions:
        return True
    ref = message.reference
    if ref is None or ref.message_id is None:
        return False
    cible = ref.resolved
    if not isinstance(cible, discord.Message):
        try:
            cible = await message.channel.fetch_message(ref.message_id)
        except discord.HTTPException:
            return False
    return cible.author.id == client.user.id


async def demander(question, utilisateur):
    """(texte de réponse, statut court pour le journal, outils, durée)."""
    try:
        async with httpx.AsyncClient(timeout=DELAI_API) as http:
            r = await http.post(API_URL, json={"question": question, "user": utilisateur},
                                headers={"Authorization": f"Bearer {lire(API_TOKEN_FILE)}"})
    except httpx.TimeoutException:
        return ("La réponse prend trop de temps (GPU indisponible ou très chargé) : "
                "réessaie dans quelques minutes.", "delai", [], DELAI_API)
    except httpx.HTTPError:
        return ("L'assistant est injoignable pour le moment : réessaie plus tard.", "injoignable", [], 0.0)
    if r.status_code == 200:
        d = r.json()
        outils = d.get("tools") or []
        modele = (d.get("model") or "?").split(" (")[0]
        pied = f"-# {modele} · {', '.join(outils) or 'sans outil'} · {d.get('duration_s', 0):.0f} s"
        if d.get("mode") == "documentation":
            pied += " · mode dégradé (documentation seule)"
        return f"{d.get('answer', '').strip()}\n{pied}", "ok", outils, float(d.get("duration_s", 0))
    messages = {
        429: "Je reçois trop de questions en ce moment : réessaie dans une minute.",
        503: "Je suis occupé avec une autre question : réessaie dans une minute.",
        504: "La réponse prend trop de temps (GPU indisponible ?) : réessaie dans quelques minutes.",
        401: "Je suis mal configuré (accès à l'assistant refusé) : préviens l'équipe infra.",
        422: "Question refusée : 1000 caractères au plus.",
    }
    return (messages.get(r.status_code, "L'assistant est indisponible pour le moment."),
            f"http_{r.status_code}", [], 0.0)


@client.event
async def on_message(message):
    if message.author.bot or message.guild is None or message.guild.id != GUILD_ID:
        return
    if not salon_autorise(message.channel) or not await vise_le_bot(message):
        return
    auteur = message.author
    nom = auteur.display_name
    question = re.sub(rf"<@!?{client.user.id}>", "", message.content or "").strip()
    if not question:
        await message.reply("Pose ta question en me mentionnant, par exemple : "
                            f"{client.user.mention} quelles alertes ces 2 dernières heures ?")
        return
    if len(question) > MAX_QUESTION:
        await message.reply(f"Ta question est trop longue ({len(question)} caractères, "
                            f"{MAX_QUESTION} au plus) : peux-tu la raccourcir ?")
        return
    if auteur.id in en_cours:
        await message.reply("Je traite encore ta question précédente, un instant.")
        return
    attente = PAUSE_UTILISATEUR - (time.monotonic() - derniere.get(auteur.id, 0))
    if attente > 0:
        await message.reply(f"Laisse-moi {attente:.0f} s avant la question suivante.")
        return

    en_cours.add(auteur.id)
    debut = time.monotonic()
    try:
        async with message.channel.typing():
            texte, statut, outils, duree = await demander(question, nom)
        premier = True
        for bout in morceaux(texte):
            if premier:
                await message.reply(bout)
                premier = False
            else:
                await message.channel.send(bout)
    except discord.HTTPException as e:
        statut = f"discord_{e.status}"
        outils, duree = [], 0.0
    finally:
        en_cours.discard(auteur.id)
        derniere[auteur.id] = time.monotonic()
    log.info("question utilisateur=%s statut=%s outils=%s duree_api=%.1fs total=%.1fs",
             re.sub(r"[^\w.#-]", "_", nom)[:40], statut, ",".join(outils) or "-", duree,
             time.monotonic() - debut)


def main():
    jeton = lire(DISCORD_TOKEN_FILE)
    try:
        client.run(jeton, log_handler=None)
    except discord.LoginFailure:
        log.error("connexion refusée par Discord : jeton du bot invalide (secret/infra/discord-bot)")
        sys.exit(1)
    except discord.PrivilegedIntentsRequired:
        log.error("intent privilégié demandé mais non activé dans le portail développeur")
        sys.exit(1)


if __name__ == "__main__":
    main()
