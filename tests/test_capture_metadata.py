"""Tests de `write_capture_metadata` (switch_capture_core).

Couvre l'une des six fonctions sans couverture persistante identifiées en
session 49 (CLAUDE.md, « Prochaine feature »). Écrit le sidecar
`capture-meta.json` consommé par un outil tiers de corrélation de traces
(hors périmètre de ce dépôt) — voir docstring de la fonction et
`docs/architecture.md`, section NTP/métadonnées.

Fonction à effet de bord simple (écriture d'un seul fichier JSON, aucun
réseau) : testée ici uniquement via le système de fichiers réel
(`tmp_path`), sans mock.
"""

from __future__ import annotations

import json
import time

import pytest

from switch_capture_core import Config, SharedState, write_capture_metadata


def make_config(**overrides) -> Config:
    """Construit un Config valide minimal, avec surcharges optionnelles (mêmes défauts que les autres fichiers de tests)."""
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "capture_interface": "GigabitEthernet1/0/1",
    }
    base.update(overrides)
    return Config(**base)


# --------------------------------------------------------------------- #
# Emplacement du fichier : archive_dir prioritaire, repli sur spool_dir
# --------------------------------------------------------------------- #


def test_write_capture_metadata_uses_archive_dir_when_set(tmp_path):
    archive_dir = tmp_path / "archive"
    spool_dir = tmp_path / "spool"
    cfg = make_config(archive_dir=str(archive_dir), spool_dir=str(spool_dir))

    write_capture_metadata(cfg, SharedState())

    assert (archive_dir / "capture-meta.json").exists()
    assert not (spool_dir / "capture-meta.json").exists()


def test_write_capture_metadata_falls_back_to_spool_dir_when_no_archive_dir(tmp_path):
    spool_dir = tmp_path / "spool"
    cfg = make_config(archive_dir=None, spool_dir=str(spool_dir))

    write_capture_metadata(cfg, SharedState())

    assert (spool_dir / "capture-meta.json").exists()


def test_write_capture_metadata_creates_target_dir_if_missing(tmp_path):
    target = tmp_path / "nested" / "archive"
    cfg = make_config(archive_dir=str(target))
    assert not target.exists()

    write_capture_metadata(cfg, SharedState())

    assert target.is_dir()
    assert (target / "capture-meta.json").exists()


def test_write_capture_metadata_overwrites_existing_file(tmp_path):
    cfg1 = make_config(archive_dir=str(tmp_path), capture_label="premier")
    cfg2 = make_config(archive_dir=str(tmp_path), capture_label="second")

    write_capture_metadata(cfg1, SharedState())
    write_capture_metadata(cfg2, SharedState())

    data = json.loads((tmp_path / "capture-meta.json").read_text(encoding="utf-8"))
    assert data["capture_label"] == "second"


# --------------------------------------------------------------------- #
# Contenu du JSON
# --------------------------------------------------------------------- #


def test_write_capture_metadata_content_fields(tmp_path):
    cfg = make_config(
        archive_dir=str(tmp_path),
        capture_label="client",
        capture_filter="host 10.0.0.5",
        output_mode="tap",
        tap_interface="vcap1",
    )
    state = SharedState(
        model="5130EI",
        started_at=1_725_000_000.0,
        ntp_synced=True,
        ntp_detail="Clock status: synchronized",
    )

    write_capture_metadata(cfg, state)

    data = json.loads((tmp_path / "capture-meta.json").read_text(encoding="utf-8"))
    assert data["capture_label"] == "client"
    assert data["switch_ip"] == "10.0.0.1"
    assert data["capture_interface"] == "GigabitEthernet1/0/1"
    assert data["capture_filter"] == "host 10.0.0.5"
    assert data["model"] == "5130EI"
    assert data["ntp_synced"] is True
    assert data["ntp_detail"] == "Clock status: synchronized"
    assert data["output_mode"] == "tap"
    assert data["tap_interface"] == "vcap1"
    assert data["started_at_epoch"] == pytest.approx(1_725_000_000.0)


def test_write_capture_metadata_started_at_iso_matches_local_strftime(tmp_path):
    cfg = make_config(archive_dir=str(tmp_path))
    state = SharedState(started_at=1_725_000_000.0)

    write_capture_metadata(cfg, state)

    data = json.loads((tmp_path / "capture-meta.json").read_text(encoding="utf-8"))
    expected = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(1_725_000_000.0))
    assert data["started_at_iso"] == expected


def test_write_capture_metadata_started_at_none_gives_epoch_and_iso_none(tmp_path):
    cfg = make_config(archive_dir=str(tmp_path))
    state = SharedState()  # started_at par défaut : None

    write_capture_metadata(cfg, state)

    data = json.loads((tmp_path / "capture-meta.json").read_text(encoding="utf-8"))
    assert data["started_at_epoch"] is None
    assert data["started_at_iso"] is None


def test_write_capture_metadata_ntp_not_yet_checked_is_none(tmp_path):
    """`SharedState.ntp_synced` par défaut est `None` (« pas encore vérifié »,
    voir sa docstring) — distinct de `True`/`False`, doit être préservé tel quel."""
    cfg = make_config(archive_dir=str(tmp_path))

    write_capture_metadata(cfg, SharedState())

    data = json.loads((tmp_path / "capture-meta.json").read_text(encoding="utf-8"))
    assert data["ntp_synced"] is None


def test_write_capture_metadata_is_valid_json_with_utf8_content(tmp_path):
    """`ensure_ascii=False` : un label accentué doit être écrit tel quel, pas échappé en \\uXXXX."""
    cfg = make_config(archive_dir=str(tmp_path), capture_label="passerelle-cœur")

    write_capture_metadata(cfg, SharedState())

    raw = (tmp_path / "capture-meta.json").read_text(encoding="utf-8")
    assert "passerelle-cœur" in raw
    assert "\\u" not in raw
