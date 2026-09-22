"""Tests de la persistance des préférences GUI dans config.yaml.

Couvre `switch_capture_core.load_gui_preferences`/`save_gui_preferences`,
qui portent la partie « enregistrement » du point 1 de features.md (« Menu
et préférences ») : la page Préférences GTK4 (menu hamburger) sauvegarde
`slot`/`model`/`feature_bin_path`/`keepass_path` dans un fichier
config.yaml, en fusion avec tout ce qui peut déjà s'y trouver (ex: un
fichier réutilisé par ailleurs pour `switch-capture capture --config`).

Ne nécessite ni switch réel ni GTK4 : uniquement switch_capture_core et un
système de fichiers temporaire (tmp_path), même principe que
test_capture_templates.py. Le câblage GTK4 lui-même (fenêtre Préférences,
menu hamburger, retrait des champs du formulaire principal) est couvert
séparément dans test_gui_preferences_window.py (nécessite Xvfb).
"""

from __future__ import annotations

import yaml

from switch_capture_core import (
    PREFERENCES_FIELDS,
    TEMPLATE_EXCLUDED_FIELDS,
    load_gui_preferences,
    save_gui_preferences,
)

# --------------------------------------------------------------------- #
# load_gui_preferences
# --------------------------------------------------------------------- #


def test_load_returns_empty_dict_when_file_missing(tmp_path):
    assert load_gui_preferences(tmp_path / "config.yaml") == {}


def test_load_returns_empty_dict_on_empty_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("", encoding="utf-8")
    assert load_gui_preferences(path) == {}


def test_load_ignores_keys_outside_preferences_fields(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({"switch_ip": "10.0.0.1", "ssh_user": "alice", "slot": 2}),
        encoding="utf-8",
    )
    assert load_gui_preferences(path) == {"slot": 2}


def test_load_reads_all_preferences_fields_present():
    assert set(PREFERENCES_FIELDS) == {"slot", "model", "feature_bin_path", "keepass_path"}


# --------------------------------------------------------------------- #
# save_gui_preferences — écriture simple
# --------------------------------------------------------------------- #


def test_save_creates_file_and_parent_dir(tmp_path):
    path = tmp_path / "sub" / "dir" / "config.yaml"
    assert not path.parent.exists()
    result = save_gui_preferences(path, {"slot": 3})
    assert result == path
    assert path.is_file()


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "config.yaml"
    save_gui_preferences(
        path,
        {
            "slot": 2,
            "model": "5130EI",
            "feature_bin_path": "/opt/switch-capture/forced.bin",
            "keepass_path": "/home/alice/.local/share/switch-capture/vault.kdbx",
        },
    )
    assert load_gui_preferences(path) == {
        "slot": 2,
        "model": "5130EI",
        "feature_bin_path": "/opt/switch-capture/forced.bin",
        "keepass_path": "/home/alice/.local/share/switch-capture/vault.kdbx",
    }


def test_save_ignores_keys_outside_preferences_fields(tmp_path):
    """Un dict de préférences ne doit jamais pouvoir écrire switch_ip/ssh_user/etc."""
    path = tmp_path / "config.yaml"
    save_gui_preferences(path, {"slot": 1, "switch_ip": "10.0.0.9", "ssh_user": "mallory"})
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw == {"slot": 1}


# --------------------------------------------------------------------- #
# save_gui_preferences — fusion avec un fichier existant (jamais d'écrasement)
# --------------------------------------------------------------------- #


def test_save_preserves_unrelated_existing_keys(tmp_path):
    """Un config.yaml déjà utilisé pour `switch-capture capture --config`

    (switch_ip, ssh_user, capture_interface...) ne doit jamais perdre ces
    clés quand la page Préférences enregistre slot/model/etc.
    """
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({"switch_ip": "10.0.0.9", "ssh_user": "alice", "capture_interface": "GigabitEthernet1/0/1"}),
        encoding="utf-8",
    )
    save_gui_preferences(path, {"model": "5140HI"})
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["switch_ip"] == "10.0.0.9"
    assert raw["ssh_user"] == "alice"
    assert raw["capture_interface"] == "GigabitEthernet1/0/1"
    assert raw["model"] == "5140HI"


def test_save_does_not_touch_preferences_fields_absent_from_data(tmp_path):
    """Un save partiel (ex: un seul champ modifié en page Préférences) ne

    doit pas réinitialiser les autres champs de préférences déjà présents.
    """
    path = tmp_path / "config.yaml"
    save_gui_preferences(path, {"slot": 3, "model": "5130HI"})
    save_gui_preferences(path, {"slot": 5})
    assert load_gui_preferences(path) == {"slot": 5, "model": "5130HI"}


# --------------------------------------------------------------------- #
# save_gui_preferences — None/"" retire la clé plutôt que d'écrire un vide
# --------------------------------------------------------------------- #


def test_save_none_value_removes_key(tmp_path):
    path = tmp_path / "config.yaml"
    save_gui_preferences(path, {"model": "5130EI"})
    save_gui_preferences(path, {"model": None})
    assert load_gui_preferences(path) == {}


def test_save_empty_string_value_removes_key(tmp_path):
    path = tmp_path / "config.yaml"
    save_gui_preferences(path, {"feature_bin_path": "/opt/forced.bin"})
    save_gui_preferences(path, {"feature_bin_path": ""})
    assert load_gui_preferences(path) == {}


def test_save_none_on_never_set_key_is_a_noop(tmp_path):
    path = tmp_path / "config.yaml"
    save_gui_preferences(path, {"slot": 2})
    save_gui_preferences(path, {"model": None})
    assert load_gui_preferences(path) == {"slot": 2}


# --------------------------------------------------------------------- #
# Cohérence avec TEMPLATE_EXCLUDED_FIELDS (modèles de capture)
# --------------------------------------------------------------------- #


def test_preferences_fields_minus_keepass_path_are_template_excluded():
    """`keepass_path` n'est de toute façon pas un champ de Config (donc

    jamais un champ de template) ; les 3 autres doivent être exclus des
    modèles de capture réutilisables (voir test_capture_templates.py).
    """
    assert set(PREFERENCES_FIELDS) - {"keepass_path"} <= TEMPLATE_EXCLUDED_FIELDS
