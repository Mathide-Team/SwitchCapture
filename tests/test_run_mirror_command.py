"""Tests de `run_mirror` (switch_capture_cli.py).

Piste laissée ouverte en fin de session 52 (« poursuivre l'audit de
couverture ») : `run_mirror` était entièrement à 0 % de couverture (lignes
874-897), jamais exercée par aucun test du dépôt — confirmé par recherche
croisée (`grep -rn "run_mirror\\b" tests/*.py`, aucun résultat avant ce
fichier). `switch-capture mirror` (le sous-parseur argparse) et
`MirrorConfig`/`MirrorThread` (côté switch_capture_core) sont eux bien
couverts ailleurs (`test_mirror_vxlan.py`, `test_mirror_acl_filter.py`,
`test_gui_mirroring.py`) — seul le fin câblage CLI autour manquait :
construction de `MirrorConfig` depuis `args`, gestion de l'exception de
validation, exécution synchrone de `MirrorThread`, code de retour.

Même principe que `test_uninstall_confirm.py`/`test_run_capture_dispatch.py` :
`MirrorThread` est remplacée par un faux thread synchrone qui n'ouvre
aucune connexion SSH.

Sans dépendance GTK4/PyGObject ni switch réel.
"""

from __future__ import annotations

import argparse
from typing import ClassVar

import switch_capture_cli as cli


def _mirror_namespace(**overrides) -> argparse.Namespace:
    """Espace de noms minimal valide pour la sous-commande `mirror`, mode 'local' (défaut).

    Ne couvre que les clés de `_MIRROR_CONFIG_FIELDS` réellement nécessaires
    au test ; `run_mirror` utilise `getattr(args, key, None)` pour les
    autres (voir `build_config`, même logique) donc les attributs absents
    du Namespace sont traités comme `None` sans lever.
    """
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "source_interfaces": ["GigabitEthernet1/0/1"],
        "monitor_interface": "GigabitEthernet1/0/2",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class _FakeMirrorThread:
    """Remplace MirrorThread : n'ouvre aucune connexion SSH, appelle on_done immédiatement.

    `outcome`/`message` sont des attributs de classe, redéfinis par chaque
    test avant l'appel (même pattern que `_FakeSetupThread` dans
    `test_run_capture_dispatch.py`).
    """

    instances: ClassVar[list[_FakeMirrorThread]] = []
    outcome = True
    message = "ok (faux thread de test, aucune connexion SSH)"

    def __init__(self, mirror_cfg, teardown=False, on_done=None):
        self.mirror_cfg = mirror_cfg
        self.teardown = teardown
        self.on_done = on_done
        _FakeMirrorThread.instances.append(self)

    def run(self) -> None:
        if self.on_done:
            self.on_done(_FakeMirrorThread.outcome, _FakeMirrorThread.message)


def _reset_fake(monkeypatch, *, outcome: bool = True, message: str = "ok") -> None:
    monkeypatch.setattr(cli, "MirrorThread", _FakeMirrorThread)
    _FakeMirrorThread.instances.clear()
    _FakeMirrorThread.outcome = outcome
    _FakeMirrorThread.message = message


def test_success_returns_0(monkeypatch):
    _reset_fake(monkeypatch, outcome=True)

    rc = cli.run_mirror(_mirror_namespace())

    assert rc == 0
    assert len(_FakeMirrorThread.instances) == 1


def test_failure_returns_1(monkeypatch):
    _reset_fake(monkeypatch, outcome=False, message="échec simulé")

    rc = cli.run_mirror(_mirror_namespace())

    assert rc == 1


def test_invalid_config_returns_2_without_starting_thread(monkeypatch):
    # mode "local" (défaut) sans monitor_interface -> ValueError levée par
    # MirrorConfig.__post_init__, interceptée par run_mirror -> 2, et
    # MirrorThread ne doit jamais être instanciée (échec avant toute
    # tentative de connexion, même garantie que test_uninstall_confirm.py
    # pour la mauvaise IP saisie).
    _reset_fake(monkeypatch)

    rc = cli.run_mirror(_mirror_namespace(monitor_interface=None))

    assert rc == 2
    assert _FakeMirrorThread.instances == []


def test_teardown_flag_passed_through(monkeypatch):
    _reset_fake(monkeypatch)

    cli.run_mirror(_mirror_namespace(teardown=True))

    assert _FakeMirrorThread.instances[0].teardown is True


def test_teardown_defaults_to_false_when_attribute_absent(monkeypatch):
    # run_mirror utilise getattr(args, "teardown", False) : un Namespace
    # sans l'attribut `teardown` (ex: construit à la main comme ici, sans
    # passer par argparse) ne doit pas lever, et doit se comporter comme
    # teardown=False.
    _reset_fake(monkeypatch)

    cli.run_mirror(_mirror_namespace())

    assert _FakeMirrorThread.instances[0].teardown is False


def test_mirror_config_built_from_namespace_fields(monkeypatch):
    _reset_fake(monkeypatch)

    cli.run_mirror(_mirror_namespace(mode="local", group_id=7))

    cfg = _FakeMirrorThread.instances[0].mirror_cfg
    assert cfg.switch_ip == "10.0.0.1"
    assert cfg.group_id == 7
    assert cfg.source_interfaces == ["GigabitEthernet1/0/1"]
