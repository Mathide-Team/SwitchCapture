"""Tests de la confirmation renforcée (retaper l'IP) avant désinstallation.

Couvre la piste d'amélioration « Confirmation renforcée avant
désinstallation en production (ex: ressaisir l'IP du switch) plutôt qu'une
simple boîte Oui/Non », listée dans CLAUDE.md.

Deux volets, mais un seul est automatisé ici :

- `confirm_ip_matches` (switch_capture_core, sans dépendance CLI/GTK) et le
  garde-fou côté CLI (`run_uninstall(..., confirm_ip=True)`) : couverts
  ci-dessous, sans switch réel. `UninstallThread` est remplacée par un faux
  thread qui n'ouvre aucune connexion SSH (même principe que le FakeConn
  utilisé ailleurs dans le projet pour les tests d'audit de commandes, voir
  CLAUDE.md section Journalisation) — on vérifie que la connexion n'est
  *jamais* tentée quand l'IP saisie ne correspond pas.
- Le bouton "Désinstaller" du formulaire GTK (`_on_uninstall_session`),
  qui utilise la même fonction `confirm_ip_matches`, est validé par
  introspection directe des widgets sous Xvfb au moment de ce
  changement (voir features.md) mais volontairement pas ajouté à cette
  suite pytest : `tests/` reste indépendant de GTK4/PyGObject, comme le
  reste du projet le documente déjà (conftest.py, CLAUDE.md).
"""

from __future__ import annotations

from typing import ClassVar

import switch_capture_cli as cli_mod
from switch_capture_core import Config, confirm_ip_matches


def make_config(**overrides) -> Config:
    """Construit un Config valide minimal, avec surcharges optionnelles (mêmes défauts que test_capture_templates.py)."""
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "capture_interface": "GigabitEthernet1/0/1",
    }
    base.update(overrides)
    return Config(**base)


class _FakeUninstallThread:
    """Remplace UninstallThread : n'ouvre aucune connexion SSH, appelle on_done immédiatement.

    Enregistre chaque instance construite dans `started`, pour que les tests
    puissent vérifier qu'aucune tentative de connexion n'a été faite quand
    la confirmation d'IP échoue.
    """

    started: ClassVar[list[_FakeUninstallThread]] = []

    def __init__(self, cfg, state, remove_bin_from_flash, on_done=None):
        self.cfg = cfg
        self.state = state
        self.remove_bin_from_flash = remove_bin_from_flash
        self.on_done = on_done

    def run(self) -> None:
        _FakeUninstallThread.started.append(self)
        if self.on_done:
            self.on_done(True, "ok (faux thread de test, aucune connexion SSH)")


# --------------------------------------------------------------------- #
# confirm_ip_matches (switch_capture_core, pure, sans dépendance CLI/GTK)
# --------------------------------------------------------------------- #


def test_confirm_ip_matches_exact():
    assert confirm_ip_matches("10.0.0.1", "10.0.0.1") is True


def test_confirm_ip_matches_mismatch():
    assert confirm_ip_matches("10.0.0.99", "10.0.0.1") is False


def test_confirm_ip_matches_strips_whitespace_and_newline():
    assert confirm_ip_matches("  10.0.0.1  \n", "10.0.0.1") is True


def test_confirm_ip_matches_empty_input():
    assert confirm_ip_matches("", "10.0.0.1") is False


def test_confirm_ip_matches_case_sensitive():
    # Une IP ne varie pas en casse dans ce projet ; un nom de switch pourrait,
    # donc la comparaison reste volontairement stricte (pas de .lower()).
    assert confirm_ip_matches("switch-A", "switch-a") is False


# --------------------------------------------------------------------- #
# run_uninstall(..., confirm_ip=...) — CLI, UninstallThread remplacée
# --------------------------------------------------------------------- #


def test_confirm_ip_matching_input_proceeds(monkeypatch):
    monkeypatch.setattr(cli_mod, "UninstallThread", _FakeUninstallThread)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "10.0.0.1")
    _FakeUninstallThread.started.clear()

    cfg = make_config(switch_ip="10.0.0.1")
    rc = cli_mod.run_uninstall(cfg, remove_bin_from_flash=False, confirm_ip=True)

    assert rc == 0
    assert len(_FakeUninstallThread.started) == 1


def test_confirm_ip_mismatch_aborts_without_connecting(monkeypatch):
    monkeypatch.setattr(cli_mod, "UninstallThread", _FakeUninstallThread)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "10.0.0.99")
    _FakeUninstallThread.started.clear()

    cfg = make_config(switch_ip="10.0.0.1")
    rc = cli_mod.run_uninstall(cfg, remove_bin_from_flash=False, confirm_ip=True)

    assert rc == 1
    assert len(_FakeUninstallThread.started) == 0  # jamais construit -> jamais de connexion tentée


def test_confirm_ip_eof_on_stdin_aborts(monkeypatch):
    """stdin fermée (ex: lancement accidentel sans terminal) -> abandon propre, pas de traceback."""

    def _raise_eof(*_a, **_k):
        raise EOFError

    monkeypatch.setattr(cli_mod, "UninstallThread", _FakeUninstallThread)
    monkeypatch.setattr("builtins.input", _raise_eof)
    _FakeUninstallThread.started.clear()

    cfg = make_config(switch_ip="10.0.0.1")
    rc = cli_mod.run_uninstall(cfg, remove_bin_from_flash=False, confirm_ip=True)

    assert rc == 1
    assert len(_FakeUninstallThread.started) == 0


def test_confirm_ip_default_false_skips_prompt_entirely(monkeypatch):
    """Comportement par défaut inchangé : sans --confirm-ip, aucun prompt (compat cron/systemd)."""

    def _boom(*_a, **_k):
        raise AssertionError("input() ne doit pas être appelé sans confirm_ip=True")

    monkeypatch.setattr(cli_mod, "UninstallThread", _FakeUninstallThread)
    monkeypatch.setattr("builtins.input", _boom)
    _FakeUninstallThread.started.clear()

    cfg = make_config(switch_ip="10.0.0.1")
    rc = cli_mod.run_uninstall(cfg, remove_bin_from_flash=False)  # confirm_ip par défaut = False

    assert rc == 0
    assert len(_FakeUninstallThread.started) == 1


def test_confirm_ip_passes_remove_bin_through(monkeypatch):
    monkeypatch.setattr(cli_mod, "UninstallThread", _FakeUninstallThread)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "10.0.0.1")
    _FakeUninstallThread.started.clear()

    cfg = make_config(switch_ip="10.0.0.1")
    cli_mod.run_uninstall(cfg, remove_bin_from_flash=True, confirm_ip=True)

    assert _FakeUninstallThread.started[0].remove_bin_from_flash is True


# --------------------------------------------------------------------- #
# run_uninstall(...) — branche échec (session 53)
#
# Tous les tests ci-dessus font réussir _FakeUninstallThread
# (on_done(True, ...)) : la branche `else: logger.error(...)` / `return 1`
# de run_uninstall (switch_capture_cli.py, lignes ~808-817) n'était encore
# jamais exercée — confirmé par recherche croisée (`grep -rn "on_done(False"
# tests/*.py`, aucun résultat avant ce test) avant d'écrire le test
# ci-dessous.
# --------------------------------------------------------------------- #


class _FakeUninstallThreadFailure:
    """Comme `_FakeUninstallThread`, mais simule un échec (ex: connexion SSH refusée)."""

    def __init__(self, cfg, state, remove_bin_from_flash, on_done=None):
        self.cfg = cfg
        self.state = state
        self.remove_bin_from_flash = remove_bin_from_flash
        self.on_done = on_done

    def run(self) -> None:
        if self.on_done:
            self.on_done(False, "échec simulé (faux thread de test, aucune connexion SSH)")


def test_uninstall_failure_returns_1_and_logs_error(monkeypatch):
    # `échec simulé` bascule bien la branche `else:` (logger.error, ligne
    # ~816) : confirmé au passage par la sortie stderr affichée par pytest
    # en cas d'échec du test pendant la mise au point (loguru écrit
    # directement sur le descripteur de fichier stderr d'origine, capturé
    # par `logger.add(sys.stderr, ...)` avant même le démarrage de la
    # capture pytest — ni `capsys` ni `capfd` ni `caplog` ne voient ce
    # texte depuis un test, cf. absence de `caplog` déjà non exploité
    # ailleurs dans ce fichier et dans test_cli_uncovered_pure_functions.py :
    # ce dépôt ne vérifie donc le contenu des logs loguru nulle part,
    # seulement le comportement qu'ils accompagnent). On se limite donc
    # ici, comme le reste du dépôt, à vérifier le code de retour.
    monkeypatch.setattr(cli_mod, "UninstallThread", _FakeUninstallThreadFailure)

    cfg = make_config(switch_ip="10.0.0.1")
    rc = cli_mod.run_uninstall(cfg, remove_bin_from_flash=False)  # confirm_ip par défaut = False

    assert rc == 1
