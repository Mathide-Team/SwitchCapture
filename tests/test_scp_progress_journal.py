"""Issue #70 : progression SCP remontée jusqu'à la page « Journal ».

Le cœur publie chaque palier de `make_scp_progress_logger` (mêmes paliers
que le journal DEBUG) dans `SharedState.scp_progress` ; la page « Journal »
le lit sur le thread GTK à chaque rafraîchissement (`format_scp_progress`).
Aucun réseau : `open_scp_ssh_client`/`scp_put`/`scp_get` sont remplacés.
"""

from __future__ import annotations

import switch_capture_core as core
from switch_capture_core import (
    CaptureRotationThread,
    Config,
    ScpProgress,
    SetupAndCaptureThread,
    SharedState,
    format_scp_progress,
    make_scp_progress_logger,
)


def make_config(**overrides) -> Config:
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "capture_interface": "GigabitEthernet1/0/1",
    }
    base.update(overrides)
    return Config(**base)


# --------------------------------------------------------------------- #
# make_scp_progress_logger(on_progress=...)
# --------------------------------------------------------------------- #


def test_on_progress_recoit_les_memes_paliers_que_le_journal():
    vus: list[ScpProgress] = []
    progress = make_scp_progress_logger("ctx", on_progress=vus.append)

    progress(b"a.pcap", 1000, 50)  # 5 % : sous le premier palier
    progress(b"a.pcap", 1000, 100)  # 10 %
    progress(b"a.pcap", 1000, 150)  # 15 % : même palier, ignoré
    progress("a.pcap", 1000, 350)  # 30 % (nom en str)
    progress(b"a.pcap", 1000, 1000)  # 100 %

    assert [(p.name, p.percent, p.sent, p.size, p.context) for p in vus] == [
        ("a.pcap", 10, 100, 1000, "ctx"),
        ("a.pcap", 30, 350, 1000, "ctx"),
        ("a.pcap", 100, 1000, 1000, "ctx"),
    ]


def test_on_progress_suivi_par_fichier():
    vus: list[ScpProgress] = []
    progress = make_scp_progress_logger("ctx", on_progress=vus.append)
    progress(b"a.pcap", 100, 50)
    progress(b"b.pcap", 100, 20)
    progress(b"a.pcap", 100, 50)
    assert [(p.name, p.percent) for p in vus] == [("a.pcap", 50), ("b.pcap", 20)]


def test_fichier_vide_aucun_palier():
    vus: list[ScpProgress] = []
    make_scp_progress_logger("ctx", on_progress=vus.append)(b"vide.pcap", 0, 0)
    assert vus == []


def test_on_progress_en_echec_n_interrompt_pas_le_transfert():
    appels = []

    def casse(progress):
        appels.append(progress.percent)
        raise RuntimeError("widget détruit")

    progress = make_scp_progress_logger("ctx", on_progress=casse)
    progress(b"a.pcap", 100, 10)
    progress(b"a.pcap", 100, 100)
    assert appels == [10, 100]


def test_sans_on_progress_retrocompatible():
    progress = make_scp_progress_logger("ctx")
    progress(b"a.pcap", 100, 100)  # ne lève rien, journalise seulement


# --------------------------------------------------------------------- #
# format_scp_progress (texte de la page « Journal »)
# --------------------------------------------------------------------- #


def test_format_sans_palier():
    assert format_scp_progress(None) == ""


def test_format_palier():
    texte = format_scp_progress(ScpProgress("ctx", "cap_00003.pcap", 40, 4 * 1024**2, 10 * 1024**2))
    assert texte == "SCP cap_00003.pcap : 40 % (4.0 Mo / 10.0 Mo)"


def test_format_petites_tailles():
    assert format_scp_progress(ScpProgress("ctx", "x.bin", 100, 512, 512)) == "SCP x.bin : 100 % (512 o / 512 o)"


# --------------------------------------------------------------------- #
# Câblage : threads -> SharedState.scp_progress
# --------------------------------------------------------------------- #


class _FakeSshClient:
    def close(self) -> None:
        pass


def test_envoi_de_la_feature_publie_la_progression(monkeypatch, tmp_path):
    feature = tmp_path / "packet-capture.bin"
    feature.write_bytes(b"\x00" * 10)

    def fake_put(_client, local_path, remote_path, progress_callback=None):
        progress_callback(remote_path.encode(), 10, 5)
        progress_callback(remote_path.encode(), 10, 10)

    monkeypatch.setattr(core, "open_scp_ssh_client", lambda _cfg: _FakeSshClient())
    monkeypatch.setattr(core, "scp_put", fake_put)
    state = SharedState()
    thread = SetupAndCaptureThread(make_config(feature_bin_path=str(feature)), state)
    thread._push_feature_file()

    assert state.scp_progress == ScpProgress("push_feature_file", feature.name, 100, 10, 10)


def test_rapatriement_de_rotation_publie_la_progression():
    state = SharedState()
    thread = CaptureRotationThread(make_config(), state)
    assert state.scp_progress is None

    thread._scp_progress_logger(b"cap_00001.pcap", 2000, 1000)

    assert state.scp_progress == ScpProgress("process_closed_file_scp", "cap_00001.pcap", 50, 1000, 2000)
    assert "cap_00001.pcap : 50 %" in format_scp_progress(state.scp_progress)


def test_etat_partage_par_defaut():
    assert SharedState().scp_progress is None
