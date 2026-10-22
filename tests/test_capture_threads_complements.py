"""Tests de la capture et de la rotation des fichiers (issue #86).

`SetupAndCaptureThread` : capture locale (`packet-capture … write flash:`)
et RPCAP dans leur propre session SSH, montage sshfs, push de la feature
par sshfs. `CaptureRotationThread` : boucle `run()`, mode FIFO sur un
**vrai FIFO nommé** lu par un vrai lecteur, rapatriement SCP et sshfs (vrai
dossier de flash), nettoyage.

Remplacés seulement : le switch (session netmiko simulée, SCP), Wireshark
(`subprocess.Popen`), l'interface TAP (root requis) et `time.sleep` du
module (pour arrêter les boucles après quelques tours, sans attendre).
"""

from __future__ import annotations

import os
import struct
import threading
import time
from pathlib import Path

import pytest
from test_setup_and_capture_thread import FakeConn, make_config
from test_tap_pacing import write_synthetic_pcap

import switch_capture_core as core
from switch_capture_core import CaptureRotationThread, SetupAndCaptureThread, SharedState

DIR_TROIS_FICHIERS = """Directory of flash:
   1 -rw-     1024 Oct 22 2026 10:00:00   capture_00001_20261022100000.pcap
   2 -rw-     1024 Oct 22 2026 10:01:00   capture_00002_20261022100100.pcap
   3 -rw-      512 Oct 22 2026 10:02:00   capture_00003_20261022100200.pcap

1046512 KB total (1045000 KB free)"""


class CanalSimule(FakeConn):
    """FakeConn + canal brut (`write_channel`/`read_channel`) de la capture locale."""

    def __init__(self, *args, lectures: list[str] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.ecrit: list[str] = []
        self.lectures = list(lectures or [])

    def write_channel(self, data: str) -> None:
        self.ecrit.append(data)

    def read_channel(self) -> str:
        return self.lectures.pop(0) if self.lectures else ""


def _arret_apres(monkeypatch, state: SharedState, tours: int) -> list[float]:
    """Remplace `time.sleep` du module : positionne stop_event après `tours` appels."""
    attentes: list[float] = []

    class Temps:
        @staticmethod
        def sleep(secondes: float) -> None:
            attentes.append(secondes)
            if len(attentes) >= tours:
                state.stop_event.set()

        def __getattr__(self, nom: str):
            return getattr(time, nom)

    monkeypatch.setattr(core, "time", Temps())
    return attentes


def _pcap(chemin: Path, *trames: bytes) -> bytes:
    write_synthetic_pcap(chemin, [(1_700_000_000 + i, t) for i, t in enumerate(trames)])
    return chemin.read_bytes()


# ───────────────────────────── SetupAndCaptureThread ─────────────────────────────


class TestCaptureLocale:
    def test_commande_nettoyage_lecture_puis_ctrl_c(self, monkeypatch) -> None:
        state = SharedState()
        conn = CanalSimule({"dir flash:/capture*.pcap": DIR_TROIS_FICHIERS}, lectures=["", "Capturing on GE1/0/1"])
        monkeypatch.setattr(core, "connect_switch", lambda cfg: conn)
        attentes = _arret_apres(monkeypatch, state, tours=3)
        cfg = make_config(rotation_seconds=60, max_ring_files=4, capture_direction="outbound")
        SetupAndCaptureThread(cfg, state)._run_capture_blocking()

        # fichiers d'une capture précédente supprimés avant de relancer
        assert conn.timing_commands[:3] == [
            f"delete flash:/capture_0000{i}_2026102210{i - 1:02d}00.pcap" for i in (1, 2, 3)
        ]
        commande, ctrl_c = conn.ecrit
        assert commande.startswith("packet-capture interface GigabitEthernet1/0/1 outbound capture-filter ")
        assert commande.endswith(
            "limit-captured-frames 0 capture-ring-buffer duration 60 "
            "capture-ring-buffer files 4 write flash:/capture.pcap\n"
        )
        assert 'capture-filter "' in commande  # trafic de la capture masqué par défaut
        assert ctrl_c == "\x03"
        assert attentes == [1, 1, 1, 2] and conn.disconnected

    def test_session_fermee_si_le_nettoyage_echoue(self, monkeypatch) -> None:
        class SuppressionRefusee(CanalSimule):
            def send_command_timing(self, cmd, read_timeout=15):
                raise OSError("session SSH coupée")

        conn = SuppressionRefusee({"dir flash:/": DIR_TROIS_FICHIERS})
        monkeypatch.setattr(core, "connect_switch", lambda cfg: conn)
        with pytest.raises(OSError, match="session SSH coupée"):
            SetupAndCaptureThread(make_config(), SharedState())._run_capture_blocking_local()
        assert conn.disconnected
        assert conn.ecrit == []  # aucune capture lancée


class TestCaptureRpcap:
    def test_demarrage_attente_et_arret(self, monkeypatch) -> None:
        state = SharedState()
        conn = CanalSimule()
        monkeypatch.setattr(core, "connect_switch", lambda cfg: conn)
        _arret_apres(monkeypatch, state, tours=2)
        cfg = make_config(output_mode="rpcap", rpcap_port=2010, capture_direction="inbound")
        SetupAndCaptureThread(cfg, state)._run_capture_blocking()
        assert conn.timing_commands == [
            "packet-capture remote interface GigabitEthernet1/0/1 port 2010",  # inbound : aucun mot-clé
            "packet-capture stop",
        ]
        assert conn.ecrit == [] and conn.disconnected

    def test_session_fermee_si_le_switch_refuse(self, monkeypatch) -> None:
        class Refus(CanalSimule):
            def send_command_timing(self, cmd, read_timeout=15):
                raise ValueError("% Unrecognized command")

        conn = Refus()
        monkeypatch.setattr(core, "connect_switch", lambda cfg: conn)
        with pytest.raises(ValueError):
            SetupAndCaptureThread(make_config(output_mode="rpcap"), SharedState())._run_rpcap_blocking()
        assert conn.disconnected


class TestSshfs:
    def test_montage_lance_sshfs(self, tmp_path: Path, monkeypatch) -> None:
        commandes = []
        monkeypatch.setattr(core.subprocess, "run", lambda cmd, check: commandes.append((cmd, check)))
        monkeypatch.setattr(SetupAndCaptureThread, "_is_mounted", staticmethod(lambda path: False))
        mnt = tmp_path / "mnt" / "switch"
        SetupAndCaptureThread(make_config(mount_point=str(mnt)), SharedState())._mount_sshfs()
        assert mnt.is_dir()
        assert commandes == [
            (
                ["sshfs", "mathilde@10.0.0.1:/", str(mnt), "-o", "reconnect", "-o", "ServerAliveInterval=15",
                 "-o", "ServerAliveCountMax=3"],
                True,
            )
        ]  # fmt: skip

    def test_deja_monte(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: pytest.fail("sshfs relancé"))
        monkeypatch.setattr(SetupAndCaptureThread, "_is_mounted", staticmethod(lambda path: True))
        SetupAndCaptureThread(make_config(mount_point=str(tmp_path)), SharedState())._mount_sshfs()

    @pytest.mark.skipif(not Path("/usr/bin/mountpoint").exists() and not Path("/bin/mountpoint").exists(),
                        reason="mountpoint (util-linux) absent")  # fmt: skip
    def test_is_mounted_reel(self, tmp_path: Path) -> None:
        assert SetupAndCaptureThread._is_mounted(tmp_path) is False
        assert SetupAndCaptureThread._is_mounted(Path("/proc")) is True

    def test_push_feature_par_sshfs(self, tmp_path: Path, monkeypatch) -> None:
        binaire = tmp_path / "feature.bin"
        binaire.write_bytes(b"\x7fELF-feature")
        (tmp_path / "mnt" / "flash").mkdir(parents=True)
        montages = []
        cfg = make_config(
            transfer_mode="sshfs",
            mount_point=str(tmp_path / "mnt"),
            feature_bin_path=str(binaire),
        )
        thread = SetupAndCaptureThread(cfg, SharedState())
        monkeypatch.setattr(thread, "_mount_sshfs", lambda: montages.append(True))
        thread._push_feature_file()
        assert montages == [True]
        assert (tmp_path / "mnt" / "flash" / "feature.bin").read_bytes() == b"\x7fELF-feature"


# ───────────────────────────── CaptureRotationThread ─────────────────────────────


def _rotation(tmp_path: Path, **options) -> CaptureRotationThread:
    base = {"output_mode": "fifo", "spool_dir": str(tmp_path / "spool"), "fifo_path": str(tmp_path / "live")}
    base.update(options)
    return CaptureRotationThread(make_config(**base), SharedState())


class _Lecteur(threading.Thread):
    """Vrai lecteur du FIFO (rôle de Wireshark) : lit jusqu'à la fermeture côté écriture."""

    def __init__(self, chemin: Path) -> None:
        super().__init__(daemon=True)
        self.chemin, self.recu = chemin, b""

    def run(self) -> None:
        with open(self.chemin, "rb") as fifo:
            self.recu = fifo.read()


class TestModeFifo:
    def test_flux_live_reel(self, tmp_path: Path, monkeypatch) -> None:
        lances = []
        monkeypatch.setattr(core.subprocess, "Popen", lambda cmd: lances.append(cmd))
        rotation = _rotation(tmp_path, archive_dir=str(tmp_path / "archive"), archive_as_pcapng=False)
        rotation.fifo_path.write_text("fichier ordinaire resté d'une session précédente")
        rotation._setup_fifo()
        assert rotation.fifo_path.is_fifo()

        lecteur = _Lecteur(rotation.fifo_path)
        lecteur.start()
        rotation._launch_wireshark()  # bloque jusqu'à l'ouverture côté lecture
        assert lances == [["wireshark", "-k", "-i", str(rotation.fifo_path)]]

        premier = _pcap(rotation.spool_dir / "a.pcap", b"\x01" * 60)
        second = _pcap(rotation.spool_dir / "b.pcap", b"\x02" * 70, b"\x03" * 80)
        rotation._dispatch_for_injection(rotation.spool_dir / "a.pcap")
        rotation._dispatch_for_injection(rotation.spool_dir / "b.pcap")
        rotation._cleanup()
        lecteur.join(timeout=5)

        # en-tête global une seule fois, puis les enregistrements des deux fichiers
        assert lecteur.recu == premier + second[core.PCAP_GLOBAL_HEADER_LEN :]
        assert rotation.state.files_merged == 2
        assert rotation.state.bytes_merged == len(premier) + len(second)
        assert rotation.state.last_file_name == "b.pcap"
        assert sorted(p.name for p in (tmp_path / "archive").iterdir()) == ["a.pcap", "b.pcap"]
        assert not rotation.fifo_path.exists()

    def test_sans_archive_le_fichier_est_supprime(self, tmp_path: Path) -> None:
        rotation = _rotation(tmp_path)
        lecture, ecriture = os.pipe()
        rotation._fifo_fd = os.fdopen(ecriture, "wb", buffering=0)
        _pcap(rotation.spool_dir / "a.pcap", b"\x01" * 10)
        rotation._feed_into_fifo(rotation.spool_dir / "a.pcap")
        rotation._fifo_fd.close()
        with os.fdopen(lecture, "rb") as flux:
            assert len(flux.read()) == core.PCAP_GLOBAL_HEADER_LEN + 16 + 10
        assert not (rotation.spool_dir / "a.pcap").exists()

    @pytest.mark.parametrize(
        "contenu",
        [
            pytest.param(b"\xd4\xc3", id="trop-petit"),
            pytest.param(struct.pack("<I", 0x0A0D0D0A) + b"\x00" * 20, id="pcapng"),
        ],
    )
    def test_fichier_invalide_ignore_et_conserve(self, tmp_path: Path, contenu: bytes) -> None:
        rotation = _rotation(tmp_path)
        rotation._fifo_fd = open(os.devnull, "wb")  # noqa: SIM115 - fermé ci-dessous
        fichier = rotation.spool_dir / "x.pcap"
        fichier.write_bytes(contenu)
        rotation._feed_into_fifo(fichier)
        rotation._fifo_fd.close()
        assert fichier.exists() and rotation.state.files_merged == 0

    def test_fifo_pas_pret(self, tmp_path: Path) -> None:
        rotation = _rotation(tmp_path)
        _pcap(rotation.spool_dir / "a.pcap", b"\x01")
        rotation._feed_into_fifo(rotation.spool_dir / "a.pcap")
        assert rotation.state.files_merged == 0 and (rotation.spool_dir / "a.pcap").exists()

    def test_nettoyage_tolere_les_erreurs(self, tmp_path: Path, monkeypatch) -> None:
        class Echec:
            def close(self):
                raise OSError("déjà fermé")

            def disconnect(self):
                raise OSError("session perdue")

        rotation = _rotation(tmp_path)
        rotation._setup_fifo()
        rotation._fifo_fd = rotation._poll_conn = Echec()
        monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: (_ for _ in ()).throw(PermissionError()))
        rotation._cleanup()
        monkeypatch.undo()
        assert rotation.fifo_path.exists()  # suppression refusée, sans exception


class TestModeTap:
    def test_writer_absent(self, tmp_path: Path) -> None:
        rotation = _rotation(tmp_path, output_mode="tap", tap_interface="vcap0")
        _pcap(rotation.spool_dir / "a.pcap", b"\x01")
        rotation._feed_into_tap(rotation.spool_dir / "a.pcap")
        assert rotation.state.files_merged == 0

    def test_archive_apres_injection(self, tmp_path: Path) -> None:
        from test_tap_injector_thread import FakeTapWriter

        rotation = _rotation(tmp_path, output_mode="tap", tap_interface="vcap0", archive_dir=str(tmp_path / "arch"))
        rotation._tap_writer = FakeTapWriter()
        _pcap(rotation.spool_dir / "a.pcap", b"\x01" * 60)
        rotation._feed_into_tap(rotation.spool_dir / "a.pcap")
        assert rotation._tap_writer.written == [b"\x01" * 60]
        assert [p.name for p in (tmp_path / "arch").iterdir()] == ["a.pcapng"]


class TestRapatriementScp:
    @pytest.fixture
    def rotation(self, tmp_path: Path, monkeypatch):
        rotation = _rotation(tmp_path)
        rotation._poll_conn = FakeConn({"dir flash:/capture*.pcap": DIR_TROIS_FICHIERS})
        self.injectes: list[str] = []
        self.clients: list[str] = []
        monkeypatch.setattr(rotation, "_dispatch_for_injection", lambda chemin: self.injectes.append(chemin.name))

        class Client:
            def close(client):
                self.clients.append("fermé")

        def scp_get(client, distant, local, progress_callback):
            local.write_bytes(b"pcap de " + distant.encode())
            progress_callback(distant.encode(), 8, 8)  # signature de la bibliothèque scp

        monkeypatch.setattr(core, "open_scp_ssh_client", lambda cfg: Client())
        monkeypatch.setattr(core, "scp_get", scp_get)
        return rotation

    def test_fichiers_clotures_rapatries_supprimes_injectes(self, rotation) -> None:
        rotation._poll_once()
        attendus = ["capture_00001_20261022100000.pcap", "capture_00002_20261022100100.pcap"]
        assert self.injectes == attendus  # le dernier, en cours d'écriture, n'est pas touché
        assert rotation._poll_conn.timing_commands == [f"delete flash:/{f}" for f in attendus]
        assert self.clients == ["fermé", "fermé"]  # une connexion SCP par fichier
        assert (rotation.spool_dir / attendus[0]).read_bytes() == b"pcap de " + attendus[0].encode()
        assert rotation.state.scp_progress.name == attendus[1]

    def test_un_seul_fichier_rien_a_faire(self, rotation) -> None:
        rotation._poll_conn.responses = {"dir": "   1 -rw-  512 Oct 22 2026 10:02:00   capture_1.pcap"}
        rotation._poll_once_scp()
        assert self.injectes == [] and self.clients == []

    def test_liste_en_echec(self, rotation, monkeypatch) -> None:
        monkeypatch.setattr(core, "list_remote_pcap_files", lambda conn, prefix: (_ for _ in ()).throw(EOFError()))
        rotation._poll_once_scp()
        assert self.injectes == []

    def test_connexion_scp_en_echec(self, rotation, monkeypatch) -> None:
        monkeypatch.setattr(core, "open_scp_ssh_client", lambda cfg: (_ for _ in ()).throw(TimeoutError()))
        rotation._poll_once_scp()
        assert self.injectes == [] and rotation._poll_conn.timing_commands == []

    def test_transfert_en_echec_ni_suppression_ni_injection(self, rotation, monkeypatch) -> None:
        monkeypatch.setattr(core, "scp_get", lambda *a, **k: (_ for _ in ()).throw(OSError("Bad file descriptor")))
        rotation._poll_once_scp()
        assert self.injectes == [] and rotation._poll_conn.timing_commands == []
        assert self.clients == ["fermé", "fermé"]

    def test_fermeture_et_suppression_en_echec_non_bloquantes(self, rotation, monkeypatch) -> None:
        class ClientCasse:
            def close(self):
                raise OSError("transport mort")

        monkeypatch.setattr(core, "open_scp_ssh_client", lambda cfg: ClientCasse())
        monkeypatch.setattr(core, "delete_remote_file", lambda conn, f: (_ for _ in ()).throw(OSError("flash occupée")))
        rotation._poll_once_scp()
        assert len(self.injectes) == 2


class TestRapatriementSshfs:
    @pytest.fixture
    def rotation(self, tmp_path: Path, monkeypatch):
        flash = tmp_path / "mnt" / "flash"
        flash.mkdir(parents=True)
        for nom in ("capture_1.pcap", "capture_2.pcap", "capture_3.pcap", "autre_9.pcap"):
            (flash / nom).write_bytes(nom.encode())
        rotation = _rotation(tmp_path, transfer_mode="sshfs", mount_point=str(tmp_path / "mnt"))
        self.flash, self.injectes = flash, []
        monkeypatch.setattr(rotation, "_dispatch_for_injection", lambda chemin: self.injectes.append(chemin.name))
        return rotation

    def test_copie_suppression_injection(self, rotation) -> None:
        rotation._poll_once()
        assert self.injectes == ["capture_1.pcap", "capture_2.pcap"]
        assert sorted(p.name for p in self.flash.iterdir()) == ["autre_9.pcap", "capture_3.pcap"]
        assert (rotation.spool_dir / "capture_1.pcap").read_bytes() == b"capture_1.pcap"

    def test_montage_inaccessible(self, rotation, monkeypatch) -> None:
        monkeypatch.setattr(Path, "glob", lambda self, motif: (_ for _ in ()).throw(FileNotFoundError()))
        rotation._poll_once_sshfs()
        assert self.injectes == []

    def test_copie_en_echec(self, rotation, monkeypatch) -> None:
        monkeypatch.setattr(core.shutil, "copy", lambda a, b: (_ for _ in ()).throw(OSError("sshfs déconnecté")))
        rotation._poll_once_sshfs()
        assert self.injectes == [] and len(list(self.flash.iterdir())) == 4

    def test_suppression_en_echec_non_bloquante(self, rotation, monkeypatch) -> None:
        vrai_unlink = Path.unlink

        def unlink(self, missing_ok=False):
            if self.parent.name == "flash":
                raise PermissionError(self)
            return vrai_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", unlink)
        rotation._poll_once_sshfs()
        assert self.injectes == ["capture_1.pcap", "capture_2.pcap"]


class TestBoucleRun:
    def test_arret_avant_le_debut_de_capture(self, tmp_path: Path, monkeypatch) -> None:
        rotation = _rotation(tmp_path)
        rotation.state.capture_started.set()
        rotation.state.stop_event.set()
        monkeypatch.setattr(rotation, "_setup_fifo", lambda: pytest.fail("FIFO créé après l'arrêt"))
        rotation.run()

    def test_tap_scp_metadonnees_en_echec_puis_arret(self, tmp_path: Path, monkeypatch) -> None:
        from test_tap_injector_thread import FakeTapWriter

        evenements: list[str] = []
        writer = FakeTapWriter()
        conn = FakeConn({"dir": ""})
        monkeypatch.setattr(core, "ensure_tap_interface", lambda nom: evenements.append(f"tap {nom}"))
        monkeypatch.setattr(core, "delete_tap_interface", lambda nom: evenements.append(f"suppression {nom}"))
        monkeypatch.setattr(core, "TapFrameWriter", lambda nom: writer)
        monkeypatch.setattr(core.subprocess, "Popen", lambda cmd: evenements.append(" ".join(cmd)))
        monkeypatch.setattr(core, "connect_switch", lambda cfg: conn)

        def metadonnees(cfg, state):
            raise OSError("disque plein")

        monkeypatch.setattr(core, "write_capture_metadata", metadonnees)
        rotation = _rotation(
            tmp_path, output_mode="tap", tap_interface="vcap7", tap_launch_wireshark=True, tap_cleanup_on_stop=True
        )
        rotation.state.capture_started.set()
        attentes = _arret_apres(monkeypatch, rotation.state, tours=2)
        rotation.run()

        assert evenements == ["tap vcap7", "wireshark -k -i vcap7", "suppression vcap7"]
        assert conn.sent_commands == ["dir flash:/capture*.pcap"] * 2
        assert attentes == [rotation.cfg.poll_interval] * 2
        assert conn.disconnected and writer.closed
        assert not rotation._injector_thread.is_alive()

    def test_fifo_sshfs(self, tmp_path: Path, monkeypatch) -> None:
        rotation = _rotation(tmp_path, transfer_mode="sshfs", mount_point=str(tmp_path / "mnt"))
        etapes: list[str] = []
        monkeypatch.setattr(rotation, "_setup_fifo", lambda: etapes.append("fifo"))
        monkeypatch.setattr(rotation, "_launch_wireshark", lambda: etapes.append("wireshark"))
        monkeypatch.setattr(core, "write_capture_metadata", lambda cfg, state: etapes.append("métadonnées"))
        monkeypatch.setattr(core, "connect_switch", lambda cfg: pytest.fail("pas de session SSH en sshfs"))
        rotation.state.capture_started.set()
        _arret_apres(monkeypatch, rotation.state, tours=1)
        rotation.run()
        assert etapes == ["fifo", "wireshark", "métadonnées"]
        assert rotation._poll_conn is None
