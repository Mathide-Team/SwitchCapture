"""Tests du garde-fou empêchant de lancer une installation pendant qu'une
capture est déjà en cours (voir features.md, section « Comportement de
capture », point 7 : « Empêcher le lancement d'une installation si une
trace est déjà en cours : bouton grisé et/ou pop-up d'alerte »).

Nécessite PyGObject/GTK4 ET un affichage graphique accessible (Xvfb en
CI/sandbox, voir CLAUDE.md) — se saute proprement (`pytest.skip`) si l'un
des deux manque, même principe que tests/test_gui_new_fields.py.
"""

from __future__ import annotations

import pytest
from conftest import require_gtk4

gi = require_gtk4()

from gi.repository import Gtk

import switch_capture_core as core
import switch_capture_gtk as gtk_app


def _make_window():
    """Construit une CaptureWindow réelle, ou saute le test si aucun
    affichage graphique n'est accessible (pas d'Xvfb dans cet
    environnement)."""
    app = Gtk.Application(application_id="org.transcende.switch_capture.tests.installguard")
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


def _make_session(**overrides) -> gtk_app.CaptureSession:
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "capture_interface": "GigabitEthernet1/0/1",
    }
    base.update(overrides)
    return gtk_app.CaptureSession(core.Config(**base))


class TestInstallButtonGreyedWhileRunning:
    def test_button_sensitive_with_no_running_capture(self):
        win = _make_window()
        win._sessions.append(_make_session())
        win._refresh_install_list()
        assert win._btn_install.get_sensitive() is True

    def test_button_insensitive_while_a_capture_is_running(self):
        win = _make_window()
        session = _make_session()
        session.capture_running = True
        win._sessions.append(session)
        win._refresh_install_list()
        assert win._btn_install.get_sensitive() is False

    def test_button_sensitive_again_once_capture_stops(self):
        win = _make_window()
        session = _make_session()
        session.capture_running = True
        win._sessions.append(session)
        win._refresh_install_list()
        assert win._btn_install.get_sensitive() is False

        session.capture_running = False
        win._refresh_install_list()
        assert win._btn_install.get_sensitive() is True


class TestInstallAllRefusesWhileRunning:
    def test_on_install_all_does_not_start_prepare_while_running(self, monkeypatch):
        win = _make_window()
        running_session = _make_session(switch_ip="10.0.0.1")
        pending_session = _make_session(switch_ip="10.0.0.2")
        running_session.capture_running = True
        win._sessions.extend([running_session, pending_session])

        started: list[gtk_app.CaptureSession] = []
        monkeypatch.setattr(win, "_start_prepare", lambda session: started.append(session))

        dialogs: list[tuple[str, str]] = []
        monkeypatch.setattr(win, "_show_dialog", lambda title, body: dialogs.append((title, body)))

        win._on_install_all(win._btn_install)

        assert started == []
        assert pending_session.install_status == "pending"
        assert dialogs, "une alerte aurait dû être affichée"
        assert "impossible" in dialogs[0][0].lower()

    def test_on_install_all_proceeds_when_nothing_running(self, monkeypatch):
        win = _make_window()
        pending_session = _make_session()
        win._sessions.append(pending_session)

        started: list[gtk_app.CaptureSession] = []
        monkeypatch.setattr(win, "_start_prepare", lambda session: started.append(session))

        win._on_install_all(win._btn_install)

        assert started == [pending_session]
        assert pending_session.install_status == "running"
