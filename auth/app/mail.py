"""
Envoi des e-mails transactionnels.

En démonstration, le SMTP est une boîte locale (Mailpit dans docker-compose) :
l'e-mail part réellement et se consulte sur http://localhost:8025, sans Internet.
En production, les mêmes variables pointeraient vers un vrai relais.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

SUBJECT = "Réinitialisez votre mot de passe YAZNOW"

BODY = """\
Bonjour {name},

Vous avez demandé à réinitialiser votre mot de passe YAZNOW.
Ouvrez ce lien dans les {minutes} prochaines minutes pour en choisir un nouveau :

    {link}

Si vous n'êtes pas à l'origine de cette demande, ignorez simplement ce message :
votre mot de passe actuel reste valable.

— YAZNOW, plateforme de démonstration. Aucun achat réel.
"""


def send_reset(to: str, name: str, link: str, minutes: int) -> None:
    """Lève smtplib.SMTPException ou OSError si l'envoi échoue : l'appelant décide quoi tracer."""
    msg = EmailMessage()
    msg["From"] = os.getenv("MAIL_FROM", "YAZNOW <no-reply@yaznow.local>")
    msg["To"] = to
    msg["Subject"] = SUBJECT
    msg.set_content(BODY.format(name=name or to, link=link, minutes=minutes))

    host = os.getenv("SMTP_HOST", "localhost")
    port = int(os.getenv("SMTP_PORT", "1025"))
    with smtplib.SMTP(host, port, timeout=5) as smtp:
        smtp.send_message(msg)
