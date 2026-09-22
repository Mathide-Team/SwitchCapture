"""Tests du menu hamburger et de la page Préférences GTK4 (features.md,
point 1 « Menu et préférences ») : retrait de slot/modèle/.bin forcé/
keepass_path du formulaire principal, chargement au démarrage depuis
config.yaml, actions win.preferences/win.quit-app, cycle de vie de la
fenêtre Préférences, et `_save_preferences` (persistance + mise à jour de
`self._prefs`).

Nécessite PyGObject/GTK4 ET un affichage graphique accessible (Xvfb, voir
CLAUDE.md) -- se saute proprement (pytest.skip) si l'un des deux manque,
même principe que test_gui_new_fields.py/test_gui_mirroring.py. Le pendant
sans GTK4 (persistance YAML pure, fusion, retrait de clé) est couvert par
test_gui_preferences_config.py.
"""

from __future__ import annotations

import pytest
from conftest import require_gtk4

gi = require_gtk4()

from gi.repository import Gio, GLib, Gtk

import switch_capture_core as core
import switch_capture_gtk as gtk_app


def _make_window():
    """Construit une CaptureWindow réelle, ou saute le test si aucun
    affichage graphique n'est accessible (pas d'Xvfb dans cet
    environnement)."""
    app = Gtk.Application(application_id="org.transcende.switch_capture.tests")
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


def _fill_required_fields(win) -> None:
    win._entries["switch_ip"].set_text("10.0.0.1")
    win._entries["ssh_user"].set_text("mathilde")
    win._entries["ssh_password"].set_text("secret")
    win._entries["capture_interface"].set_text("GigabitEthernet1/0/1")


def _pump_main_loop() -> None:
    """Traite les évènements GTK4 en attente (ex: signal close-request

    émis par Gtk.Window.close()) sans bloquer si la file est vide.
    """
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


# --------------------------------------------------------------------- #
# Retrait des 3 champs du formulaire principal (+ keepass_path)
# --------------------------------------------------------------------- #


class TestFieldsRemovedFromMainForm:
    def test_slot_model_feature_bin_path_keepass_path_no_longer_in_entries(self):
        win = _make_window()
        for key in ("slot", "model", "feature_bin_path", "keepass_path"):
            assert key not in win._entries, f"{key} devrait avoir été retiré du formulaire principal"
            assert key not in win._rows, f"{key} devrait avoir été retiré du formulaire principal"

    def test_feature_bin_dir_and_import_bin_still_present(self):
        """Seuls slot/modèle/.bin forcé bougent -- le dépôt .bin lui-même

        (feature_bin_dir) et son bouton d'import restent dans le
        formulaire principal (voir CLAUDE.md, choix documenté du
        28/08/2026 de ne pas déplacer plus que ces 3 champs).
        """
        win = _make_window()
        assert "feature_bin_dir" in win._entries
        assert "feature_bin_dir" in win._rows


# --------------------------------------------------------------------- #
# Chargement de self._prefs au démarrage
# --------------------------------------------------------------------- #


class TestPreferencesLoadedAtStartup:
    def test_defaults_when_no_config_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))
        win = _make_window()
        assert win._prefs == gtk_app.DEFAULT_PREFERENCES

    def test_prefs_loaded_from_existing_config_file(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.yaml"
        core.save_gui_preferences(
            config_path,
            {"slot": 4, "model": "5130EI", "feature_bin_path": "/opt/forced.bin", "keepass_path": "/opt/vault.kdbx"},
        )
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(config_path))
        win = _make_window()
        assert win._prefs["slot"] == 4
        assert win._prefs["model"] == "5130EI"
        assert win._prefs["feature_bin_path"] == "/opt/forced.bin"
        assert win._prefs["keepass_path"] == "/opt/vault.kdbx"

    def test_partial_config_file_keeps_other_defaults(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.yaml"
        core.save_gui_preferences(config_path, {"slot": 9})
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(config_path))
        win = _make_window()
        assert win._prefs["slot"] == 9
        assert win._prefs["model"] is None
        assert win._prefs["feature_bin_path"] == ""
        assert win._prefs["keepass_path"] == ""

    def test_config_file_with_unrelated_keys_only_reads_preferences_fields(self, tmp_path, monkeypatch):
        """Un config.yaml déjà utilisé pour `switch-capture capture

        --config` (switch_ip, ssh_user...) ne doit ni faire planter le
        chargement des préférences ni s'y mélanger.
        """
        config_path = tmp_path / "config.yaml"
        import yaml

        config_path.write_text(
            yaml.safe_dump({"switch_ip": "10.0.0.9", "ssh_user": "alice", "capture_interface": "eth0"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(config_path))
        win = _make_window()
        assert win._prefs == gtk_app.DEFAULT_PREFERENCES

    def test_invalid_yaml_falls_back_to_defaults_without_crashing(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("slot: [1, 2\n", encoding="utf-8")  # crochet non refermé
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(config_path))
        win = _make_window()  # ne doit pas lever
        assert win._prefs == gtk_app.DEFAULT_PREFERENCES


# --------------------------------------------------------------------- #
# self._prefs pris en compte par _build_config
# --------------------------------------------------------------------- #


class TestBuildConfigUsesPreferences:
    def test_build_config_uses_default_prefs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))
        win = _make_window()
        _fill_required_fields(win)
        cfg = win._build_config()
        assert cfg.slot == 1
        assert cfg.model is None
        assert cfg.feature_bin_path is None

    def test_build_config_uses_loaded_prefs(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.yaml"
        core.save_gui_preferences(config_path, {"slot": 7, "model": "MSR4000", "feature_bin_path": "/opt/x.bin"})
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(config_path))
        win = _make_window()
        _fill_required_fields(win)
        cfg = win._build_config()
        assert cfg.slot == 7
        assert cfg.model == "MSR4000"
        assert cfg.feature_bin_path == "/opt/x.bin"

    def test_build_config_reflects_prefs_change_within_session(self, tmp_path, monkeypatch):
        """Un _save_preferences() met à jour self._prefs immédiatement,

        sans attendre un redémarrage -- une capture ajoutée juste après
        doit refléter le nouveau réglage.
        """
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))
        win = _make_window()
        _fill_required_fields(win)
        win._save_preferences(slot=12, model="5140EI", feature_bin_path="", keepass_path="")
        cfg = win._build_config()
        assert cfg.slot == 12
        assert cfg.model == "5140EI"


# --------------------------------------------------------------------- #
# _save_preferences : persistance + mise à jour de self._prefs
# --------------------------------------------------------------------- #


class TestSavePreferences:
    def test_save_updates_in_memory_prefs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))
        win = _make_window()
        win._save_preferences(slot=3, model="5130HI", feature_bin_path="/opt/f.bin", keepass_path="/opt/v.kdbx")
        assert win._prefs["slot"] == 3
        assert win._prefs["model"] == "5130HI"
        assert win._prefs["feature_bin_path"] == "/opt/f.bin"
        assert win._prefs["keepass_path"] == "/opt/v.kdbx"

    def test_save_persists_to_disk(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.yaml"
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(config_path))
        win = _make_window()
        win._save_preferences(slot=3, model="5130HI", feature_bin_path="/opt/f.bin", keepass_path="/opt/v.kdbx")
        on_disk = core.load_gui_preferences(config_path)
        assert on_disk == {
            "slot": 3,
            "model": "5130HI",
            "feature_bin_path": "/opt/f.bin",
            "keepass_path": "/opt/v.kdbx",
        }

    def test_save_empty_strings_remove_keys_from_disk(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.yaml"
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(config_path))
        win = _make_window()
        win._save_preferences(slot=3, model="5130HI", feature_bin_path="/opt/f.bin", keepass_path="/opt/v.kdbx")
        win._save_preferences(slot=3, model=None, feature_bin_path="", keepass_path="")
        assert core.load_gui_preferences(config_path) == {"slot": 3}
        assert win._prefs["model"] is None
        assert win._prefs["feature_bin_path"] == ""
        assert win._prefs["keepass_path"] == ""

    def test_save_preserves_unrelated_keys_already_on_disk(self, tmp_path, monkeypatch):
        """Un config.yaml partagé avec `switch-capture capture --config`

        ne doit jamais perdre switch_ip/ssh_user/etc. quand la page
        Préférences enregistre.
        """
        config_path = tmp_path / "config.yaml"
        import yaml

        config_path.write_text(yaml.safe_dump({"switch_ip": "10.0.0.9", "ssh_user": "alice"}), encoding="utf-8")
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(config_path))
        win = _make_window()
        win._save_preferences(slot=2, model=None, feature_bin_path="", keepass_path="")
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert raw["switch_ip"] == "10.0.0.9"
        assert raw["ssh_user"] == "alice"
        assert raw["slot"] == 2


# --------------------------------------------------------------------- #
# Menu hamburger : actions win.preferences / win.quit-app
# --------------------------------------------------------------------- #


class TestHamburgerMenuActions:
    def test_preferences_and_quit_actions_exist(self):
        win = _make_window()
        assert isinstance(win.lookup_action("preferences"), Gio.SimpleAction)
        assert isinstance(win.lookup_action("quit-app"), Gio.SimpleAction)

    def test_activating_preferences_action_opens_window(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))
        win = _make_window()
        assert win._prefs_window is None
        win.lookup_action("preferences").activate(None)
        assert win._prefs_window is not None
        assert isinstance(win._prefs_window, Gtk.Window)


# --------------------------------------------------------------------- #
# Cycle de vie de la fenêtre Préférences
# --------------------------------------------------------------------- #


class TestPreferencesWindowLifecycle:
    def test_opening_twice_reuses_same_window(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))
        win = _make_window()
        win._open_preferences_window()
        first = win._prefs_window
        win._open_preferences_window()
        assert win._prefs_window is first

    def test_closing_preferences_window_clears_reference(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))
        win = _make_window()
        win._open_preferences_window()
        assert win._prefs_window is not None
        win._prefs_window.close()
        _pump_main_loop()
        assert win._prefs_window is None

    def test_main_window_close_request_also_closes_open_preferences_window(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))
        win = _make_window()
        win._open_preferences_window()
        assert win._prefs_window is not None
        win._on_close_request(win)
        assert win._prefs_window is None


# --------------------------------------------------------------------- #
# _on_edit_session : resynchronisation de self._prefs (pas de dérive silencieuse)
# --------------------------------------------------------------------- #


class TestEditSessionResyncsPreferences:
    def test_editing_a_session_restores_its_own_slot_model_bin(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))
        win = _make_window()
        _fill_required_fields(win)

        # Capture ajoutée avec les préférences "d'origine".
        win._save_preferences(slot=1, model="5130EI", feature_bin_path="", keepass_path="")
        cfg1 = win._build_config()
        session = gtk_app.CaptureSession(cfg1)
        win._sessions.append(session)

        # Les préférences changent avant d'éditer cette capture.
        win._save_preferences(slot=9, model="MSR4000", feature_bin_path="", keepass_path="")

        win._on_edit_session(None, session)
        assert win._prefs["slot"] == 1
        assert win._prefs["model"] == "5130EI"

        # Soumettre à nouveau doit donc reconstruire avec les valeurs
        # d'origine, pas celles (différentes) actuellement en Préférences.
        cfg2 = win._build_config()
        assert cfg2.slot == 1
        assert cfg2.model == "5130EI"
