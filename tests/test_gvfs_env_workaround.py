"""Contournement GVfs/GOA pour le sélecteur de fichiers GTK (features.md,
bugs 8/9/11/12 — "Erreur creating proxy … org.gtk.vfs.GoaVolumeMonitor",
"Gtk-CRITICAL **: thaw_updates: assertion 'GTK_IS_FILE_SYSTEM_MODEL (model)'
failed", "Erreur de segmentation (core dumped)").

Cause diagnostiquée dans cette session : `Gtk.FileChooserNative` sollicite,
pour peupler sa barre latérale, les moniteurs de volumes distants fournis
par le paquet système `gvfs` (démons D-Bus `org.gtk.vfs.GoaVolumeMonitor`/
`org.gtk.vfs.UDisks2VolumeMonitor`, entre autres). Sur un poste où ces
démons sont absents ou mal enregistrés (rapporté par l'utilisateur en
session RDP/xrdp), leur activation échoue — au mieux un avertissement, au
pire l'instabilité/le crash observés. Reproduit dans cette session : sous
Xvfb avec une vraie session D-Bus mais sans udisks2/GOA, l'ouverture d'un
`Gtk.FileChooserNative` produit `GVFS-RemoteVolumeMonitor-WARNING **:
remote volume monitor with dbus name org.gtk.vfs.UDisks2VolumeMonitor is
not supported` — même famille d'erreur que celle rapportée par
l'utilisateur pour le moniteur GOA.

switch-capture n'a jamais besoin de choisir un emplacement distant
(sftp://, google-drive://…) dans ses sélecteurs de fichiers/dossiers
(dossier de la feature .bin, dossier d'archivage, fichier KeePass) :
positionner `GIO_USE_VFS=local`/`GIO_USE_VOLUME_MONITOR=unix` (mécanismes
GIO documentés, https://docs.gtk.org/gio/overview.html) avant tout import
de `gi`/`Gtk` supprime cette dépendance à gvfs pour tout le processus.
Vérifié dans cette session : le même avertissement `GVFS-RemoteVolumeMonitor`
disparaît une fois ces deux variables positionnées (avant/après comparés
sous Xvfb + session D-Bus réelle, log complet conservé dans CLAUDE.md).

Ces tests-ci ne nécessitent PAS d'affichage graphique (Xvfb) : les deux
variables sont lues par GIO au moment de résoudre ses extension points,
pas par le rendu GTK lui-même — les vérifier ne requiert donc pas
d'instancier de fenêtre, contrairement aux autres tests `test_gui_*.py` de
ce dépôt.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

_GIO_VARS = ("GIO_USE_VFS", "GIO_USE_VOLUME_MONITOR")


def _gtk4_typelib_available() -> bool:
    """`switch_capture_gtk.py` fait un `gi.require_version("Gtk", "4.0")`
    inconditionnel dès son import (contrairement à `src/switch-capture`,
    dont `_gtk_available()` avale l'exception) — les tests qui importent ce
    module directement (`TestSwitchCaptureGtkModule` ci-dessous) échouent
    donc franchement, plutôt que de sauter proprement, quand `gi` est
    installé mais que le typelib GTK4 ne l'est pas (même combinaison que
    celle centralisée dans `conftest.require_gtk4()` pour les fichiers
    `test_gui_*.py` — non réutilisable telle quelle ici : `require_gtk4()`
    est fait pour un skip au niveau module, alors que ce fichier a aussi
    des tests qui ne nécessitent pas GTK4 (`TestEntrypointScript`)."""
    try:
        import gi

        gi.require_version("Gtk", "4.0")
    except (ImportError, ValueError):
        return False
    return True


def _clean_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Environnement de test : hérite du process courant, sans les deux
    variables GIO ciblées (sauf override explicite), pour ne jamais
    dépendre de ce qui est déjà positionné dans le sandbox d'exécution."""
    env = {k: v for k, v in os.environ.items() if k not in _GIO_VARS}
    if overrides:
        env.update(overrides)
    return env


def _probe(code: str, env: dict[str, str]) -> str:
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(SRC_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    return result.stdout.strip()


@pytest.mark.skipif(
    not _gtk4_typelib_available(),
    reason="GTK4 indisponible (typelib gir1.2-gtk-4.0 manquant) : import de switch_capture_gtk impossible",
)
class TestSwitchCaptureGtkModule:
    """`switch_capture_gtk.py` positionne les deux variables à l'import,
    avant même `import gi` (le commentaire en tête de fichier explique
    pourquoi l'ordre importe)."""

    def test_sets_defaults_when_absent(self):
        out = _probe(
            "import switch_capture_gtk, os; "
            "print(os.environ.get('GIO_USE_VFS'), os.environ.get('GIO_USE_VOLUME_MONITOR'))",
            _clean_env(),
        )
        assert out == "local unix"

    def test_does_not_override_explicit_env(self):
        """`setdefault` : un réglage déjà présent dans l'environnement de
        qui lance l'outil n'est jamais écrasé."""
        out = _probe(
            "import switch_capture_gtk, os; "
            "print(os.environ.get('GIO_USE_VFS'), os.environ.get('GIO_USE_VOLUME_MONITOR'))",
            _clean_env({"GIO_USE_VFS": "gvfs", "GIO_USE_VOLUME_MONITOR": "udisks2"}),
        )
        assert out == "gvfs udisks2"

    def test_partial_override_only_replaces_missing_one(self):
        out = _probe(
            "import switch_capture_gtk, os; "
            "print(os.environ.get('GIO_USE_VFS'), os.environ.get('GIO_USE_VOLUME_MONITOR'))",
            _clean_env({"GIO_USE_VFS": "gvfs"}),
        )
        assert out == "gvfs unix"


class TestEntrypointScript:
    """`src/switch-capture` (point d'entrée unique CLI/GTK, voir sa
    docstring) doit positionner les mêmes variables avant son propre
    premier `import gi`, fait dans `_gtk_available()` pour la simple
    détection de disponibilité — un cas que `switch_capture_gtk.py` seul
    ne couvre pas, puisque ce module n'est pas encore importé à ce
    moment-là."""

    def test_entrypoint_sets_defaults_without_running_main(self):
        # exec() du corps du module sous un __name__ différent de
        # "__main__" : les imports/affectations de haut niveau (dont le
        # positionnement des variables GIO, tout en haut du fichier)
        # s'exécutent, mais le bloc `if __name__ == "__main__":
        # sys.exit(main())` final ne se déclenche pas — aucune fenêtre ni
        # sous-commande CLI n'est réellement lancée.
        code = (
            "import os\n"
            "ns = {'__name__': 'switch_capture_entrypoint_probe', '__file__': 'switch-capture'}\n"
            "src = open('switch-capture', encoding='utf-8').read()\n"
            "exec(compile(src, 'switch-capture', 'exec'), ns)\n"
            "print(os.environ.get('GIO_USE_VFS'), os.environ.get('GIO_USE_VOLUME_MONITOR'))\n"
        )
        out = _probe(code, _clean_env())
        assert out == "local unix"

    def test_entrypoint_does_not_override_explicit_env(self):
        code = (
            "import os\n"
            "ns = {'__name__': 'switch_capture_entrypoint_probe', '__file__': 'switch-capture'}\n"
            "src = open('switch-capture', encoding='utf-8').read()\n"
            "exec(compile(src, 'switch-capture', 'exec'), ns)\n"
            "print(os.environ.get('GIO_USE_VFS'), os.environ.get('GIO_USE_VOLUME_MONITOR'))\n"
        )
        out = _probe(code, _clean_env({"GIO_USE_VFS": "gvfs", "GIO_USE_VOLUME_MONITOR": "udisks2"}))
        assert out == "gvfs udisks2"

    def test_env_set_before_gi_available_check(self):
        """Preuve structurelle, pas seulement documentaire : au moment où
        `_gtk_available()` (qui fait `import gi` en premier) devient
        appelable, les deux variables sont déjà positionnées — car les
        lignes `os.environ.setdefault(...)` sont au niveau module, donc
        exécutées avant que la moindre fonction du fichier ne soit
        définie, a fortiori avant qu'aucune ne soit appelée."""
        code = (
            "import os\n"
            "ns = {'__name__': 'switch_capture_entrypoint_probe', '__file__': 'switch-capture'}\n"
            "src = open('switch-capture', encoding='utf-8').read()\n"
            "exec(compile(src, 'switch-capture', 'exec'), ns)\n"
            "assert os.environ.get('GIO_USE_VFS') == 'local'\n"
            "assert os.environ.get('GIO_USE_VOLUME_MONITOR') == 'unix'\n"
            "result = ns['_gtk_available']()\n"
            "print('ok', result, os.environ.get('GIO_USE_VFS'), os.environ.get('GIO_USE_VOLUME_MONITOR'))\n"
        )
        out = _probe(code, _clean_env())
        assert out.startswith("ok ")
        assert out.endswith("local unix")


class TestGvfsRemoteVolumeMonitorWarningGone:
    """Reproduction de bout en bout de la classe d'erreur rapportée
    (avertissement GVfs sur l'ouverture d'un vrai `Gtk.FileChooserNative`),
    avec et sans le contournement — nécessite un affichage graphique et une
    session D-Bus réelles, contrairement aux tests ci-dessus. Se saute
    proprement si l'environnement ne s'y prête pas (pas d'Xvfb, ou GTK4/
    PyGObject absents) : même politique que le reste des tests `test_gui_*`
    de ce dépôt."""

    def test_warning_present_without_workaround_absent_with(self):
        import shutil

        if not shutil.which("Xvfb") or not shutil.which("dbus-daemon"):
            import pytest

            pytest.skip("Xvfb ou dbus-daemon absent de cet environnement")

        gi_probe = subprocess.run(
            [sys.executable, "-c", "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk"],
            capture_output=True,
            check=False,
        )
        if gi_probe.returncode != 0:
            import pytest

            pytest.skip("GTK4/PyGObject indisponibles dans cet environnement")

        script = r"""
import faulthandler, sys
faulthandler.enable()
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib

app = Gtk.Application(application_id="org.test.gvfs_probe")

def on_activate(app):
    win = Gtk.ApplicationWindow(application=app)
    win.present()

    def open_and_close(_data=None):
        dialog = Gtk.FileChooserNative(
            title="Choisir",
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            transient_for=win,
        )
        def on_response(dlg, response):
            dlg.destroy()
        dialog.connect("response", on_response)
        dialog.show()
        GLib.timeout_add(50, lambda: (dialog.emit("response", Gtk.ResponseType.CANCEL), False)[1])

    GLib.timeout_add(200, open_and_close)
    GLib.timeout_add(1200, lambda: (app.quit(), False)[1])

app.connect("activate", on_activate)
sys.exit(app.run(None))
"""
        import time

        display = ":97"
        xvfb = subprocess.Popen(["Xvfb", display, "-screen", "0", "1280x1024x24"])
        try:
            time.sleep(1)
            dbus_out = subprocess.run(
                ["dbus-daemon", "--session", "--print-address=1", "--print-pid=1", "--fork"],
                capture_output=True,
                text=True,
                check=False,
            )
            lines = dbus_out.stdout.strip().splitlines()
            dbus_addr, dbus_pid = lines[0], lines[1]
            time.sleep(0.5)

            def run_with(vfs_env: dict[str, str]) -> str:
                env = _clean_env(vfs_env)
                env["DISPLAY"] = display
                env["DBUS_SESSION_BUS_ADDRESS"] = dbus_addr
                proc = subprocess.run(
                    [sys.executable, "-c", script],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                return proc.stderr

            stderr_without = run_with({})
            stderr_with = run_with({"GIO_USE_VFS": "local", "GIO_USE_VOLUME_MONITOR": "unix"})
        finally:
            subprocess.run(["kill", dbus_pid], capture_output=False, check=False)
            xvfb.terminate()
            xvfb.wait(timeout=5)

        assert "GVFS-RemoteVolumeMonitor" in stderr_without, (
            "avertissement GVfs attendu absent sans le contournement (environnement "
            f"peut-être trop différent de celui de reproduction) — stderr : {stderr_without!r}"
        )
        assert "GVFS-RemoteVolumeMonitor" not in stderr_with, (
            f"avertissement GVfs toujours présent malgré le contournement — stderr : {stderr_with!r}"
        )
