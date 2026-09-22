"""Tests du repli KeePass (fichier `.kdbx`) pour le mot de passe SSH.

Couvre la partie « repli sur un fichier KeePass si aucun trousseau système
n'est installé », listée dans features.md (section « Menu et
préférences », point 4) et jusqu'ici non implémentée. N'intervient qu'en
dernier recours, derrière le trousseau système (`keyring`, voir
test_keyring_password.py) — voir switch_capture_core.py, section « Repli
KeePass ».

Même principe que `test_keyring_password.py` : un faux module `pykeepass`
en mémoire (`FakeKeePassModule`/`FakePyKeePass`), monkeypatché sur
`switch_capture_core.PyKeePass`/`CredentialsError`, aucun vrai fichier
`.kdbx` chiffré ni bibliothèque `pykeepass` réelle requis pour cette suite.
Un fichier vide (`tmp_path`) sert uniquement à satisfaire la vérification
« le fichier doit exister » de `_open_keepass_db` — son contenu n'est
jamais lu par le faux backend.
"""

from __future__ import annotations

import argparse
from typing import ClassVar

import pytest

import switch_capture_cli as cli_mod
import switch_capture_core as core_mod
from switch_capture_core import (
    delete_ssh_password_from_keepass,
    load_ssh_password_from_keepass,
    save_ssh_password_to_keepass,
)

# --------------------------------------------------------------------- #
# Faux backend pykeepass en mémoire (remplace PyKeePass/CredentialsError
# importés dans switch_capture_core), sur le modèle de FakeKeyringModule.
# --------------------------------------------------------------------- #


class _FakeCredentialsError(Exception):
    pass


class _FakeEntry:
    def __init__(self, title: str, username: str, password: str) -> None:
        self.title = title
        self.username = username
        self.password = password


class FakePyKeePass:
    """Remplace `pykeepass.PyKeePass` : stockage en dict par chemin, aucun fichier réel lu."""

    # Un seul « fichier » partagé par test (au travers de la fixture), avec son
    # propre mot de passe maître et ses propres entrées — pas de vraie
    # persistence disque, juste assez pour exercer save/load/delete/erreurs.
    # `keyfile` accepté (comme le vrai `pykeepass.PyKeePass`) et mémorisé tel
    # quel dans le store partagé, pour permettre aux tests de vérifier qu'il
    # a bien été transmis jusqu'ici — jamais vérifié/utilisé au-delà de ça
    # par ce faux backend (pas de vraie cryptographie de fichier de clé).
    def __init__(self, path: str, password: str | None = None, keyfile: str | None = None) -> None:
        store = FakePyKeePass._stores.setdefault(path, {"password": password, "keyfile": keyfile, "entries": {}})
        if store["password"] != password:
            raise _FakeCredentialsError("mot de passe maître incorrect (simulation de test)")
        self.keyfile = keyfile
        self._entries = store["entries"]
        self.root_group = object()

    _stores: ClassVar[dict] = {}

    def find_entries(self, title: str | None = None, first: bool = False):
        entry = self._entries.get(title)
        if first:
            return entry
        return [entry] if entry else []

    def add_entry(self, group, title: str, username: str, password: str) -> _FakeEntry:
        entry = _FakeEntry(title, username, password)
        self._entries[title] = entry
        return entry

    def delete_entry(self, entry: _FakeEntry) -> None:
        self._entries.pop(entry.title, None)

    def save(self) -> None:
        pass


@pytest.fixture(autouse=False)
def fake_pykeepass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Branche un faux backend `pykeepass` sur switch_capture_core, isolément de tout fichier réel."""
    FakePyKeePass._stores = {}
    monkeypatch.setattr(core_mod, "PyKeePass", FakePyKeePass)
    monkeypatch.setattr(core_mod, "CredentialsError", _FakeCredentialsError)
    monkeypatch.setattr(core_mod, "KEEPASS_AVAILABLE", True)


@pytest.fixture
def kdbx_path(tmp_path) -> str:
    """Un chemin de fichier `.kdbx` qui existe (vide) — seule la présence compte pour le faux backend."""
    path = tmp_path / "vault.kdbx"
    path.write_bytes(b"")
    return str(path)


@pytest.fixture
def keepass_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simule l'absence du module `pykeepass` (dépendance optionnelle non installée)."""
    monkeypatch.setattr(core_mod, "PyKeePass", None)
    monkeypatch.setattr(core_mod, "KEEPASS_AVAILABLE", False)


# --------------------------------------------------------------------- #
# save/load/delete — avec le faux backend
# --------------------------------------------------------------------- #


def test_save_then_load_round_trip(fake_pykeepass, kdbx_path: str):
    save_ssh_password_to_keepass("10.0.0.1", "admin", "s3cr3t", kdbx_path, "master")
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") == "s3cr3t"


def test_load_returns_none_when_nothing_stored(fake_pykeepass, kdbx_path: str):
    assert load_ssh_password_from_keepass("10.0.0.9", "personne", kdbx_path, "master") is None


def test_save_does_not_leak_across_accounts(fake_pykeepass, kdbx_path: str):
    save_ssh_password_to_keepass("10.0.0.1", "admin", "pass-admin", kdbx_path, "master")
    save_ssh_password_to_keepass("10.0.0.1", "backup", "pass-backup", kdbx_path, "master")
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") == "pass-admin"
    assert load_ssh_password_from_keepass("10.0.0.1", "backup", kdbx_path, "master") == "pass-backup"


def test_save_overwrites_existing_entry(fake_pykeepass, kdbx_path: str):
    save_ssh_password_to_keepass("10.0.0.1", "admin", "old", kdbx_path, "master")
    save_ssh_password_to_keepass("10.0.0.1", "admin", "new", kdbx_path, "master")
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") == "new"


def test_delete_removes_stored_password(fake_pykeepass, kdbx_path: str):
    save_ssh_password_to_keepass("10.0.0.1", "admin", "s3cr3t", kdbx_path, "master")
    deleted = delete_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master")
    assert deleted is True
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") is None


def test_delete_is_idempotent_when_nothing_stored(fake_pykeepass, kdbx_path: str):
    deleted = delete_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master")
    assert deleted is False


def test_load_returns_none_on_wrong_master_password(fake_pykeepass, kdbx_path: str):
    save_ssh_password_to_keepass("10.0.0.1", "admin", "s3cr3t", kdbx_path, "master")
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "wrong") is None


def test_save_raises_on_wrong_master_password(fake_pykeepass, kdbx_path: str):
    save_ssh_password_to_keepass("10.0.0.1", "admin", "s3cr3t", kdbx_path, "master")
    with pytest.raises(RuntimeError):
        save_ssh_password_to_keepass("10.0.0.1", "admin", "x", kdbx_path, "wrong")


def test_save_raises_when_file_missing(fake_pykeepass, tmp_path):
    missing = str(tmp_path / "absent.kdbx")
    with pytest.raises(RuntimeError):
        save_ssh_password_to_keepass("10.0.0.1", "admin", "s3cr3t", missing, "master")


def test_open_keepass_db_wraps_unexpected_exception(monkeypatch, kdbx_path: str):
    """Erreur autre qu'un mot de passe incorrect (format de fichier invalide,
    base corrompue...) : `_open_keepass_db` la convertit aussi en
    RuntimeError explicite, pas seulement `CredentialsError` — branche
    encore non exercée (ligne 1506-1507, audit coverage.py de session 54)."""

    class _CorruptedFilePyKeePass:
        def __init__(self, path: str, password: str | None = None, keyfile: str | None = None) -> None:
            raise ValueError("format de fichier .kdbx invalide (corruption simulée)")

    monkeypatch.setattr(core_mod, "PyKeePass", _CorruptedFilePyKeePass)
    monkeypatch.setattr(core_mod, "CredentialsError", _FakeCredentialsError)

    with pytest.raises(RuntimeError, match="Impossible d'ouvrir le fichier KeePass"):
        core_mod._open_keepass_db(kdbx_path, "master")


def test_save_wraps_unexpected_exception_during_write(fake_pykeepass, kdbx_path: str, monkeypatch):
    """Une erreur pendant l'écriture elle-même (recherche/ajout/sauvegarde de
    l'entrée — ex. disque plein) devient une RuntimeError explicite plutôt
    que l'exception brute de pykeepass — branche encore non exercée (ligne
    1548-1549, audit coverage.py de session 54)."""

    class _SaveFailsPyKeePass(FakePyKeePass):
        def save(self) -> None:
            raise OSError("disque plein (simulation)")

    monkeypatch.setattr(core_mod, "PyKeePass", _SaveFailsPyKeePass)

    with pytest.raises(RuntimeError, match="Échec de l'écriture dans le fichier KeePass"):
        save_ssh_password_to_keepass("10.0.0.1", "admin", "s3cr3t", kdbx_path, "master")


def test_delete_returns_false_when_file_missing(fake_pykeepass, tmp_path):
    """`_open_keepass_db` lève RuntimeError (fichier absent) -> capturée et
    convertie en `False`, même garantie d'idempotence que le cas « rien à
    supprimer » — branche encore non exercée (ligne 1611-1612, audit
    coverage.py de session 54 ; l'équivalent côté `load_*` était déjà
    couvert par `test_load_returns_none_*` ci-dessus)."""
    missing = str(tmp_path / "absent.kdbx")
    assert delete_ssh_password_from_keepass("10.0.0.1", "admin", missing, "master") is False


# --------------------------------------------------------------------- #
# Repli désactivé : pas de chemin, pas de mot de passe maître, ou module absent
# --------------------------------------------------------------------- #


def test_load_returns_none_without_path(fake_pykeepass):
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", None, "master") is None


def test_load_returns_none_without_master_password(fake_pykeepass, kdbx_path: str):
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, None) is None


def test_delete_returns_false_without_path(fake_pykeepass):
    assert delete_ssh_password_from_keepass("10.0.0.1", "admin", None, "master") is False


def test_load_returns_none_when_module_unavailable(keepass_unavailable, kdbx_path: str):
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") is None


def test_delete_returns_false_when_module_unavailable(keepass_unavailable, kdbx_path: str):
    assert delete_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") is False


def test_save_raises_explicit_error_when_module_unavailable(keepass_unavailable, kdbx_path: str):
    with pytest.raises(RuntimeError):
        save_ssh_password_to_keepass("10.0.0.1", "admin", "s3cr3t", kdbx_path, "master")


# --------------------------------------------------------------------- #
# Câblage CLI : keyring toujours prioritaire, KeePass en dernier recours
# --------------------------------------------------------------------- #


def test_maybe_fill_password_falls_back_to_keepass_when_keyring_empty(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", False)
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    save_ssh_password_to_keepass("10.0.0.1", "admin", "from-keepass", kdbx_path, "master")
    raw = {"switch_ip": "10.0.0.1", "ssh_user": "admin"}
    cli_mod._maybe_fill_password_from_keyring(raw, keepass_path=kdbx_path)
    assert raw["ssh_password"] == "from-keepass"


def test_maybe_fill_password_prefers_keyring_over_keepass(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    save_ssh_password_to_keepass("10.0.0.1", "admin", "from-keepass", kdbx_path, "master")
    monkeypatch.setattr(cli_mod, "load_ssh_password_from_keyring", lambda ip, user: "from-keyring")
    raw = {"switch_ip": "10.0.0.1", "ssh_user": "admin"}
    cli_mod._maybe_fill_password_from_keyring(raw, keepass_path=kdbx_path)
    assert raw["ssh_password"] == "from-keyring"


def test_maybe_fill_password_env_var_wins_over_keepass(fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SWITCH_SSH_PASSWORD", "from-env")
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    save_ssh_password_to_keepass("10.0.0.1", "admin", "from-keepass", kdbx_path, "master")
    raw = {"switch_ip": "10.0.0.1", "ssh_user": "admin"}
    cli_mod._maybe_fill_password_from_keyring(raw, keepass_path=kdbx_path)
    assert "ssh_password" not in raw


def test_maybe_fill_password_noop_without_keepass_master_password(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    monkeypatch.delenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", raising=False)
    save_ssh_password_to_keepass("10.0.0.1", "admin", "from-keepass", kdbx_path, "master")
    raw = {"switch_ip": "10.0.0.1", "ssh_user": "admin"}
    cli_mod._maybe_fill_password_from_keyring(raw, keepass_path=kdbx_path)
    assert "ssh_password" not in raw


def test_build_config_end_to_end_fills_password_from_keepass(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", False)
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    save_ssh_password_to_keepass("10.0.0.1", "admin", "from-keepass", kdbx_path, "master")
    args = argparse.Namespace(
        config=None,
        switch_ip="10.0.0.1",
        ssh_user="admin",
        ssh_password=None,
        capture_interface="GigabitEthernet1/0/1",
        keepass_path=kdbx_path,
    )
    for field_name in cli_mod._CONFIG_FIELDS:
        if not hasattr(args, field_name):
            setattr(args, field_name, None)
    cfg = cli_mod.build_config(args)
    assert cfg.ssh_password == "from-keepass"


# --------------------------------------------------------------------- #
# Câblage CLI : _apply_password_keyring_actions, repli KeePass uniquement
# quand le trousseau système est absent
# --------------------------------------------------------------------- #


class _NamespaceStub(argparse.Namespace):
    remember_password: ClassVar[bool] = False
    forget_password: ClassVar[bool] = False
    keepass_path: ClassVar[str | None] = None


def test_apply_actions_remember_falls_back_to_keepass_when_keyring_unavailable(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", False)
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    args = _NamespaceStub(remember_password=True, forget_password=False, keepass_path=kdbx_path)
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") == "s3cr3t"


def test_apply_actions_forget_falls_back_to_keepass_when_keyring_unavailable(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", False)
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    save_ssh_password_to_keepass("10.0.0.1", "admin", "s3cr3t", kdbx_path, "master")
    args = _NamespaceStub(remember_password=False, forget_password=True, keepass_path=kdbx_path)
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") is None


def test_apply_actions_does_not_touch_keepass_when_keyring_available(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    # Le trousseau système reste toujours prioritaire : si `keyring` est
    # disponible, le repli KeePass ne doit même pas être consulté, même si
    # --keepass-path est fourni par ailleurs (ex. réglage laissé dans
    # config.yaml après une migration).
    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", True)
    monkeypatch.setattr(cli_mod, "save_ssh_password_to_keyring", lambda ip, user, pw: None)
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    args = _NamespaceStub(remember_password=True, forget_password=False, keepass_path=kdbx_path)
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") is None


def test_apply_actions_remember_without_keepass_path_warns_but_does_not_raise(
    fake_pykeepass, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", False)
    args = _NamespaceStub(remember_password=True, forget_password=False, keepass_path=None)
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")


def test_apply_actions_missing_keepass_path_attribute_defaults_to_none(fake_pykeepass, monkeypatch: pytest.MonkeyPatch):
    # Sous-parseur qui n'expose pas --keepass-path (ex. 'mirror') : getattr(...,
    # None) ne doit jamais lever d'AttributeError.
    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", False)
    args = argparse.Namespace()
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")


def test_apply_actions_remember_keepass_save_failure_warns_but_does_not_raise(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    """Repli KeePass disponible, mais `save_ssh_password_to_keepass` échoue
    (ex. base corrompue, droits) : avalé en warning, ne remonte jamais —
    même garantie que pour le trousseau système (voir
    `test_apply_actions_remember_*` dans test_keyring_password.py). Seule
    branche de `_apply_password_keyring_actions` encore non exercée, repérée
    via l'audit `coverage.py` de la session 51."""

    def _raise(*_args, **_kwargs):
        raise RuntimeError("Échec de l'écriture dans le fichier KeePass : disque plein")

    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", False)
    monkeypatch.setattr(cli_mod, "save_ssh_password_to_keepass", _raise)
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    args = _NamespaceStub(remember_password=True, forget_password=False, keepass_path=kdbx_path)

    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")  # ne doit pas lever

    # Rien n'a été réellement écrit, puisque save_ssh_password_to_keepass a
    # été remplacée par une fonction qui échoue toujours.
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") is None


# --------------------------------------------------------------------- #
# Analyseur d'arguments : --keepass-path exposé sur capture/inspect
# --------------------------------------------------------------------- #


def test_argparser_exposes_keepass_path_on_capture():
    parser = cli_mod.build_arg_parser()
    args = parser.parse_args(
        [
            "capture",
            "--switch-ip",
            "10.0.0.1",
            "--ssh-user",
            "admin",
            "--capture-interface",
            "GigabitEthernet1/0/1",
            "--keepass-path",
            "/tmp/vault.kdbx",
        ]
    )
    assert args.keepass_path == "/tmp/vault.kdbx"


def test_argparser_exposes_keepass_path_on_inspect():
    parser = cli_mod.build_arg_parser()
    args = parser.parse_args(
        ["inspect", "--switch-ip", "10.0.0.1", "--ssh-user", "admin", "--keepass-path", "/tmp/vault.kdbx"]
    )
    assert args.keepass_path == "/tmp/vault.kdbx"


# --------------------------------------------------------------------- #
# Fichier de clé KeePass additionnel (candidat #8, audit Context7 session
# 56) — même principe que keepass_path/keepass_master_password partout où
# ils apparaissent, mais jamais utilisé seul : le mot de passe maître reste
# toujours requis par ce dépôt (choix délibéré, pas une limite de
# pykeepass — voir docstring de _open_keepass_db).
# --------------------------------------------------------------------- #


class FakePyKeePassRequiringKeyfile(FakePyKeePass):
    """Simule une base dont le fichier de clé est réellement vérifié.

    `FakePyKeePass` mémorise `keyfile` sans jamais le contrôler (voir sa
    docstring) : insuffisant pour prouver qu'un `keyfile` erroné ferait
    échouer l'ouverture avec le vrai `pykeepass`. Ce faux backend, utilisé
    uniquement par les deux tests d'erreur ci-dessous, ajoute cette
    vérification explicite.
    """

    def __init__(self, path: str, password: str | None = None, keyfile: str | None = None) -> None:
        super().__init__(path, password=password, keyfile=keyfile)
        store = FakePyKeePass._stores[path]
        if "required_keyfile" in store and store["required_keyfile"] != keyfile:
            raise _FakeCredentialsError("fichier de clé KeePass incorrect ou manquant (simulation de test)")


def test_open_keepass_db_passes_keyfile_through_to_pykeepass(fake_pykeepass, kdbx_path: str):
    """Vérifie que `keepass_keyfile` atteint bien `PyKeePass(..., keyfile=...)`
    — pas seulement qu'il est accepté en paramètre sans erreur."""
    kp = core_mod._open_keepass_db(kdbx_path, "master", keepass_keyfile="/etc/switch-capture/vault.key")
    assert kp.keyfile == "/etc/switch-capture/vault.key"


def test_save_then_load_round_trip_with_keyfile(fake_pykeepass, kdbx_path: str, monkeypatch):
    monkeypatch.setattr(core_mod, "PyKeePass", FakePyKeePassRequiringKeyfile)
    FakePyKeePass._stores[kdbx_path] = {
        "password": "master",
        "keyfile": None,
        "entries": {},
        "required_keyfile": "/etc/switch-capture/vault.key",
    }
    save_ssh_password_to_keepass(
        "10.0.0.1", "admin", "s3cr3t", kdbx_path, "master", keepass_keyfile="/etc/switch-capture/vault.key"
    )
    assert (
        load_ssh_password_from_keepass(
            "10.0.0.1", "admin", kdbx_path, "master", keepass_keyfile="/etc/switch-capture/vault.key"
        )
        == "s3cr3t"
    )


def test_load_raises_wrong_keyfile_treated_like_wrong_master_password(fake_pykeepass, kdbx_path: str, monkeypatch):
    """Un fichier de clé incorrect est signalé par pykeepass via la même
    `CredentialsError` qu'un mot de passe maître incorrect (confirmé contre
    la documentation pykeepass à jour, session 56) — `load_*` l'avale donc
    déjà silencieusement en `None`, comme pour un mauvais mot de passe."""
    monkeypatch.setattr(core_mod, "PyKeePass", FakePyKeePassRequiringKeyfile)
    FakePyKeePass._stores[kdbx_path] = {
        "password": "master",
        "keyfile": None,
        "entries": {},
        "required_keyfile": "/etc/switch-capture/vault.key",
    }
    assert (
        load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master", keepass_keyfile="/wrong/vault.key")
        is None
    )


def test_delete_with_keyfile_round_trip(fake_pykeepass, kdbx_path: str):
    save_ssh_password_to_keepass("10.0.0.1", "admin", "s3cr3t", kdbx_path, "master", keepass_keyfile="/vault.key")
    deleted = delete_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master", keepass_keyfile="/vault.key")
    assert deleted is True


def test_keepass_functions_work_without_keyfile_argument_at_all(fake_pykeepass, kdbx_path: str):
    """Garde-fou de non-régression explicite : les trois fonctions publiques
    restent utilisables sans jamais mentionner `keepass_keyfile` (valeur par
    défaut `None`), exactement comme avant cette fonctionnalité."""
    save_ssh_password_to_keepass("10.0.0.1", "admin", "s3cr3t", kdbx_path, "master")
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") == "s3cr3t"
    assert delete_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") is True


def test_argparser_exposes_keepass_keyfile_on_capture():
    parser = cli_mod.build_arg_parser()
    args = parser.parse_args(
        [
            "capture",
            "--switch-ip",
            "10.0.0.1",
            "--ssh-user",
            "admin",
            "--capture-interface",
            "GigabitEthernet1/0/1",
            "--keepass-path",
            "/tmp/vault.kdbx",
            "--keepass-keyfile",
            "/tmp/vault.key",
        ]
    )
    assert args.keepass_keyfile == "/tmp/vault.key"


def test_argparser_exposes_keepass_keyfile_on_inspect():
    parser = cli_mod.build_arg_parser()
    args = parser.parse_args(
        [
            "inspect",
            "--switch-ip",
            "10.0.0.1",
            "--ssh-user",
            "admin",
            "--keepass-path",
            "/tmp/vault.kdbx",
            "--keepass-keyfile",
            "/tmp/vault.key",
        ]
    )
    assert args.keepass_keyfile == "/tmp/vault.key"


def test_argparser_keepass_keyfile_defaults_to_none_when_omitted():
    parser = cli_mod.build_arg_parser()
    args = parser.parse_args(
        ["capture", "--switch-ip", "10.0.0.1", "--ssh-user", "admin", "--capture-interface", "GigabitEthernet1/0/1"]
    )
    assert args.keepass_keyfile is None


def test_maybe_fill_password_threads_keyfile_through_to_keepass(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(core_mod, "PyKeePass", FakePyKeePassRequiringKeyfile)
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", False)
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    FakePyKeePass._stores[kdbx_path] = {
        "password": "master",
        "keyfile": None,
        "entries": {},
        "required_keyfile": "/etc/switch-capture/vault.key",
    }
    save_ssh_password_to_keepass(
        "10.0.0.1", "admin", "from-keepass", kdbx_path, "master", keepass_keyfile="/etc/switch-capture/vault.key"
    )
    raw = {"switch_ip": "10.0.0.1", "ssh_user": "admin"}
    cli_mod._maybe_fill_password_from_keyring(
        raw, keepass_path=kdbx_path, keepass_keyfile="/etc/switch-capture/vault.key"
    )
    assert raw["ssh_password"] == "from-keepass"


def test_maybe_fill_password_wrong_keyfile_does_not_find_password(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(core_mod, "PyKeePass", FakePyKeePassRequiringKeyfile)
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", False)
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    FakePyKeePass._stores[kdbx_path] = {
        "password": "master",
        "keyfile": None,
        "entries": {},
        "required_keyfile": "/etc/switch-capture/vault.key",
    }
    raw = {"switch_ip": "10.0.0.1", "ssh_user": "admin"}
    cli_mod._maybe_fill_password_from_keyring(raw, keepass_path=kdbx_path, keepass_keyfile="/wrong/vault.key")
    assert "ssh_password" not in raw


def test_apply_actions_remember_and_forget_thread_keyfile_through(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    """`_apply_password_keyring_actions` (--remember-password/--forget-password)
    doit lui aussi transmettre `--keepass-keyfile`, pas seulement
    `_maybe_fill_password_from_keyring` (chargement automatique)."""
    monkeypatch.setattr(core_mod, "PyKeePass", FakePyKeePassRequiringKeyfile)
    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", False)
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    FakePyKeePass._stores[kdbx_path] = {
        "password": "master",
        "keyfile": None,
        "entries": {},
        "required_keyfile": "/etc/switch-capture/vault.key",
    }
    args = argparse.Namespace(
        remember_password=True,
        forget_password=False,
        keepass_path=kdbx_path,
        keepass_keyfile="/etc/switch-capture/vault.key",
    )
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")
    assert (
        load_ssh_password_from_keepass(
            "10.0.0.1", "admin", kdbx_path, "master", keepass_keyfile="/etc/switch-capture/vault.key"
        )
        == "s3cr3t"
    )

    args = argparse.Namespace(
        remember_password=False,
        forget_password=True,
        keepass_path=kdbx_path,
        keepass_keyfile="/etc/switch-capture/vault.key",
    )
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")
    assert (
        load_ssh_password_from_keepass(
            "10.0.0.1", "admin", kdbx_path, "master", keepass_keyfile="/etc/switch-capture/vault.key"
        )
        is None
    )


def test_apply_actions_missing_keepass_keyfile_attribute_defaults_to_none(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    """Sous-parseur/appelant qui n'expose pas --keepass-keyfile (ex. objet
    `argparse.Namespace` construit à la main sans cet attribut, comme le
    faisaient tous les tests existants avant cette fonctionnalité) :
    `getattr(..., None)` ne doit jamais lever d'AttributeError."""
    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", False)
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    args = argparse.Namespace(remember_password=True, forget_password=False, keepass_path=kdbx_path)
    cli_mod._apply_password_keyring_actions(args, "10.0.0.1", "admin", "s3cr3t")  # ne doit pas lever
    assert load_ssh_password_from_keepass("10.0.0.1", "admin", kdbx_path, "master") == "s3cr3t"


def test_build_config_end_to_end_threads_keyfile_through(
    fake_pykeepass, kdbx_path: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(core_mod, "PyKeePass", FakePyKeePassRequiringKeyfile)
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    monkeypatch.setattr(cli_mod, "KEYRING_AVAILABLE", False)
    monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master")
    FakePyKeePass._stores[kdbx_path] = {
        "password": "master",
        "keyfile": None,
        "entries": {},
        "required_keyfile": "/etc/switch-capture/vault.key",
    }
    save_ssh_password_to_keepass(
        "10.0.0.1", "admin", "from-keepass", kdbx_path, "master", keepass_keyfile="/etc/switch-capture/vault.key"
    )
    args = argparse.Namespace(
        config=None,
        switch_ip="10.0.0.1",
        ssh_user="admin",
        ssh_password=None,
        capture_interface="GigabitEthernet1/0/1",
        keepass_path=kdbx_path,
        keepass_keyfile="/etc/switch-capture/vault.key",
    )
    for field_name in cli_mod._CONFIG_FIELDS:
        if not hasattr(args, field_name):
            setattr(args, field_name, None)
    cfg = cli_mod.build_config(args)
    assert cfg.ssh_password == "from-keepass"
