"""Tests du câblage GTK4 des 4 réglages ajoutés au formulaire principal
cette session : `hide_capture_traffic`, `capture_direction`,
`archive_as_pcapng`, `tap_launch_wireshark` (voir features.md, sections
« Menu et préférences »/« Filtre de capture »/« Comportement de capture »
— ces 4 champs étaient déjà traités côté core/CLI, seul le câblage GUI
manquait).

Nécessite PyGObject/GTK4 ET un affichage graphique accessible (Xvfb en
CI/sandbox, voir CLAUDE.md) — sessions précédentes de ce projet n'avaient
ni l'un ni l'autre de disponible. Se saute proprement (`pytest.skip`) si
l'un des deux manque, plutôt que d'échouer la collecte pour tout le monde.
"""

from __future__ import annotations

import pytest
from conftest import require_gtk4

gi = require_gtk4()

from gi.repository import Gtk

import switch_capture_core as core
import switch_capture_gtk as gtk_app

NEW_KEYS = ("hide_capture_traffic", "capture_direction", "archive_as_pcapng", "tap_launch_wireshark")


def _make_window():
    """Construit une CaptureWindow réelle, ou saute le test si aucun
    affichage graphique n'est accessible (pas d'Xvfb dans cet
    environnement)."""
    app = Gtk.Application(application_id="org.transcende.switch_capture.tests")
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


def _fill_required_fields(win) -> None:
    win._entries["switch_ip"].set_text("10.0.0.1")
    win._entries["ssh_user"].set_text("mathilde")
    win._entries["ssh_password"].set_text("secret")
    win._entries["capture_interface"].set_text("GigabitEthernet1/0/1")


class TestNewFieldsPresent:
    def test_entries_and_rows_exist(self):
        win = _make_window()
        for key in NEW_KEYS:
            assert key in win._entries, f"champ manquant : {key}"
            assert key in win._rows, f"ligne manquante : {key}"


class TestNewFieldsDefaultsMatchConfig:
    def test_defaults_match_config_dataclass(self):
        win = _make_window()
        _fill_required_fields(win)
        cfg = win._build_config()
        default_cfg = core.Config(
            switch_ip="10.0.0.1",
            ssh_user="mathilde",
            ssh_password="secret",
            capture_interface="GigabitEthernet1/0/1",
        )
        for key in NEW_KEYS:
            assert getattr(cfg, key) == getattr(default_cfg, key), key


class TestNewFieldsToggleAndRebuild:
    def test_toggling_widgets_changes_built_config(self):
        win = _make_window()
        _fill_required_fields(win)

        win._entries["hide_capture_traffic"].set_active(False)
        win._entries["capture_direction"].set_selected(win._capture_direction_options.index("inbound"))
        win._entries["archive_as_pcapng"].set_active(False)
        win._entries["tap_launch_wireshark"].set_active(True)

        cfg = win._build_config()
        assert cfg.hide_capture_traffic is False
        assert cfg.capture_direction == "inbound"
        assert cfg.archive_as_pcapng is False
        assert cfg.tap_launch_wireshark is True


class TestOutputModeVisibility:
    def test_fifo_hides_tap_launch_wireshark_but_shows_archive_as_pcapng(self):
        win = _make_window()
        win._entries["output_mode"].set_selected(win._output_mode_options.index("fifo"))
        win._apply_output_mode_visibility()
        assert win._rows["archive_as_pcapng"].get_visible() is True
        assert win._rows["tap_launch_wireshark"].get_visible() is False

    def test_tap_shows_both(self):
        win = _make_window()
        win._entries["output_mode"].set_selected(win._output_mode_options.index("tap"))
        win._apply_output_mode_visibility()
        assert win._rows["archive_as_pcapng"].get_visible() is True
        assert win._rows["tap_launch_wireshark"].get_visible() is True

    def test_rpcap_hides_both_file_based_fields(self):
        win = _make_window()
        win._entries["output_mode"].set_selected(win._output_mode_options.index("rpcap"))
        win._apply_output_mode_visibility()
        assert win._rows["archive_as_pcapng"].get_visible() is False
        assert win._rows["tap_launch_wireshark"].get_visible() is False

    def test_hide_capture_traffic_and_capture_direction_always_visible(self):
        win = _make_window()
        for mode in ("fifo", "tap", "rpcap"):
            win._entries["output_mode"].set_selected(win._output_mode_options.index(mode))
            win._apply_output_mode_visibility()
            assert win._rows["hide_capture_traffic"].get_visible() is True, mode
            assert win._rows["capture_direction"].get_visible() is True, mode


class TestTemplateRoundTrip:
    def test_config_to_raw_dict_has_new_keys(self):
        win = _make_window()
        _fill_required_fields(win)
        cfg = win._build_config()
        raw = win._config_to_raw_dict(cfg)
        for key in NEW_KEYS:
            assert key in raw

    def test_apply_form_values_restores_new_fields(self):
        win = _make_window()
        raw = {
            "hide_capture_traffic": False,
            "capture_direction": "outbound",
            "archive_as_pcapng": False,
            "tap_launch_wireshark": True,
        }
        win._apply_form_values(raw)
        assert win._entries["hide_capture_traffic"].get_active() is False
        assert win._capture_direction_options[win._entries["capture_direction"].get_selected()] == "outbound"
        assert win._entries["archive_as_pcapng"].get_active() is False
        assert win._entries["tap_launch_wireshark"].get_active() is True
