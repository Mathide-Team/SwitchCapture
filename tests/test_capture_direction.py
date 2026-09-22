"""Tests pour build_capture_direction_clause et Config.capture_direction
(point 6, features.md, « Comportement de capture »).

Fonction pure, sans dépendance GTK4/PyGObject ni switch réel — même
principe que tests/test_capture_filter.py.
"""

import pytest

from switch_capture_core import Config, build_capture_direction_clause


class TestBuildCaptureDirectionClause:
    def test_inbound_gives_no_keyword_at_all(self):
        # Comware ne connaît pas de mot-clé "inbound" explicite : l'absence
        # de "bidirection"/"outbound" EST le sens entrant côté switch.
        assert build_capture_direction_clause("inbound") == ""

    def test_bidirection_keyword(self):
        assert build_capture_direction_clause("bidirection") == "bidirection "

    def test_outbound_keyword(self):
        assert build_capture_direction_clause("outbound") == "outbound "

    def test_trailing_space_present_for_command_concatenation(self):
        assert build_capture_direction_clause("bidirection").endswith(" ")
        assert build_capture_direction_clause("outbound").endswith(" ")

    def test_inbound_has_no_trailing_space(self):
        assert build_capture_direction_clause("inbound") == ""

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError, match="capture_direction invalide"):
            build_capture_direction_clause("both")


class TestConfigCaptureDirection:
    def _base_kwargs(self, **overrides):
        kwargs = {
            "switch_ip": "10.0.0.1",
            "ssh_user": "admin",
            "ssh_password": "secret",
            "capture_interface": "GigabitEthernet1/0/1",
        }
        kwargs.update(overrides)
        return kwargs

    def test_default_is_bidirection(self):
        # Changement de comportement volontaire par rapport au défaut
        # Comware (qui serait "inbound" en l'absence de tout mot-clé) :
        # switch-capture capture les deux sens par défaut désormais,
        # conformément à l'objectif du point 6 de features.md.
        cfg = Config(**self._base_kwargs())
        assert cfg.capture_direction == "bidirection"

    def test_explicit_inbound_accepted(self):
        cfg = Config(**self._base_kwargs(capture_direction="inbound"))
        assert cfg.capture_direction == "inbound"

    def test_explicit_outbound_accepted(self):
        cfg = Config(**self._base_kwargs(capture_direction="outbound"))
        assert cfg.capture_direction == "outbound"

    def test_invalid_direction_rejected(self):
        with pytest.raises(ValueError, match="capture_direction invalide"):
            Config(**self._base_kwargs(capture_direction="both"))


class TestBuildConfigCliCaptureDirection:
    def test_cli_flag_sets_capture_direction(self):
        from switch_capture_cli import build_arg_parser, build_config

        parser = build_arg_parser()
        args = parser.parse_args(
            [
                "capture",
                "--switch-ip",
                "10.0.0.1",
                "--ssh-user",
                "admin",
                "--ssh-password",
                "secret",
                "--capture-interface",
                "GigabitEthernet1/0/1",
                "--capture-direction",
                "outbound",
            ]
        )
        cfg = build_config(args)
        assert cfg.capture_direction == "outbound"

    def test_cli_flag_omitted_keeps_default(self):
        from switch_capture_cli import build_arg_parser, build_config

        parser = build_arg_parser()
        args = parser.parse_args(
            [
                "capture",
                "--switch-ip",
                "10.0.0.1",
                "--ssh-user",
                "admin",
                "--ssh-password",
                "secret",
                "--capture-interface",
                "GigabitEthernet1/0/1",
            ]
        )
        cfg = build_config(args)
        assert cfg.capture_direction == "bidirection"

    def test_cli_flag_rejects_invalid_choice(self):
        from switch_capture_cli import build_arg_parser

        parser = build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "capture",
                    "--switch-ip",
                    "10.0.0.1",
                    "--ssh-user",
                    "admin",
                    "--capture-interface",
                    "GigabitEthernet1/0/1",
                    "--capture-direction",
                    "both",
                ]
            )
