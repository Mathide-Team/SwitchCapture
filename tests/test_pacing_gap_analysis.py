"""Tests de `analyze_pacing_gaps` et `format_pacing_analysis_report` (switch_capture_core).

Couvre le volet nouvellement ajouté du point #1 de la section « Pas
fait » de features.md (« mesure réelle du timing spool -> injection
TAP ») : étant donné un fichier .pcap déjà rapatrié (réel ou
synthétique), quelle serait la distribution des écarts inter-trames et
l'effet de différentes valeurs candidates de `--tap-pace-max-gap` sur
CETTE capture. Ne couvre PAS — et ne peut pas couvrir sans switch réel,
voir features.md et CLAUDE.md — la mesure de la durée SCP elle-même.

Réutilise `write_synthetic_pcap` de `test_tap_pacing.py` plutôt que d'en
dupliquer une variante.

`format_pacing_analysis_report` (section dédiée en fin de fichier) était
l'une des six fonctions sans couverture persistante identifiées en
session 49 (CLAUDE.md, « Prochaine feature ») — regroupée ici plutôt que
dans un fichier séparé car elle ne fait que mettre en forme le résultat
d'`analyze_pacing_gaps`, déjà testée ci-dessus (même principe que
`format_inspect_report` ajoutée à `test_inspect.py` plutôt qu'isolée).
"""

from __future__ import annotations

import pytest
from test_tap_pacing import write_synthetic_pcap

from switch_capture_core import (
    DEFAULT_PACING_CANDIDATE_MAX_GAPS,
    PacingGapAnalysis,
    analyze_pacing_gaps,
    format_pacing_analysis_report,
)

# --------------------------------------------------------------------- #
# Cas de base
# --------------------------------------------------------------------- #


def test_analyze_pacing_gaps_basic_stats(tmp_path):
    """4 trames, écarts réguliers de 1s : stats de base correctes."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(
        pcap,
        [(1000.0, b"a"), (1001.0, b"b"), (1002.0, b"c"), (1003.0, b"d")],
    )

    report = analyze_pacing_gaps(pcap)

    assert report.frame_count == 4
    assert report.gap_count == 3
    assert report.capture_duration_seconds == pytest.approx(3.0)
    assert report.min_gap_seconds == pytest.approx(1.0)
    assert report.max_gap_seconds == pytest.approx(1.0)
    assert report.median_gap_seconds == pytest.approx(1.0)


def test_analyze_pacing_gaps_returns_dataclass_instance(tmp_path):
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1001.0, b"b")])

    report = analyze_pacing_gaps(pcap)

    assert isinstance(report, PacingGapAnalysis)


# --------------------------------------------------------------------- #
# Cas limites : 0 ou 1 trame
# --------------------------------------------------------------------- #


def test_analyze_pacing_gaps_single_frame_no_gaps(tmp_path):
    """Une seule trame : aucun écart, tout à 0, pas de division par zéro."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a")])

    report = analyze_pacing_gaps(pcap)

    assert report.frame_count == 1
    assert report.gap_count == 0
    assert report.capture_duration_seconds == pytest.approx(0.0)
    assert report.min_gap_seconds == 0.0
    assert report.max_gap_seconds == 0.0
    assert report.median_gap_seconds == 0.0
    for effect in report.candidate_effects.values():
        assert effect.clamped_gap_count == 0
        assert effect.clamped_gap_fraction == 0.0
        assert effect.total_playback_seconds == pytest.approx(0.0)


def test_analyze_pacing_gaps_empty_file_raises(tmp_path):
    """Fichier .pcap valide (en-tête seul) mais sans aucune trame : erreur explicite."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [])

    with pytest.raises(ValueError, match="aucune trame"):
        analyze_pacing_gaps(pcap)


def test_analyze_pacing_gaps_bad_magic_propagates(tmp_path):
    """Un fichier non-pcap propage la même erreur qu'`iter_pcap_frames` (pas de re-wrap silencieux)."""
    bogus = tmp_path / "not_a_pcap.pcap"
    bogus.write_bytes(b"not a real pcap file")

    with pytest.raises(ValueError):
        analyze_pacing_gaps(bogus)


# --------------------------------------------------------------------- #
# Écarts négatifs (horloge switch imprécise / réordonnancement)
# --------------------------------------------------------------------- #


def test_analyze_pacing_gaps_negative_gap_clamped_to_zero(tmp_path):
    """Même convention que `compute_pacing_delays` : un écart négatif compte comme 0, jamais négatif."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (999.5, b"b")])

    report = analyze_pacing_gaps(pcap)

    assert report.gap_count == 1
    assert report.min_gap_seconds == pytest.approx(0.0)
    assert report.max_gap_seconds == pytest.approx(0.0)


# --------------------------------------------------------------------- #
# Percentiles sur une distribution non triviale
# --------------------------------------------------------------------- #


def test_analyze_pacing_gaps_percentiles_on_known_distribution(tmp_path):
    """9 écarts connus (1..9s) : percentiles vérifiés contre un calcul de référence indépendant."""
    pcap = tmp_path / "capture.pcap"
    frames = [(1000.0, b"f0")]
    ts = 1000.0
    for gap in range(1, 10):  # écarts 1,2,...,9 -> 10 trames, 9 écarts
        ts += gap
        frames.append((ts, f"f{gap}".encode()))
    write_synthetic_pcap(pcap, frames)

    report = analyze_pacing_gaps(pcap)

    assert report.frame_count == 10
    assert report.gap_count == 9
    assert report.min_gap_seconds == pytest.approx(1.0)
    assert report.max_gap_seconds == pytest.approx(9.0)
    assert report.median_gap_seconds == pytest.approx(5.0)
    # Percentile par interpolation linéaire (méthode "nearest-rank" pondérée)
    # sur [1..9], n=9 : p90 -> rang (9-1)*0.90 = 7.2 -> interpolation entre
    # l'indice 7 (valeur 8) et l'indice 8 (valeur 9) à 0.2 -> 8.2.
    assert report.p90_gap_seconds == pytest.approx(8.2)


# --------------------------------------------------------------------- #
# candidate_effects : cohérence avec compute_pacing_delays
# --------------------------------------------------------------------- #


def test_analyze_pacing_gaps_default_candidates_present(tmp_path):
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1001.0, b"b")])

    report = analyze_pacing_gaps(pcap)

    assert set(report.candidate_effects) == set(DEFAULT_PACING_CANDIDATE_MAX_GAPS)


def test_analyze_pacing_gaps_custom_candidates(tmp_path):
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1001.0, b"b")])

    report = analyze_pacing_gaps(pcap, candidate_max_gaps=[0.1, 3.0])

    assert set(report.candidate_effects) == {0.1, 3.0}


def test_analyze_pacing_gaps_candidate_below_all_gaps_clamps_everything(tmp_path):
    """Un plafond très petit devant tous les écarts réels : 100% des écarts sont raccourcis."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1005.0, b"b"), (1010.0, b"c")])

    report = analyze_pacing_gaps(pcap, candidate_max_gaps=[0.01])

    effect = report.candidate_effects[0.01]
    assert effect.clamped_gap_count == 2
    assert effect.clamped_gap_fraction == pytest.approx(1.0)
    assert effect.total_playback_seconds == pytest.approx(0.02)


def test_analyze_pacing_gaps_candidate_above_all_gaps_clamps_nothing(tmp_path):
    """Un plafond très large devant tous les écarts réels : le rejeu reproduit fidèlement la durée d'origine."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1005.0, b"b"), (1010.0, b"c")])

    report = analyze_pacing_gaps(pcap, candidate_max_gaps=[1000.0])

    effect = report.candidate_effects[1000.0]
    assert effect.clamped_gap_count == 0
    assert effect.clamped_gap_fraction == pytest.approx(0.0)
    assert effect.total_playback_seconds == pytest.approx(report.capture_duration_seconds)


def test_analyze_pacing_gaps_total_playback_matches_compute_pacing_delays(tmp_path):
    """`total_playback_seconds` doit être exactement `sum(compute_pacing_delays(...))` — pas de logique dupliquée."""
    from switch_capture_core import compute_pacing_delays

    pcap = tmp_path / "capture.pcap"
    timestamps = [1000.0, 1000.3, 1002.0, 1002.1, 1010.0]
    write_synthetic_pcap(pcap, [(ts, f"f{i}".encode()) for i, ts in enumerate(timestamps)])

    report = analyze_pacing_gaps(pcap, candidate_max_gaps=[1.5])

    expected = sum(compute_pacing_delays(timestamps, 1.5))
    assert report.candidate_effects[1.5].total_playback_seconds == pytest.approx(expected)


# --------------------------------------------------------------------- #
# format_pacing_analysis_report (pure — mise en forme du PacingGapAnalysis)
# --------------------------------------------------------------------- #


def test_format_pacing_analysis_report_includes_file_path_and_frame_count(tmp_path):
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1001.0, b"b"), (1003.0, b"c")])
    report = analyze_pacing_gaps(pcap)

    text = format_pacing_analysis_report(pcap, report)

    assert f"Fichier : {pcap}" in text
    assert f"Trames : {report.frame_count}" in text
    assert f"{report.capture_duration_seconds:.3f} s" in text


def test_format_pacing_analysis_report_single_frame_short_circuits(tmp_path):
    """`gap_count == 0` (une seule trame, ou aucune) : message dédié, pas de
    section de distribution des écarts ni de tableau des candidats."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a")])
    report = analyze_pacing_gaps(pcap)
    assert report.gap_count == 0  # précondition du cas testé

    text = format_pacing_analysis_report(pcap, report)

    assert "pas d'écart inter-trames" in text
    assert "Écarts inter-trames" not in text
    assert "--tap-pace-max-gap" not in text


def test_format_pacing_analysis_report_gap_distribution_lines_present(tmp_path):
    pcap = tmp_path / "capture.pcap"
    frames = [(1000.0, b"f0")]
    ts = 1000.0
    for gap in range(1, 10):
        ts += gap
        frames.append((ts, f"f{gap}".encode()))
    write_synthetic_pcap(pcap, frames)
    report = analyze_pacing_gaps(pcap)

    text = format_pacing_analysis_report(pcap, report)

    assert f"Écarts inter-trames ({report.gap_count}) :" in text
    assert f"min    : {report.min_gap_seconds:.3f} s" in text
    assert f"médian : {report.median_gap_seconds:.3f} s" in text
    assert f"p90    : {report.p90_gap_seconds:.3f} s" in text
    assert f"p95    : {report.p95_gap_seconds:.3f} s" in text
    assert f"p99    : {report.p99_gap_seconds:.3f} s" in text
    assert f"max    : {report.max_gap_seconds:.3f} s" in text


def test_format_pacing_analysis_report_candidate_effects_lines_sorted_ascending(tmp_path):
    """Les lignes candidates doivent apparaître triées par valeur de plafond croissante
    (`sorted(report.candidate_effects)`), indépendamment de l'ordre d'insertion du dict."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1002.0, b"b"), (1010.0, b"c")])
    report = analyze_pacing_gaps(pcap, candidate_max_gaps=[5.0, 0.5, 2.0])

    text = format_pacing_analysis_report(pcap, report)

    positions = [text.index(f"{max_gap:>6.2f} s ->") for max_gap in (0.5, 2.0, 5.0)]
    assert positions == sorted(positions)


def test_format_pacing_analysis_report_candidate_effect_values_rendered(tmp_path):
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1000.01, b"b"), (1010.0, b"c")])
    report = analyze_pacing_gaps(pcap, candidate_max_gaps=[1.0])
    effect = report.candidate_effects[1.0]

    text = format_pacing_analysis_report(pcap, report)

    assert (
        f"  {1.0:>6.2f} s -> {effect.clamped_gap_count}/{report.gap_count} écarts "
        f"raccourcis ({effect.clamped_gap_fraction * 100:.1f} %), "
        f"rejeu total {effect.total_playback_seconds:.3f} s "
        f"(capture d'origine : {report.capture_duration_seconds:.3f} s)"
    ) in text


def test_format_pacing_analysis_report_mentions_scp_duration_caveat(tmp_path):
    """Rappel explicite : ceci n'évalue pas la durée SCP réelle (seule chose
    bloquée par l'absence de switch physique, voir features-backlog.md)."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1001.0, b"b")])
    report = analyze_pacing_gaps(pcap)

    text = format_pacing_analysis_report(pcap, report)

    assert "pas la durée SCP de rapatriement" in text
    assert "switch réel" in text


def test_format_pacing_analysis_report_returns_multiline_string(tmp_path):
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1001.0, b"b")])
    report = analyze_pacing_gaps(pcap)

    text = format_pacing_analysis_report(pcap, report)

    assert isinstance(text, str)
    assert text.count("\n") > 5
