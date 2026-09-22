"""Tests pour le flow mirroring filtré par ACL (« Filtrage ACL pour
`switch-capture mirror` », piste d'amélioration listée dans CLAUDE.md,
traitée le 01/09/2026 — voir aussi CAPTURE-METHODS.md section 4, dont la
syntaxe a été vérifiée contre la doc H3C officielle en session du
01/09/2026 précédente).

Comme pour test_capture_direction.py/test_capture_filter.py : fonctions
pures ou quasi-pures, sans dépendance GTK4/PyGObject ni switch réel.
`configure_acl_mirror`/`teardown_acl_mirror` prennent `conn` directement
(comme `configure_local_mirror`/`configure_gre_mirror`/`teardown_mirror`,
déjà non couvertes par un test dédié avant ce fichier) : on les exerce
avec un faux `conn` minimal (`FakeConn`) qui journalise chaque commande
envoyée, sans jamais ouvrir de connexion SSH réelle.
"""

from __future__ import annotations

import pytest

from switch_capture_core import MirrorConfig, configure_acl_mirror, teardown_acl_mirror


class FakeConn:
    """Simule une session netmiko en écriture, sans connexion réelle.

    Journalise chaque commande envoyée (`send_command`) dans l'ordre, plus
    les appels à `config_mode`/`exit_config_mode`, pour que les tests
    puissent vérifier la séquence exacte de commandes poussées au switch.
    """

    def __init__(self) -> None:
        self.sent_commands: list[str] = []
        self.config_mode_calls = 0
        self.exit_config_mode_calls = 0
        self.disconnected = False

    def config_mode(self) -> None:
        self.config_mode_calls += 1

    def exit_config_mode(self) -> None:
        self.exit_config_mode_calls += 1

    def send_command(self, cmd: str, **_kwargs) -> str:
        self.sent_commands.append(cmd)
        return ""

    def disconnect(self) -> None:
        self.disconnected = True


def make_acl_cfg(**overrides) -> MirrorConfig:
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "filter_mode": "acl",
        "source_interfaces": ["GigabitEthernet1/0/1"],
        "acl_rules": ["rule 0 permit ip source 10.0.0.5 0"],
        "monitor_interface": "GigabitEthernet1/0/2",  # mode "local" par défaut
    }
    base.update(overrides)
    return MirrorConfig(**base)


# --------------------------------------------------------------------- #
# Validation (MirrorConfig.__post_init__, filter_mode == "acl")
# --------------------------------------------------------------------- #


class TestMirrorConfigAclValidation:
    def test_filter_mode_defaults_to_port(self):
        cfg = MirrorConfig(
            switch_ip="10.0.0.1",
            ssh_user="mathilde",
            ssh_password="secret",
            source_interfaces=["GigabitEthernet1/0/1"],
            monitor_interface="GigabitEthernet1/0/2",
        )
        assert cfg.filter_mode == "port"
        # Régression : le mode "port" existant ne doit pas exiger acl_rules.
        assert cfg.acl_rules == []

    def test_invalid_filter_mode_rejected(self):
        with pytest.raises(ValueError, match="filter_mode invalide"):
            make_acl_cfg(filter_mode="bogus")

    def test_acl_mode_requires_acl_rules(self):
        with pytest.raises(ValueError, match="au moins une règle ACL"):
            make_acl_cfg(acl_rules=[])

    @pytest.mark.parametrize("bad_number", [2999, 4000, 3998, 3999, 1])
    def test_acl_number_out_of_range_rejected(self, bad_number):
        with pytest.raises(ValueError, match="acl_number invalide"):
            make_acl_cfg(acl_number=bad_number)

    @pytest.mark.parametrize("good_number", [3000, 3500, 3997])
    def test_acl_number_in_range_accepted(self, good_number):
        cfg = make_acl_cfg(acl_number=good_number)
        assert cfg.acl_number == good_number

    def test_default_names_derived_from_group_id(self):
        cfg = make_acl_cfg(group_id=7)
        assert cfg.classifier_name == "SWCAP_CLS_7"
        assert cfg.behavior_name == "SWCAP_BEH_7"
        assert cfg.qos_policy_name == "SWCAP_POL_7"

    def test_explicit_names_respected(self):
        cfg = make_acl_cfg(classifier_name="C_HOST", behavior_name="B_ERSPAN", qos_policy_name="P_HOST")
        assert cfg.classifier_name == "C_HOST"
        assert cfg.behavior_name == "B_ERSPAN"
        assert cfg.qos_policy_name == "P_HOST"

    def test_local_mode_still_requires_monitor_interface(self):
        with pytest.raises(ValueError, match="monitor_interface requis"):
            make_acl_cfg(monitor_interface=None)

    def test_gre_mode_acl_does_not_require_tunnel_ip(self):
        # Différence avec le mode "port" : pas d'interface Tunnel créée en
        # mode "acl", donc tunnel_ip n'est pas nécessaire (voir docstring).
        cfg = make_acl_cfg(
            mode="gre",
            monitor_interface=None,
            tunnel_local_ip="10.0.0.1",
            remote_ip="203.0.113.10",
        )
        assert cfg.tunnel_ip is None

    def test_gre_mode_acl_still_requires_tunnel_local_ip_and_remote_ip(self):
        with pytest.raises(ValueError, match="champs requis en mode 'gre' manquants"):
            make_acl_cfg(mode="gre", monitor_interface=None)

    def test_gre_mode_port_still_requires_tunnel_ip(self):
        # Non-régression : le mode "port" (mirroring-group + vraie interface
        # Tunnel) continue d'exiger tunnel_ip comme avant ce changement.
        with pytest.raises(ValueError, match="tunnel_ip"):
            MirrorConfig(
                switch_ip="10.0.0.1",
                ssh_user="mathilde",
                ssh_password="secret",
                mode="gre",
                source_interfaces=["GigabitEthernet1/0/1"],
                tunnel_local_ip="10.0.0.1",
                remote_ip="203.0.113.10",
            )


# --------------------------------------------------------------------- #
# configure_acl_mirror
# --------------------------------------------------------------------- #


class TestConfigureAclMirrorLocal:
    def test_full_command_sequence_local_both_directions(self):
        cfg = make_acl_cfg(acl_number=3001)
        conn = FakeConn()
        configure_acl_mirror(conn, cfg)

        assert conn.config_mode_calls == 1
        assert conn.exit_config_mode_calls == 1
        assert conn.sent_commands == [
            "acl advanced 3001",
            "rule 0 permit ip source 10.0.0.5 0",
            "quit",
            "traffic classifier SWCAP_CLS_1",
            "if-match acl 3001",
            "quit",
            "traffic behavior SWCAP_BEH_1",
            "mirror-to interface GigabitEthernet1/0/2",
            "quit",
            "qos policy SWCAP_POL_1",
            "classifier SWCAP_CLS_1 behavior SWCAP_BEH_1",
            "quit",
            "interface GigabitEthernet1/0/1",
            "qos apply policy SWCAP_POL_1 inbound",
            "qos apply policy SWCAP_POL_1 outbound",
            "quit",
        ]

    def test_multiple_acl_rules_sent_in_order(self):
        cfg = make_acl_cfg(
            acl_rules=[
                "rule 0 permit ip source 10.0.0.5 0",
                "rule 5 permit ip source 10.0.0.6 0",
            ]
        )
        conn = FakeConn()
        configure_acl_mirror(conn, cfg)
        assert conn.sent_commands[0] == "acl advanced 3000"
        assert conn.sent_commands[1] == "rule 0 permit ip source 10.0.0.5 0"
        assert conn.sent_commands[2] == "rule 5 permit ip source 10.0.0.6 0"
        assert conn.sent_commands[3] == "quit"

    def test_multiple_source_interfaces_each_get_policy_applied(self):
        cfg = make_acl_cfg(source_interfaces=["GigabitEthernet1/0/1", "GigabitEthernet1/0/3"])
        conn = FakeConn()
        configure_acl_mirror(conn, cfg)
        tail = conn.sent_commands[-8:]
        assert tail == [
            "interface GigabitEthernet1/0/1",
            "qos apply policy SWCAP_POL_1 inbound",
            "qos apply policy SWCAP_POL_1 outbound",
            "quit",
            "interface GigabitEthernet1/0/3",
            "qos apply policy SWCAP_POL_1 inbound",
            "qos apply policy SWCAP_POL_1 outbound",
            "quit",
        ]

    @pytest.mark.parametrize(
        "direction, expected",
        [
            ("inbound", ["qos apply policy SWCAP_POL_1 inbound"]),
            ("outbound", ["qos apply policy SWCAP_POL_1 outbound"]),
            (
                "both",
                [
                    "qos apply policy SWCAP_POL_1 inbound",
                    "qos apply policy SWCAP_POL_1 outbound",
                ],
            ),
        ],
    )
    def test_direction_controls_qos_apply_commands(self, direction, expected):
        # Piège documenté dans CAPTURE-METHODS.md section 4 : "qos apply
        # policy" ne prend jamais le mot-clé "both", contrairement à
        # "mirroring-group ... mirroring-port ... both" (mode "port").
        cfg = make_acl_cfg(direction=direction)
        conn = FakeConn()
        configure_acl_mirror(conn, cfg)
        apply_commands = [c for c in conn.sent_commands if c.startswith("qos apply policy")]
        assert apply_commands == expected
        assert not any("both" in c for c in conn.sent_commands)


class TestConfigureAclMirrorGre:
    def test_mirror_to_uses_destination_ip_source_ip(self):
        cfg = make_acl_cfg(
            mode="gre",
            monitor_interface=None,
            tunnel_local_ip="10.0.0.1",
            remote_ip="203.0.113.10",
        )
        conn = FakeConn()
        configure_acl_mirror(conn, cfg)
        assert "mirror-to interface destination-ip 203.0.113.10 source-ip 10.0.0.1" in conn.sent_commands
        # Pas d'interface Tunnel créée en mode "acl" (contrairement au mode
        # "port"/configure_gre_mirror) : aucune commande "interface tunnel".
        assert not any("interface tunnel" in c for c in conn.sent_commands)
        # Pas de service-loopback non plus (obsolète pour cette forme
        # encapsulée, voir CAPTURE-METHODS.md section 4).
        assert not any("service-loopback" in c for c in conn.sent_commands)


# --------------------------------------------------------------------- #
# teardown_acl_mirror
# --------------------------------------------------------------------- #


class TestTeardownAclMirror:
    def test_full_undo_sequence_both_directions(self):
        cfg = make_acl_cfg(acl_number=3002)
        conn = FakeConn()
        teardown_acl_mirror(conn, cfg)

        assert conn.config_mode_calls == 1
        assert conn.exit_config_mode_calls == 1
        assert conn.sent_commands == [
            "interface GigabitEthernet1/0/1",
            "undo qos apply policy inbound",
            "undo qos apply policy outbound",
            "quit",
            "undo qos policy SWCAP_POL_1",
            "undo traffic behavior SWCAP_BEH_1",
            "undo traffic classifier SWCAP_CLS_1",
            "undo acl advanced 3002",
        ]

    def test_undo_qos_apply_never_uses_both_keyword(self):
        cfg = make_acl_cfg(direction="both")
        conn = FakeConn()
        teardown_acl_mirror(conn, cfg)
        assert not any("both" in c for c in conn.sent_commands)

    @pytest.mark.parametrize(
        "direction, expected",
        [
            ("inbound", ["undo qos apply policy inbound"]),
            ("outbound", ["undo qos apply policy outbound"]),
        ],
    )
    def test_single_direction_undo(self, direction, expected):
        cfg = make_acl_cfg(direction=direction)
        conn = FakeConn()
        teardown_acl_mirror(conn, cfg)
        undo_apply = [c for c in conn.sent_commands if c.startswith("undo qos apply policy")]
        assert undo_apply == expected

    def test_cleanup_order_policy_then_behavior_then_classifier_then_acl(self):
        # Ordre requis par Comware (voir docstring de teardown_acl_mirror) :
        # une qos policy encore appliquée sur une interface ne peut pas être
        # supprimée, d'où le retrait préalable sur chaque interface.
        cfg = make_acl_cfg()
        conn = FakeConn()
        teardown_acl_mirror(conn, cfg)
        cleanup = conn.sent_commands[-4:]
        assert cleanup == [
            "undo qos policy SWCAP_POL_1",
            "undo traffic behavior SWCAP_BEH_1",
            "undo traffic classifier SWCAP_CLS_1",
            "undo acl advanced 3000",
        ]


# --------------------------------------------------------------------- #
# MirrorThread : dispatch vers configure_acl_mirror/teardown_acl_mirror
# --------------------------------------------------------------------- #


class TestMirrorThreadAclDispatch:
    """Vérifie que MirrorThread route bien vers les fonctions ACL quand
    filter_mode == "acl", sans passer par mirroring-group — sans connexion
    SSH réelle (switch_capture_core.ConnectHandler monkeypatché).
    """

    def test_configure_dispatches_to_acl_mirror(self, monkeypatch):
        import switch_capture_core as core_mod

        conn = FakeConn()
        monkeypatch.setattr(core_mod, "ConnectHandler", lambda **_kwargs: conn)

        called = {}

        def fake_configure_acl_mirror(c, cfg):
            called["configure_acl_mirror"] = (c, cfg)

        def fail_if_called(*_a, **_k):
            raise AssertionError("ne doit pas être appelée en filter_mode='acl'")

        monkeypatch.setattr(core_mod, "configure_acl_mirror", fake_configure_acl_mirror)
        monkeypatch.setattr(core_mod, "configure_local_mirror", fail_if_called)
        monkeypatch.setattr(core_mod, "configure_gre_mirror", fail_if_called)

        cfg = make_acl_cfg()
        thread = core_mod.MirrorThread(cfg, teardown=False)
        thread.run()

        assert "configure_acl_mirror" in called
        assert called["configure_acl_mirror"] == (conn, cfg)

    def test_teardown_dispatches_to_teardown_acl_mirror(self, monkeypatch):
        import switch_capture_core as core_mod

        conn = FakeConn()
        monkeypatch.setattr(core_mod, "ConnectHandler", lambda **_kwargs: conn)

        called = {}

        def fake_teardown_acl_mirror(c, cfg):
            called["teardown_acl_mirror"] = (c, cfg)

        def fail_if_called(*_a, **_k):
            raise AssertionError("ne doit pas être appelée en filter_mode='acl'")

        monkeypatch.setattr(core_mod, "teardown_acl_mirror", fake_teardown_acl_mirror)
        monkeypatch.setattr(core_mod, "teardown_mirror", fail_if_called)

        cfg = make_acl_cfg()
        thread = core_mod.MirrorThread(cfg, teardown=True)
        thread.run()

        assert "teardown_acl_mirror" in called
        assert called["teardown_acl_mirror"] == (conn, cfg)

    def test_port_mode_unaffected_by_acl_dispatch(self, monkeypatch):
        # Non-régression : filter_mode="port" (défaut) continue de router
        # vers configure_local_mirror comme avant ce changement.
        import switch_capture_core as core_mod

        conn = FakeConn()
        monkeypatch.setattr(core_mod, "ConnectHandler", lambda **_kwargs: conn)

        called = {}
        monkeypatch.setattr(core_mod, "configure_local_mirror", lambda c, cfg: called.setdefault("local", True))

        cfg = MirrorConfig(
            switch_ip="10.0.0.1",
            ssh_user="mathilde",
            ssh_password="secret",
            source_interfaces=["GigabitEthernet1/0/1"],
            monitor_interface="GigabitEthernet1/0/2",
        )
        thread = core_mod.MirrorThread(cfg, teardown=False)
        thread.run()
        assert called.get("local") is True
