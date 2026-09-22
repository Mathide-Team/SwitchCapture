"""Tests du mode non-root pour les interfaces TAP (features.md, priorité 000
— urgente : « Ne pas avoir besoin d'être root pour écouter une interface »).

Couvre `switch_capture_core._taphelper_path`, `ensure_tap_interface` et
`delete_tap_interface` :
    - aiguillage vers l'aide privilégiée `switch-capture-taphelper` quand
      elle est trouvée et que le process n'est pas root (mocké : aucun appel
      réel à `ip` ni au vrai binaire dans ces tests unitaires) ;
    - repli sur `ip` directement quand le process est root, ou quand l'aide
      est introuvable ;
    - propagation d'une erreur de l'aide (code de sortie non nul) en
      `RuntimeError` ;
    - `_taphelper_path` : résolution via `SWITCH_CAPTURE_TAPHELPER`, chemin
      d'installation standard, repli à côté de `switch_capture_core.py`,
      None si rien de trouvé/exécutable.

Un test d'intégration séparé, marqué et non bloquant si l'environnement ne
s'y prête pas (root indisponible pour créer un utilisateur de test, `gcc`/
`setcap` absents, `/dev/net/tun` inaccessible...), compile réellement
`src/helpers/switch-capture-taphelper.c`, lui positionne `cap_net_admin+ep`,
puis vérifie de bout en bout — en tant qu'utilisateur non-root réel, pas
mocké — que `add`/`up` créent une interface TAP utilisable et que
`TapFrameWriter` (sans aucun privilège) peut s'y attacher, avant `del`. Voir
CLAUDE.md pour le détail de ce qui a été vérifié ainsi en session.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from switch_capture_core import (
    _taphelper_path,
    delete_tap_interface,
    ensure_tap_interface,
)

HELPER_SRC = Path(__file__).resolve().parents[1] / "src" / "helpers" / "switch-capture-taphelper.c"


# --------------------------------------------------------------------------- #
# _taphelper_path : résolution du chemin de l'aide
# --------------------------------------------------------------------------- #
def test_taphelper_path_env_override(tmp_path, monkeypatch):
    """SWITCH_CAPTURE_TAPHELPER, si défini et exécutable, est prioritaire."""
    fake_helper = tmp_path / "fake-taphelper"
    fake_helper.write_text("#!/bin/sh\nexit 0\n")
    fake_helper.chmod(0o755)
    monkeypatch.setenv("SWITCH_CAPTURE_TAPHELPER", str(fake_helper))
    assert _taphelper_path() == fake_helper


def test_taphelper_path_env_override_non_executable_ignored(tmp_path, monkeypatch):
    """Un chemin défini mais non exécutable (ou absent) n'est pas retenu."""
    not_exec = tmp_path / "not-executable"
    not_exec.write_text("nope")
    # Pas de chmod +x : ne doit pas être choisi.
    monkeypatch.setenv("SWITCH_CAPTURE_TAPHELPER", str(not_exec))
    # Le repli standard (/usr/lib/...) n'existe presque certainement pas ici,
    # et le repli "à côté de switch_capture_core.py" non plus (seul le .c
    # existe dans ce dépôt, pas le binaire compilé, sauf si une session
    # précédente l'a laissé) : on vérifie juste que ce chemin invalide n'est
    # pas retourné tel quel.
    result = _taphelper_path()
    assert result != not_exec


def test_taphelper_path_none_when_nothing_found(monkeypatch):
    """Aucun candidat exécutable trouvé -> None (pas d'exception)."""
    monkeypatch.delenv("SWITCH_CAPTURE_TAPHELPER", raising=False)
    # Empêche un binaire réellement présent (installé, ou laissé par un
    # test précédent de cette session) de fausser ce test précis : on
    # pointe explicitement vers un chemin qui n'existe pas via l'env, ce qui
    # doit se comporter comme "pas de candidat env" et retomber sur les
    # deux autres candidats fixes.
    monkeypatch.setenv("SWITCH_CAPTURE_TAPHELPER", "/nonexistent/does-not-exist")
    result = _taphelper_path()
    # Ne peut pas garantir l'absence des deux chemins fixes sur toutes les
    # machines de dev, donc on vérifie seulement la cohérence du contrat :
    # soit None, soit un fichier réellement exécutable.
    assert result is None or (result.is_file() and os.access(result, os.X_OK))


# --------------------------------------------------------------------------- #
# ensure_tap_interface / delete_tap_interface : aiguillage (mocké)
# --------------------------------------------------------------------------- #
def test_ensure_tap_interface_uses_helper_when_available_and_not_root(tmp_path, monkeypatch):
    """Non-root + aide trouvée -> appelle l'aide (add puis up), jamais `ip`."""
    helper = tmp_path / "switch-capture-taphelper"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o755)
    monkeypatch.setenv("SWITCH_CAPTURE_TAPHELPER", str(helper))
    monkeypatch.setattr(os, "geteuid", lambda: 1000)  # simule non-root

    calls: list[list[str]] = []
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return real_run(["true"], **{k: v for k, v in kwargs.items() if k != "cmd"})

    import switch_capture_core as core

    monkeypatch.setattr(core.subprocess, "run", fake_run)

    ensure_tap_interface("vcap1")

    assert calls == [
        [str(helper), "add", "vcap1"],
        [str(helper), "up", "vcap1"],
    ]


def test_ensure_tap_interface_falls_back_to_ip_when_root(tmp_path, monkeypatch):
    """Même si l'aide est présente, un process root utilise `ip` directement
    (compatibilité avec un usage historique root/cron, inchangée)."""
    helper = tmp_path / "switch-capture-taphelper"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o755)
    monkeypatch.setenv("SWITCH_CAPTURE_TAPHELPER", str(helper))
    monkeypatch.setattr(os, "geteuid", lambda: 0)  # simule root

    import switch_capture_core as core

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class _Result:
            returncode = 1 if cmd[:2] == ["ip", "link"] and "show" in cmd else 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(core.subprocess, "run", fake_run)

    ensure_tap_interface("vcap1")

    assert all(cmd[0] == "ip" for cmd in calls)
    assert str(helper) not in [c for cmd in calls for c in cmd]


def test_ensure_tap_interface_no_helper_not_root_uses_ip(monkeypatch):
    """Non-root mais aide introuvable -> repli `ip` (comportement historique,
    échoue avec le message d'erreur habituel si les droits manquent)."""
    monkeypatch.delenv("SWITCH_CAPTURE_TAPHELPER", raising=False)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    import switch_capture_core as core

    monkeypatch.setattr(core, "_taphelper_path", lambda: None)

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class _Result:
            returncode = 1  # "show" (n'existe pas) puis "add" (échoue) : les deux à 1
            stdout = ""
            stderr = "Operation not permitted"

        return _Result()

    monkeypatch.setattr(core.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="root/CAP_NET_ADMIN"):
        ensure_tap_interface("vcap1")

    assert calls[0][0] == "ip"


def test_ensure_tap_interface_helper_add_failure_raises(tmp_path, monkeypatch):
    """Un échec de l'aide (add) devient une RuntimeError explicite."""
    helper = tmp_path / "switch-capture-taphelper"
    helper.write_text("#!/bin/sh\necho 'nom d\\'interface invalide' >&2\nexit 2\n")
    helper.chmod(0o755)
    monkeypatch.setenv("SWITCH_CAPTURE_TAPHELPER", str(helper))
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    with pytest.raises(RuntimeError, match="Aide privilégiée"):
        ensure_tap_interface("vcap1")


def test_ensure_tap_interface_helper_up_failure_raises(tmp_path, monkeypatch):
    """`add` réussit mais `up` échoue -> RuntimeError explicite distincte de
    celle du `add` (seule branche de `_ensure_tap_interface_via_helper`
    encore non exercée, repérée via l'audit `coverage.py` de la session 51 —
    `test_ensure_tap_interface_helper_add_failure_raises` ci-dessus ne
    couvrait que l'échec de `add`)."""
    helper = tmp_path / "switch-capture-taphelper"
    helper.write_text('#!/bin/sh\nif [ "$1" = "add" ]; then exit 0; fi\necho \'échec activation\' >&2\nexit 3\n')
    helper.chmod(0o755)
    monkeypatch.setenv("SWITCH_CAPTURE_TAPHELPER", str(helper))
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    with pytest.raises(RuntimeError, match="impossible d'activer l'interface TAP"):
        ensure_tap_interface("vcap1")


def test_ensure_tap_interface_reuses_existing_then_raises_on_up_failure(monkeypatch):
    """Repli `ip` direct (root ou aide introuvable), interface déjà présente
    ('show' réussit) : branche "réutilisation" jamais exercée jusqu'ici
    (audit `coverage.py` de session 54, lignes 395 et 403 de
    `switch_capture_core.py`). `up` échoue ensuite -> RuntimeError distincte
    de celle de la création (pas atteinte ici puisque l'interface existe
    déjà, `add` n'est jamais appelé)."""
    monkeypatch.delenv("SWITCH_CAPTURE_TAPHELPER", raising=False)
    monkeypatch.setattr(os, "geteuid", lambda: 0)  # simule root : jamais l'aide, toujours `ip`

    import switch_capture_core as core

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class _Result:
            returncode = 0 if cmd[:3] == ["ip", "link", "show"] else 1
            stdout = ""
            stderr = "RTNETLINK answers: Operation not permitted"

        return _Result()

    monkeypatch.setattr(core.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Impossible d'activer l'interface TAP"):
        ensure_tap_interface("vcap1")

    # "show" (existe) puis directement "up" : jamais de "tuntap add" pour une
    # interface déjà présente.
    assert calls == [
        ["ip", "link", "show", "vcap1"],
        ["ip", "link", "set", "vcap1", "up"],
    ]


def test_delete_tap_interface_uses_helper_when_available_and_not_root(tmp_path, monkeypatch):
    """Non-root + aide trouvée -> `del` via l'aide, jamais `ip link delete`."""
    helper = tmp_path / "switch-capture-taphelper"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o755)
    monkeypatch.setenv("SWITCH_CAPTURE_TAPHELPER", str(helper))
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    import switch_capture_core as core

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(core.subprocess, "run", fake_run)

    delete_tap_interface("vcap1")

    assert calls == [[str(helper), "del", "vcap1"]]


def test_delete_tap_interface_falls_back_to_real_ip_and_warns_on_failure(monkeypatch):
    """Aide introuvable (ou root) -> `ip link delete` direct (ligne 425, jamais
    exercée jusqu'ici) ; un échec ne lève pas mais log un warning explicite
    (ligne 432, non vérifiable via `caplog` dans ce dépôt — voir session 53,
    loguru sans bridge vers `logging`) — cohérent avec la docstring ("non
    bloquant")."""
    monkeypatch.delenv("SWITCH_CAPTURE_TAPHELPER", raising=False)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    import switch_capture_core as core

    monkeypatch.setattr(core, "_taphelper_path", lambda: None)

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class _Result:
            returncode = 1
            stdout = ""
            stderr = 'Cannot find device "vcap1"'

        return _Result()

    monkeypatch.setattr(core.subprocess, "run", fake_run)

    delete_tap_interface("vcap1")  # ne doit pas lever

    assert calls == [["ip", "link", "delete", "vcap1"]]


# --------------------------------------------------------------------------- #
# Test d'intégration réel : compile l'aide, positionne cap_net_admin+ep, et
# vérifie de bout en bout en tant qu'utilisateur non-root réel (pas mocké).
# Ignoré proprement (pas en échec) si l'environnement ne le permet pas.
# --------------------------------------------------------------------------- #
def _run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)


@pytest.mark.skipif(os.geteuid() != 0, reason="nécessite root pour compiler/setcap/créer un utilisateur de test")
def test_taphelper_end_to_end_as_real_nonroot_user():
    """Compile l'aide, cap_net_admin+ep, crée un utilisateur non-root
    jetable, et vérifie add/up/attach-TapFrameWriter/del en conditions
    réelles (mêmes étapes que la vérification manuelle documentée dans
    CLAUDE.md, ici automatisées et rejouables)."""
    if _run(["which", "gcc"]).returncode != 0:
        pytest.skip("gcc indisponible dans cet environnement")
    if _run(["which", "setcap"]).returncode != 0:
        pytest.skip("setcap (libcap2-bin) indisponible dans cet environnement")
    if not Path("/dev/net/tun").exists():
        pytest.skip("/dev/net/tun absent (module tun non chargé)")

    # Le fixture pytest `tmp_path` crée des répertoires 0700 (les ancêtres
    # sous /tmp/pytest-of-<user>/ le sont aussi) : non traversables par
    # l'utilisateur non-root de test créé plus bas via `su -`. On utilise un
    # répertoire dédié sous /tmp, entièrement hors de cette arborescence et
    # explicitement rendu traversable, plutôt que `tmp_path`.
    tmp_dir = Path(tempfile.mkdtemp(prefix="switch-capture-taphelper-e2e-", dir="/tmp"))
    os.chmod(tmp_dir, 0o755)
    try:
        _run_taphelper_e2e(tmp_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _run_taphelper_e2e(tmp_dir: Path) -> None:
    helper_bin = tmp_dir / "switch-capture-taphelper"
    compile_result = _run(["gcc", "-O2", "-o", str(helper_bin), str(HELPER_SRC)])
    assert compile_result.returncode == 0, compile_result.stderr

    setcap_result = _run(["setcap", "cap_net_admin+ep", str(helper_bin)])
    if setcap_result.returncode != 0:
        pytest.skip(f"setcap a échoué dans ce sandbox : {setcap_result.stderr.strip()}")

    ifname = "vcaphelpertest"
    username = "sc_helper_test_user"
    _run(["userdel", "-r", username])  # nettoyage d'un résidu éventuel
    useradd_result = _run(["useradd", "-m", username])
    assert useradd_result.returncode == 0, useradd_result.stderr

    try:
        add = _run(["su", "-", username, "-c", f"{helper_bin} add {ifname}"])
        assert add.returncode == 0, add.stderr
        up = _run(["su", "-", username, "-c", f"{helper_bin} up {ifname}"])
        assert up.returncode == 0, up.stderr

        show = _run(["ip", "-d", "link", "show", ifname])  # -d : détail (persist/user)
        assert show.returncode == 0
        assert f"user {username}" in show.stdout or "persist on" in show.stdout

        # switch_capture_core.TapFrameWriter, sans aucun privilège, doit
        # pouvoir s'attacher à cette interface (propriétaire = username).
        attach_script = (
            "import sys; sys.path.insert(0, 'src'); "
            "from switch_capture_core import TapFrameWriter; "
            f"w = TapFrameWriter({ifname!r}); "
            "w.write_frame(b'\\x00' * 14 + b'PYTEST-NONROOT'); "
            "w.close(); "
            "print('OK')"
        )
        attach = _run(
            [
                "su",
                "-",
                username,
                "-c",
                f'cd {Path(__file__).resolve().parents[1]} && python3 -c "{attach_script}"',
            ]
        )
        assert attach.returncode == 0, attach.stderr
        assert "OK" in attach.stdout

        delete = _run(["su", "-", username, "-c", f"{helper_bin} del {ifname}"])
        assert delete.returncode == 0, delete.stderr

        show_after = _run(["ip", "link", "show", ifname])
        assert show_after.returncode != 0
    finally:
        _run(["userdel", "-r", username])
        _run(["ip", "link", "delete", ifname])
