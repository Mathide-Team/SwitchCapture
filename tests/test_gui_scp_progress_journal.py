"""Issue #70 : la page « Journal » affiche le dernier palier SCP de chaque
capture en cours, lu dans `SharedState.scp_progress` par
`_refresh_journal` (thread GTK) — le thread de transfert n'appelle jamais
GTK.

Nécessite PyGObject/GTK4 ET un affichage (Xvfb) ; se saute proprement
sinon, même pattern que test_gui_mirroring.py.
"""

from __future__ import annotations

import pytest
from conftest import require_gtk4

gi = require_gtk4()

from gi.repository import Gtk

import switch_capture_gtk as gtk_app
from switch_capture_core import Config, ScpProgress


def _make_window():
    app = Gtk.Application(application_id="org.transcende.switch_capture.tests.scpprogress")
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


class _Alive:
    def is_alive(self) -> bool:
        return True


def _session(**cfg):
    session = gtk_app.CaptureSession(
        Config(
            switch_ip="10.0.0.1",
            ssh_user="mathilde",
            ssh_password="secret",
            capture_interface="GigabitEthernet1/0/1",
            **cfg,
        )
    )
    session.capture_running = True
    session.setup = _Alive()
    return session


def _row_texts(win) -> list[str]:
    texts = []
    row = win._progress_list.get_first_child()
    while row is not None:
        box = row.get_child()
        label = box.get_first_child()
        while label is not None:
            texts.append(label.get_label())
            label = label.get_next_sibling()
        row = row.get_next_sibling()
    return texts


def test_palier_scp_affiche_dans_le_journal():
    win = _make_window()
    session = _session()
    win._sessions.append(session)

    win._refresh_journal()
    assert not any("SCP" in t for t in _row_texts(win))

    session.state.scp_progress = ScpProgress("process_closed_file_scp", "cap_00002.pcap", 60, 600, 1000)
    win._refresh_journal()
    textes = _row_texts(win)
    assert any("SCP cap_00002.pcap : 60 % (600 o / 1000 o)" in t for t in textes), textes
    win.close()


def test_rpcap_sans_palier():
    win = _make_window()
    win._sessions.append(_session(output_mode="rpcap"))
    win._refresh_journal()
    assert any("rpcap" in t for t in _row_texts(win))
    assert not any("SCP" in t for t in _row_texts(win))
    win.close()
