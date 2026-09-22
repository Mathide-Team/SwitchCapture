"""Tests pour le mirroring vers VLAN sonde + extension L2 VXLAN
(`switch-capture mirror --mode vxlan`), piste de capture distante
signalée par l'utilisateur le 04/09/2026 et imposée comme méthode valide
le 05/09/2026 malgré l'absence de combinaison H3C officielle unique
documentée (voir features.md et le docstring de
`MirrorConfig.reflector_interface`).

Comme pour test_mirror_acl_filter.py : fonctions pures ou quasi-pures,
sans dépendance GTK4/PyGObject ni switch réel. `configure_vxlan_mirror`/
`teardown_vxlan_mirror` prennent `conn` directement : on les exerce avec
un faux `conn` minimal (`FakeConn`) qui journalise chaque commande
envoyée (y compris `send_command_timing`, utilisé par
`teardown_vxlan_mirror` pour la confirmation « Continue? [Y/N] » de
`undo interface tunnel`, comme `teardown_mirror` en mode gre), sans
jamais ouvrir de connexion SSH réelle.
"""

from __future__ import annotations

import pytest

from switch_capture_core import MirrorConfig, configure_vxlan_mirror, teardown_vxlan_mirror


class FakeConn:
    """Simule une session netmiko en écriture, sans connexion réelle.

    Journalise chaque commande envoyée (`send_command` et
    `send_command_timing`) dans l'ordre, plus les appels à
    `config_mode`/`exit_config_mode`, pour que les tests puissent
    vérifier la séquence exacte de commandes poussées au switch.
    """

    def __init__(self, timing_responses: dict[str, str] | None = None) -> None:
        self.sent_commands: list[str] = []
        self.config_mode_calls = 0
        self.exit_config_mode_calls = 0
        self.disconnected = False
        self._timing_responses = timing_responses or {}

    def config_mode(self) -> None:
        self.config_mode_calls += 1

    def exit_config_mode(self) -> None:
        self.exit_config_mode_calls += 1

    def send_command(self, cmd: str, **_kwargs) -> str:
        self.sent_commands.append(cmd)
        return ""

    def send_command_timing(self, cmd: str, **_kwargs) -> str:
        self.sent_commands.append(cmd)
        return self._timing_responses.get(cmd, "")

    def disconnect(self) -> None:
        self.disconnected = True


def make_vxlan_cfg(**overrides) -> MirrorConfig:
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "mode": "vxlan",
        "group_id": 10,
        "source_interfaces": ["GigabitEthernet1/0/1"],
        "remote_probe_vlan": 666,
        "vsi_name": "mirror",
        "vxlan_vni": 666,
        "tunnel_id": 0,
        "tunnel_local_ip": "10.0.0.1",
        "remote_ip": "203.0.113.10",
        "reflector_interface": "GigabitEthernet1/0/24",
    }
    base.update(overrides)
    return MirrorConfig(**base)


# --------------------------------------------------------------------- #
# Validation (MirrorConfig.__post_init__, mode == "vxlan")
# --------------------------------------------------------------------- #


class TestMirrorConfigVxlanValidation:
    def test_valid_config_accepted_with_exact_user_provided_parameters(self):
        # Paramètres exacts fournis par l'utilisateur (04-05/09/2026) : VLAN
        # 666 / groupe 10, vsi=mirror / vni=666, tunnel 0 mode vxlan,
        # raccordement par service-instance.
        cfg = make_vxlan_cfg()
        assert cfg.mode == "vxlan"
        assert cfg.group_id == 10
        assert cfg.remote_probe_vlan == 666
        assert cfg.vsi_name == "mirror"
        assert cfg.vxlan_vni == 666
        assert cfg.tunnel_id == 0
        assert cfg.reflector_interface == "GigabitEthernet1/0/24"

    def test_invalid_mode_message_lists_vxlan(self):
        with pytest.raises(ValueError, match="local, gre, vxlan"):
            make_vxlan_cfg(mode="bogus")

    def test_service_instance_id_defaults_to_group_id(self):
        cfg = make_vxlan_cfg(group_id=7, service_instance_id=None)
        assert cfg.service_instance_id == 7

    def test_explicit_service_instance_id_respected(self):
        cfg = make_vxlan_cfg(service_instance_id=42)
        assert cfg.service_instance_id == 42

    @pytest.mark.parametrize(
        "missing_field",
        [
            "remote_probe_vlan",
            "vsi_name",
            "vxlan_vni",
            "tunnel_local_ip",
            "remote_ip",
            "reflector_interface",
        ],
    )
    def test_missing_required_vxlan_field_rejected(self, missing_field):
        with pytest.raises(ValueError, match="champs requis en mode 'vxlan' manquants"):
            make_vxlan_cfg(**{missing_field: None})

    @pytest.mark.parametrize("bad_vlan", [0, 4095, -1])
    def test_remote_probe_vlan_out_of_range_rejected(self, bad_vlan):
        with pytest.raises(ValueError, match="remote_probe_vlan invalide"):
            make_vxlan_cfg(remote_probe_vlan=bad_vlan)

    @pytest.mark.parametrize("good_vlan", [1, 666, 4094])
    def test_remote_probe_vlan_in_range_accepted(self, good_vlan):
        cfg = make_vxlan_cfg(remote_probe_vlan=good_vlan)
        assert cfg.remote_probe_vlan == good_vlan

    @pytest.mark.parametrize("bad_vni", [-1, 16777216])
    def test_vxlan_vni_out_of_range_rejected(self, bad_vni):
        with pytest.raises(ValueError, match="vxlan_vni invalide"):
            make_vxlan_cfg(vxlan_vni=bad_vni)

    def test_vxlan_mode_not_combinable_with_acl_filter_mode(self):
        # Portée volontairement limitée cette session : la combinaison
        # mode=vxlan + filter_mode=acl introduirait des interactions non
        # vérifiées (mirror-to inline vs. mirroring-group classique) —
        # explicitement refusée plutôt que silencieusement mal gérée.
        with pytest.raises(ValueError, match="non combinable avec filter_mode 'acl'"):
            make_vxlan_cfg(filter_mode="acl", acl_rules=["rule 0 permit ip source 10.0.0.5 0"])

    def test_local_and_gre_modes_unaffected_by_vxlan_fields(self):
        # Non-régression : les modes existants ne doivent pas soudainement
        # exiger les nouveaux champs vxlan.
        cfg = MirrorConfig(
            switch_ip="10.0.0.1",
            ssh_user="mathilde",
            ssh_password="secret",
            mode="local",
            source_interfaces=["GigabitEthernet1/0/1"],
            monitor_interface="GigabitEthernet1/0/2",
        )
        assert cfg.remote_probe_vlan is None
        assert cfg.vsi_name is None
        assert cfg.service_instance_id is None


# --------------------------------------------------------------------- #
# configure_vxlan_mirror
# --------------------------------------------------------------------- #


class TestConfigureVxlanMirror:
    def test_full_command_sequence(self):
        cfg = make_vxlan_cfg()
        conn = FakeConn()
        configure_vxlan_mirror(conn, cfg)

        assert conn.config_mode_calls == 1
        assert conn.exit_config_mode_calls == 1
        assert conn.sent_commands == [
            "vlan 666",
            "quit",
            "vsi mirror",
            "vxlan 666",
            "quit",
            "interface tunnel 0 mode vxlan",
            "source 10.0.0.1",
            "destination 203.0.113.10",
            "quit",
            "vsi mirror",
            "tunnel 0",
            "quit",
            "interface GigabitEthernet1/0/24",
            "service-instance 10",
            "encapsulation s-vid 666",
            "xconnect vsi mirror",
            "quit",
            "quit",
            "mirroring-group 10 remote-probe vlan 666",
            "mirroring-group 10 mirroring-port GigabitEthernet1/0/1 both",
            "mirroring-group 10 reflector-port GigabitEthernet1/0/24",
        ]

    def test_multiple_source_interfaces_joined_on_mirroring_port_line(self):
        cfg = make_vxlan_cfg(
            source_interfaces=["GigabitEthernet1/0/1", "GigabitEthernet1/0/2"],
            direction="inbound",
        )
        conn = FakeConn()
        configure_vxlan_mirror(conn, cfg)
        assert (
            "mirroring-group 10 mirroring-port GigabitEthernet1/0/1 GigabitEthernet1/0/2 inbound" in conn.sent_commands
        )

    def test_uses_explicit_service_instance_id_when_provided(self):
        cfg = make_vxlan_cfg(service_instance_id=999)
        conn = FakeConn()
        configure_vxlan_mirror(conn, cfg)
        assert "service-instance 999" in conn.sent_commands


# --------------------------------------------------------------------- #
# teardown_vxlan_mirror
# --------------------------------------------------------------------- #


class TestTeardownVxlanMirror:
    def test_full_command_sequence_no_confirmation_prompt(self):
        cfg = make_vxlan_cfg()
        conn = FakeConn()
        teardown_vxlan_mirror(conn, cfg)

        assert conn.config_mode_calls == 1
        assert conn.exit_config_mode_calls == 1
        assert conn.sent_commands == [
            "undo mirroring-group 10",
            "interface GigabitEthernet1/0/24",
            "undo service-instance 10",
            "quit",
            "vsi mirror",
            "undo tunnel 0",
            "quit",
            "undo interface tunnel 0",
            "undo vsi mirror",
            "undo vlan 666",
        ]

    def test_confirmation_prompt_answered_yes(self):
        # Comme teardown_mirror en mode gre : si le switch demande une
        # confirmation avant de supprimer l'interface Tunnel, "y" est
        # envoyé automatiquement.
        cfg = make_vxlan_cfg()
        conn = FakeConn(timing_responses={"undo interface tunnel 0": "Continue? [Y/N]"})
        teardown_vxlan_mirror(conn, cfg)
        idx = conn.sent_commands.index("undo interface tunnel 0")
        assert conn.sent_commands[idx + 1] == "y"

    def test_teardown_uses_same_reflector_and_service_instance_as_configure(self):
        cfg = make_vxlan_cfg(reflector_interface="GigabitEthernet1/0/23", service_instance_id=5)
        conn = FakeConn()
        teardown_vxlan_mirror(conn, cfg)
        assert "interface GigabitEthernet1/0/23" in conn.sent_commands
        assert "undo service-instance 5" in conn.sent_commands
