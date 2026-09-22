"""Tests du trousseau système (libsecret/GNOME Keyring) pour le mot de passe SSH.

Couvre la piste d'amélioration « Trousseau système (libsecret/GNOME
Keyring) pour mémoriser le mot de passe SSH entre deux lancements sans le
stocker en clair », listée dans CLAUDE.md (section « Pistes d'amélioration
envisagées, non implémentées »).

Deux volets :

- `switch_capture_core.save_ssh_password_to_keyring`/
  `load_ssh_password_from_keyring`/`delete_ssh_password_from_keyring` et le
  câblage CLI (`_maybe_fill_password_from_keyring`,
  `_apply_password_keyring_actions`) : couverts ci-dessous avec un faux
  backend `keyring` en mémoire (`FakeKeyringModule`) — même principe que le
  `FakeConn` utilisé ailleurs dans le projet pour l'audit de commandes (voir
  CLAUDE.md, section Journalisation) : aucun trousseau système réel, aucun
  service Secret Service/D-Bus requis pour cette suite pytest.
- Le round-trip contre un **vrai** service Secret Service (`gnome-keyring-
  daemon` sous une session D-Bus dédiée, `dbus-run-session -- ...`) a été
  validé séparément, en dehors de cette suite — voir CLAUDE.md, section
  « Trousseau système » : script de validation ad hoc, non committé, même
  choix que les validations GTK sous Xvfb de ce dépôt (aucun service Secret
  Service n'est disponible dans l'environnement d'exécution habituel de
  `pytest tests/`, ce module ne peut donc pas en dépendre).
"""

from __future__ import annotations

import argparse
from typing import ClassVar

import pytest

import switch_capture_cli as cli_mod
import switch_capture_core as core_mod
from switch_capture_core import (
    Config,
    delete_ssh_password_from_keyring,
    keyring_account_id,
    load_ssh_password_from_keyring,
    save_ssh_password_to_keyring,
)

# --------------------------------------------------------------------- #
# Faux backend keyring en mémoire (remplace le module `keyring` importé
# dans switch_capture_core), sur le modèle du FakeConn utilisé ailleurs.
# --------------------------------------------------------------------- #


class _FakeKeyringErrors:
    """Reproduit la forme de `keyring.errors` utilisée par switch_capture_core."""

    class KeyringError(Exception):
        pass

    class PasswordDeleteError(KeyringError):
        pass


class FakeKeyringModule:
    """Remplace le module `keyring` réel : stockage en dict, aucun D-Bus."""

    errors = _FakeKeyringErrors

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}
        self.fail_on_write = False  # simule un trousseau verrouillé/indisponible

    def set_password(self, service: str, account: str, password: str) -> None:
        if self.fail_on_write:
            raise self.errors.KeyringError("trousseau verrouillé (simulation de test)")
        self._store[(service, account)] = password

    def get_password(self, service: str, account: str) -> str | None:
        return self._store.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        try:
            del self._store[(service, account)]
        except KeyError:
            raise self.errors.PasswordDeleteError("aucune entrée à supprimer") from None


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyringModule:
    """Branche un faux backend `keyring` sur switch_capture_core, isolément de tout trousseau réel."""
    fake = FakeKeyringModule()
    monkeypatch.setattr(core_mod, "keyring", fake)
    monkeypatch.setattr(core_mod, "KEYRING_AVAILABLE", True)
    return fake


@pytest.fixture
def keyring_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simule l'absence du module `keyring` (dépendance optionnelle non installée)."""
    monkeypatch.setattr(core_mod, "keyring", None)
    monkeypatch.setattr(core_mod, "KEYRING_AVAILABLE", False)


# --------------------------------------------------------------------- #
# keyring_account_id (fonction pure)
# --------------------------------------------------------------------- #


def test_keyring_account_id_format():
    assert keyring_account_id("10.0.0.1", "admin") == "admin@10.0.0.1"


def test_keyring_account_id_distinguishes_users_on_same_switch():
    a = keyring_account_id("10.0.0.1", "admin")
    b = keyring_account_id("10.0.0.1", "backup")
    assert a != b


def test_keyring_account_id_distinguishes_switches_for_same_user():
    a = keyring_account_id("10.0.0.1", "admin")
    b = keyring_account_id("10.0.0.2", "admin")
    assert a != b


# --------------------------------------------------------------------- #
# save/load/delete — avec le faux backend
# --------------------------------------------------------------------- #


def test_save_then_load_round_trip(fake_keyring: FakeKeyringModule):
    save_ssh_password_to_keyring("10.0.0.1", "admin", "s3cr3t")
    assert load_ssh_password_from_keyring("10.0.0.1", "admin") == "s3cr3t"


def test_load_returns_none_when_nothing_stored(fake_keyring: FakeKeyringModule):
    assert load_ssh_password_from_keyring("10.0.0.9", "personne") is None


def test_save_does_not_leak_across_accounts(fake_keyring: FakeKeyringModule):
    save_ssh_password_to_keyring("10.0.0.1", "admin", "pass-admin")
    save_ssh_password_to_keyring("10.0.0.1", "backup", "pass-backup")
    assert load_ssh_password_from_keyring("10.0.0.1", "admin") == "pass-admin"
    assert load_ssh_password_from_keyring("10.0.0.1", "backup") == "pass-backup"


def test_delete_removes_stored_password(fake_keyring: FakeKeyringModule):
    save_ssh_password_to_keyring("10.0.0.1", "admin", "s3cr3t")
    deleted = delete_ssh_password_from_keyring("10.0.0.1", "admin")
    assert deleted is True
    assert load_ssh_password_from_keyring("10.0.0.1", "admin") is None


def test_delete_is_idempotent_when_nothing_stored(fake_keyring: FakeKeyringModule):
    deleted = delete_ssh_password_from_keyring("10.0.0.1", "admin")
    assert deleted is False


def test_save_failure_raises_runtime_error(fake_keyring: FakeKeyringModule):
    fake_keyring.fail_on_write = True
    with pytest.raises(RuntimeError):
        save_ssh_password_to_keyring("10.0.0.1", "admin", "s3cr3t")


# --------------------------------------------------------------------- #
# Dépendance optionnelle absente : jamais d'exception surprise en lecture
# --------------------------------------------------------------------- #


def test_load_returns_none_when_keyring_module_unavailable(keyring_unavailable):
    assert load_ssh_password_from_keyring("10.0.0.1", "admin") is None


def test_delete_returns_false_when_keyring_module_unavailable(keyring_unavailable):
    assert delete_ssh_password_from_keyring("10.0.0.1", "admin") is False


def test_save_raises_explicit_error_when_keyring_module_unavailable(keyring_unavailable):
    # Contrairement à la lecture (silencieuse), une demande explicite
    # d'enregistrement qui échoue doit être signalée à l'appelant.
    with pytest.raises(RuntimeError):
        save_ssh_password_to_keyring("10.0.0.1", "admin", "s3cr3t")


# --------------------------------------------------------------------- #
# Câblage CLI : _maybe_fill_password_from_keyring (build_config/build_inspect_config)
# --------------------------------------------------------------------- #


def test_maybe_fill_password_loads_from_keyring_when_nothing_else_provided(
    fake_keyring: FakeKeyringModule, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    save_ssh_password_to_keyring("10.0.0.1", "admin", "from-keyring")
    raw = {"switch_ip": "10.0.0.1", "ssh_user": "admin"}
    cli_mod._maybe_fill_password_from_keyring(raw)
    assert raw["ssh_password"] == "from-keyring"


def test_maybe_fill_password_does_not_override_explicit_password(
    fake_keyring: FakeKeyringModule, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    save_ssh_password_to_keyring("10.0.0.1", "admin", "from-keyring")
    raw = {"switch_ip": "10.0.0.1", "ssh_user": "admin", "ssh_password": "from-cli"}
    cli_mod._maybe_fill_password_from_keyring(raw)
    assert raw["ssh_password"] == "from-cli"


def test_maybe_fill_password_does_not_consult_keyring_when_env_var_set(
    fake_keyring: FakeKeyringModule, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("SWITCH_SSH_PASSWORD", "from-env")
    save_ssh_password_to_keyring("10.0.0.1", "admin", "from-keyring")
    raw = {"switch_ip": "10.0.0.1", "ssh_user": "admin"}
    cli_mod._maybe_fill_password_from_keyring(raw)
    # SWITCH_SSH_PASSWORD est prioritaire : le trousseau n'a même pas dû
    # être consulté, et raw['ssh_password'] doit rester absent ici (c'est
    # Config.__post_init__ qui lit la variable d'environnement, pas cette
    # fonction).
    assert "ssh_password" not in raw


def test_maybe_fill_password_noop_without_switch_ip_or_user(
    fake_keyring: FakeKeyringModule, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    raw = {"ssh_user": "admin"}  # switch_ip manquant
    cli_mod._maybe_fill_password_from_keyring(raw)
    assert "ssh_password" not in raw


def test_build_config_end_to_end_fills_password_from_keyring(
    fake_keyring: FakeKeyringModule, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    save_ssh_password_to_keyring("10.0.0.1", "admin", "from-keyring")
    args = argparse.Namespace(
        config=None,
        switch_ip="10.0.0.1",
        ssh_user="admin",
        ssh_password=None,
        capture_interface="GigabitEthernet1/0/1",
    )
    for field_name in cli_mod._CONFIG_FIELDS:
        if not hasattr(args, field_name):
            setattr(args, field_name, None)
    cfg = cli_mod.build_config(args)
    assert isinstance(cfg, Config)
    assert cfg.ssh_password == "from-keyring"


# --------------------------------------------------------------------- #
# Câblage CLI : _apply_password_keyring_actions (--remember-password / --forget-password)
# --------------------------------------------------------------------- #


class _NamespaceStub(argparse.Namespace):
    remember_password: ClassVar[bool] = False
    forget_password: ClassVar[bool] = False


def test_apply_actions_remember_saves_password(fake_keyring: FakeKeyringModule):
    args = _NamespaceStub(remember_password=True, forget_password=False)
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")
    assert load_ssh_password_from_keyring("10.0.0.1", "admin") == "s3cr3t"


def test_apply_actions_forget_deletes_password(fake_keyring: FakeKeyringModule):
    save_ssh_password_to_keyring("10.0.0.1", "admin", "s3cr3t")
    args = _NamespaceStub(remember_password=False, forget_password=True)
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")
    assert load_ssh_password_from_keyring("10.0.0.1", "admin") is None


def test_apply_actions_neither_flag_is_a_noop(fake_keyring: FakeKeyringModule):
    args = _NamespaceStub(remember_password=False, forget_password=False)
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")
    assert load_ssh_password_from_keyring("10.0.0.1", "admin") is None


def test_apply_actions_remember_failure_is_logged_not_raised(fake_keyring: FakeKeyringModule):
    fake_keyring.fail_on_write = True
    args = _NamespaceStub(remember_password=True, forget_password=False)
    # Ne doit jamais lever : un échec de mémorisation ne doit pas faire
    # planter une capture/désinstallation/inspection par ailleurs réussie.
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")


def test_apply_actions_missing_attributes_default_to_false(fake_keyring: FakeKeyringModule):
    # Sous-parseur qui n'expose pas ces options (ex. 'mirror') : getattr(...,
    # False) ne doit jamais lever d'AttributeError.
    args = argparse.Namespace()
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")
    assert load_ssh_password_from_keyring("10.0.0.1", "admin") is None
