"""Tests de `run_capture` (switch_capture_cli.py).

Piste laissée ouverte en fin de session 52 (« poursuivre l'audit de
couverture ») : `run_capture` était à 0 % de couverture (lignes 750-771),
jamais exercée par aucun test du dépôt — confirmé par recherche croisée
(`grep -rn "run_capture" tests/*.py`, aucun résultat avant ce fichier).

`run_capture` orchestre deux threads (`SetupAndCaptureThread`,
`CaptureRotationThread`) et un handler SIGINT, mais ne contient elle-même
aucune logique métier de capture — ce qui suit `.start()`/`.join()` est
hors périmètre ici (déjà couvert ailleurs par leurs propres fichiers de
tests dédiés : `test_setup_and_capture_thread.py`,
`test_tap_pacing.py`/`test_tap_injector_thread.py` pour la rotation/TAP).
On remplace donc les deux classes par de faux threads synchrones (même
principe que `_FakeUninstallThread` dans `test_uninstall_confirm.py`) qui
n'ouvrent aucune connexion SSH et ne bloquent jamais, tout en pouvant
positionner `state.stop_event`/`state.capture_started` pour exercer les
deux branches du code de retour.

Sans dépendance GTK4/PyGObject ni switch réel.
"""

from __future__ import annotations

import signal
from typing import ClassVar

import pytest

import switch_capture_cli as cli
from switch_capture_core import Config, SharedState


def make_config(**overrides) -> Config:
    """Construit un Config valide minimal, avec surcharges optionnelles (même style que les autres fichiers de tests)."""
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "capture_interface": "GigabitEthernet1/0/1",
    }
    base.update(overrides)
    return Config(**base)


@pytest.fixture(autouse=True)
def _restore_sigint_handler():
    # run_capture() appelle signal.signal(SIGINT, ...) pour de vrai (pas
    # mocké : c'est un appel système simple, sans effet de bord risqué en
    # test automatisé non interactif) — sans restauration, le gestionnaire
    # posé par un test resterait actif pour le reste du processus pytest
    # (et référencerait un `state` de test périmé). Restauré après chaque
    # test, même principe que `monkeypatch` mais pour une ressource
    # process-globale qu'aucun des deux ne couvre nativement.
    previous_handler = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGINT, previous_handler)


class _FakeSetupThread:
    """Remplace SetupAndCaptureThread : n'ouvre aucune connexion SSH.

    `start()` positionne `state.capture_started`/`state.stop_event` selon
    les indicateurs de classe (redéfinis par chaque test avant l'appel),
    pour simuler ce que ferait le vrai thread avant que `join()` ne rende
    la main.
    """

    instances: ClassVar[list[_FakeSetupThread]] = []
    sets_capture_started: ClassVar[bool] = False
    sets_stop_event: ClassVar[bool] = False

    def __init__(self, cfg, state):
        self.cfg = cfg
        self.state = state
        self.started = False
        self.joined = False
        _FakeSetupThread.instances.append(self)

    def start(self) -> None:
        self.started = True
        if _FakeSetupThread.sets_capture_started:
            self.state.capture_started.set()
        if _FakeSetupThread.sets_stop_event:
            self.state.stop_event.set()

    def join(self) -> None:
        self.joined = True


class _FakeRotationThread:
    """Remplace CaptureRotationThread : ne rapatrie rien, ne bloque jamais."""

    instances: ClassVar[list[_FakeRotationThread]] = []

    def __init__(self, cfg, state):
        self.cfg = cfg
        self.state = state
        self.started = False
        self.joined = False
        _FakeRotationThread.instances.append(self)

    def start(self) -> None:
        self.started = True

    def join(self) -> None:
        self.joined = True


def _reset_fakes(monkeypatch, *, sets_capture_started: bool = False, sets_stop_event: bool = False) -> None:
    monkeypatch.setattr(cli, "SetupAndCaptureThread", _FakeSetupThread)
    monkeypatch.setattr(cli, "CaptureRotationThread", _FakeRotationThread)
    _FakeSetupThread.instances.clear()
    _FakeRotationThread.instances.clear()
    _FakeSetupThread.sets_capture_started = sets_capture_started
    _FakeSetupThread.sets_stop_event = sets_stop_event


def test_normal_completion_starts_both_threads_and_returns_0(monkeypatch):
    # Cas nominal : ni Ctrl+C ni erreur, stop_event jamais positionné ->
    # 0 quel que soit l'état de capture_started (branche `not
    # state.stop_event.is_set()` de la ligne de retour).
    _reset_fakes(monkeypatch)

    rc = cli.run_capture(make_config())

    assert rc == 0
    assert len(_FakeSetupThread.instances) == 1
    assert _FakeSetupThread.instances[0].started is True
    assert _FakeSetupThread.instances[0].joined is True
    assert len(_FakeRotationThread.instances) == 1
    assert _FakeRotationThread.instances[0].started is True
    assert _FakeRotationThread.instances[0].joined is True


def test_rpcap_output_mode_skips_rotation_thread(monkeypatch):
    # output_mode == "rpcap" : Wireshark se connecte directement au
    # switch, rien à rapatrier -> CaptureRotationThread (t2) ne doit
    # jamais être instanciée ni démarrée.
    _reset_fakes(monkeypatch)

    rc = cli.run_capture(make_config(output_mode="rpcap"))

    assert rc == 0
    assert len(_FakeSetupThread.instances) == 1
    assert _FakeRotationThread.instances == []


def test_clean_ctrl_c_after_capture_started_returns_0(monkeypatch):
    # stop_event positionné (Ctrl+C) MAIS capture_started aussi (arrêt
    # propre après une capture qui a bien démarré) -> 0.
    _reset_fakes(monkeypatch, sets_capture_started=True, sets_stop_event=True)

    rc = cli.run_capture(make_config())

    assert rc == 0


def test_ctrl_c_before_capture_started_returns_1(monkeypatch):
    # stop_event positionné (Ctrl+C) SANS que capture_started ne le soit
    # (interruption pendant la préparation, avant tout début de capture)
    # -> 1.
    _reset_fakes(monkeypatch, sets_capture_started=False, sets_stop_event=True)

    rc = cli.run_capture(make_config())

    assert rc == 1


def test_shared_state_passed_to_both_threads(monkeypatch):
    # t1 et t2 doivent recevoir la même instance de SharedState (partagée
    # entre préparation/capture et rotation), pas deux états indépendants.
    _reset_fakes(monkeypatch)

    cli.run_capture(make_config())

    setup_state = _FakeSetupThread.instances[0].state
    rotation_state = _FakeRotationThread.instances[0].state
    assert isinstance(setup_state, SharedState)
    assert setup_state is rotation_state


def test_real_sigint_delivery_sets_stop_event_and_returns_1(monkeypatch):
    # Les quatre tests précédents positionnent state.stop_event/
    # capture_started directement depuis le faux thread, sans jamais
    # passer par le vrai gestionnaire handle_sigint() installé via
    # signal.signal() (lignes 757-759) : celui-ci restait donc non
    # couvert. Ici, le faux SetupAndCaptureThread envoie un vrai SIGINT
    # au processus courant *pendant* start() (donc après l'enregistrement
    # du gestionnaire, avant t1.join()) — livré de façon synchrone par
    # CPython, sans lever KeyboardInterrupt puisque handle_sigint()
    # remplace entièrement le gestionnaire par défaut.
    import os

    class _SigintDuringStart(_FakeSetupThread):
        def start(self) -> None:
            self.started = True
            os.kill(os.getpid(), signal.SIGINT)

    _reset_fakes(monkeypatch)
    monkeypatch.setattr(cli, "SetupAndCaptureThread", _SigintDuringStart)

    rc = cli.run_capture(make_config())

    # capture_started jamais positionné (le vrai handle_sigint() ne
    # positionne que stop_event) -> branche de retour 1.
    assert rc == 1
