"""
Service d'authentification de bout en bout, base SQLite et clé dans un dossier temporaire.

    cd auth && python -m pytest
"""

from __future__ import annotations

from collections.abc import Iterator

import jwt
import pytest
from fastapi.testclient import TestClient

from app import main, tokens

OPERATOR = ("operateur", "op-secret-123")
CLIENT = ("alice", "alice-secret-1")


@pytest.fixture
def env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JWT_PRIVATE_KEY_FILE", raising=False)
    monkeypatch.setenv("AUTH_SEED_USERS", "operateur:operator, alice:client, court:client")
    monkeypatch.setenv("AUTH_PASSWORD_OPERATEUR", OPERATOR[1])
    monkeypatch.setenv("AUTH_PASSWORD_ALICE", CLIENT[1])
    monkeypatch.setenv("AUTH_PASSWORD_COURT", "123")
    monkeypatch.setattr(main, "throttle", main.Throttle())
    return tmp_path


@pytest.fixture
def client(env) -> Iterator[TestClient]:
    with TestClient(main.app) as c:
        yield c


def login(client: TestClient, username: str, password: str):
    return client.post("/auth/login", json={"username": username, "password": password})


def bearer(client: TestClient, username: str, password: str) -> str:
    return client.post("/auth/token", json={"username": username, "password": password}).json()["token"]


def test_connexion_et_jeton_verifiable_avec_la_cle_publique(client: TestClient) -> None:
    res = client.post("/auth/token", json={"username": CLIENT[0], "password": CLIENT[1]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["user"] == {"username": "alice", "role": "client"}

    # Ce que fera payment-api : vérifier avec la seule clé publique publiée.
    jwk = client.get("/auth/jwks.json").json()["keys"][0]
    assert "d" not in jwk  # jamais la partie privée
    key = jwt.PyJWK(jwk).key
    claims = jwt.decode(body["token"], key, algorithms=["EdDSA"], audience=tokens.AUDIENCE, issuer=tokens.ISSUER)
    assert claims["sub"] == "alice"
    assert claims["role"] == "client"
    assert claims["exp"] == body["expiresAt"]
    assert jwt.get_unverified_header(body["token"])["kid"] == jwk["kid"]


def test_identifiant_insensible_a_la_casse(client: TestClient) -> None:
    assert login(client, "  Operateur ", OPERATOR[1]).json()["user"]["role"] == "operator"


def test_meme_reponse_pour_mauvais_mot_de_passe_et_compte_inconnu(client: TestClient) -> None:
    wrong = login(client, "alice", "pas-le-bon")
    unknown = login(client, "personne", "pas-le-bon")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_mot_de_passe_trop_court_jamais_seede(client: TestClient) -> None:
    assert login(client, "court", "123").status_code == 401


def test_blocage_apres_cinq_echecs_meme_avec_le_bon_mot_de_passe(client: TestClient) -> None:
    for _ in range(main.MAX_FAILURES):
        assert login(client, "alice", "mauvais").status_code == 401
    res = login(client, *CLIENT)
    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) > 0
    # L'opérateur n'est pas enfermé dehors par les essais visant alice.
    assert login(client, *OPERATOR).status_code == 200


def test_plafond_par_adresse_quel_que_soit_le_compte(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "MAX_FAILURES_PER_IP", 3)
    for name in ("a1", "a2", "a3"):
        assert login(client, name, "mauvais").status_code == 401
    assert login(client, *OPERATOR).status_code == 429


def test_une_connexion_reussie_remet_le_compteur_du_couple_a_zero(client: TestClient) -> None:
    for _ in range(main.MAX_FAILURES - 1):
        login(client, "alice", "mauvais")
    assert login(client, *CLIENT).status_code == 200
    for _ in range(main.MAX_FAILURES - 1):
        login(client, "alice", "mauvais")
    assert login(client, *CLIENT).status_code == 200


def test_me(client: TestClient) -> None:
    token = bearer(client, *OPERATOR)
    res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.json()["username"] == "operateur"
    assert res.json()["role"] == "operator"

    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token[:-4]}AAAA"}).status_code == 401


def test_jeton_expire_refuse(client: TestClient) -> None:
    signer = tokens.Signer(main.state.signer.key, ttl_seconds=-10)
    token, _ = signer.issue("alice", "client")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_jeton_hs256_forge_refuse(client: TestClient) -> None:
    jwk = client.get("/auth/jwks.json").json()["keys"][0]
    forged = jwt.encode(
        {"iss": tokens.ISSUER, "aud": tokens.AUDIENCE, "sub": "pirate", "role": "operator", "iat": 0, "exp": 2**31},
        jwk["x"],
        algorithm="HS256",
        headers={"kid": jwk["kid"]},
    )
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_cle_conservee_apres_redemarrage(env) -> None:
    with TestClient(main.app) as c:
        token = bearer(c, *CLIENT)
        kid = c.get("/auth/jwks.json").json()["keys"][0]["kid"]
    with TestClient(main.app) as c:
        assert c.get("/auth/jwks.json").json()["keys"][0]["kid"] == kid
        assert c.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_metriques_et_sante(client: TestClient) -> None:
    login(client, "alice", "mauvais")
    text = client.get("/metrics").text
    assert 'auth_login_total{result="failure"}' in text
    assert 'auth_login_total{result="locked"}' in text
    assert client.get("/health").json() == {"ok": True, "db": True}


def test_inscription_cree_un_client_et_connecte(client: TestClient) -> None:
    r = client.post("/auth/register", json={"username": "Nadia", "password": "nadia-secret-1"})
    assert r.status_code == 201
    body = r.json()
    assert body["user"] == {"username": "nadia", "role": "client"}
    # Connecté d'emblée par le cookie httpOnly, comme après /auth/login : aucun jeton lisible.
    assert "token" not in body
    assert "httponly" in r.headers["set-cookie"].lower()
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "nadia"
    client.cookies.clear()
    # Et le compte fonctionne ensuite comme n'importe quel autre.
    assert client.post("/auth/login", json={"username": "nadia", "password": "nadia-secret-1"}).status_code == 200


def test_inscription_refuse_identifiant_deja_pris_sans_ecraser(client: TestClient) -> None:
    r = client.post("/auth/register", json={"username": "alice", "password": "autre-secret-9"})
    assert r.status_code == 409
    # Le mot de passe d'origine n'a pas bougé.
    assert client.post("/auth/login", json={"username": "alice", "password": CLIENT[1]}).status_code == 200


def test_inscription_mot_de_passe_trop_court(client: TestClient) -> None:
    r = client.post("/auth/register", json={"username": "paul", "password": "court"})
    assert r.status_code == 422


def test_connexion_navigateur_pose_un_cookie_httponly_sans_jeton_lisible(client: TestClient) -> None:
    res = login(client, *CLIENT)
    assert res.status_code == 200
    assert "token" not in res.json()  # rien que le JavaScript puisse voler
    cookie = res.headers["set-cookie"].lower()
    assert cookie.startswith("rp_session=")
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie


def test_session_par_cookie(client: TestClient) -> None:
    login(client, *OPERATOR)  # le TestClient garde le cookie, comme un navigateur
    assert client.get("/auth/me").json()["username"] == "operateur"


def test_deconnexion_efface_le_cookie(client: TestClient) -> None:
    login(client, *CLIENT)
    res = client.post("/auth/logout")
    assert res.status_code == 204
    assert 'rp_session=""' in res.headers["set-cookie"] or "max-age=0" in res.headers["set-cookie"].lower()
    client.cookies.clear()
    assert client.get("/auth/me").status_code == 401


def test_verify_pour_le_relais(client: TestClient) -> None:
    assert client.get("/auth/verify", params={"role": "operator"}).status_code == 401

    login(client, *CLIENT)
    assert client.get("/auth/verify", params={"role": "operator"}).status_code == 403
    assert client.get("/auth/verify").status_code == 200
    client.cookies.clear()

    token = bearer(client, *OPERATOR)
    res = client.get("/auth/verify", params={"role": "operator"}, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200


def test_jeton_pour_scripts_soumis_au_meme_freinage(client: TestClient) -> None:
    for _ in range(main.MAX_FAILURES):
        assert client.post("/auth/token", json={"username": "alice", "password": "mauvais"}).status_code == 401
    assert login(client, *CLIENT).status_code == 429


def test_documentation_sous_le_prefixe_auth(client: TestClient) -> None:
    assert client.get("/auth/docs").status_code == 200
    assert "/auth/login" in client.get("/auth/openapi.json").json()["paths"]
