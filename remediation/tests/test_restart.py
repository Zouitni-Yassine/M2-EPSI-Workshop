"""Tests du chemin d'action du moteur : proxy Docker (compose) et passerelle SSH (Swarm).

Aucun appel réseau : requests.post et subprocess.run sont remplacés par des doublures.
Lancement : `pip install -r requirements.txt pytest && python -m pytest -q tests` depuis remediation/.
"""

import json
import os
import stat
import subprocess
import time

import pytest

from app import main

TARGET = "paiement_payment-api"
GATEWAYS = ["10.30.1.211", "10.30.1.212", "10.30.1.213"]


def completed(code, payload=None, stderr=""):
    stdout = json.dumps(payload) + "\n" if payload is not None else ""
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


class FakeRun:
    """Doublure de subprocess.run : rejoue des réponses dans l'ordre et garde les appels."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    main._state["events"].clear()
    main._state["status"] = "idle"
    main._state["cooldownUntil"] = 0.0
    monkeypatch.setattr(main, "_key_path", None)
    yield


@pytest.fixture
def ssh_mode(monkeypatch, tmp_path):
    key = tmp_path / "remediation_ssh_key"
    key.write_text("-----FAUSSE CLE DE TEST-----\n")
    os.chmod(key, 0o444)  # comme un secret Swarm lisible par tous
    monkeypatch.setattr(main, "MODE", "ssh")
    monkeypatch.setattr(main, "TARGETS", [TARGET])
    monkeypatch.setattr(main, "GATEWAYS", GATEWAYS)
    monkeypatch.setattr(main, "SSH_KEY_FILE", str(key))
    monkeypatch.setattr(main, "KNOWN_HOSTS_FILE", "/run/configs/remediation_known_hosts")
    monkeypatch.setattr(main, "SSH_USER", "remediation")
    monkeypatch.setattr(main.tempfile, "tempdir", str(tmp_path))  # copie de la clé hors de /tmp
    return key


def no_subprocess(*args, **kwargs):
    raise AssertionError("aucun appel ssh n'était attendu")


def texts():
    return [e["text"] for e in main._state["events"]]


# --- mode docker : comportement d'origine ---------------------------------------------------

def test_docker_mode_inchange(monkeypatch):
    calls = []

    class Res:
        status_code = 204
        text = ""

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Res()

    monkeypatch.setattr(main, "MODE", "docker")
    monkeypatch.setattr(main, "TARGETS", ["payment-api"])
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main.subprocess, "run", no_subprocess)

    detail = main.restart("payment-api")

    assert calls == [(f"{main.DOCKER_URL}/containers/payment-api/restart", {"params": {"t": 5}, "timeout": 30})]
    assert detail == "redémarré via le proxy Docker — droits limités au redémarrage"


def test_docker_mode_erreur_du_proxy(monkeypatch):
    class Res:
        status_code = 403
        text = "<html><h1>403 Forbidden</h1></html>"

    monkeypatch.setattr(main, "MODE", "docker")
    monkeypatch.setattr(main, "TARGETS", ["payment-api"])
    monkeypatch.setattr(main.requests, "post", lambda url, **kw: Res())
    with pytest.raises(RuntimeError, match="Docker a répondu 403 : 403 Forbidden"):
        main.restart("payment-api")


# --- mode ssh ----------------------------------------------------------------------------------

def test_ssh_succes(monkeypatch, ssh_mode):
    run = FakeRun(completed(0, {"ok": True, "action": "restart", "service": TARGET, "duration_s": 12.3,
                                "replicas_desired": 2, "replicas_running": 2}))
    monkeypatch.setattr(main.subprocess, "run", run)

    detail = main.restart(TARGET)

    assert "passerelle 10.30.1.211 en 12.3 s" in detail and "2/2 réplicas" in detail
    assert len(run.calls) == 1
    argv, kwargs = run.calls[0]
    assert isinstance(argv, list) and "shell" not in kwargs  # jamais de shell
    assert argv[:2] == ["ssh", "-T"]
    for opt in ("BatchMode=yes", "StrictHostKeyChecking=yes", "ConnectTimeout=5",
                "UserKnownHostsFile=/run/configs/remediation_known_hosts"):
        assert opt in argv
    assert argv[-2:] == ["remediation@10.30.1.211", f"restart {TARGET}"]
    key = argv[argv.index("-i") + 1]
    assert key != str(ssh_mode)  # la copie, pas le secret monté
    with open(key) as f:
        assert f.read() == "-----FAUSSE CLE DE TEST-----\n"
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(key).st_mode) == 0o600
    assert kwargs["timeout"] == main.SSH_TIMEOUT


def test_ssh_premiere_passerelle_injoignable(monkeypatch, ssh_mode):
    run = FakeRun(
        completed(255, stderr="ssh: connect to host 10.30.1.211 port 22: Connection timed out"),
        completed(0, {"ok": True, "action": "restart", "service": TARGET, "duration_s": 8.0}),
    )
    monkeypatch.setattr(main.subprocess, "run", run)

    detail = main.restart(TARGET)

    assert [c[0][-2] for c in run.calls] == ["remediation@10.30.1.211", "remediation@10.30.1.212"]
    assert "passerelle 10.30.1.212" in detail
    assert any("10.30.1.211 injoignable" in t for t in texts())


def test_ssh_aucune_passerelle_joignable(monkeypatch, ssh_mode):
    run = FakeRun(*[completed(255, stderr="Connection refused")] * 3)
    monkeypatch.setattr(main.subprocess, "run", run)
    with pytest.raises(ConnectionError, match="aucune passerelle joignable"):
        main.restart(TARGET)
    assert len(run.calls) == 3


def test_ssh_delai_depasse_pas_de_seconde_passerelle(monkeypatch, ssh_mode):
    run = FakeRun(subprocess.TimeoutExpired(cmd="ssh", timeout=main.SSH_TIMEOUT))
    monkeypatch.setattr(main.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="n'a pas répondu"):
        main.restart(TARGET)
    assert len(run.calls) == 1  # l'action est peut-être en cours : on ne la double pas


def test_ssh_refus_politique(monkeypatch, ssh_mode):
    run = FakeRun(completed(3, {"ok": False, "error": "remédiation désactivée (interrupteur d'arrêt)"}))
    monkeypatch.setattr(main.subprocess, "run", run)
    with pytest.raises(RuntimeError, match=r"code 3 \(refusé par la politique\)"):
        main.restart(TARGET)
    assert len(run.calls) == 1  # une réponse de la passerelle est définitive


def test_ssh_code_4_reessaye_au_prochain_cycle(monkeypatch, ssh_mode):
    run = FakeRun(completed(4, {"ok": False, "error": "délai minimal entre deux actions sur ce service",
                                "service": TARGET, "retry_in": 37}))
    monkeypatch.setattr(main.subprocess, "run", run)

    with pytest.raises(main.RateLimited) as err:
        main.restart(TARGET)
    assert err.value.retry_in == 37


def test_ssh_code_4_dans_remediate(monkeypatch, ssh_mode):
    run = FakeRun(completed(4, {"ok": False, "error": "délai minimal", "retry_in": 37}))
    monkeypatch.setattr(main.subprocess, "run", run)
    monkeypatch.setattr(main, "service_ok", lambda: pytest.fail("pas de vérification après un report"))

    before = time.time()
    main.remediate(0.9, 0.5)

    assert main._state["status"] == "idle"
    assert before + 36 <= main._state["cooldownUntil"] <= time.time() + 38  # temporisation, pas de boucle
    assert any(t.startswith("Action différée") and "37 s" in t for t in texts())
    assert not any(t.startswith("Échec") for t in texts())


def test_ssh_cible_invalide_refusee_sans_ssh(monkeypatch, ssh_mode):
    bad = "paiement_api;id"
    monkeypatch.setattr(main, "TARGETS", [bad])  # même si elle était dans la liste
    monkeypatch.setattr(main.subprocess, "run", no_subprocess)
    with pytest.raises(PermissionError):
        main.restart(bad)


def test_ssh_cible_hors_liste_refusee_sans_ssh(monkeypatch, ssh_mode):
    monkeypatch.setattr(main.subprocess, "run", no_subprocess)
    with pytest.raises(PermissionError):
        main.restart("monitoring_vmagent")


def test_ssh_cle_absente(monkeypatch, ssh_mode, tmp_path):
    monkeypatch.setattr(main, "SSH_KEY_FILE", str(tmp_path / "absente"))
    monkeypatch.setattr(main.subprocess, "run", no_subprocess)
    with pytest.raises(RuntimeError, match="clé SSH illisible"):
        main.restart(TARGET)
