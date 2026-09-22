"""Tests pour build_capture_filter — masquage du trafic SSH/SCP outil<->switch
dans le filtre de capture (point 5, features.md, « Filtre de capture »).

Fonction pure, sans dépendance GTK4/PyGObject ni switch réel.
"""

from switch_capture_core import build_capture_filter


class TestBuildCaptureFilter:
    def test_default_hides_traffic_no_user_filter(self):
        # Comportement historique de ce dépôt (patch utilisateur intégré le
        # 26/08/2026) : par défaut, le trafic SSH/SCP outil<->switch est
        # exclu même sans filtre utilisateur.
        result = build_capture_filter("10.0.0.1", "")
        assert result == 'capture-filter "not (host 10.0.0.1 and port 22)" '

    def test_default_hides_traffic_with_user_filter(self):
        result = build_capture_filter("10.0.0.1", "host 10.0.0.5")
        assert result == 'capture-filter "not (host 10.0.0.1 and port 22) and host 10.0.0.5" '

    def test_hide_explicitly_true_same_as_default(self):
        assert build_capture_filter("10.0.0.1", "", hide_capture_traffic=True) == build_capture_filter("10.0.0.1", "")

    def test_hide_false_no_user_filter_gives_no_clause_at_all(self):
        # Aucune exclusion, aucun filtre utilisateur : pas de clause
        # capture-filter du tout dans la commande envoyée au switch.
        result = build_capture_filter("10.0.0.1", "", hide_capture_traffic=False)
        assert result == ""

    def test_hide_false_with_user_filter_uses_only_user_filter(self):
        result = build_capture_filter("10.0.0.1", "host 10.0.0.5", hide_capture_traffic=False)
        assert result == 'capture-filter "host 10.0.0.5" '

    def test_switch_ip_is_interpolated_correctly(self):
        result = build_capture_filter("192.168.1.254", "")
        assert "host 192.168.1.254 and port 22" in result

    def test_trailing_space_present_for_command_concatenation(self):
        # _run_capture_blocking_local concatène directement la clause dans
        # la commande packet-capture : l'espace final est nécessaire quand
        # la clause n'est pas vide.
        result = build_capture_filter("10.0.0.1", "")
        assert result.endswith(" ")
        result_with_filter = build_capture_filter("10.0.0.1", "tcp port 80")
        assert result_with_filter.endswith(" ")

    def test_empty_result_has_no_trailing_space(self):
        assert build_capture_filter("10.0.0.1", "", hide_capture_traffic=False) == ""
