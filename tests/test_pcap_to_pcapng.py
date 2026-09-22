"""Tests de la conversion .pcap classique -> .pcapng à l'archivage.

Couvre le point #19 de la todo-list de `features.md` (« Privilégier pcapng
à pcap ») : `convert_pcap_to_pcapng` (fonction pure, sans dépendance
externe — pas de scapy/tshark, uniquement `struct`, comme le reste du
parsing pcap de ce module), `archive_capture_file` (factorisation +
repli sur `.pcap` classique en cas d'échec de conversion), et le câblage
dans `CaptureRotationThread._feed_into_tap`/`_feed_into_fifo` via
`Config.archive_as_pcapng` (défaut `True`).

Ne nécessite ni switch réel ni GTK4/Xvfb : uniquement switch_capture_core,
des fichiers .pcap synthétiques construits à la main, et `tmp_path`.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from switch_capture_core import (
    PCAPNG_EPB_BLOCK_TYPE,
    PCAPNG_IDB_BLOCK_TYPE,
    PCAPNG_SHB_BLOCK_TYPE,
    CaptureRotationThread,
    Config,
    SharedState,
    archive_capture_file,
    convert_pcap_to_pcapng,
)

PCAP_MAGIC = 0xA1B2C3D4


def write_synthetic_pcap(path: Path, frames: list[tuple[float, bytes]], linktype: int = 1) -> None:
    """Écrit un .pcap classique minimal avec des trames et timestamps donnés.

    Même helper que `test_tap_pacing.py` (dupliqué ici intentionnellement,
    comme le reste de la suite : chaque fichier de test reste autonome,
    sans import croisé entre modules de test).
    """
    with open(path, "wb") as f:
        f.write(struct.pack("<IHHiIII", PCAP_MAGIC, 2, 4, 0, 0, 65535, linktype))
        for ts, frame in frames:
            ts_sec = int(ts)
            ts_usec = round((ts - ts_sec) * 1_000_000)
            f.write(struct.pack("<IIII", ts_sec, ts_usec, len(frame), len(frame)))
            f.write(frame)


def read_pcapng_blocks(path: Path) -> list[tuple[int, bytes]]:
    """Parseur pcapng minimal pour les besoins des tests (indépendant du code testé).

    Returns:
        Liste de `(block_type, body_sans_bourrage_ni_longueurs)` — le corps
        exact tel qu'il apparaît entre les deux champs de longueur, avant
        retrait du bourrage (les tests connaissent la longueur utile
        attendue et tronquent eux-mêmes si besoin).
    """
    data = path.read_bytes()
    blocks = []
    offset = 0
    while offset < len(data):
        block_type, total_length = struct.unpack_from("<II", data, offset)
        body = data[offset + 8 : offset + total_length - 4]
        trailing_length = struct.unpack_from("<I", data, offset + total_length - 4)[0]
        assert trailing_length == total_length, "longueur de fin de bloc incohérente"
        blocks.append((block_type, body))
        offset += total_length
    return blocks


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


# --------------------------------------------------------------------- #
# convert_pcap_to_pcapng
# --------------------------------------------------------------------- #


def test_convert_produces_shb_idb_then_one_epb_per_frame(tmp_path):
    """Structure attendue : SHB, IDB, puis un EPB par trame, dans l'ordre."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"frame-a"), (1000.5, b"frame-b")])
    pcapng = tmp_path / "capture.pcapng"

    convert_pcap_to_pcapng(pcap, pcapng)

    blocks = read_pcapng_blocks(pcapng)
    types = [block_type for block_type, _ in blocks]
    assert types == [PCAPNG_SHB_BLOCK_TYPE, PCAPNG_IDB_BLOCK_TYPE, PCAPNG_EPB_BLOCK_TYPE, PCAPNG_EPB_BLOCK_TYPE]


def test_convert_preserves_frame_bytes_and_linktype(tmp_path):
    """Les octets de trame et le LinkType (network) du pcap source sont préservés à l'identique."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"frame-a"), (1000.5, b"frame-bb")], linktype=1)
    pcapng = tmp_path / "capture.pcapng"

    convert_pcap_to_pcapng(pcap, pcapng)

    blocks = read_pcapng_blocks(pcapng)
    _, idb_body = blocks[1]
    linktype = struct.unpack_from("<H", idb_body, 0)[0]
    assert linktype == 1

    epb_frames = []
    for block_type, body in blocks[2:]:
        assert block_type == PCAPNG_EPB_BLOCK_TYPE
        cap_len = struct.unpack_from("<I", body, 12)[0]
        epb_frames.append(body[20 : 20 + cap_len])
    assert epb_frames == [b"frame-a", b"frame-bb"]


def test_convert_preserves_timestamps(tmp_path):
    """Les timestamps sont reconstruits fidèlement (résolution microseconde)."""
    pcap = tmp_path / "capture.pcap"
    write_synthetic_pcap(pcap, [(1000.25, b"a"), (1002.75, b"b")])
    pcapng = tmp_path / "capture.pcapng"

    convert_pcap_to_pcapng(pcap, pcapng)

    blocks = read_pcapng_blocks(pcapng)
    timestamps = []
    for _block_type, body in blocks[2:]:
        ts_high, ts_low = struct.unpack_from("<II", body, 4)
        ts_units = (ts_high << 32) | ts_low
        timestamps.append(ts_units / 1_000_000)
    assert timestamps == pytest.approx([1000.25, 1002.75], abs=1e-6)


def test_convert_raises_on_invalid_source(tmp_path):
    """Un pcap source invalide lève ValueError (comportement propagé de `iter_pcap_frames`)."""
    bad = tmp_path / "not-a-pcap.pcap"
    bad.write_bytes(b"\x00" * 24)

    with pytest.raises(ValueError):
        convert_pcap_to_pcapng(bad, tmp_path / "out.pcapng")


def test_convert_raises_on_header_too_short(tmp_path):
    """En-tête global tronqué (< 24 octets, ex. fichier vide ou coupé en
    plein milieu de l'en-tête) : ValueError distincte de "magic inattendu"
    (branche propre à `convert_pcap_to_pcapng`, pas seulement propagée
    depuis `iter_pcap_frames` — ligne 585, audit coverage.py de session 54)."""
    too_short = tmp_path / "trop-court.pcap"
    too_short.write_bytes(b"\x00" * 10)

    with pytest.raises(ValueError, match="trop petit"):
        convert_pcap_to_pcapng(too_short, tmp_path / "out.pcapng")


def test_convert_handles_zero_frames(tmp_path):
    """Un pcap sans aucune trame produit un pcapng valide (SHB + IDB seuls)."""
    pcap = tmp_path / "vide.pcap"
    write_synthetic_pcap(pcap, [])
    pcapng = tmp_path / "vide.pcapng"

    convert_pcap_to_pcapng(pcap, pcapng)

    types = [block_type for block_type, _ in read_pcapng_blocks(pcapng)]
    assert types == [PCAPNG_SHB_BLOCK_TYPE, PCAPNG_IDB_BLOCK_TYPE]


# --------------------------------------------------------------------- #
# archive_capture_file
# --------------------------------------------------------------------- #


def test_archive_capture_file_converts_to_pcapng_by_default(tmp_path):
    """as_pcapng=True (défaut) : le fichier archivé est un .pcapng, le .pcap source disparaît."""
    pcap = tmp_path / "capture_00001.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a")])
    archive_dir = tmp_path / "archive"

    result = archive_capture_file(pcap, archive_dir)

    assert result == archive_dir / "capture_00001.pcapng"
    assert result.exists()
    assert not pcap.exists()
    assert not (archive_dir / "capture_00001.pcap").exists()


def test_archive_capture_file_keeps_pcap_when_disabled(tmp_path):
    """as_pcapng=False : comportement historique inchangé, déplacement tel quel."""
    pcap = tmp_path / "capture_00001.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a")])
    archive_dir = tmp_path / "archive"

    result = archive_capture_file(pcap, archive_dir, as_pcapng=False)

    assert result == archive_dir / "capture_00001.pcap"
    assert result.exists()
    assert not pcap.exists()


def test_archive_capture_file_falls_back_to_pcap_on_conversion_failure(tmp_path):
    """Un fichier corrompu ne doit jamais être perdu : repli sur l'archivage .pcap brut."""
    corrupted = tmp_path / "capture_00001.pcap"
    corrupted.write_bytes(b"\x00" * 24)  # magic invalide -> convert_pcap_to_pcapng lève ValueError
    archive_dir = tmp_path / "archive"

    result = archive_capture_file(corrupted, archive_dir, as_pcapng=True)

    assert result == archive_dir / "capture_00001.pcap"
    assert result.exists()
    assert result.read_bytes() == b"\x00" * 24


# --------------------------------------------------------------------- #
# Câblage dans CaptureRotationThread (_feed_into_tap / _feed_into_fifo)
# --------------------------------------------------------------------- #


class FakeTapWriter:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write_frame(self, frame: bytes) -> None:
        self.written.append(frame)


def test_feed_into_tap_archives_as_pcapng_by_default(tmp_path):
    """Config.archive_as_pcapng par défaut (True) : le fichier archivé après réinjection TAP est en .pcapng."""
    pcap = tmp_path / "capture_00001.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a"), (1000.5, b"b")])
    archive_dir = tmp_path / "archive"

    cfg = make_config(spool_dir=str(tmp_path), archive_dir=str(archive_dir))
    thread = CaptureRotationThread(cfg, SharedState())
    thread._tap_writer = FakeTapWriter()

    thread._feed_into_tap(pcap)

    assert (archive_dir / "capture_00001.pcapng").exists()
    assert not (archive_dir / "capture_00001.pcap").exists()
    assert thread._tap_writer.written == [b"a", b"b"]


def test_feed_into_tap_archives_as_pcap_when_disabled(tmp_path):
    """Config.archive_as_pcapng=False : archivage .pcap classique, comportement historique."""
    pcap = tmp_path / "capture_00001.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a")])
    archive_dir = tmp_path / "archive"

    cfg = make_config(spool_dir=str(tmp_path), archive_dir=str(archive_dir), archive_as_pcapng=False)
    thread = CaptureRotationThread(cfg, SharedState())
    thread._tap_writer = FakeTapWriter()

    thread._feed_into_tap(pcap)

    assert (archive_dir / "capture_00001.pcap").exists()
    assert not (archive_dir / "capture_00001.pcapng").exists()


def test_feed_into_fifo_archives_as_pcapng_by_default(tmp_path):
    """Même comportement par défaut côté mode fifo (_feed_into_fifo)."""
    pcap = tmp_path / "capture_00001.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a")])
    archive_dir = tmp_path / "archive"

    cfg = make_config(
        spool_dir=str(tmp_path),
        archive_dir=str(archive_dir),
        output_mode="fifo",
        tap_interface=None,
    )
    thread = CaptureRotationThread(cfg, SharedState())
    thread._fifo_fd = tmp_path.joinpath("fifo-sink").open("wb")  # évite d'ouvrir un vrai FIFO nommé

    try:
        thread._feed_into_fifo(pcap)
    finally:
        thread._fifo_fd.close()

    assert (archive_dir / "capture_00001.pcapng").exists()
    assert not (archive_dir / "capture_00001.pcap").exists()


def test_config_archive_as_pcapng_defaults_to_true():
    """Champ de configuration : activé par défaut (comportement recommandé, pas de régression d'usage)."""
    cfg = make_config()
    assert cfg.archive_as_pcapng is True
