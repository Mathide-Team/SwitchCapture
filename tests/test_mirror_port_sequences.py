"""Issue #68 : séquences de commandes du mirroring par port (« local » et
« gre ») et cycle de vie de `MirrorThread`.

Même outillage que tests/test_mirror_vxlan.py et test_uninstall_thread.py :
un faux `conn` netmiko (`FakeConn`) journalise chaque commande dans l'ordre
— aucun switch réel, aucune connexion SSH, aucun temps réel (le thread est
exécuté par `run()` direct, ou démarré puis rejoint).
"""

from __future__ import annotations

import pytest

import switch_capture_core as core_mod
from switch_capture_core import (
    MirrorConfig,
    MirrorThread,
    configure_gre_mirror,
    configure_local_mirror,
    teardown_mirror,
)


class FakeConn:
    """Session netmiko simulée : journal des commandes, réponses
    `send_command_timing` paramétrables, échec injectable sur une commande."""

    def __init__(self, timing_responses=None, command_responses=None, fail_on=None) -> None:
        self.calls: list[str] = []
        self.sent_commands: list[str] = []
        self.disconnected = False
        self._timing = timing_responses or {}
        self._responses = command_responses or {}
        self._fail_on = fail_on

    def config_mode(self) -> None:
        self.calls.append("config_mode")

    def exit_config_mode(self) -> None:
        self.calls.append("exit_config_mode")

    def _send(self, cmd: str) -> None:
        self.sent_commands.append(cmd)
        self.calls.append(cmd)
        if cmd == self._fail_on:
            raise OSError(f"session perdue pendant {cmd!r}")

    def send_command(self, cmd: str, **_kwargs) -> str:
        self._send(cmd)
        return self._responses.get(cmd, "")

    def send_command_timing(self, cmd: str, **_kwargs) -> str:
        self._send(cmd)
        return self._timing.get(cmd, "")

    def disconnect(self) -> None:
        self.disconnected = True


def make_local_cfg(**overrides) -> MirrorConfig:
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "group_id": 3,
        "source_interfaces": ["GigabitEthernet1/0/1", "GigabitEthernet1/0/2"],
        "direction": "inbound",
        "monitor_interface": "GigabitEthernet1/0/24",
    }
    base.update(overrides)
    return MirrorConfig(**base)


def make_gre_cfg(**overrides) -> MirrorConfig:
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "mode": "gre",
        "group_id": 5,
        "source_interfaces": ["GigabitEthernet1/0/1"],
        "tunnel_id": 7,
        "tunnel_local_ip": "10.0.0.1",
        "tunnel_ip": "192.0.2.1",
        "tunnel_mask": "255.255.255.252",
        "remote_ip": "203.0.113.10",
    }
    base.update(overrides)
    return MirrorConfig(**base)


# --------------------------------------------------------------------- #
# configure_local_mirror
# --------------------------------------------------------------------- #


class TestConfigureLocalMirror:
    def test_sequence_exacte(self):
        conn = FakeConn()
        configure_local_mirror(conn, make_local_cfg())
        assert conn.calls == [
            "config_mode",
            "mirroring-group 3 local",
            "mirroring-group 3 mirroring-port GigabitEthernet1/0/1 GigabitEthernet1/0/2 inbound",
            "mirroring-group 3 monitor-port GigabitEthernet1/0/24",
            "interface GigabitEthernet1/0/24",
            "undo stp enable",
            "quit",
            "exit_config_mode",
        ]

    def test_direction_et_groupe_par_defaut(self):
        cfg = MirrorConfig(
            switch_ip="10.0.0.1",
            ssh_user="mathilde",
            ssh_password="secret",
            source_interfaces=["GigabitEthernet1/0/1"],
            monitor_interface="GigabitEthernet1/0/24",
        )
        conn = FakeConn()
        configure_local_mirror(conn, cfg)
        assert "mirroring-group 1 mirroring-port GigabitEthernet1/0/1 both" in conn.sent_commands

    def test_echec_intermediaire_interrompt_la_sequence(self):
        conn = FakeConn(fail_on="mirroring-group 3 monitor-port GigabitEthernet1/0/24")
        with pytest.raises(OSError, match="session perdue"):
            configure_local_mirror(conn, make_local_cfg())
        # Rien n'est envoyé après la commande en échec, et le mode
        # configuration n'est pas quitté (c'est MirrorThread qui déconnecte).
        assert conn.calls[-1] == "mirroring-group 3 monitor-port GigabitEthernet1/0/24"
        assert "exit_config_mode" not in conn.calls


# --------------------------------------------------------------------- #
# configure_gre_mirror
# --------------------------------------------------------------------- #

GRE_TUNNEL_ET_GROUPE = [
    "interface tunnel 7 mode gre",
    "ip address 192.0.2.1 255.255.255.252",
    "source 10.0.0.1",
    "destination 203.0.113.10",
    "quit",
    "mirroring-group 5 local",
    "mirroring-group 5 mirroring-port GigabitEthernet1/0/1 both",
    "mirroring-group 5 monitor-port tunnel 7",
]


class TestConfigureGreMirror:
    def test_sequence_sans_service_loopback(self):
        conn = FakeConn()
        configure_gre_mirror(conn, make_gre_cfg())
        assert conn.calls == ["config_mode", *GRE_TUNNEL_ET_GROUPE, "exit_config_mode"]

    def test_sequence_avec_service_loopback_sans_confirmation(self):
        conn = FakeConn()
        configure_gre_mirror(conn, make_gre_cfg(loopback_interface="GigabitEthernet1/0/48"))
        assert conn.calls == [
            "config_mode",
            "service-loopback group 1 type tunnel",
            "interface GigabitEthernet1/0/48",
            "port service-loopback group 1",
            "quit",
            *GRE_TUNNEL_ET_GROUPE,
            "exit_config_mode",
        ]

    @pytest.mark.parametrize("invite", ["Continue? [Y/N]:", "The configuration will be lost. [Y/N]"])
    def test_confirmation_service_loopback(self, invite):
        conn = FakeConn(timing_responses={"port service-loopback group 1": invite})
        configure_gre_mirror(conn, make_gre_cfg(loopback_interface="GigabitEthernet1/0/48"))
        i = conn.sent_commands.index("port service-loopback group 1")
        assert conn.sent_commands[i + 1 : i + 3] == ["y", "quit"]

    def test_echec_dans_le_tunnel_interrompt_la_sequence(self):
        conn = FakeConn(fail_on="destination 203.0.113.10")
        with pytest.raises(OSError):
            configure_gre_mirror(conn, make_gre_cfg())
        assert conn.sent_commands[-1] == "destination 203.0.113.10"
        assert not any(c.startswith("mirroring-group") for c in conn.sent_commands)
        assert "exit_config_mode" not in conn.calls


# --------------------------------------------------------------------- #
# teardown_mirror
# --------------------------------------------------------------------- #


class TestTeardownMirror:
    def test_local_retire_seulement_le_groupe(self):
        conn = FakeConn()
        teardown_mirror(conn, make_local_cfg())
        assert conn.calls == ["config_mode", "undo mirroring-group 3", "exit_config_mode"]

    def test_gre_retire_groupe_puis_tunnel(self):
        conn = FakeConn()
        teardown_mirror(conn, make_gre_cfg())
        assert conn.calls == [
            "config_mode",
            "undo mirroring-group 5",
            "undo interface tunnel 7",
            "exit_config_mode",
        ]

    def test_gre_confirmation_du_retrait_du_tunnel(self):
        conn = FakeConn(timing_responses={"undo interface tunnel 7": "Continue? [Y/N]:"})
        teardown_mirror(conn, make_gre_cfg())
        assert conn.sent_commands == ["undo mirroring-group 5", "undo interface tunnel 7", "y"]

    @pytest.mark.parametrize("make_cfg", [make_local_cfg, make_gre_cfg])
    def test_idempotent_si_deja_retire(self, make_cfg):
        # Le switch répond par une erreur Comware quand le groupe/tunnel
        # n'existe plus : teardown ne doit pas échouer et termine proprement.
        deja = "% The mirroring group does not exist."
        cfg = make_cfg()
        conn = FakeConn(
            command_responses={f"undo mirroring-group {cfg.group_id}": deja},
            timing_responses={f"undo interface tunnel {cfg.tunnel_id}": "% Wrong parameter found at '^' position."},
        )
        teardown_mirror(conn, cfg)
        teardown_mirror(conn, cfg)
        assert conn.calls.count("exit_config_mode") == 2
        assert "y" not in conn.sent_commands


# --------------------------------------------------------------------- #
# MirrorThread.run : cycle de vie
# --------------------------------------------------------------------- #


@pytest.fixture
def connexion(monkeypatch):
    """ConnectHandler simulé : renvoie un FakeConn et mémorise les
    paramètres de connexion."""
    etat = {"conn": FakeConn(), "device": None}

    def fake_connect(**device):
        etat["device"] = device
        return etat["conn"]

    monkeypatch.setattr(core_mod, "ConnectHandler", fake_connect)
    return etat


def _run(cfg, teardown=False):
    resultats = []
    MirrorThread(cfg, teardown=teardown, on_done=lambda ok, msg: resultats.append((ok, msg))).run()
    return resultats


class TestMirrorThreadRun:
    def test_parametres_de_connexion(self, connexion):
        _run(make_local_cfg())
        assert connexion["device"] == {
            "device_type": "hp_comware",
            "host": "10.0.0.1",
            "username": "mathilde",
            "password": "secret",
            "fast_cli": False,
        }

    def test_local_configure_puis_deconnecte(self, connexion):
        assert _run(make_local_cfg()) == [(True, "Mirroring local configuré (groupe 3)")]
        assert "mirroring-group 3 local" in connexion["conn"].sent_commands
        assert connexion["conn"].disconnected

    def test_gre_configure(self, connexion):
        assert _run(make_gre_cfg()) == [(True, "Mirroring GRE configuré (groupe 5, tunnel7 -> 203.0.113.10)")]
        assert "interface tunnel 7 mode gre" in connexion["conn"].sent_commands
        assert connexion["conn"].disconnected

    @pytest.mark.parametrize("make_cfg", [make_local_cfg, make_gre_cfg])
    def test_retrait(self, connexion, make_cfg):
        cfg = make_cfg()
        assert _run(cfg, teardown=True) == [(True, f"Mirroring groupe {cfg.group_id} retiré")]
        assert connexion["conn"].sent_commands[0] == f"undo mirroring-group {cfg.group_id}"
        assert connexion["conn"].disconnected

    def test_echec_de_commande_signale_et_deconnecte(self, connexion):
        connexion["conn"] = FakeConn(fail_on="undo stp enable")
        resultats = _run(make_local_cfg())
        assert resultats == [(False, "session perdue pendant 'undo stp enable'")]
        assert connexion["conn"].disconnected

    def test_echec_de_connexion_signale(self, monkeypatch):
        def refuse(**_device):
            raise ConnectionRefusedError("connexion refusée")

        monkeypatch.setattr(core_mod, "ConnectHandler", refuse)
        assert _run(make_local_cfg()) == [(False, "connexion refusée")]

    def test_netmiko_absent(self, monkeypatch):
        monkeypatch.setattr(core_mod, "ConnectHandler", None)
        assert _run(make_local_cfg()) == [(False, "netmiko manquant : pip install netmiko")]

    def test_sans_callback(self, connexion):
        MirrorThread(make_local_cfg()).run()
        assert connexion["conn"].disconnected

    def test_thread_demarre_et_se_termine(self, connexion):
        resultats = []
        thread = MirrorThread(make_gre_cfg(), teardown=True, on_done=lambda ok, msg: resultats.append(ok))
        assert thread.daemon and thread.name == "mirror-config"
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert resultats == [True]


def make_vxlan_cfg() -> MirrorConfig:
    return MirrorConfig(
        switch_ip="10.0.0.1",
        ssh_user="mathilde",
        ssh_password="secret",
        mode="vxlan",
        group_id=10,
        source_interfaces=["GigabitEthernet1/0/1"],
        remote_probe_vlan=666,
        vsi_name="mirror",
        vxlan_vni=666,
        tunnel_id=0,
        tunnel_local_ip="10.0.0.1",
        remote_ip="203.0.113.10",
        reflector_interface="GigabitEthernet1/0/24",
    )


class TestMirrorThreadVxlan:
    """Aiguillage du mode vxlan (les séquences elles-mêmes sont couvertes
    par tests/test_mirror_vxlan.py)."""

    def test_configure(self, connexion, monkeypatch):
        vus = []
        monkeypatch.setattr(core_mod, "configure_vxlan_mirror", lambda c, cfg: vus.append(c))
        assert _run(make_vxlan_cfg()) == [
            (
                True,
                "Mirroring VXLAN configuré (groupe 10, vlan sonde 666 -> vsi mirror -> tunnel0 -> 203.0.113.10)",
            )
        ]
        assert vus == [connexion["conn"]]

    def test_retrait(self, connexion, monkeypatch):
        vus = []
        monkeypatch.setattr(core_mod, "teardown_vxlan_mirror", lambda c, cfg: vus.append(c))
        assert _run(make_vxlan_cfg(), teardown=True) == [(True, "Mirroring VXLAN groupe 10 retiré")]
        assert vus == [connexion["conn"]]
        assert connexion["conn"].disconnected
