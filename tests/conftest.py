"""Configuration pytest partagée : rend src/ importable pour tous les tests.

switch_capture_core.py n'est pas packagé (pas de [build-system]/[project]
dans pyproject.toml, voir CLAUDE.md — src/ est copié tel quel par
install.sh/build_deb.sh/build_rpm.sh). Le pyproject.toml à la racine du
dépôt (session 60) ne contient que des sections [tool.*] (ruff/pytest/
coverage) : il centralise la config des outils, il ne remet pas en cause
ce choix. On ajoute donc src/ à sys.path ici plutôt que dans chaque
fichier de test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def require_gtk4():
    """Importe `gi` et exige GTK4 (`Gtk` + `Gdk`), avec un `pytest.skip()`
    propre dans tous les cas où l'environnement ne le permet pas — y
    compris la combinaison précise repérée en session du 29/08/2026
    (features.md, remarque annexe au point 10, « Ctrl+C/SIGINT ») puis
    reproduite et corrigée le 31/08/2026 : `gi` (PyGObject) installé, mais
    le typelib `gir1.2-gtk-4.0` absent.

    Jusqu'ici, chacun des 6 fichiers `test_gui_*.py`/`test_gtk_sigint.py`/
    `test_install_guard_while_running.py` protégeait sa collecte avec
    `pytest.importorskip("gi")` seul, puis appelait
    `gi.require_version("Gtk", "4.0")` sans filet. `pytest.importorskip`
    ne protège que l'absence du module `gi` lui-même — pas cette
    combinaison précise, où `gi` s'importe sans erreur mais où
    `gi.require_version("Gtk", "4.0")` lève un `ValueError` non intercepté
    au moment de la collecte, faisant échouer *toute* la suite pytest
    (« Interrupted: N errors during collection », 0 test exécuté), y
    compris les fichiers sans rapport avec GTK4.

    Centralisé ici plutôt que dupliqué dans chacun des 6 fichiers
    concernés, pour que ce garde-fou reste unique et que les futurs
    fichiers de test GUI en bénéficient automatiquement.
    """
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
    except ValueError as exc:
        # allow_module_level=True : ces 6 fichiers appellent require_gtk4()
        # au niveau module (avant toute fonction de test), exactement comme
        # ils appelaient gi.require_version() au niveau module auparavant —
        # pytest.skip() lève sinon RuntimeError(« Using pytest.skip outside
        # of a test will skip the entire module ») au lieu de sauter
        # proprement, ce qui a été observé et corrigé en écrivant cette
        # fonction (voir docstring ci-dessus).
        pytest.skip(f"GTK4 indisponible (typelib gir1.2-gtk-4.0 manquant) : {exc}", allow_module_level=True)
    return gi
