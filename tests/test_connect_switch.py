"""Tests unitaires de `connect_switch` (switch_capture_core).

Repérée à 0 % par l'audit `coverage.py` de session 54 : chaque appelant
(`inspect_switch`, `SetupAndCaptureThread`, `CaptureRotationThread`,
`UninstallThread`, la GUI...) est testé en remplaçant `connect_switch`
lui-même par un faux (`monkeypatch.setattr(core_mod, "connect_switch",
...)`, voir `test_inspect.py`/`test_setup_and_capture_thread.py`) — la
fonction elle-même, fine enveloppe autour de `netmiko.ConnectHandler`,
n'avait donc jamais été exercée directement.
"""

from __future__ import annotations

import pytest

import switch_capture_core as core_mod
from switch_capture_core import Config, InspectConfig, connect_switch


def make_config(**overrides) -> Config:
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "admin",
        "ssh_password": "secret",
        "capture_interface": "GigabitEthernet1/0/1",
    }
    base.update(overrides)
    return Config(**base)


def test_raises_when_netmiko_not_installed(monkeypatch):
    monkeypatch.setattr(core_mod, "ConnectHandler", None)

    with pytest.raises(RuntimeError, match="netmiko manquant"):
        connect_switch(make_config())


def test_builds_expected_device_dict_and_returns_handler(monkeypatch):
    captured_kwargs: dict = {}
    sentinel = object()

    def fake_connect_handler(**kwargs):
        captured_kwargs.update(kwargs)
        return sentinel

    monkeypatch.setattr(core_mod, "ConnectHandler", fake_connect_handler)

    result = connect_switch(make_config(switch_ip="10.0.0.99", ssh_user="mathilde", ssh_password="s3cr3t"))

    assert result is sentinel
    assert captured_kwargs == {
        "device_type": "hp_comware",
        "host": "10.0.0.99",
        "username": "mathilde",
        "password": "s3cr3t",
        "fast_cli": False,
        "keepalive": core_mod.NETMIKO_KEEPALIVE_SECONDS,
    }


def test_works_with_inspect_config_too(monkeypatch):
    """`connect_switch` accepte aussi bien `Config` que `InspectConfig` (type
    hint `Config | InspectConfig`) : les deux exposent les mêmes trois champs."""
    captured_kwargs: dict = {}

    def fake_connect_handler(**kwargs):
        captured_kwargs.update(kwargs)
        return object()

    monkeypatch.setattr(core_mod, "ConnectHandler", fake_connect_handler)

    cfg = InspectConfig(switch_ip="10.0.0.5", ssh_user="admin", ssh_password="secret")
    connect_switch(cfg)

    assert captured_kwargs["host"] == "10.0.0.5"
    assert captured_kwargs["username"] == "admin"
    assert captured_kwargs["password"] == "secret"
    assert captured_kwargs["keepalive"] == core_mod.NETMIKO_KEEPALIVE_SECONDS


def test_keepalive_is_a_positive_interval_in_seconds():
    """`NETMIKO_KEEPALIVE_SECONDS` doit rester un entier strictement positif :

    `0` désactiverait le keepalive côté netmiko (comportement antérieur,
    silencieusement réintroduit par un futur oubli/refactor), une valeur
    négative n'a pas de sens pour un intervalle. Garde-fou léger, pas un
    test de la valeur exacte (30 s), qui reste un choix documenté au-dessus
    de `connect_switch`, ajustable sans casser ce test.
    """
    assert isinstance(core_mod.NETMIKO_KEEPALIVE_SECONDS, int)
    assert core_mod.NETMIKO_KEEPALIVE_SECONDS > 0
