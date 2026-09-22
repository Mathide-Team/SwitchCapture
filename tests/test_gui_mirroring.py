"""Tests du câblage GTK4 du bloc « Port mirroring » sur le formulaire
principal (voir features.md, section « Urgences », point 18 : le
formulaire ne permettait pas de choisir entre packet-capture/SCP,
mirroring-tunnel et rpcap — `MirrorConfig`/`MirrorThread` existaient déjà
côté core, utilisés jusqu'ici uniquement par le CLI `switch-capture
mirror`, totalement absents de la GUI).

Nécessite PyGObject/GTK4 ET un affichage graphique accessible (Xvfb en
CI/sandbox, voir CLAUDE.md). Se saute proprement (`pytest.skip`) si l'un
des deux manque, plutôt que d'échouer la collecte pour tout le monde —
même pattern que test_gui_new_fields.py.
"""

from __future__ import annotations

import pytest
from conftest import require_gtk4

gi = require_gtk4()

from gi.repository import Gtk

import switch_capture_core as core
import switch_capture_gtk as gtk_app

MIRROR_KEYS = (
    "capture_type",
    "mirror_mode",
    "mirror_group_id",
    "mirror_source_interfaces",
    "mirror_direction",
    "mirror_monitor_interface",
    "mirror_tunnel_id",
    "mirror_tunnel_local_ip",
    "mirror_tunnel_ip",
    "mirror_tunnel_mask",
    "mirror_remote_ip",
    "mirror_loopback_interface",
    "mirror_filter_mode",
    "mirror_acl_number",
    "mirror_acl_rules",
    "mirror_classifier_name",
    "mirror_behavior_name",
    "mirror_qos_policy_name",
    "mirror_remote_probe_vlan",
    "mirror_vsi_name",
    "mirror_vxlan_vni",
    "mirror_service_instance_id",
    "mirror_reflector_interface",
)


def _make_window():
    """Construit une CaptureWindow réelle, ou saute le test si aucun
    affichage graphique n'est accessible (pas d'Xvfb dans cet
    environnement) — copié de test_gui_new_fields.py."""
    app = Gtk.Application(application_id="org.transcende.switch_capture.tests.mirroring")
    holder: dict = {}

    def on_activate(a):
        try:
            holder["win"] = gtk_app.CaptureWindow(a)
        except RuntimeError as exc:
            holder["error"] = exc
        a.quit()

    app.connect("activate", on_activate)
    app.run([])

    if "error" in holder:
        pytest.skip(f"pas d'affichage graphique disponible : {holder['error']}")
    return holder["win"]


def _fill_local_mirror_fields(win) -> None:
    win._entries["switch_ip"].set_text("10.0.0.1")
    win._entries["ssh_user"].set_text("mathilde")
    win._entries["ssh_password"].set_text("secret")
    win._entries["mirror_source_interfaces"].set_text("GigabitEthernet1/0/1, GigabitEthernet1/0/2")
    win._entries["mirror_monitor_interface"].set_text("GigabitEthernet1/0/24")


def _fill_gre_mirror_fields(win) -> None:
    win._entries["switch_ip"].set_text("10.0.0.1")
    win._entries["ssh_user"].set_text("mathilde")
    win._entries["ssh_password"].set_text("secret")
    win._entries["mirror_source_interfaces"].set_text("GigabitEthernet1/0/1")
    win._entries["mirror_mode"].set_selected(win._mirror_mode_options.index("gre"))
    win._entries["mirror_tunnel_local_ip"].set_text("10.0.0.1")
    win._entries["mirror_tunnel_ip"].set_text("192.0.2.1")
    win._entries["mirror_remote_ip"].set_text("203.0.113.1")


def _set_multiline(win, key: str, text: str) -> None:
    """Écrit `text` dans le buffer du `Gtk.TextView` associé à `key`
    (`mirror_acl_rules`) — équivalent de `set_text()` pour un champ
    multi-lignes."""
    win._entries[key].get_buffer().set_text(text, -1)


def _fill_vxlan_mirror_fields(win) -> None:
    win._entries["switch_ip"].set_text("10.0.0.1")
    win._entries["ssh_user"].set_text("mathilde")
    win._entries["ssh_password"].set_text("secret")
    win._entries["mirror_source_interfaces"].set_text("GigabitEthernet1/0/1")
    win._entries["mirror_mode"].set_selected(win._mirror_mode_options.index("vxlan"))
    win._entries["mirror_tunnel_local_ip"].set_text("10.0.0.1")
    win._entries["mirror_remote_ip"].set_text("203.0.113.1")
    win._entries["mirror_remote_probe_vlan"].set_value(666)
    win._entries["mirror_vsi_name"].set_text("mirror")
    win._entries["mirror_vxlan_vni"].set_value(666)
    win._entries["mirror_reflector_interface"].set_text("GigabitEthernet1/0/23")


def _fill_acl_mirror_fields(win, mode: str = "local") -> None:
    win._entries["switch_ip"].set_text("10.0.0.1")
    win._entries["ssh_user"].set_text("mathilde")
    win._entries["ssh_password"].set_text("secret")
    win._entries["mirror_source_interfaces"].set_text("GigabitEthernet1/0/1")
    win._entries["mirror_filter_mode"].set_selected(win._mirror_filter_mode_options.index("acl"))
    _set_multiline(win, "mirror_acl_rules", "rule 0 permit ip source 10.0.0.5 0")
    if mode == "local":
        win._entries["mirror_monitor_interface"].set_text("GigabitEthernet1/0/24")
    else:
        win._entries["mirror_mode"].set_selected(win._mirror_mode_options.index("gre"))
        win._entries["mirror_tunnel_local_ip"].set_text("10.0.0.1")
        win._entries["mirror_remote_ip"].set_text("203.0.113.1")


class TestMirrorFieldsPresent:
    def test_entries_and_rows_exist(self):
        win = _make_window()
        for key in MIRROR_KEYS:
            assert key in win._entries, f"champ manquant : {key}"
        # capture_type n'a pas de ligne propre dans self._rows (dropdown
        # de section, toujours visible) ; tous les autres champs si.
        for key in MIRROR_KEYS:
            if key == "capture_type":
                continue
            assert key in win._rows, f"ligne manquante : {key}"


class TestCaptureTypeVisibility:
    def test_packet_capture_selected_by_default(self):
        win = _make_window()
        assert win._packet_capture_box.get_visible() is True
        assert win._mirroring_box.get_visible() is False

    def test_switching_to_mirroring_swaps_visible_block(self):
        win = _make_window()
        win._entries["capture_type"].set_selected(win._capture_type_options.index("mirroring"))
        win._apply_capture_type_visibility()
        assert win._packet_capture_box.get_visible() is False
        assert win._mirroring_box.get_visible() is True

    def test_switching_back_to_packet_capture_restores_block(self):
        win = _make_window()
        win._entries["capture_type"].set_selected(win._capture_type_options.index("mirroring"))
        win._apply_capture_type_visibility()
        win._entries["capture_type"].set_selected(win._capture_type_options.index("packet-capture"))
        win._apply_capture_type_visibility()
        assert win._packet_capture_box.get_visible() is True
        assert win._mirroring_box.get_visible() is False


class TestMirrorModeVisibility:
    def test_local_mode_shows_monitor_interface_hides_gre_fields(self):
        win = _make_window()
        win._entries["mirror_mode"].set_selected(win._mirror_mode_options.index("local"))
        win._apply_mirror_mode_visibility()
        assert win._rows["mirror_monitor_interface"].get_visible() is True
        for key in (
            "mirror_tunnel_id",
            "mirror_tunnel_local_ip",
            "mirror_tunnel_ip",
            "mirror_tunnel_mask",
            "mirror_remote_ip",
            "mirror_loopback_interface",
        ):
            assert win._rows[key].get_visible() is False, key

    def test_gre_mode_hides_monitor_interface_shows_gre_fields(self):
        win = _make_window()
        win._entries["mirror_mode"].set_selected(win._mirror_mode_options.index("gre"))
        win._apply_mirror_mode_visibility()
        assert win._rows["mirror_monitor_interface"].get_visible() is False
        for key in (
            "mirror_tunnel_id",
            "mirror_tunnel_local_ip",
            "mirror_tunnel_ip",
            "mirror_tunnel_mask",
            "mirror_remote_ip",
            "mirror_loopback_interface",
        ):
            assert win._rows[key].get_visible() is True, key


class TestMirrorModeVxlanVisibility:
    """Câblage GUI du mode `vxlan` (features.md, point 20 — voir
    CLAUDE.md/CAPTURE-METHODS.md section 5, core+CLI traités le
    05/09/2026, GUI ici). Non combinable avec filter_mode=acl côté core
    (MirrorConfig.__post_init__) : les champs vxlan doivent donc rester
    masqués dans cette combinaison précise (voir dernier test)."""

    def test_vxlan_mode_shows_vxlan_fields_and_shared_gre_fields(self):
        win = _make_window()
        win._entries["mirror_mode"].set_selected(win._mirror_mode_options.index("vxlan"))
        win._apply_mirror_mode_visibility()
        for key in (
            "mirror_remote_probe_vlan",
            "mirror_vsi_name",
            "mirror_vxlan_vni",
            "mirror_service_instance_id",
            "mirror_reflector_interface",
        ):
            assert win._rows[key].get_visible() is True, key
        # tunnel_local_ip/remote_ip communs à gre et vxlan (voir MirrorConfig).
        for key in ("mirror_tunnel_local_ip", "mirror_remote_ip"):
            assert win._rows[key].get_visible() is True, key
        # Champs "gre"-uniquement (tunnel_id/tunnel_ip/...) : pas utilisés
        # en mode vxlan, doivent rester masqués.
        for key in (
            "mirror_tunnel_id",
            "mirror_tunnel_ip",
            "mirror_tunnel_mask",
            "mirror_loopback_interface",
        ):
            assert win._rows[key].get_visible() is False, key
        assert win._rows["mirror_monitor_interface"].get_visible() is False

    def test_local_and_gre_modes_hide_vxlan_fields(self):
        win = _make_window()
        for mode in ("local", "gre"):
            win._entries["mirror_mode"].set_selected(win._mirror_mode_options.index(mode))
            win._apply_mirror_mode_visibility()
            for key in (
                "mirror_remote_probe_vlan",
                "mirror_vsi_name",
                "mirror_vxlan_vni",
                "mirror_service_instance_id",
                "mirror_reflector_interface",
            ):
                assert win._rows[key].get_visible() is False, f"{mode}/{key}"

    def test_vxlan_mode_with_acl_filter_mode_hides_vxlan_fields(self):
        """Non combinable côté core (ValueError) : les champs vxlan ne
        doivent pas laisser croire que la combinaison est acceptée."""
        win = _make_window()
        win._entries["mirror_mode"].set_selected(win._mirror_mode_options.index("vxlan"))
        win._entries["mirror_filter_mode"].set_selected(win._mirror_filter_mode_options.index("acl"))
        win._apply_mirror_mode_visibility()
        for key in (
            "mirror_vxlan_hint",
            "mirror_remote_probe_vlan",
            "mirror_vsi_name",
            "mirror_vxlan_vni",
            "mirror_service_instance_id",
            "mirror_reflector_interface",
        ):
            assert win._rows[key].get_visible() is False, key


class TestMirrorFilterModeVisibility:
    def test_port_filter_mode_hides_acl_fields_by_default(self):
        win = _make_window()
        win._apply_mirror_mode_visibility()
        for key in (
            "mirror_acl_number",
            "mirror_acl_rules",
            "mirror_classifier_name",
            "mirror_behavior_name",
            "mirror_qos_policy_name",
        ):
            assert win._rows[key].get_visible() is False, key

    def test_acl_filter_mode_shows_acl_fields(self):
        win = _make_window()
        win._entries["mirror_filter_mode"].set_selected(win._mirror_filter_mode_options.index("acl"))
        win._apply_mirror_mode_visibility()
        for key in (
            "mirror_acl_number",
            "mirror_acl_rules",
            "mirror_classifier_name",
            "mirror_behavior_name",
            "mirror_qos_policy_name",
        ):
            assert win._rows[key].get_visible() is True, key

    def test_acl_filter_mode_with_gre_hides_legacy_tunnel_fields_only(self):
        """En filter_mode=acl + mode=gre, configure_acl_mirror() (core) ne
        lit que tunnel_local_ip/remote_ip — tunnel_id/tunnel_ip/
        tunnel_mask/loopback_interface doivent rester masqués car ignorés
        côté switch dans cette combinaison (contrairement à
        configure_gre_mirror(), filter_mode=port seul)."""
        win = _make_window()
        win._entries["mirror_mode"].set_selected(win._mirror_mode_options.index("gre"))
        win._entries["mirror_filter_mode"].set_selected(win._mirror_filter_mode_options.index("acl"))
        win._apply_mirror_mode_visibility()
        for key in ("mirror_tunnel_local_ip", "mirror_remote_ip"):
            assert win._rows[key].get_visible() is True, key
        for key in (
            "mirror_tunnel_id",
            "mirror_tunnel_ip",
            "mirror_tunnel_mask",
            "mirror_loopback_interface",
        ):
            assert win._rows[key].get_visible() is False, key
        for key in (
            "mirror_acl_number",
            "mirror_acl_rules",
            "mirror_classifier_name",
            "mirror_behavior_name",
            "mirror_qos_policy_name",
        ):
            assert win._rows[key].get_visible() is True, key


class TestBuildMirrorConfig:
    def test_local_mode_builds_valid_mirror_config(self):
        win = _make_window()
        _fill_local_mirror_fields(win)
        cfg = win._build_mirror_config()
        assert isinstance(cfg, core.MirrorConfig)
        assert cfg.mode == "local"
        assert cfg.switch_ip == "10.0.0.1"
        assert cfg.source_interfaces == ["GigabitEthernet1/0/1", "GigabitEthernet1/0/2"]
        assert cfg.monitor_interface == "GigabitEthernet1/0/24"
        assert cfg.group_id == 1
        assert cfg.direction == "both"

    def test_gre_mode_builds_valid_mirror_config(self):
        win = _make_window()
        _fill_gre_mirror_fields(win)
        cfg = win._build_mirror_config()
        assert cfg.mode == "gre"
        assert cfg.tunnel_local_ip == "10.0.0.1"
        assert cfg.tunnel_ip == "192.0.2.1"
        assert cfg.remote_ip == "203.0.113.1"
        assert cfg.tunnel_mask == "255.255.255.0"

    def test_source_interfaces_parsed_and_stripped_from_comma_list(self):
        win = _make_window()
        _fill_local_mirror_fields(win)
        win._entries["mirror_source_interfaces"].set_text(
            " GigabitEthernet1/0/1 ,GigabitEthernet1/0/2 ,  GigabitEthernet1/0/3"
        )
        cfg = win._build_mirror_config()
        assert cfg.source_interfaces == [
            "GigabitEthernet1/0/1",
            "GigabitEthernet1/0/2",
            "GigabitEthernet1/0/3",
        ]

    def test_missing_monitor_interface_in_local_mode_raises(self):
        win = _make_window()
        win._entries["switch_ip"].set_text("10.0.0.1")
        win._entries["ssh_user"].set_text("mathilde")
        win._entries["ssh_password"].set_text("secret")
        win._entries["mirror_source_interfaces"].set_text("GigabitEthernet1/0/1")
        # mirror_monitor_interface volontairement laissé vide.
        with pytest.raises(ValueError):
            win._build_mirror_config()

    def test_missing_source_interfaces_raises(self):
        win = _make_window()
        win._entries["switch_ip"].set_text("10.0.0.1")
        win._entries["ssh_user"].set_text("mathilde")
        win._entries["ssh_password"].set_text("secret")
        win._entries["mirror_monitor_interface"].set_text("GigabitEthernet1/0/24")
        with pytest.raises(ValueError):
            win._build_mirror_config()

    def test_missing_gre_required_fields_raises(self):
        win = _make_window()
        win._entries["switch_ip"].set_text("10.0.0.1")
        win._entries["ssh_user"].set_text("mathilde")
        win._entries["ssh_password"].set_text("secret")
        win._entries["mirror_source_interfaces"].set_text("GigabitEthernet1/0/1")
        win._entries["mirror_mode"].set_selected(win._mirror_mode_options.index("gre"))
        # tunnel_local_ip/tunnel_ip/remote_ip volontairement laissés vides.
        with pytest.raises(ValueError):
            win._build_mirror_config()

    def test_acl_local_mode_builds_valid_mirror_config(self):
        win = _make_window()
        _fill_acl_mirror_fields(win, mode="local")
        cfg = win._build_mirror_config()
        assert isinstance(cfg, core.MirrorConfig)
        assert cfg.filter_mode == "acl"
        assert cfg.mode == "local"
        assert cfg.acl_number == 3000
        assert cfg.acl_rules == ["rule 0 permit ip source 10.0.0.5 0"]
        # classifier/behavior/qos_policy laissés vides côté formulaire :
        # MirrorConfig.__post_init__ les dérive de group_id (défaut 1).
        assert cfg.group_id == 1
        assert cfg.classifier_name == "SWCAP_CLS_1"
        assert cfg.behavior_name == "SWCAP_BEH_1"
        assert cfg.qos_policy_name == "SWCAP_POL_1"

    def test_acl_gre_mode_builds_valid_mirror_config_without_legacy_tunnel_fields(self):
        win = _make_window()
        _fill_acl_mirror_fields(win, mode="gre")
        cfg = win._build_mirror_config()
        assert cfg.filter_mode == "acl"
        assert cfg.mode == "gre"
        assert cfg.tunnel_local_ip == "10.0.0.1"
        assert cfg.remote_ip == "203.0.113.1"
        # tunnel_id/tunnel_ip/loopback_interface non renseignés (champs
        # masqués, non utilisés par configure_acl_mirror) : cfg reste
        # valide, MirrorConfig ne les exige pas en filter_mode=acl.
        assert cfg.tunnel_ip is None
        assert cfg.loopback_interface is None

    def test_acl_rules_parsed_one_per_line_blank_lines_ignored(self):
        win = _make_window()
        _fill_acl_mirror_fields(win, mode="local")
        _set_multiline(
            win,
            "mirror_acl_rules",
            "\n  rule 0 permit ip source 10.0.0.5 0  \n\nrule 5 deny ip source any\n   \n",
        )
        cfg = win._build_mirror_config()
        assert cfg.acl_rules == [
            "rule 0 permit ip source 10.0.0.5 0",
            "rule 5 deny ip source any",
        ]

    def test_acl_optional_names_overridden_when_provided(self):
        win = _make_window()
        _fill_acl_mirror_fields(win, mode="local")
        win._entries["mirror_classifier_name"].set_text("SWCAP_CLS_CUSTOM")
        win._entries["mirror_behavior_name"].set_text("SWCAP_BEH_CUSTOM")
        win._entries["mirror_qos_policy_name"].set_text("SWCAP_POL_CUSTOM")
        cfg = win._build_mirror_config()
        assert cfg.classifier_name == "SWCAP_CLS_CUSTOM"
        assert cfg.behavior_name == "SWCAP_BEH_CUSTOM"
        assert cfg.qos_policy_name == "SWCAP_POL_CUSTOM"

    def test_acl_mode_missing_acl_rules_raises(self):
        win = _make_window()
        win._entries["switch_ip"].set_text("10.0.0.1")
        win._entries["ssh_user"].set_text("mathilde")
        win._entries["ssh_password"].set_text("secret")
        win._entries["mirror_source_interfaces"].set_text("GigabitEthernet1/0/1")
        win._entries["mirror_filter_mode"].set_selected(win._mirror_filter_mode_options.index("acl"))
        win._entries["mirror_monitor_interface"].set_text("GigabitEthernet1/0/24")
        # mirror_acl_rules volontairement laissé vide.
        with pytest.raises(ValueError):
            win._build_mirror_config()

    def test_acl_mode_invalid_acl_number_raises(self):
        win = _make_window()
        _fill_acl_mirror_fields(win, mode="local")
        win._entries["mirror_acl_number"].set_value(3999)  # exclu (voir MirrorConfig)
        with pytest.raises(ValueError):
            win._build_mirror_config()


class TestBuildMirrorConfigVxlan:
    def test_vxlan_mode_builds_valid_mirror_config(self):
        win = _make_window()
        _fill_vxlan_mirror_fields(win)
        cfg = win._build_mirror_config()
        assert isinstance(cfg, core.MirrorConfig)
        assert cfg.mode == "vxlan"
        assert cfg.tunnel_local_ip == "10.0.0.1"
        assert cfg.remote_ip == "203.0.113.1"
        assert cfg.remote_probe_vlan == 666
        assert cfg.vsi_name == "mirror"
        assert cfg.vxlan_vni == 666
        assert cfg.reflector_interface == "GigabitEthernet1/0/23"
        # service_instance_id laissé vide côté formulaire : dérivé de
        # group_id par MirrorConfig.__post_init__ (défaut 1).
        assert cfg.service_instance_id == 1

    def test_vxlan_service_instance_id_overridden_when_provided(self):
        win = _make_window()
        _fill_vxlan_mirror_fields(win)
        win._entries["mirror_service_instance_id"].set_text("42")
        cfg = win._build_mirror_config()
        assert cfg.service_instance_id == 42

    def test_vxlan_mode_missing_required_fields_raises(self):
        win = _make_window()
        win._entries["switch_ip"].set_text("10.0.0.1")
        win._entries["ssh_user"].set_text("mathilde")
        win._entries["ssh_password"].set_text("secret")
        win._entries["mirror_source_interfaces"].set_text("GigabitEthernet1/0/1")
        win._entries["mirror_mode"].set_selected(win._mirror_mode_options.index("vxlan"))
        # tunnel_local_ip/remote_ip/vsi_name/reflector_interface volontairement vides.
        with pytest.raises(ValueError):
            win._build_mirror_config()

    def test_vxlan_mode_combined_with_acl_filter_mode_raises(self):
        win = _make_window()
        _fill_vxlan_mirror_fields(win)
        win._entries["mirror_filter_mode"].set_selected(win._mirror_filter_mode_options.index("acl"))
        _set_multiline(win, "mirror_acl_rules", "rule 0 permit ip source 10.0.0.5 0")
        with pytest.raises(ValueError):
            win._build_mirror_config()


class TestRunMirrorThreadDoesNotCrashOnInvalidConfig:
    def test_push_with_incomplete_form_shows_dialog_instead_of_raising(self):
        win = _make_window()
        # Formulaire mirroring vide : doit afficher un dialogue d'erreur
        # (comme _on_add_session avec un Config incomplet), jamais lever.
        win._run_mirror_thread(teardown=False)
        assert win._mirror_threads == []
