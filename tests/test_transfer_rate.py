"""Tests pour le débit de transfert moyen en direct (compute_average_throughput,
format_transfer_rate) — voir la section dédiée dans features.md.

Fonctions pures, sans dépendance GTK4/PyGObject ni switch réel.
"""

from switch_capture_core import compute_average_throughput, format_transfer_rate


class TestComputeAverageThroughput:
    def test_none_when_not_started(self):
        assert compute_average_throughput(1000, None, 100.0) is None

    def test_none_when_elapsed_is_zero(self):
        assert compute_average_throughput(1000, 100.0, 100.0) is None

    def test_none_when_elapsed_is_negative(self):
        # Horloge locale imprécise / now antérieur à started_at : pas de
        # débit négatif trompeur, on refuse plutôt de répondre.
        assert compute_average_throughput(1000, 100.0, 90.0) is None

    def test_normal_case(self):
        assert compute_average_throughput(2048, 0.0, 2.0) == 1024.0

    def test_zero_bytes_merged_is_a_valid_zero_rate(self):
        # Capture démarrée, rien de rapatrié pour l'instant : 0.0, pas None
        # (distinct de "pas encore calculable").
        assert compute_average_throughput(0, 0.0, 5.0) == 0.0

    def test_fractional_elapsed(self):
        assert compute_average_throughput(100, 0.0, 0.5) == 200.0


class TestFormatTransferRate:
    def test_none_input(self):
        assert format_transfer_rate(None) == "—"

    def test_zero(self):
        assert format_transfer_rate(0) == "0 o/s"

    def test_negative_clamped_to_zero(self):
        # Ne devrait jamais arriver en pratique (compute_average_throughput
        # ne renvoie jamais de négatif), mais l'appelant ne doit pas afficher
        # un débit négatif si jamais une valeur arbitraire est passée.
        assert format_transfer_rate(-42.0) == "0 o/s"

    def test_bytes_per_second(self):
        assert format_transfer_rate(500) == "500 o/s"

    def test_boundary_just_under_1kb(self):
        assert format_transfer_rate(1023) == "1023 o/s"

    def test_kilobytes_per_second(self):
        assert format_transfer_rate(1536) == "1.5 Ko/s"

    def test_boundary_just_under_1mb(self):
        assert format_transfer_rate(1024**2 - 1) == "1024.0 Ko/s"

    def test_megabytes_per_second(self):
        assert format_transfer_rate(5 * 1024**2) == "5.0 Mo/s"

    def test_gigabytes_per_second(self):
        assert format_transfer_rate(3 * 1024**3) == "3.0 Go/s"

    def test_exact_unit_boundaries_use_next_unit(self):
        # Exactement 1024 o/s bascule sur "Ko/s" (< 1024 est la seule
        # condition testée pour rester dans l'unité inférieure).
        assert format_transfer_rate(1024) == "1.0 Ko/s"
        assert format_transfer_rate(1024**2) == "1.0 Mo/s"
        assert format_transfer_rate(1024**3) == "1.0 Go/s"
