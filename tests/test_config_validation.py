"""Tests de validation de `Config.__post_init__` et `resolve_default_mount_point`.

Repérées à 0 % par l'audit `coverage.py` de session 54 : `InspectConfig`
(classe sœur, volontairement plus légère — voir sa docstring) a déjà ses
propres tests de validation dans `test_inspect.py`, mais `Config` elle-même
n'avait jusqu'ici aucun test dédié pour ses branches de validation propres
(mot de passe manquant, modèle/output_mode/transfer_mode invalides,
tap_interface requis) ni pour `resolve_default_mount_point` — seules
`capture_direction` (`test_capture_direction.py`) et
`tap_pace_max_gap_seconds` (`test_tap_pacing.py`) avaient déjà les leurs.
"""

from __future__ import annotations

import pytest

from switch_capture_core import Config


def _base_kwargs(**overrides) -> dict:
    kwargs = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "admin",
        "ssh_password": "secret",
        "capture_interface": "GigabitEthernet1/0/1",
    }
    kwargs.update(overrides)
    return kwargs


# --------------------------------------------------------------------- #
# Mot de passe SSH manquant (champ vide ET SWITCH_SSH_PASSWORD absente)
# --------------------------------------------------------------------- #


def test_missing_password_raises_when_env_var_also_absent(monkeypatch):
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="Mot de passe SSH manquant"):
        Config(**_base_kwargs(ssh_password=""))


def test_empty_password_falls_back_to_env_var(monkeypatch):
    monkeypatch.setenv("SWITCH_SSH_PASSWORD", "depuis-env")
    cfg = Config(**_base_kwargs(ssh_password=""))
    assert cfg.ssh_password == "depuis-env"


# --------------------------------------------------------------------- #
# model invalide
# --------------------------------------------------------------------- #


def test_invalid_model_raises():
    with pytest.raises(ValueError, match="Modèle invalide"):
        Config(**_base_kwargs(model="inconnu-9999"))


def test_valid_model_accepted():
    cfg = Config(**_base_kwargs(model="5130EI"))
    assert cfg.model == "5130EI"


def test_model_none_skips_validation():
    cfg = Config(**_base_kwargs(model=None))
    assert cfg.model is None


# --------------------------------------------------------------------- #
# output_mode invalide, et tap_interface requis en mode "tap"
# --------------------------------------------------------------------- #


def test_invalid_output_mode_raises():
    with pytest.raises(ValueError, match="output_mode invalide"):
        Config(**_base_kwargs(output_mode="pcap-or-nothing"))


def test_tap_mode_without_tap_interface_raises():
    with pytest.raises(ValueError, match="tap_interface requis"):
        Config(**_base_kwargs(output_mode="tap"))


def test_tap_mode_with_tap_interface_accepted():
    cfg = Config(**_base_kwargs(output_mode="tap", tap_interface="vcap1"))
    assert cfg.output_mode == "tap"
    assert cfg.tap_interface == "vcap1"


def test_rpcap_mode_does_not_require_tap_interface():
    cfg = Config(**_base_kwargs(output_mode="rpcap"))
    assert cfg.tap_interface is None


# --------------------------------------------------------------------- #
# transfer_mode invalide
# --------------------------------------------------------------------- #


def test_invalid_transfer_mode_raises():
    with pytest.raises(ValueError, match="transfer_mode invalide"):
        Config(**_base_kwargs(transfer_mode="ftp"))


def test_sshfs_transfer_mode_accepted():
    cfg = Config(**_base_kwargs(transfer_mode="sshfs"))
    assert cfg.transfer_mode == "sshfs"


# --------------------------------------------------------------------- #
# resolve_default_mount_point
# --------------------------------------------------------------------- #


def test_resolve_default_mount_point_replaces_default():
    cfg = Config(**_base_kwargs(switch_ip="10.0.0.42"))
    assert cfg.mount_point == "./mount"  # défaut du champ, avant résolution

    cfg.resolve_default_mount_point()

    assert cfg.mount_point == "./10.0.0.42"


def test_resolve_default_mount_point_replaces_empty_string():
    cfg = Config(**_base_kwargs(switch_ip="10.0.0.42", mount_point=""))

    cfg.resolve_default_mount_point()

    assert cfg.mount_point == "./10.0.0.42"


def test_resolve_default_mount_point_leaves_custom_value_untouched():
    cfg = Config(**_base_kwargs(mount_point="/mnt/switch-custom"))

    cfg.resolve_default_mount_point()

    assert cfg.mount_point == "/mnt/switch-custom"
