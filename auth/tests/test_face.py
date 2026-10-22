"""
Reconnaissance faciale du back-office (consigne additionnelle 1), avec un moteur simulé :
une « image » b"face:A" donne toujours le même visage A, b"face:B" un autre visage.

    cd auth && python -m pytest
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import face, main

OPERATOR = ("operateur", "op-secret-123")  # compte de service : la sonde
HUMAN = ("gregoire", "gregoire-secret-1")  # opérateur nominatif : passe la caméra
CLIENT = ("alice", "alice-secret-1")
INTERNAL = ("127.0.0.1", 50000)
INTERNET = ("203.0.113.5", 50000)

FACES = {b"face:A": np.eye(128, dtype=np.float32)[0], b"face:B": np.eye(128, dtype=np.float32)[1]}


class FakeEngine:
    """b"face:A" : visage A de face ; b"face:A@0.3" : le même, tête tournée (orientation 0,3)."""

    def analyze(self, data: bytes):
        name, _, angle = data.partition(b"@")
        vector = FACES.get(name)
        if vector is None:
            return None, "aucun visage", 0.0
        return vector, "ok", float(angle or 0)

    def embed(self, data: bytes):
        vector, why, _ = self.analyze(data)
        return vector, why

    def locate(self, data: bytes):
        vector, _, angle = self.analyze(data)
        if vector is None:
            return {"faces": 0}
        return {"faces": 1, "box": [0.3, 0.2, 0.4, 0.55], "points": [[0.4, 0.4]] * 5, "yaw": angle}


class BrokenEngine:
    def embed(self, data: bytes):
        raise face.EngineUnavailable("modèles absents")


@pytest.fixture
def env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JWT_PRIVATE_KEY_FILE", raising=False)
    monkeypatch.setenv("AUTH_SEED_USERS", "operateur:operator, gregoire:operator, alice:client")
    monkeypatch.setenv("AUTH_PASSWORD_OPERATEUR", OPERATOR[1])
    monkeypatch.setenv("AUTH_PASSWORD_GREGOIRE", HUMAN[1])
    monkeypatch.setenv("AUTH_PASSWORD_ALICE", CLIENT[1])
    monkeypatch.setattr(main, "throttle", main.Throttle())
    monkeypatch.setattr(main.state, "gate", face.Gate())
    monkeypatch.setattr(main.state, "engine", FakeEngine())
    return tmp_path


def make_client(address: tuple[str, int]) -> TestClient:
    return TestClient(main.app, client=address)


@pytest.fixture
def admin(env) -> Iterator[TestClient]:
    """Session du compte de service, depuis le réseau interne : il enrôle les premiers visages."""
    with make_client(INTERNAL) as c:
        res = c.post("/auth/login", json={"username": OPERATOR[0], "password": OPERATOR[1]})
        assert res.status_code == 200, res.text
        yield c


def frames(*images: bytes):
    return [("frames", (f"{i}.jpg", data, "image/jpeg")) for i, data in enumerate(images)]


def enroll(admin: TestClient, username: str = HUMAN[0], image: bytes = b"face:A") -> None:
    res = admin.post(f"/auth/admin/accounts/{username}/face", files=frames(image, image, image))
    assert res.status_code == 200, res.text


def identify(c: TestClient, username: str = HUMAN[0]):
    return c.post("/auth/identify", json={"username": username})


def recognize(c: TestClient, username: str = HUMAN[0], image: bytes = b"face:A") -> str:
    res = identify(c, username)
    assert res.status_code == 200, res.text
    assert res.json()["step"] == "face"
    challenge = res.json()["challenge"]
    res = c.post(f"/auth/identify/{challenge}/frames", files=frames(image, image, image))
    assert res.json()["status"] == "recognized", res.text
    return challenge


# ---------------------------------------------------------------- parcours


def test_un_client_ou_un_inconnu_passe_directement_au_mot_de_passe(env) -> None:
    with make_client(INTERNET) as c:
        assert identify(c, CLIENT[0]).json() == {"step": "password"}
        assert identify(c, "personne").json() == {"step": "password"}
        assert c.post("/auth/login", json={"username": CLIENT[0], "password": CLIENT[1]}).status_code == 200


def test_operateur_nominatif_visage_reconnu_puis_mot_de_passe(admin: TestClient) -> None:
    enroll(admin)
    with make_client(INTERNET) as c:
        challenge = recognize(c)
        res = c.post("/auth/login", json={"username": HUMAN[0], "password": HUMAN[1], "challenge": challenge})
        assert res.status_code == 200, res.text
        assert res.json()["user"]["role"] == "operator"
        assert "rp_session" in res.cookies
        # L'identification ne sert qu'une fois.
        again = c.post("/auth/login", json={"username": HUMAN[0], "password": HUMAN[1], "challenge": challenge})
        assert again.status_code == 403
    kinds = [e["kind"] for e in admin.get("/auth/admin/events").json()["events"]]
    assert {"face_enrolled", "face_ok", "login_ok"} <= set(kinds)


def test_sans_visage_reconnu_le_mot_de_passe_n_est_meme_pas_verifie(admin: TestClient) -> None:
    enroll(admin)
    with make_client(INTERNET) as c:
        res = c.post("/auth/login", json={"username": HUMAN[0], "password": HUMAN[1]})
        assert res.status_code == 403
        assert res.headers["X-Auth-Restart"] == "identify"
        # Pas de contournement par le jeton des scripts.
        assert c.post("/auth/token", json={"username": HUMAN[0], "password": HUMAN[1]}).status_code == 403


def test_compte_sans_visage_enrole(env) -> None:
    with make_client(INTERNET) as c:
        res = identify(c)
        assert res.status_code == 409
        assert "enrôler" in res.json()["detail"]


def test_visage_refuse_30_s_puis_un_seul_nouvel_essai_puis_5_min(admin: TestClient, monkeypatch) -> None:
    enroll(admin)
    with make_client(INTERNET) as c:
        challenge = identify(c).json()["challenge"]
        first = c.post(f"/auth/identify/{challenge}/frames", files=frames(b"face:B", b"face:B")).json()
        assert first["status"] == "rejected"
        assert first["retryAfter"] == face.RETRY_SECONDS

        # Pendant les 30 s : la caméra ne se rallume pas.
        res = identify(c)
        assert res.status_code == 429
        assert res.headers["X-Auth-Lock"] == "retry"

        # Les 30 s écoulées (simulées), le nouvel essai rate aussi : bloqué 5 minutes.
        main.state.gate._accounts[HUMAN[0]].retry_until = 0.0
        challenge = identify(c).json()["challenge"]
        second = c.post(f"/auth/identify/{challenge}/frames", files=frames(b"face:B", b"face:B")).json()
        assert second == {"status": "locked", "retryAfter": face.LOCK_SECONDS, "reason": "visage différent du gabarit"}
        res = identify(c)
        assert res.status_code == 429
        assert res.headers["X-Auth-Lock"] == "locked"

        # Les 5 minutes écoulées : de nouveau un essai, et un seul nouvel essai.
        main.state.gate._accounts[HUMAN[0]].locked_until = 0.0
        recognize(c)


def test_aucun_visage_dans_l_image_compte_comme_un_refus(admin: TestClient) -> None:
    enroll(admin)
    with make_client(INTERNET) as c:
        challenge = identify(c).json()["challenge"]
        res = c.post(f"/auth/identify/{challenge}/frames", files=frames(b"mur", b"mur")).json()
        assert res["status"] == "rejected"
        assert res["reason"] == "aucun visage"


def test_mauvais_mot_de_passe_recommence_l_identification_et_compte(admin: TestClient) -> None:
    enroll(admin)
    with make_client(INTERNET) as c:
        challenge = recognize(c)
        res = c.post("/auth/login", json={"username": HUMAN[0], "password": "faux-mot-de-passe", "challenge": challenge})
        assert res.status_code == 401
        assert res.headers["X-Auth-Restart"] == "identify"

        challenge = recognize(c)
        res = c.post("/auth/login", json={"username": HUMAN[0], "password": "faux-mot-de-passe", "challenge": challenge})
        assert res.status_code == 401
        assert "bloqué" in res.json()["detail"]
        assert identify(c).status_code == 429


def test_identification_liee_a_l_adresse_qui_l_a_ouverte(admin: TestClient) -> None:
    enroll(admin)
    with make_client(INTERNET) as c:
        challenge = identify(c).json()["challenge"]
    with make_client(("198.51.100.7", 50000)) as other:
        res = other.post(f"/auth/identify/{challenge}/frames", files=frames(b"face:A", b"face:A"))
        assert res.status_code == 410


def test_compte_de_service_dispense_seulement_depuis_le_reseau_interne(admin: TestClient) -> None:
    assert identify(admin, OPERATOR[0]).json() == {"step": "password"}
    with make_client(INTERNET) as c:
        assert identify(c, OPERATOR[0]).status_code == 409  # depuis Internet : caméra, et aucun visage enrôlé
        assert c.post("/auth/login", json={"username": OPERATOR[0], "password": OPERATOR[1]}).status_code == 403


def test_reconnaissance_indisponible(admin: TestClient, monkeypatch) -> None:
    enroll(admin)
    monkeypatch.setattr(main.state, "engine", BrokenEngine())
    with make_client(INTERNET) as c:
        challenge = identify(c).json()["challenge"]
        res = c.post(f"/auth/identify/{challenge}/frames", files=frames(b"face:A", b"face:A"))
        assert res.status_code == 503


def probe(c: TestClient, path: str, image: bytes):
    return c.post(path, files=[("frame", ("probe.jpg", image, "image/jpeg"))])


def test_guidage_pendant_la_capture_sans_rien_juger(admin: TestClient) -> None:
    enroll(admin)
    with make_client(INTERNET) as c:
        challenge = identify(c).json()["challenge"]
        res = probe(c, f"/auth/identify/{challenge}/probe", b"face:A@0.05")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["faces"] == 1 and body["yaw"] == 0.05
        assert body["frontMaxYaw"] == face.FRONT_MAX_YAW and body["sideMinYaw"] == face.SIDE_MIN_YAW
        assert probe(c, f"/auth/identify/{challenge}/probe", b"mur").json()["faces"] == 0
        # Le guidage ne compte aucun échec : l'identification attend toujours ses images.
        res = c.post(f"/auth/identify/{challenge}/frames", files=frames(b"face:A", b"face:A"))
        assert res.json()["status"] == "recognized"
        # Une fois jugée, l'identification ne se guide plus.
        assert probe(c, f"/auth/identify/{challenge}/probe", b"face:A").status_code == 410
    with make_client(("198.51.100.7", 50000)) as other:
        assert probe(other, f"/auth/identify/{identify(other).json()['challenge']}/probe", b"face:A").status_code == 200
        assert probe(other, "/auth/identify/inconnu/probe", b"face:A").status_code == 410


def test_guidage_borne_par_identification(admin: TestClient, monkeypatch) -> None:
    enroll(admin)
    monkeypatch.setattr(face, "MAX_PROBES", 2)
    with make_client(INTERNET) as c:
        challenge = identify(c).json()["challenge"]
        assert probe(c, f"/auth/identify/{challenge}/probe", b"face:A").status_code == 200
        assert probe(c, f"/auth/identify/{challenge}/probe", b"face:A").status_code == 200
        res = probe(c, f"/auth/identify/{challenge}/probe", b"face:A")
        assert res.status_code == 410
        assert res.headers["X-Auth-Restart"] == "identify"


def test_guidage_du_scan_reserve_au_back_office(admin: TestClient) -> None:
    res = probe(admin, "/auth/admin/face/probe", b"face:A@0.3")
    assert res.status_code == 200
    assert res.json()["yaw"] == 0.3
    with make_client(INTERNET) as c:
        assert probe(c, "/auth/admin/face/probe", b"face:A").status_code == 401


def test_back_office_ne_se_reinitialise_pas_par_e_mail(admin: TestClient) -> None:
    signer = main.state.signer
    token = signer.issue_reset(HUMAN[0], 15, main.state.store.password_stamp(HUMAN[0]) or "")
    res = admin.post("/auth/reset", json={"token": token, "password": "nouveau-secret-1"})
    assert res.status_code == 403


# ---------------------------------------------------------------- habilitations


def test_habilitations_reservees_au_back_office(env) -> None:
    with make_client(INTERNET) as c:
        assert c.get("/auth/admin/accounts").status_code == 401
        c.post("/auth/login", json={"username": CLIENT[0], "password": CLIENT[1]})
        assert c.get("/auth/admin/accounts").status_code == 403


def test_gestion_complete_des_habilitations(admin: TestClient) -> None:
    res = admin.post("/auth/admin/accounts", json={
        "username": "remi", "password": "remi-secret-1", "role": "operator", "firstName": "Rémi", "lastName": "Reze",
    })
    assert res.status_code == 201, res.text
    enroll(admin, "remi")

    accounts = {a["username"]: a for a in admin.get("/auth/admin/accounts").json()["accounts"]}
    assert accounts["remi"]["faces"] == 1
    assert accounts["remi"]["faceRequired"] is True
    assert accounts["operateur"]["serviceAccount"] is True
    assert accounts["operateur"]["self"] is True
    assert accounts["alice"]["faceRequired"] is False

    assert admin.post("/auth/admin/accounts/remi", json={"disabled": True}).status_code == 200
    assert admin.post("/auth/admin/accounts/remi", json={"disabled": False, "role": "client"}).status_code == 200
    assert admin.post("/auth/admin/accounts/remi/password", json={"password": "autre-secret-1"}).status_code == 200
    assert admin.post("/auth/admin/accounts/remi/face/delete").json() == {"deleted": 1}

    # On ne touche pas à ses propres habilitations, ni au compte de service de la configuration.
    assert admin.post("/auth/admin/accounts/operateur", json={"disabled": True}).status_code == 409
    assert admin.post("/auth/admin/accounts/gregoire", json={"role": "pirate"}).status_code == 422
    assert admin.post("/auth/admin/accounts/inconnu", json={"disabled": True}).status_code == 404

    kinds = {e["kind"] for e in admin.get("/auth/admin/events").json()["events"]}
    assert {"account_created", "account_updated", "password_set", "face_deleted"} <= kinds


def test_enrolement_refuse_sans_visage_net(admin: TestClient) -> None:
    res = admin.post(f"/auth/admin/accounts/{HUMAN[0]}/face", files=frames(b"face:A", b"mur", b"mur"))
    assert res.status_code == 422
    assert "1 image" in res.json()["detail"]


# ---------------------------------------------------------------- scan sous trois angles


def scan(admin: TestClient, username: str = HUMAN[0], front=b"face:A", left=b"face:A@0.3", right=b"face:A@-0.3"):
    files = [
        *[("face", (f"f{i}.jpg", front, "image/jpeg")) for i in range(3)],
        *[("gauche", (f"g{i}.jpg", left, "image/jpeg")) for i in range(3)],
        *[("droite", (f"d{i}.jpg", right, "image/jpeg")) for i in range(3)],
    ]
    return admin.post(f"/auth/admin/accounts/{username}/face/scan", files=files)


def test_scan_sous_trois_angles_remplace_les_gabarits(admin: TestClient) -> None:
    enroll(admin)
    res = scan(admin)
    assert res.status_code == 200, res.text
    assert res.json() == {"faces": 3, "angles": {"face": 0.0, "gauche": 0.3, "droite": -0.3}}
    accounts = {a["username"]: a for a in admin.get("/auth/admin/accounts").json()["accounts"]}
    assert accounts[HUMAN[0]]["faces"] == 3  # l'ancien gabarit a été remplacé
    with make_client(INTERNET) as c:
        recognize(c)  # à la connexion, un regard de face suffit


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"front": b"face:A@0.3"}, "Prise de face"),
        ({"left": b"face:A@0.05"}, "pas assez tournée"),
        ({"right": b"face:A@0.3"}, "même côté"),
        ({"right": b"face:B@-0.3"}, "même personne"),
        ({"left": b"mur"}, "visage trouvé sur 0"),
    ],
)
def test_scan_refuse_sans_rien_enregistrer(admin: TestClient, change: dict, message: str) -> None:
    res = scan(admin, **change)
    assert res.status_code == 422
    assert message in res.json()["detail"]
    accounts = {a["username"]: a for a in admin.get("/auth/admin/accounts").json()["accounts"]}
    assert accounts[HUMAN[0]]["faces"] == 0


def test_orientation_lue_sur_les_reperes() -> None:
    # Yeux à x=100 et x=160 : de face, le nez est au milieu ; décalé de 15 px, orientation 0,25.
    detection = np.zeros(15, dtype=np.float32)
    detection[4], detection[6], detection[8] = 100, 160, 130
    assert face.yaw(detection) == 0.0
    detection[8] = 145
    assert face.yaw(detection) == 0.25


# ---------------------------------------------------------------- moteur et comparaison


def test_comparaison_et_gabarit() -> None:
    a, b = FACES[b"face:A"], FACES[b"face:B"]
    assert face.match([a, a], [a]) == (True, 1.0)
    assert face.match([b, b], [a])[0] is False
    assert face.match([], [a]) == (False, 0.0)
    template = face.template_from([a, a, a])
    assert np.isclose(np.linalg.norm(template), 1.0)


@pytest.mark.skipif(
    not os.path.isfile(os.path.join(face.MODELS_DIR, face.RECOGNIZER_FILE)),
    reason="modèles absents (python scripts/fetch_models.py)",
)
def test_moteur_reel_sur_une_image_sans_visage() -> None:
    import cv2

    ok, jpeg = cv2.imencode(".jpg", np.full((240, 320, 3), 127, np.uint8))
    assert ok
    engine = face.Engine()
    vector, why = engine.embed(jpeg.tobytes())
    assert vector is None
    assert why == "aucun visage"
    assert engine.locate(jpeg.tobytes()) == {"faces": 0}
