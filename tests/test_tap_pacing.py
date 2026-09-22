"""Tests du lissage de réinjection TAP (switch_capture_core).

Couvre la partie testable en isolation du point #1 de la section « Pas
fait » de features.md (« test réel du timing spool -> injection TAP, et
évaluation d'un délai de lissage ») : l'extraction des timestamps
d'origine (`iter_pcap_frames(..., with_timestamps=True)`), le calcul pur
des délais de rejeu (`compute_pacing_delays`), la validation du nouveau
champ `Config.tap_pace_max_gap_seconds`, et le câblage dans
`CaptureRotationThread._feed_into_tap` (délais réellement attendus via
`time.sleep`, monkeypatché ici).

Ne couvre PAS — et ne peut pas couvrir sans switch réel, voir features.md
et CLAUDE.md — la question empirique laissée ouverte : mesurer la durée
réelle SCP + extraction sur un fichier de taille représentative, et
déterminer si un lissage améliore réellement la fluidité côté TAP en
conditions réelles. Ce module ne fait que garantir que le mécanisme de
lissage, une fois activé, fait ce qu'il est censé faire.

Ne nécessite ni switch réel ni GTK4 : uniquement switch_capture_core, un
fichier .pcap synthétique construit à la main, et `tmp_path`.
"""

from __future__ import annotations

import struct
import time as time_module
from pathlib import Path

import pytest

from switch_capture_core import (
    PCAP_GLOBAL_HEADER_LEN,
    CaptureRotationThread,
    Config,
    SharedState,
    compute_pacing_delays,
    iter_pcap_frames,
)

PCAP_MAGIC = 0xA1B2C3D4


def make_config(**overrides) -> Config:
    """Construit un Config valide minimal, avec surcharges optionnelles."""
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "capture_interface": "GigabitEthernet1/0/1",
        "output_mode": "tap",
        "tap_interface": "vcap0",
    }
    base.update(overrides)
    return Config(**base)


def write_synthetic_pcap(path: Path, frames: list[tuple[float, bytes]]) -> None:
    """Écrit un .pcap classique minimal avec des trames et timestamps donnés.

    Args:
        path: fichier .pcap à créer.
        frames: liste de (timestamp_epoch, octets_de_trame), dans l'ordre
            d'écriture souhaité.
    """
    with open(path, "wb") as f:
        # En-tête global pcap classique (little-endian, magic standard) :
        # magic, version_major, version_minor, thiszone, sigfigs, snaplen, network.
        f.write(struct.pack("<IHHiIII", PCAP_MAGIC, 2, 4, 0, 0, 65535, 1))
        for ts, frame in frames:
            ts_sec = int(ts)
            ts_usec = round((ts - ts_sec) * 1_000_000)
            f.write(struct.pack("<IIII", ts_sec, ts_usec, len(frame), len(frame)))
            f.write(frame)


# --------------------------------------------------------------------- #
# iter_pcap_frames(with_timestamps=...)
# --------------------------------------------------------------------- #


def test_iter_pcap_frames_default_unchanged(tmp_path):
    """with_timestamps=False (défaut) : comportement historique inchangé."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"frame-a"), (1000.5, b"frame-b")])

    frames = list(iter_pcap_frames(pcap))

    assert frames == [b"frame-a", b"frame-b"]


def test_iter_pcap_frames_with_timestamps(tmp_path):
    """with_timestamps=True : yield (timestamp, frame), timestamp reconstruit fidèlement."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"frame-a"), (1000.25, b"frame-b"), (1002.75, b"frame-c")])

    result = list(iter_pcap_frames(pcap, with_timestamps=True))

    assert len(result) == 3
    (ts0, f0), (ts1, f1), (ts2, f2) = result
    assert f0 == b"frame-a" and ts0 == pytest.approx(1000.0, abs=1e-6)
    assert f1 == b"frame-b" and ts1 == pytest.approx(1000.25, abs=1e-6)
    assert f2 == b"frame-c" and ts2 == pytest.approx(1002.75, abs=1e-6)


def test_iter_pcap_frames_still_raises_on_bad_magic(tmp_path):
    """Le comportement d'erreur existant (magic invalide) n'est pas affecté par le nouveau paramètre."""
    bad = tmp_path / "not-a-pcap.pcap"
    bad.write_bytes(b"\x00" * PCAP_GLOBAL_HEADER_LEN)

    with pytest.raises(ValueError):
        list(iter_pcap_frames(bad, with_timestamps=True))


def test_iter_pcap_frames_stops_silently_on_truncated_final_record(tmp_path):
    """Capture coupée en cours d'écriture (arrêt brutal, disque plein...) :
    l'enregistrement final annonce `incl_len` octets mais le fichier
    s'arrête avant — ignoré silencieusement plutôt que de lever, seule
    branche de `iter_pcap_frames` encore non exercée (ligne 526, audit
    coverage.py de session 54). Les trames complètes précédentes restent
    récupérées."""
    pcap = tmp_path / "tronque.pcap"
    with open(pcap, "wb") as f:
        f.write(struct.pack("<IHHiIII", PCAP_MAGIC, 2, 4, 0, 0, 65535, 1))
        # Un enregistrement complet et valide.
        f.write(struct.pack("<IIII", 1000, 0, len(b"frame-a"), len(b"frame-a")))
        f.write(b"frame-a")
        # Un en-tête d'enregistrement annonçant 100 octets, mais seuls 5 sont
        # réellement écrits avant la fin du fichier (capture coupée en cours
        # d'écriture de cette trame).
        f.write(struct.pack("<IIII", 1001, 0, 100, 100))
        f.write(b"trunc")

    frames = list(iter_pcap_frames(pcap))

    assert frames == [b"frame-a"]


# --------------------------------------------------------------------- #
# compute_pacing_delays (fonction pure)
# --------------------------------------------------------------------- #


def test_compute_pacing_delays_first_is_always_zero():
    delays = compute_pacing_delays([1000.0, 1000.5, 1001.0], max_gap_seconds=5.0)
    assert delays[0] == 0.0


def test_compute_pacing_delays_reflects_original_gaps():
    delays = compute_pacing_delays([1000.0, 1000.3, 1001.1], max_gap_seconds=5.0)
    assert delays == pytest.approx([0.0, 0.3, 0.8])


def test_compute_pacing_delays_clamped_to_max_gap():
    """Un silence réel de 10 minutes dans la capture d'origine ne doit jamais bloquer 10 minutes."""
    delays = compute_pacing_delays([1000.0, 1600.0], max_gap_seconds=2.0)
    assert delays == [0.0, 2.0]


def test_compute_pacing_delays_negative_gap_clamped_to_zero():
    """Horloge imprécise / trames réordonnées : jamais de délai négatif."""
    delays = compute_pacing_delays([1000.5, 1000.0, 1000.2], max_gap_seconds=5.0)
    assert delays == [0.0, 0.0, pytest.approx(0.2)]


def test_compute_pacing_delays_empty_input():
    assert compute_pacing_delays([], max_gap_seconds=2.0) == []


def test_compute_pacing_delays_same_length_as_input():
    timestamps = [1000.0, 1000.1, 1000.4, 1000.9, 1001.7]
    delays = compute_pacing_delays(timestamps, max_gap_seconds=2.0)
    assert len(delays) == len(timestamps)


# --------------------------------------------------------------------- #
# Config : validation du nouveau champ
# --------------------------------------------------------------------- #


def test_config_tap_pace_playback_defaults_to_false():
    cfg = make_config()
    assert cfg.tap_pace_playback is False
    assert cfg.tap_pace_max_gap_seconds == 2.0


def test_config_rejects_non_positive_max_gap():
    with pytest.raises(ValueError, match="tap_pace_max_gap_seconds"):
        make_config(tap_pace_max_gap_seconds=0)


def test_config_rejects_negative_max_gap():
    with pytest.raises(ValueError, match="tap_pace_max_gap_seconds"):
        make_config(tap_pace_max_gap_seconds=-1.0)


def test_config_accepts_pacing_enabled():
    cfg = make_config(tap_pace_playback=True, tap_pace_max_gap_seconds=0.5)
    assert cfg.tap_pace_playback is True
    assert cfg.tap_pace_max_gap_seconds == 0.5


# --------------------------------------------------------------------- #
# CaptureRotationThread._feed_into_tap : câblage réel du lissage
# --------------------------------------------------------------------- #


class FakeTapWriter:
    """Remplace TapFrameWriter : enregistre les trames écrites sans /dev/net/tun."""

    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write_frame(self, frame: bytes) -> None:
        self.written.append(frame)


def make_rotation_thread(cfg: Config) -> CaptureRotationThread:
    """Construit un CaptureRotationThread minimal, sans démarrer .run()."""
    state = SharedState()
    thread = CaptureRotationThread(cfg, state)
    thread._tap_writer = FakeTapWriter()
    return thread


def test_feed_into_tap_without_pacing_never_sleeps(tmp_path, monkeypatch):
    """Comportement par défaut (tap_pace_playback=False) : aucun sleep, écriture immédiate."""
    pcap = tmp_path / "capture_00001.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1005.0, b"b")])

    cfg = make_config(spool_dir=str(tmp_path), archive_dir=str(tmp_path / "archive"))
    thread = make_rotation_thread(cfg)

    sleep_calls: list[float] = []
    monkeypatch.setattr(time_module, "sleep", lambda s: sleep_calls.append(s))

    thread._feed_into_tap(pcap)

    assert sleep_calls == []
    assert thread._tap_writer.written == [b"a", b"b"]


def test_feed_into_tap_with_pacing_sleeps_between_frames(tmp_path, monkeypatch):
    """tap_pace_playback=True : sleep appelé avec les délais attendus, dans l'ordre, plafonnés."""
    pcap = tmp_path / "capture_00001.pcap"
    # 0.4s puis un silence de 10s (à plafonner à max_gap_seconds=1.0).
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1000.4, b"b"), (1010.4, b"c")])

    cfg = make_config(
        spool_dir=str(tmp_path),
        archive_dir=str(tmp_path / "archive"),
        tap_pace_playback=True,
        tap_pace_max_gap_seconds=1.0,
    )
    thread = make_rotation_thread(cfg)

    sleep_calls: list[float] = []
    monkeypatch.setattr(time_module, "sleep", lambda s: sleep_calls.append(s))

    thread._feed_into_tap(pcap)

    assert sleep_calls == pytest.approx([0.4, 1.0])
    assert thread._tap_writer.written == [b"a", b"b", b"c"]


def test_feed_into_tap_pacing_updates_progress_state(tmp_path, monkeypatch):
    """Le lissage ne doit pas casser la mise à jour de SharedState (files_merged, etc.)."""
    pcap = tmp_path / "capture_00001.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a")])

    cfg = make_config(
        spool_dir=str(tmp_path),
        archive_dir=str(tmp_path / "archive"),
        tap_pace_playback=True,
    )
    thread = make_rotation_thread(cfg)
    monkeypatch.setattr(time_module, "sleep", lambda s: None)

    thread._feed_into_tap(pcap)

    assert thread.state.files_merged == 1
    assert thread.state.last_file_name == "capture_00001.pcap"
