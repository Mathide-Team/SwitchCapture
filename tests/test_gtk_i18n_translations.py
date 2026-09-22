"""Tests de complétude de l'i18n GUI (`switch_capture_gtk.py`) — point 13 de features.md.

Convertit en test automatisé permanent la vérification faite manuellement
en session le 31/08/2026 (voir CLAUDE.md, « Internationalisation de la
GUI ») : jusqu'ici, aucun test de la suite pytest n'exerçait réellement
`switch_capture_gtk._()` dans CE sandbox — les tests `test_gui_*.py`
nécessitent un vrai GTK4/Xvfb (absents ici) et sont explicitement exclus
des lancements de cette session (voir CLAUDE.md, commande pytest
utilisée). Ce fichier mock intégralement `gi`/`gi.repository` avec des
stubs Python purs (aucun rendu, aucune fenêtre — même technique que la
vérification manuelle de session) pour importer le module tel quel et
exercer sa vraie fonction `_()`, sans dépendre de GTK4.

Ne teste PAS le rendu visuel (toujours hors de portée sans GTK4 réel —
voir CLAUDE.md, section « Reste ouvert »). Teste uniquement la logique de
traduction :
  1. Complétude — chaque chaîne `_(...)` du code source de
     `switch_capture_gtk.py` (extraite via `ast`, donc à l'abri d'un
     oubli de mise à jour manuelle de cette liste de test) a une entrée
     non vide dans le `.mo` compilé en_US. Une chaîne ajoutée en source
     sans régénérer/traduire le `.po`/`.mo` ferait échouer ce test,
     plutôt que d'être découverte seulement à l'usage.
  2. Exactitude — un échantillon de chaînes connues traduit vers la
     valeur anglaise attendue.
  3. Repli — sans variable de langue positionnée, `_()` retourne le texte
     source français inchangé (`fallback=True`).
"""

from __future__ import annotations

import ast
import gettext
import sys
import types
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
GTK_SOURCE = SRC_DIR / "switch_capture_gtk.py"
MO_PATH = SRC_DIR / "locale" / "en_US" / "LC_MESSAGES" / "switch-capture.mo"

# Chaînes délibérément identiques en français et en anglais (voir CLAUDE.md,
# « Internationalisation de la GUI ») : nom de produit et terme technique
# usuel, pas des oublis de traduction. Exclues du test d'exactitude
# "must differ" mais toujours couvertes par le test de complétude.
_INTENTIONALLY_IDENTICAL = {"switch-capture — HPE Comware", "<b>Logs</b>"}


# --------------------------------------------------------------------- #
# Extraction des chaînes `_("...")` du code source, via ast (pas de regex
# fragile : gère nativement la concaténation implicite de littéraux
# adjacents sur plusieurs lignes, exactement comme xgettext).
# --------------------------------------------------------------------- #


def _extract_underscore_literals(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    literals: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            literals.add(node.args[0].value)
    return literals


# --------------------------------------------------------------------- #
# Stubs gi/Gtk (même technique que la vérification manuelle de session)
# --------------------------------------------------------------------- #


class _StubMeta(type):
    """Renvoie un stub pour tout attribut demandé sur la classe elle-même
    (ex: `Gtk.Orientation.VERTICAL`) sans lever `AttributeError`."""

    def __getattr__(cls, name):
        return _StubClass


class _StubClass(metaclass=_StubMeta):
    """Accepte n'importe quel attribut/appel/héritage sans rien faire.

    Suffisant pour que `switch_capture_gtk.py` s'importe intégralement
    (ses classes héritent de `Gtk.ApplicationWindow`, etc., et le module
    ne construit des widgets qu'au niveau des méthodes, pas à l'import)
    sans GTK4 réellement installé.
    """

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        def _f(*a, **k):
            return _StubClass()

        return _f

    def __call__(self, *a, **k):
        return _StubClass()

    def __init_subclass__(cls, **kwargs):
        pass


def _install_gi_stub() -> None:
    gi_mock = types.ModuleType("gi")
    gi_mock.require_version = lambda *a, **k: None
    repo_mock = types.ModuleType("gi.repository")
    for name in ("Gdk", "Gio", "GLib", "Gtk", "Pango"):
        setattr(repo_mock, name, _StubClass)
    gi_mock.repository = repo_mock
    sys.modules["gi"] = gi_mock
    sys.modules["gi.repository"] = repo_mock


@pytest.fixture()
def gtk_module_en(monkeypatch):
    """Importe `switch_capture_gtk` avec `gi` mocké et `en_US` forcé, indépendamment de l'environnement réel."""
    _install_gi_stub()
    real_translation = gettext.translation

    def _patched(domain, localedir=None, languages=None, fallback=False):
        return real_translation(domain, localedir=localedir, languages=["en_US"], fallback=fallback)

    monkeypatch.setattr(gettext, "translation", _patched)
    sys.modules.pop("switch_capture_gtk", None)
    import switch_capture_gtk as module

    yield module
    sys.modules.pop("switch_capture_gtk", None)


@pytest.fixture()
def gtk_module_default(monkeypatch):
    """Importe `switch_capture_gtk` avec `gi` mocké, sans variable de langue forcée (repli français attendu)."""
    _install_gi_stub()
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    sys.modules.pop("switch_capture_gtk", None)
    import switch_capture_gtk as module

    yield module
    sys.modules.pop("switch_capture_gtk", None)


# --------------------------------------------------------------------- #
# Complétude
# --------------------------------------------------------------------- #


def test_mo_file_exists():
    assert MO_PATH.is_file(), f"{MO_PATH} introuvable — i18n GUI non compilée ?"


def test_every_gtk_source_string_is_translated():
    """Chaque chaîne `_("...")` de `switch_capture_gtk.py` a une entrée non vide dans le `.mo` compilé.

    `msgfmt` omet par défaut les entrées "fuzzy" du `.mo` compilé, donc ce
    test couvre aussi implicitement l'absence de fuzzy pour ces chaînes.
    """
    source_strings = _extract_underscore_literals(GTK_SOURCE)
    assert source_strings, "aucune chaîne _(...) trouvée dans switch_capture_gtk.py — extraction cassée ?"

    with open(MO_PATH, "rb") as f:
        translations = gettext.GNUTranslations(f)

    missing = []
    empty = []
    for s in sorted(source_strings):
        if s not in translations._catalog:
            missing.append(s)
        elif not translations._catalog[s]:
            empty.append(s)

    assert not missing, f"chaînes de switch_capture_gtk.py absentes du .mo en_US : {missing}"
    assert not empty, f"chaînes de switch_capture_gtk.py traduites vides dans le .mo en_US : {empty}"


def test_translations_differ_from_source_except_known_exceptions():
    """Toute chaîne traduite doit différer du français source, sauf les 2 exceptions délibérées documentées.

    Détecte une régression fréquente de `msgmerge`/traduction manuelle :
    une entrée laissée avec `msgstr` identique au `msgid` par erreur
    (fuzzy mal résolue, copier-coller).
    """
    source_strings = _extract_underscore_literals(GTK_SOURCE)
    with open(MO_PATH, "rb") as f:
        translations = gettext.GNUTranslations(f)

    unexpectedly_identical = [
        s for s in source_strings if s not in _INTENTIONALLY_IDENTICAL and translations._catalog.get(s) == s
    ]
    assert not unexpectedly_identical, f"traduction identique au français, à vérifier : {unexpectedly_identical}"


# --------------------------------------------------------------------- #
# Exactitude (échantillon connu)
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "french,expected_english",
    [
        ("Préférences", "Preferences"),
        ("Enregistrer", "Save"),
        ("Annuler", "Cancel"),
        ("Configuration incomplète", "Incomplete configuration"),
        ("en cours", "running"),
        ("arrêtée", "stopped"),
        ("Rien à installer", "Nothing to install"),
        ("Connexion réussie", "Connection successful"),
        ("Échec de l'inspection", "Inspection failed"),
        ("Mirroring configuré", "Mirroring configured"),
        # Relecture .po du 02-03/09/2026 (voir CLAUDE.md) : états vides au
        # pluriel en anglais ("No captures...", pas "No capture...", même
        # si le français source utilise le singulier "Aucune capture").
        ("Aucune capture.", "No captures."),
        ("Aucune capture en cours.", "No captures running."),
        # Cohérence de "e.g." (jamais "e.g.:", incohérent avec le reste du
        # fichier malgré un français source en "ex:" avec deux-points).
        ("ex: labo-5130-client", "e.g. lab-5130-client"),
    ],
)
def test_known_strings_translate_to_english(gtk_module_en, french, expected_english):
    assert gtk_module_en._(french) == expected_english


def test_default_locale_falls_back_to_french_source(gtk_module_default):
    """Sans LANGUAGE/LC_ALL/LC_MESSAGES/LANG positionnés, `_()` retourne le texte source inchangé."""
    for french in ("Préférences", "en cours", "Rien à installer"):
        assert gtk_module_default._(french) == french
