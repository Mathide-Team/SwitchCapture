"""Tests des dialogues GTK4 sans classe dépréciée (issue #69).

`Gtk.FileChooserNative` et `Gtk.MessageDialog` sont dépréciés depuis
GTK 4.10. `switch_capture_gtk` choisit à l'exécution `Gtk.FileDialog` /
`Gtk.AlertDialog` (GTK >= 4.10 : Debian 13, Rocky/RHEL 9) et garde
l'ancienne API en repli pour Debian 12 (GTK 4.8.3). Les confirmations qui
portent des widgets passent par `_open_form_dialog`, une `Gtk.Window`
modale identique sur toutes les versions.

Nécessite PyGObject/GTK4 ET un affichage graphique (Xvfb) ; se saute
proprement sinon, comme test_gui_preferences_window.py.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from conftest import require_gtk4

gi = require_gtk4()

from gi.repository import Gio, GLib, Gtk

import switch_capture_core as core
import switch_capture_gtk as gtk_app


def _make_window():
    app = Gtk.Application(application_id="org.transcende.switch_capture.tests.dialogs")
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


def _pump() -> None:
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


def _toplevel(title: str) -> Gtk.Window | None:
    for win in Gtk.Window.list_toplevels():
        if isinstance(win, Gtk.Window) and win.get_title() == title and win.get_visible():
            return win
    return None


def _buttons(widget: Gtk.Widget) -> dict[str, Gtk.Button]:
    found: dict[str, Gtk.Button] = {}
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Button) and child.get_label():
            found[child.get_label()] = child
        found.update(_buttons(child))
        child = child.get_next_sibling()
    return found


# --------------------------------------------------------------------- #
# Détection de version
# --------------------------------------------------------------------- #


def test_nouvelle_api_detectee_sur_gtk_410_et_plus():
    recent = (Gtk.get_major_version(), Gtk.get_minor_version()) >= (4, 10)
    assert gtk_app._HAS_FILE_DIALOG is recent
    assert gtk_app._HAS_ALERT_DIALOG is recent


# --------------------------------------------------------------------- #
# _choose_path
# --------------------------------------------------------------------- #


class _FakeFileDialog:
    """Remplace Gtk.FileDialog : rappelle immédiatement le callback."""

    instances: ClassVar[list[_FakeFileDialog]] = []
    result: Gio.File | None = None
    error: GLib.Error | None = None

    def __init__(self, title, modal):
        self.title = title
        self.modal = modal
        self.calls: list[str] = []
        _FakeFileDialog.instances.append(self)

    def _finish(self, _result):
        if _FakeFileDialog.error is not None:
            raise _FakeFileDialog.error
        return _FakeFileDialog.result

    select_folder_finish = _finish
    open_finish = _finish

    def select_folder(self, parent, cancellable, callback):
        self.calls.append("select_folder")
        callback(self, None)

    def open(self, parent, cancellable, callback):
        self.calls.append("open")
        callback(self, None)


@pytest.fixture
def fake_file_dialog(monkeypatch):
    _FakeFileDialog.instances = []
    _FakeFileDialog.result = None
    _FakeFileDialog.error = None
    monkeypatch.setattr(gtk_app, "_HAS_FILE_DIALOG", True)
    monkeypatch.setattr(gtk_app.Gtk, "FileDialog", _FakeFileDialog, raising=False)
    return _FakeFileDialog


@pytest.mark.parametrize(("select_folder", "method"), [(True, "select_folder"), (False, "open")])
def test_choose_path_filedialog_transmet_le_chemin(fake_file_dialog, tmp_path, select_folder, method):
    fake_file_dialog.result = Gio.File.new_for_path(str(tmp_path))
    got: list[str] = []
    gtk_app._choose_path(None, "Choisir", select_folder, got.append)
    assert got == [str(tmp_path)]
    dialog = fake_file_dialog.instances[0]
    assert dialog.calls == [method]
    assert dialog.title == "Choisir"
    assert dialog.modal is True


def test_choose_path_filedialog_annule_sans_appel(fake_file_dialog):
    fake_file_dialog.error = GLib.Error.new_literal(Gtk.DialogError.quark(), "Dismissed by user", 2)
    got: list[str] = []
    gtk_app._choose_path(None, "Choisir", True, got.append)
    assert got == []


def test_choose_path_filedialog_sans_chemin_local(fake_file_dialog):
    fake_file_dialog.result = Gio.File.new_for_uri("sftp://hote/dossier")
    got: list[str] = []
    gtk_app._choose_path(None, "Choisir", True, got.append)
    assert got == []


class _FakeNative:
    instances: ClassVar[list[_FakeNative]] = []

    def __init__(self, title, action, transient_for):
        self.title = title
        self.action = action
        self.handler = None
        self.destroyed = False
        self.file: Gio.File | None = None
        _FakeNative.instances.append(self)

    def connect(self, signal, handler):
        assert signal == "response"
        self.handler = handler

    def show(self):
        pass

    def get_file(self):
        return self.file

    def destroy(self):
        self.destroyed = True


@pytest.mark.parametrize(
    ("response", "expected"),
    [(Gtk.ResponseType.ACCEPT, True), (Gtk.ResponseType.CANCEL, False)],
)
def test_choose_path_repli_gtk_ancien(monkeypatch, tmp_path, response, expected):
    _FakeNative.instances = []
    monkeypatch.setattr(gtk_app, "_HAS_FILE_DIALOG", False)
    monkeypatch.setattr(gtk_app.Gtk, "FileChooserNative", _FakeNative)
    got: list[str] = []
    gtk_app._choose_path(None, "Choisir", True, got.append)
    native = _FakeNative.instances[0]
    assert native.action == Gtk.FileChooserAction.SELECT_FOLDER
    native.file = Gio.File.new_for_path(str(tmp_path))
    native.handler(native, response)
    assert native.destroyed
    assert got == ([str(tmp_path)] if expected else [])


# --------------------------------------------------------------------- #
# _show_message
# --------------------------------------------------------------------- #


def test_show_message_alertdialog(monkeypatch):
    shown: list[tuple] = []

    class FakeAlert:
        def __init__(self, message, detail, modal):
            self.args = (message, detail, modal)

        def show(self, parent):
            shown.append((*self.args, parent))

    monkeypatch.setattr(gtk_app, "_HAS_ALERT_DIALOG", True)
    monkeypatch.setattr(gtk_app.Gtk, "AlertDialog", FakeAlert, raising=False)
    gtk_app._show_message("parent", "Titre", "Détail")
    assert shown == [("Titre", "Détail", True, "parent")]


def test_show_message_repli_messagedialog_reel():
    win = _make_window()
    old = gtk_app._HAS_ALERT_DIALOG
    gtk_app._HAS_ALERT_DIALOG = False
    try:
        gtk_app._show_message(win, "Titre repli", "Corps")
        _pump()
        dialogs = [w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.MessageDialog)]
        assert dialogs, "MessageDialog de repli non affiché"
        for d in dialogs:
            d.response(Gtk.ResponseType.OK)
        _pump()
        assert not [w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.MessageDialog) and w.get_visible()]
    finally:
        gtk_app._HAS_ALERT_DIALOG = old
        win.destroy()


def test_show_dialog_passe_par_show_message(monkeypatch):
    win = _make_window()
    seen: list[tuple] = []
    monkeypatch.setattr(gtk_app, "_show_message", lambda parent, t, b: seen.append((parent, t, b)))
    win._show_dialog("T", "B")
    assert seen == [(win, "T", "B")]
    win.destroy()


# --------------------------------------------------------------------- #
# _open_form_dialog
# --------------------------------------------------------------------- #


@pytest.fixture
def window():
    win = _make_window()
    yield win
    win.destroy()


def test_form_dialog_accepte_widgets_lisibles_avant_destruction(window):
    entry = Gtk.Entry()
    seen: list[tuple[bool, str]] = []
    btn = gtk_app._open_form_dialog(
        window, "Formulaire", "Corps", [entry], "Annuler", "Valider", lambda ok: seen.append((ok, entry.get_text()))
    )
    _pump()
    dlg = _toplevel("Formulaire")
    assert dlg is not None and dlg.get_modal() and dlg.get_transient_for() is window
    entry.set_text("valeur")
    btn.emit("clicked")
    btn.emit("clicked")  # second clic : ignoré
    _pump()
    assert seen == [(True, "valeur")]
    assert _toplevel("Formulaire") is None


@pytest.mark.parametrize("how", ["cancel", "close", "escape"])
def test_form_dialog_annulation(window, how):
    seen: list[bool] = []
    gtk_app._open_form_dialog(window, "Annulable", "", [], "Annuler", "OK", seen.append)
    _pump()
    dlg = _toplevel("Annulable")
    assert dlg is not None
    if how == "cancel":
        _buttons(dlg)["Annuler"].emit("clicked")
    elif how == "close":
        dlg.close()
    else:
        ctrl = next(c for c in dlg.observe_controllers() if isinstance(c, Gtk.ShortcutController))
        ctrl.get_item(0).get_action().activate(0, dlg, None)
    _pump()
    assert seen == [False]
    assert _toplevel("Annulable") is None


def test_form_dialog_bouton_destructif(window):
    btn = gtk_app._open_form_dialog(
        window, "Danger", "", [], "Annuler", "Supprimer", lambda _ok: None, destructive=True
    )
    assert btn.has_css_class("destructive-action")
    btn.emit("clicked")
    _pump()


# --------------------------------------------------------------------- #
# Sites d'appel de CaptureWindow
# --------------------------------------------------------------------- #


def _session(win):
    cfg = core.Config(
        switch_ip="10.0.0.1",
        ssh_user="mathilde",
        ssh_password="secret",
        capture_interface="GigabitEthernet1/0/1",
    )

    class _S:
        pass

    s = _S()
    s.cfg = cfg
    s.state = core.SharedState() if hasattr(core, "SharedState") else object()
    s.label = "session-test"
    return s


def test_desinstallation_exige_l_ip_puis_lance_le_thread(window, monkeypatch):
    started: list[tuple] = []

    class FakeThread:
        def __init__(self, cfg, state, remove_bin, on_done):
            self.args = (cfg.switch_ip, remove_bin)

        def start(self):
            started.append(self.args)

    monkeypatch.setattr(gtk_app, "UninstallThread", FakeThread)
    session = _session(window)
    window._on_uninstall_session(None, session)
    _pump()
    dlg = _toplevel("Désinstaller packet-capture sur 10.0.0.1 ?")
    assert dlg is not None
    btns = _buttons(dlg)
    accept = btns["Désinstaller"]
    assert not accept.get_sensitive()
    entry = next(w for w in _iter(dlg) if isinstance(w, Gtk.Entry))
    check = next(w for w in _iter(dlg) if isinstance(w, Gtk.CheckButton))
    entry.set_text("10.0.0.2")
    assert not accept.get_sensitive()
    entry.set_text("10.0.0.1")
    assert accept.get_sensitive()
    check.set_active(True)
    accept.emit("clicked")
    _pump()
    assert started == [("10.0.0.1", True)]
    assert _toplevel("Désinstaller packet-capture sur 10.0.0.1 ?") is None


def test_desinstallation_annulee_ne_lance_rien(window, monkeypatch):
    started: list = []
    monkeypatch.setattr(gtk_app, "UninstallThread", lambda *a: started.append(a))
    window._on_uninstall_session(None, _session(window))
    _pump()
    dlg = _toplevel("Désinstaller packet-capture sur 10.0.0.1 ?")
    _buttons(dlg)["Annuler"].emit("clicked")
    _pump()
    assert started == []


def _iter(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _iter(child)
        child = child.get_next_sibling()


def test_enregistrer_modele(window, monkeypatch, tmp_path):
    saved: list[str] = []
    monkeypatch.setattr(gtk_app, "save_capture_template", lambda d, name, values: saved.append(name) or tmp_path / name)
    window._on_save_template(None)
    _pump()
    dlg = _toplevel("Enregistrer comme modèle")
    assert dlg is not None
    next(w for w in _iter(dlg) if isinstance(w, Gtk.Entry)).set_text("labo")
    _buttons(dlg)["Enregistrer"].emit("clicked")
    _pump()
    assert saved == ["labo"]


def test_importer_modele(window, monkeypatch):
    applied: list[dict] = []
    monkeypatch.setattr(gtk_app, "list_capture_templates", lambda d: ["a", "b"])
    monkeypatch.setattr(gtk_app, "load_capture_template", lambda d, name: {"name": name})
    monkeypatch.setattr(window, "_apply_form_values", applied.append)
    window._on_load_template(None)
    _pump()
    dlg = _toplevel("Importer un modèle")
    assert dlg is not None
    next(w for w in _iter(dlg) if isinstance(w, Gtk.DropDown)).set_selected(1)
    _buttons(dlg)["Importer"].emit("clicked")
    _pump()
    assert applied == [{"name": "b"}]


def test_parcourir_remplit_le_champ(window, fake_file_dialog, tmp_path):
    fake_file_dialog.result = Gio.File.new_for_path(str(tmp_path))
    entry = Gtk.Entry()
    window._on_browse(None, entry, True)
    assert entry.get_text() == str(tmp_path)


def test_import_bin_lance_l_import(window, fake_file_dialog, monkeypatch, tmp_path):
    fake_file_dialog.result = Gio.File.new_for_path(str(tmp_path))
    calls: list[tuple] = []
    monkeypatch.setattr(window, "_run_import_bin_async", lambda src, dst: calls.append((src, dst)))
    window._entries["feature_bin_dir"].set_text("")
    window._on_import_bin(None)
    assert calls == [(str(tmp_path), None)]
