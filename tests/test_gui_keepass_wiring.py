"""Tests du câblage GTK4 du repli KeePass pour la mémorisation du mot de
passe SSH (voir features.md, section « Repli KeePass pour le mot de passe
SSH (27/08/2026, suite) »).

Depuis features.md, point 1 (« Menu et préférences », 28/08/2026),
`keepass_path` n'est plus un champ du formulaire principal
(`win._entries`) : il vit dans la page Préférences (menu ☰), exposé via
`win._prefs_entries["keepass_path"]` une fois la fenêtre ouverte (voir
`_open_preferences_window`), et sa valeur courante est lue/écrite via
`win._prefs["keepass_path"]` (voir `_save_preferences`). Les tests
ci-dessous ont été adaptés en conséquence — voir
test_gui_preferences_window.py pour la couverture générale de la page
Préférences elle-même (chargement, sauvegarde, cycle de vie).

Nécessite PyGObject/GTK4 ET un affichage graphique accessible (Xvfb en
CI/sandbox, voir CLAUDE.md) — se saute proprement (`pytest.skip`) si l'un
des deux manque, même principe que les autres tests GUI de ce dépôt.
"""

from __future__ import annotations

import pytest
from conftest import require_gtk4

gi = require_gtk4()

from gi.repository import Gtk

import switch_capture_gtk as gtk_app


def _make_window(tmp_path=None, monkeypatch=None):
    """Construit une CaptureWindow réelle, ou saute le test si aucun
    affichage graphique n'est accessible (pas d'Xvfb dans cet
    environnement). Si `tmp_path`/`monkeypatch` sont fournis, redirige
    DEFAULT_PREFS_CONFIG_PATH vers un fichier temporaire pour ne jamais
    lire/écrire le config.yaml réel du dépôt."""
    if tmp_path is not None and monkeypatch is not None:
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))

    app = Gtk.Application(application_id="org.transcende.switch_capture.tests.keepass")
    holder: dict = {}

    def on_activate(a):
        try:
            holder["win"] = gtk_app.CaptureWindow(a)
        except RuntimeError as exc:
            holder["error"] = exc
        a.quit()

    app.connect("activate", on_activate)
    app.run([])

    if "error" in holder:
        pytest.skip(f"pas d'affichage graphique disponible : {holder['error']}")
    return holder["win"]


def _fill_required_fields(win, switch_ip="10.0.0.1", ssh_user="mathilde") -> None:
    win._entries["switch_ip"].set_text(switch_ip)
    win._entries["ssh_user"].set_text(ssh_user)
    win._entries["ssh_password"].set_text("secret")
    win._entries["capture_interface"].set_text("GigabitEthernet1/0/1")


class TestKeepassFieldNoLongerInMainForm:
    def test_keepass_path_not_in_main_form_entries_regardless_of_backend(self, tmp_path, monkeypatch):
        """Contrairement à avant le 28/08/2026, le champ n'est plus

        jamais dans le formulaire principal, même quand le trousseau
        système est indisponible : il vit désormais dans la page
        Préférences (voir TestKeepassFieldInPreferencesPage ci-dessous).
        """
        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", False)
        monkeypatch.setattr(gtk_app, "KEEPASS_AVAILABLE", True)
        win = _make_window(tmp_path, monkeypatch)
        assert "keepass_path" not in win._entries
        assert "keepass_path" not in win._rows


class TestKeepassFieldInPreferencesPage:
    def test_field_enabled_when_keyring_unavailable_and_keepass_available(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", False)
        monkeypatch.setattr(gtk_app, "KEEPASS_AVAILABLE", True)
        win = _make_window(tmp_path, monkeypatch)
        win._open_preferences_window()
        assert "keepass_path" in win._prefs_entries
        assert win._prefs_entries["keepass_path"].get_sensitive() is True

    def test_field_disabled_when_keyring_available(self, tmp_path, monkeypatch):
        """Le champ reste affiché (réglage persistant, potentiellement

        utile si le trousseau système devient indisponible plus tard)
        mais désactivé, plutôt que masqué — voir _open_preferences_window.
        """
        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", True)
        monkeypatch.setattr(gtk_app, "KEEPASS_AVAILABLE", True)
        win = _make_window(tmp_path, monkeypatch)
        win._open_preferences_window()
        assert win._prefs_entries["keepass_path"].get_sensitive() is False

    def test_field_disabled_when_pykeepass_missing_too(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", False)
        monkeypatch.setattr(gtk_app, "KEEPASS_AVAILABLE", False)
        win = _make_window(tmp_path, monkeypatch)
        win._open_preferences_window()
        assert win._prefs_entries["keepass_path"].get_sensitive() is False


class TestRememberRowSensitivityInMainForm:
    """La case « mémoriser »/bouton « oublier » (self._entries, formulaire

    principal) : inchangés par le déménagement de keepass_path, toujours
    conditionnés à la disponibilité d'AU MOINS un backend (trousseau OU
    KeePass).
    """

    def test_remember_row_disabled_when_no_backend_at_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", False)
        monkeypatch.setattr(gtk_app, "KEEPASS_AVAILABLE", False)
        win = _make_window(tmp_path, monkeypatch)
        assert win._entries["remember_password"].get_sensitive() is False

    def test_remember_row_enabled_when_only_keepass_available(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", False)
        monkeypatch.setattr(gtk_app, "KEEPASS_AVAILABLE", True)
        win = _make_window(tmp_path, monkeypatch)
        assert win._entries["remember_password"].get_sensitive() is True


class TestKeepassNotPartOfConfigOrTemplate:
    def test_keepass_path_not_a_config_field(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", False)
        monkeypatch.setattr(gtk_app, "KEEPASS_AVAILABLE", True)
        win = _make_window(tmp_path, monkeypatch)
        _fill_required_fields(win)
        win._prefs["keepass_path"] = "/tmp/whatever.kdbx"
        cfg = win._build_config()
        assert not hasattr(cfg, "keepass_path")

    def test_keepass_path_not_in_template_dict(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", False)
        monkeypatch.setattr(gtk_app, "KEEPASS_AVAILABLE", True)
        win = _make_window(tmp_path, monkeypatch)
        _fill_required_fields(win)
        win._prefs["keepass_path"] = "/tmp/whatever.kdbx"
        raw = win._collect_raw_form_values()
        assert "keepass_path" not in raw


class TestMaybeRememberPasswordUsesKeepassFallback:
    def test_save_called_via_keepass_when_keyring_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", False)
        monkeypatch.setattr(gtk_app, "KEEPASS_AVAILABLE", True)
        monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master-pw")
        win = _make_window(tmp_path, monkeypatch)
        _fill_required_fields(win)
        win._prefs["keepass_path"] = "/tmp/base.kdbx"
        win._entries["remember_password"].set_active(True)

        calls = []

        def fake_save(switch_ip, ssh_user, password, keepass_path, keepass_master_password):
            calls.append((switch_ip, ssh_user, password, keepass_path, keepass_master_password))

        monkeypatch.setattr(gtk_app, "save_ssh_password_to_keepass", fake_save)

        cfg = win._build_config()
        win._maybe_remember_password(cfg)
        # L'écriture se fait dans un thread daemon : on laisse GTK/le thread
        # se synchroniser brièvement (même approche que les autres tests
        # GUI de ce dépôt qui touchent des workers en tâche de fond).
        import time

        for _ in range(50):
            if calls:
                break
            time.sleep(0.02)

        assert calls == [("10.0.0.1", "mathilde", "secret", "/tmp/base.kdbx", "master-pw")]

    def test_shows_dialog_when_no_backend_ready(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", False)
        monkeypatch.setattr(gtk_app, "KEEPASS_AVAILABLE", True)
        monkeypatch.delenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", raising=False)
        win = _make_window(tmp_path, monkeypatch)
        _fill_required_fields(win)
        # keepass_path laissé à sa valeur par défaut (""), master password
        # absent : rien n'est prêt.
        win._entries["remember_password"].set_active(True)

        dialogs = []
        monkeypatch.setattr(win, "_show_dialog", lambda title, body: dialogs.append((title, body)))

        called = []
        monkeypatch.setattr(gtk_app, "save_ssh_password_to_keepass", lambda *a, **k: called.append(a))

        cfg = win._build_config()
        win._maybe_remember_password(cfg)

        assert called == []
        assert len(dialogs) == 1
        assert dialogs[0][0] == "Mémorisation impossible"


class TestForgetPasswordFallsBackToKeepass:
    def test_forget_calls_keepass_delete_when_keyring_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", False)
        monkeypatch.setattr(gtk_app, "KEEPASS_AVAILABLE", True)
        monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "master-pw")
        win = _make_window(tmp_path, monkeypatch)
        _fill_required_fields(win)
        win._prefs["keepass_path"] = "/tmp/base.kdbx"

        monkeypatch.setattr(gtk_app, "delete_ssh_password_from_keyring", lambda *a, **k: False)

        calls = []

        def fake_delete(switch_ip, ssh_user, keepass_path, keepass_master_password):
            calls.append((switch_ip, ssh_user, keepass_path, keepass_master_password))
            return True

        monkeypatch.setattr(gtk_app, "delete_ssh_password_from_keepass", fake_delete)

        win._on_forget_password(None)

        import time

        for _ in range(50):
            if calls:
                break
            time.sleep(0.02)

        assert calls == [("10.0.0.1", "mathilde", "/tmp/base.kdbx", "master-pw")]


class TestResolveKeepassMasterPassword:
    def test_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "abc")
        assert gtk_app.CaptureWindow._resolve_keepass_master_password() == "abc"

    def test_none_when_absent(self, monkeypatch):
        monkeypatch.delenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", raising=False)
        assert gtk_app.CaptureWindow._resolve_keepass_master_password() is None
