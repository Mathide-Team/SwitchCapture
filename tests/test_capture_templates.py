"""Tests des modèles de capture réutilisables (switch_capture_core).

Couvre la fonctionnalité #1 de la section « Pas fait » de features.md :
sérialisation/désérialisation YAML d'un Config en modèle réutilisable,
en excluant systématiquement `ssh_password` (jamais écrit sur disque),
et la validation des noms de modèle (protection contre la traversée de
dossier).

Ne nécessite ni switch réel ni GTK4 : uniquement switch_capture_core et
un système de fichiers temporaire (tmp_path).
"""

from __future__ import annotations

import pytest

from switch_capture_core import (
    Config,
    config_to_template_dict,
    list_capture_templates,
    load_capture_template,
    sanitize_template_name,
    save_capture_template,
    template_dict_to_config_kwargs,
)


def make_config(**overrides) -> Config:
    """Construit un Config valide minimal, avec surcharges optionnelles."""
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "capture_interface": "GigabitEthernet1/0/1",
    }
    base.update(overrides)
    return Config(**base)


# --------------------------------------------------------------------- #
# config_to_template_dict / template_dict_to_config_kwargs
# --------------------------------------------------------------------- #


def test_config_to_template_dict_excludes_password():
    cfg = make_config(capture_label="client")
    data = config_to_template_dict(cfg)
    assert "ssh_password" not in data
    assert data["switch_ip"] == "10.0.0.1"
    assert data["ssh_user"] == "mathilde"
    assert data["capture_label"] == "client"


def test_config_to_template_dict_covers_all_relevant_fields():
    cfg = make_config()
    data = config_to_template_dict(cfg)
    # Champs représentatifs des différentes sections du formulaire GTK.
    for key in (
        "switch_ip",
        "ssh_user",
        "transfer_mode",
        "capture_interface",
        "capture_filter",
        "output_mode",
        "rotation_seconds",
        "spool_dir",
        "ntp_server",
    ):
        assert key in data
    # Les champs dérivés (non "init") ne doivent pas apparaître.
    assert "feature_filename" not in data
    assert "capture_prefix" not in data


def test_config_to_template_dict_excludes_gui_preferences_fields():
    """Depuis la page Préférences (features.md, point 1), `slot`/`model`/

    `feature_bin_path` sont des réglages globaux à l'outil, plus des
    réglages "par capture" : un modèle de capture réutilisable ne doit
    plus les embarquer (voir TEMPLATE_EXCLUDED_FIELDS dans
    switch_capture_core.py), même principe que `ssh_password` déjà exclu.
    """
    cfg = make_config(slot=4, model="5130EI", feature_bin_path="/opt/forced.bin")
    data = config_to_template_dict(cfg)
    assert "slot" not in data
    assert "model" not in data
    assert "feature_bin_path" not in data


def test_template_dict_to_config_kwargs_filters_password_and_unknown():
    kwargs = template_dict_to_config_kwargs({"switch_ip": "10.0.0.2", "ssh_password": "leaked", "bogus_field": 1})
    assert kwargs == {"switch_ip": "10.0.0.2"}


def test_template_dict_to_config_kwargs_handles_empty_or_none():
    assert template_dict_to_config_kwargs({}) == {}
    assert template_dict_to_config_kwargs(None) == {}


# --------------------------------------------------------------------- #
# sanitize_template_name
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["", "   ", "a/b", "../evil", "a\\b"])
def test_sanitize_template_name_rejects_invalid(name):
    with pytest.raises(ValueError):
        sanitize_template_name(name)


@pytest.mark.parametrize("name", ["labo-5130", "client B", "modele_1", "labo 5130 - client (été)"])
def test_sanitize_template_name_accepts_valid(name):
    assert sanitize_template_name(name) == name.strip()


def test_sanitize_template_name_strips_whitespace():
    assert sanitize_template_name("  mon modele  ") == "mon modele"


# --------------------------------------------------------------------- #
# save_capture_template / load_capture_template / list_capture_templates
# --------------------------------------------------------------------- #


def test_save_and_load_roundtrip(tmp_path):
    cfg = make_config(
        capture_label="routeur-core",
        rotation_seconds=45,
        ensure_ntp=False,
        tap_interface="vcap2",
        output_mode="tap",
    )
    values = config_to_template_dict(cfg)

    target = save_capture_template(tmp_path, "mon modèle", values)
    assert target.exists()
    assert target.name == "mon modèle.yaml"

    loaded = load_capture_template(tmp_path, "mon modèle")
    assert "ssh_password" not in loaded
    assert loaded["switch_ip"] == "10.0.0.1"
    assert loaded["rotation_seconds"] == 45
    assert loaded["ensure_ntp"] is False
    assert loaded["output_mode"] == "tap"
    assert loaded["tap_interface"] == "vcap2"


def test_loaded_template_can_rebuild_a_valid_config(tmp_path):
    """Le kwargs chargé + un mot de passe ressaisi doit reconstruire un Config valide."""
    cfg = make_config(capture_label="serveur-web", capture_interface="GigabitEthernet1/0/2")
    save_capture_template(tmp_path, "reconstruction", config_to_template_dict(cfg))

    kwargs = load_capture_template(tmp_path, "reconstruction")
    rebuilt = Config(ssh_password="nouveau-mot-de-passe", **kwargs)

    assert rebuilt.switch_ip == cfg.switch_ip
    assert rebuilt.capture_interface == cfg.capture_interface
    assert rebuilt.capture_label == "serveur-web"
    assert rebuilt.ssh_password == "nouveau-mot-de-passe"


def test_save_template_never_persists_password_even_if_passed(tmp_path):
    data = {"switch_ip": "10.0.0.9", "ssh_password": "should-not-be-written"}
    target = save_capture_template(tmp_path, "leak-check", data)
    content = target.read_text(encoding="utf-8")
    assert "should-not-be-written" not in content
    assert "ssh_password" not in content


def test_save_capture_template_rejects_invalid_name(tmp_path):
    with pytest.raises(ValueError):
        save_capture_template(tmp_path, "../evil", {"switch_ip": "10.0.0.1"})
    # Rien n'a été écrit hors du dossier cible.
    assert list(tmp_path.parent.glob("evil.yaml")) == []


def test_list_capture_templates_sorted(tmp_path):
    save_capture_template(tmp_path, "zeta", {"switch_ip": "10.0.0.1"})
    save_capture_template(tmp_path, "alpha", {"switch_ip": "10.0.0.2"})
    assert list_capture_templates(tmp_path) == ["alpha", "zeta"]


def test_list_capture_templates_missing_dir_returns_empty(tmp_path):
    assert list_capture_templates(tmp_path / "does-not-exist") == []


def test_load_capture_template_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_capture_template(tmp_path, "does-not-exist")


def test_save_capture_template_creates_models_dir(tmp_path):
    models_dir = tmp_path / "models"
    assert not models_dir.exists()
    save_capture_template(models_dir, "premier", {"switch_ip": "10.0.0.1"})
    assert models_dir.is_dir()
    assert list_capture_templates(models_dir) == ["premier"]
