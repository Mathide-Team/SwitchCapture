"""Tests du gestionnaire Ctrl+C (SIGINT) de l'app GTK4 (features.md,
point 10, reformulé le 28/08/2026 : « Ctrl+C remonte toujours un
Traceback/KeyboardInterrupt brut au lieu d'une sortie propre »).

Vérifie que CaptureApp installe un gestionnaire SIGINT via
GLib.unix_signal_add (do_activate) et que ce gestionnaire ferme la fenêtre
principale par le même chemin que le bouton de fermeture natif / « Quitter »
du menu hamburger (_on_close_request), sans dupliquer cette logique.

Nécessite PyGObject/GTK4 ET un affichage graphique accessible (Xvfb, voir
CLAUDE.md) -- se saute proprement (pytest.skip) si l'un des deux manque,
même principe que test_gui_preferences_window.py. Ne re-teste pas la
remise SIGINT au niveau OS elle-même (mécanisme interne à GLib, aucune
valeur à re-vérifier ici) : _on_sigint est appelé directement, exactement
comme test_gui_preferences_window.py::TestPreferencesWindowLifecycle le
fait déjà pour _on_close_request.
"""

from __future__ import annotations

import pytest
from conftest import require_gtk4

gi = require_gtk4()

from gi.repository import GLib

import switch_capture_gtk as gtk_app


def _make_app_and_window():
    """Construit une CaptureApp réelle et déclenche son activation (même
    mécanisme que le programme réel : app.run() -> signal "activate" ->
    CaptureApp.do_activate(), qui installe le gestionnaire SIGINT), ou
    saute le test si aucun affichage graphique n'est accessible (pas
    d'Xvfb dans cet environnement) -- même principe que
    test_gui_preferences_window.py::_make_window, mais en passant par
    CaptureApp (pas directement par CaptureWindow) puisque l'installation
    du gestionnaire SIGINT a lieu dans do_activate(), pas dans
    CaptureWindow.__init__. connect_after (et non connect) : garantit que
    notre a.quit() s'exécute après le gestionnaire par défaut du signal
    "activate" (do_activate lui-même), pas avant.
    """
    app = gtk_app.CaptureApp()
    app.connect_after("activate", lambda a: a.quit())
    app.run([])
    if app._window is None:
        pytest.skip("pas d'affichage graphique disponible (do_activate a échoué)")
    return app, app._window


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
# Installation du gestionnaire (do_activate -> _install_sigint_handler)
# --------------------------------------------------------------------- #


class TestSigintHandlerInstalled:
    def test_source_registered_after_activate(self):
        app, _win = _make_app_and_window()
        assert app._sigint_source_id is not None

    def test_installing_twice_does_not_register_a_second_source(self):
        app, _win = _make_app_and_window()
        first_id = app._sigint_source_id
        app._install_sigint_handler()
        assert app._sigint_source_id == first_id


# --------------------------------------------------------------------- #
# _on_sigint : même chemin de fermeture que le bouton natif / « Quitter »
# --------------------------------------------------------------------- #


class TestOnSigintClosesLikeCloseRequest:
    def test_stops_running_captures(self, tmp_path, monkeypatch):
        """Ctrl+C doit arrêter les captures en cours exactement comme

        _on_close_request (state.stop_event), pas les laisser tourner
        derrière un process déjà terminé.
        """
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))
        app, win = _make_app_and_window()
        _fill_required_fields(win)
        cfg = win._build_config()
        session = gtk_app.CaptureSession(cfg)
        session.capture_running = True
        win._sessions.append(session)

        assert not session.state.stop_event.is_set()
        result = app._on_sigint()
        _pump_main_loop()

        assert session.state.stop_event.is_set()
        assert result is False  # GLib.SOURCE_REMOVE : un seul déclenchement suffit

    def test_closes_open_preferences_window(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))
        app, win = _make_app_and_window()
        win._open_preferences_window()
        assert win._prefs_window is not None

        app._on_sigint()
        _pump_main_loop()

        assert win._prefs_window is None

    def test_without_window_is_a_harmless_no_op(self):
        """Garde-fou défensif : ne doit jamais lever, même dans un état

        normalement impossible en pratique (do_activate n'appelle
        _install_sigint_handler qu'après avoir posé self._window).
        """
        app = gtk_app.CaptureApp()
        assert app._on_sigint() is False
