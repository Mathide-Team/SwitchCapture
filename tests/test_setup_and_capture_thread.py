"""Tests de `SetupAndCaptureThread` (switch_capture_core).

Couvre la dernière des six fonctions/classes sans couverture persistante
identifiées en session 49 (CLAUDE.md, « Prochaine feature »). C'est la plus
volumineuse des six (classe `threading.Thread` orchestrant SSH/SCP/NTP/
installation de feature) — portée volontairement limitée à ce qui est
testable sans switch réel ni accès réseau : `prepare()` (détection modèle,
service de transfert, NTP, push+activation de la feature) et le garde-fou
de `start_capture_blocking()`. La capture elle-même
(`_run_capture_blocking_local`/`_run_rpcap_blocking`, qui délèguent à
`CaptureRotationThread`/Wireshark/FIFO/TAP) reste hors périmètre : elle est
déjà couverte ailleurs par ses propres fichiers de tests dédiés
(`test_tap_pacing.py`, `test_tap_injector_thread.py`, etc.) et nécessiterait
ici une duplication de mocks sans valeur ajoutée.

Même principe que `test_inspect.py` (FakeConn sans switch réel) et
`test_scp_transfer.py` (mock des globals `open_scp_ssh_client`/`scp_put`) —
`SetupAndCaptureThread` est la seule classe du dépôt qui combine les deux
en une seule séquence (`_prepare_switch` en lecture/écriture netmiko,
`_push_feature_file` en SCP paramiko, `_activate_feature` en netmiko avec
confirmation), d'où un `FakeConn` un peu plus complet que celui de
`test_inspect.py` (ajoute `config_mode`/`exit_config_mode`/
`send_command_timing`) plutôt qu'une réutilisation directe.
"""

from __future__ import annotations

import time as time_module
from pathlib import Path

import pytest

import switch_capture_core as core
from switch_capture_core import Config, SetupAndCaptureThread, SharedState


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


def make_thread(cfg: Config | None = None, state: SharedState | None = None) -> SetupAndCaptureThread:
    return SetupAndCaptureThread(cfg or make_config(), state or SharedState())


class FakeConn:
    """Simule une session netmiko complète (lecture + configuration).

    `send_command(cmd)` fait correspondre `cmd` à la première clé de
    `responses` qu'elle contient (même principe que `FakeConn` dans
    `test_inspect.py`). `send_command_timing` répond `confirm_activate`
    (« Continue? [Y/N] ») ou directement le résultat, et enregistre un `y`
    séparé quand `SetupAndCaptureThread` le renvoie (même principe que
    `FakeConn` dans `test_scp_transfer.py`). `config_mode`/
    `exit_config_mode` comptent leurs appels, pour vérifier qu'aucune
    configuration n'est poussée quand ce n'est pas nécessaire.
    """

    def __init__(self, responses: dict[str, str] | None = None, confirm_activate: bool = False):
        self.responses = responses or {}
        self.confirm_activate = confirm_activate
        self.sent_commands: list[str] = []
        self.timing_commands: list[str] = []
        self.config_mode_calls = 0
        self.exit_config_mode_calls = 0
        self.disconnected = False

    def send_command(self, cmd: str, **_kwargs) -> str:
        self.sent_commands.append(cmd)
        for key, value in self.responses.items():
            if key in cmd:
                return value
        return ""

    def send_command_timing(self, cmd: str, read_timeout: int = 15) -> str:
        self.timing_commands.append(cmd)
        if cmd == "y":
            return ""
        return "Continue? [Y/N]" if self.confirm_activate else "Load File to flash succeeded."

    def config_mode(self) -> None:
        self.config_mode_calls += 1

    def exit_config_mode(self) -> None:
        self.exit_config_mode_calls += 1

    def disconnect(self) -> None:
        self.disconnected = True


class SequencedNtpConn(FakeConn):
    """Variante de FakeConn dont `display ntp-service status` répond
    « non synchronisé » au premier appel puis « synchronisé » au second —
    pour tester la revérification après configuration NTP
    (`SetupAndCaptureThread._ensure_ntp`)."""

    def __init__(self):
        super().__init__()
        self._ntp_status_calls = 0

    def send_command(self, cmd: str, **_kwargs) -> str:
        self.sent_commands.append(cmd)
        if "ntp-service status" in cmd:
            self._ntp_status_calls += 1
            if self._ntp_status_calls == 1:
                return "Clock status: unsynchronized\n"
            return "Clock status: synchronized\nClock stratum: 2\n"
        return ""


class FakeSshClient:
    """Remplace l'objet retourné par `open_scp_ssh_client` : seule sa
    méthode `close()` est utilisée par `_push_feature_file`."""

    def __init__(self):
        self.closed = False

    def close(self) -> None:
        self.closed = True


def patch_connect(monkeypatch, fake_conn) -> dict:
    """Remplace `connect_switch` pour renvoyer `fake_conn`, et compte les appels."""
    calls = {"count": 0}

    def _connect(_cfg):
        calls["count"] += 1
        return fake_conn

    monkeypatch.setattr(core, "connect_switch", _connect)
    return calls


def patch_scp_push(monkeypatch) -> list[tuple]:
    """Remplace `open_scp_ssh_client`/`scp_put` (globals du module) : enregistre
    les appels `put` sans jamais toucher au réseau — même principe que
    `fake_paramiko` dans `test_scp_transfer.py`, mais au niveau des fonctions
    plutôt que des classes paramiko sous-jacentes (déjà couvertes là-bas).

    `progress_callback` accepté (signature réelle de `scp_put` depuis la
    session 60) mais ignoré ici, non enregistré dans `put_calls` : sa
    transmission est déjà testée précisément dans `test_scp_transfer.py`
    (`test_scp_put_forwards_progress_callback_to_scpclient`), ce fichier-ci
    ne s'intéresse qu'à `local_path`/`remote_path`.
    """
    put_calls: list[tuple] = []

    def _fake_open(_cfg):
        return FakeSshClient()

    def _fake_put(_ssh_client, local_path, remote_path, progress_callback=None):
        put_calls.append((local_path, remote_path))

    monkeypatch.setattr(core, "open_scp_ssh_client", _fake_open)
    monkeypatch.setattr(core, "scp_put", _fake_put)
    return put_calls


VERSION_5130EI = "HPE Comware Software, Version 7.1.070, Release 6555P05\nHPE 5130-28-EI Switch\n"
VERSION_MSR4000 = "HPE Comware Software, Version 7.1.070, Release 8377\nHPE MSR4000 Router\n"
VERSION_3600V2 = "HPE Comware Software, Version 5.20.99, Release 2513\nHPE A3600-24 3600 V2 EI Switch\n"
VERSION_UNKNOWN = "HPE Comware Software, Version 9.9.99, Release 9999\nHPE MystereSwitch\n"
NTP_SYNCED = "Clock status: synchronized\nClock stratum: 3\n"


# --------------------------------------------------------------------- #
# __init__ / start_capture_blocking — garde-fous simples
# --------------------------------------------------------------------- #


def test_init_sets_initial_state():
    cfg = make_config()
    state = SharedState()

    thread = SetupAndCaptureThread(cfg, state)

    assert thread.cfg is cfg
    assert thread.state is state
    assert thread._prepared is False
    assert thread.daemon is True
    assert thread.name == "setup-capture"


def test_start_capture_blocking_without_prepare_raises():
    thread = make_thread()

    with pytest.raises(RuntimeError, match="prepare"):
        thread.start_capture_blocking()


def test_start_capture_blocking_after_prepare_marks_started_and_delegates(monkeypatch):
    """Chemin normal (déjà `prepare()`) : jamais exercé directement jusqu'ici
    (lignes 2356-2358, audit coverage.py de session 54) — seul le garde-fou
    ci-dessus, et `test_run_calls_prepare_then_start_capture_blocking_in_order`
    qui remplace entièrement `start_capture_blocking` par un mock, l'étaient.
    `_run_capture_blocking` lui-même reste hors périmètre (voir docstring de
    ce fichier) : mocké ici, jamais appelé réellement."""
    state = SharedState()
    thread = make_thread(state=state)
    thread._prepared = True
    calls = []
    monkeypatch.setattr(thread, "_run_capture_blocking", lambda: calls.append("called"))

    before = time_module.time()
    thread.start_capture_blocking()
    after = time_module.time()

    assert calls == ["called"]
    assert state.capture_started.is_set()
    assert before <= state.started_at <= after


# --------------------------------------------------------------------- #
# prepare() / _prepare_switch — modèle builtin (MSR4000)
# --------------------------------------------------------------------- #


def test_prepare_builtin_model_skips_feature_install(monkeypatch):
    fake = FakeConn(
        {
            "display version": VERSION_MSR4000,
            "display current-configuration": "scp server enable\n",
            "display ntp-service status": NTP_SYNCED,
            "packet-capture ?": "capture-ring-buffer  files  interface  ...\n",
        }
    )
    connect_calls = patch_connect(monkeypatch, fake)
    put_calls = patch_scp_push(monkeypatch)

    thread = make_thread()
    thread.prepare()

    assert thread._prepared is True
    assert thread.state.model == "MSR4000"
    assert thread.state.needs_feature_install is False
    assert thread.state.feature_already_installed is True
    assert connect_calls["count"] == 1  # une seule connexion : jamais _activate_feature
    assert put_calls == []  # jamais de push SCP pour un modèle déjà natif
    assert "packet-capture ?" in fake.sent_commands
    assert fake.disconnected is True


# --------------------------------------------------------------------- #
# prepare() / _prepare_switch — modèle installable, feature déjà active
# --------------------------------------------------------------------- #


def test_prepare_installable_feature_already_active_skips_push_and_activate(monkeypatch):
    fake = FakeConn(
        {
            "display version": VERSION_5130EI,
            "display install active": "packet-capture-5130-6555p05.bin actif depuis...",
            "display current-configuration": "scp server enable\n",
            "display ntp-service status": NTP_SYNCED,
        }
    )
    connect_calls = patch_connect(monkeypatch, fake)
    put_calls = patch_scp_push(monkeypatch)

    cfg = make_config(feature_bin_path="/tmp/packet-capture-5130-6555p05.bin")
    thread = make_thread(cfg)
    thread.prepare()

    assert thread._prepared is True
    assert thread.state.needs_feature_install is True  # profil "installable"
    assert thread.state.feature_already_installed is True
    assert put_calls == []  # _push_feature_file : retour anticipé
    assert connect_calls["count"] == 1  # _activate_feature : retour anticipé avant connect_switch
    assert not any(cmd.startswith("install activate feature") for cmd in fake.timing_commands)


# --------------------------------------------------------------------- #
# prepare() / _prepare_switch — modèle installable, feature à installer
# --------------------------------------------------------------------- #


def test_prepare_installable_feature_needs_push_and_activate(monkeypatch):
    fake = FakeConn(
        responses={
            "display version": VERSION_5130EI,
            "display install active": "aucune feature packet-capture listée ici",
            "display current-configuration": "scp server enable\n",
            "display ntp-service status": NTP_SYNCED,
        },
        confirm_activate=True,
    )
    connect_calls = patch_connect(monkeypatch, fake)
    put_calls = patch_scp_push(monkeypatch)

    cfg = make_config(feature_bin_path="/tmp/packet-capture-5130-6555p05.bin", slot=2)
    thread = make_thread(cfg)
    thread.prepare()

    assert thread._prepared is True
    assert thread.state.feature_already_installed is False
    # _push_feature_file (mode scp) : chemin distant = nom de fichier seul, jamais de préfixe "flash:".
    assert put_calls == [(Path(cfg.feature_bin_path), "packet-capture-5130-6555p05.bin")]
    # _activate_feature : une deuxième connexion dédiée, avec confirmation "y" envoyée.
    assert connect_calls["count"] == 2
    assert fake.timing_commands == [
        "install activate feature flash:/packet-capture-5130-6555p05.bin slot 2",
        "y",
    ]


def test_prepare_resolves_feature_bin_when_path_not_given(monkeypatch, tmp_path):
    """Si `feature_bin_path` n'est pas fourni, `prepare()` doit résoudre le
    `.bin` via `resolve_feature_bin(feature_bin_dir, model, software_version)`
    plutôt que de planter — vérifié avec un vrai dossier `tmp_path` (pas
    mocké), pour couvrir la jonction entre les deux fonctions."""
    versioned = tmp_path / "5130EI" / "6555P05"
    versioned.mkdir(parents=True)
    bin_file = versioned / "packet-capture-5130-6555p05.bin"
    bin_file.write_bytes(b"\x00")

    fake = FakeConn(
        {
            "display version": VERSION_5130EI,
            "display install active": "aucune feature listée",
            "display current-configuration": "scp server enable\n",
            "display ntp-service status": NTP_SYNCED,
        }
    )
    patch_connect(monkeypatch, fake)
    put_calls = patch_scp_push(monkeypatch)

    cfg = make_config(feature_bin_dir=str(tmp_path))
    thread = make_thread(cfg)
    thread.prepare()

    assert cfg.feature_bin_path == str(bin_file)
    assert put_calls == [(bin_file, "packet-capture-5130-6555p05.bin")]


def test_prepare_no_feature_bin_found_raises(monkeypatch, tmp_path):
    fake = FakeConn(
        {
            "display version": VERSION_5130EI,
            "display install active": "aucune feature listée",
            "display current-configuration": "scp server enable\n",
            "display ntp-service status": NTP_SYNCED,
        }
    )
    patch_connect(monkeypatch, fake)

    cfg = make_config(feature_bin_dir=str(tmp_path / "vide"))
    thread = make_thread(cfg)

    with pytest.raises(RuntimeError, match="Aucun .bin packet-capture trouvé"):
        thread.prepare()
    assert thread._prepared is False


# --------------------------------------------------------------------- #
# prepare() / _prepare_switch — modèles non supporté / non reconnu / forcé
# --------------------------------------------------------------------- #


def test_prepare_unsupported_model_raises_and_stops_early(monkeypatch):
    fake = FakeConn({"display version": VERSION_3600V2})
    patch_connect(monkeypatch, fake)

    thread = make_thread()

    with pytest.raises(RuntimeError, match="non supporté"):
        thread.prepare()
    assert thread._prepared is False
    # Doit s'arrêter avant toute autre commande (pas d'install active/ntp/transfert).
    assert fake.sent_commands == ["display version"]
    assert fake.disconnected is True  # le `finally` de _prepare_switch déconnecte quand même


def test_prepare_unknown_model_raises(monkeypatch):
    fake = FakeConn({"display version": VERSION_UNKNOWN})
    patch_connect(monkeypatch, fake)

    thread = make_thread()

    with pytest.raises(RuntimeError, match="non reconnu automatiquement"):
        thread.prepare()
    assert thread._prepared is False
    assert fake.sent_commands == ["display version"]


def test_prepare_forced_model_skips_autodetection(monkeypatch):
    """`cfg.model` forcé : la sortie `display version` n'a même pas besoin de
    matcher un alias connu (ici volontairement `VERSION_UNKNOWN`)."""
    fake = FakeConn(
        {
            "display version": VERSION_UNKNOWN,
            "display current-configuration": "scp server enable\n",
            "display ntp-service status": NTP_SYNCED,
            "packet-capture ?": "ok",
        }
    )
    patch_connect(monkeypatch, fake)

    cfg = make_config(model="MSR4000")
    thread = make_thread(cfg)
    thread.prepare()

    assert thread.state.model == "MSR4000"
    assert thread._prepared is True


# --------------------------------------------------------------------- #
# _ensure_transfer_service — isolée (scp / sshfs, actif / à activer)
# --------------------------------------------------------------------- #


def test_ensure_transfer_service_scp_already_enabled_skips_config():
    thread = make_thread(make_config(transfer_mode="scp"))
    conn = FakeConn({"display current-configuration": "scp server enable\n"})

    thread._ensure_transfer_service(conn)

    assert conn.config_mode_calls == 0
    assert conn.exit_config_mode_calls == 0
    assert "display current-configuration | include scp" in conn.sent_commands


def test_ensure_transfer_service_scp_not_enabled_configures_it():
    thread = make_thread(make_config(transfer_mode="scp"))
    conn = FakeConn({"display current-configuration": ""})

    thread._ensure_transfer_service(conn)

    assert conn.config_mode_calls == 1
    assert conn.exit_config_mode_calls == 1
    assert "scp server enable" in conn.sent_commands


def test_ensure_transfer_service_sshfs_mode_checks_sftp():
    thread = make_thread(make_config(transfer_mode="sshfs"))
    conn = FakeConn({"display current-configuration": "sftp server enable\n"})

    thread._ensure_transfer_service(conn)

    assert conn.config_mode_calls == 0
    assert "display current-configuration | include sftp" in conn.sent_commands


def test_ensure_transfer_service_sshfs_not_enabled_configures_sftp():
    thread = make_thread(make_config(transfer_mode="sshfs"))
    conn = FakeConn({"display current-configuration": ""})

    thread._ensure_transfer_service(conn)

    assert conn.config_mode_calls == 1
    assert "sftp server enable" in conn.sent_commands
    assert "scp server enable" not in conn.sent_commands


# --------------------------------------------------------------------- #
# _ensure_ntp — isolée (désactivé / déjà synchro / pas de serveur / configuré)
# --------------------------------------------------------------------- #


def test_ensure_ntp_disabled_sends_nothing():
    thread = make_thread(make_config(ensure_ntp=False))
    conn = FakeConn()

    thread._ensure_ntp(conn)

    assert conn.sent_commands == []
    assert thread.state.ntp_synced is None


def test_ensure_ntp_already_synced_does_not_configure():
    thread = make_thread(make_config(ensure_ntp=True))
    conn = FakeConn({"display ntp-service status": NTP_SYNCED})

    thread._ensure_ntp(conn)

    assert thread.state.ntp_synced is True
    assert thread.state.ntp_detail == "Clock status: synchronized"
    assert conn.config_mode_calls == 0


def test_ensure_ntp_unsynced_without_server_only_warns():
    thread = make_thread(make_config(ensure_ntp=True, ntp_server=None))
    conn = FakeConn({"display ntp-service status": "Clock status: unsynchronized\n"})

    thread._ensure_ntp(conn)

    assert thread.state.ntp_synced is False
    assert conn.config_mode_calls == 0


def test_ensure_ntp_unsynced_with_server_configures_and_confirms_after_recheck(monkeypatch):
    sleep_calls: list[float] = []
    monkeypatch.setattr(time_module, "sleep", lambda s: sleep_calls.append(s))
    thread = make_thread(make_config(ensure_ntp=True, ntp_server="10.0.0.9"))
    conn = SequencedNtpConn()

    thread._ensure_ntp(conn)

    assert conn.config_mode_calls == 1
    assert conn.exit_config_mode_calls == 1
    assert "ntp-service enable" in conn.sent_commands
    assert "ntp-service unicast-server 10.0.0.9" in conn.sent_commands
    assert sleep_calls == [3]  # délai best-effort avant revérification, jamais un vrai sleep ici
    assert thread.state.ntp_synced is True  # synchronisé après la revérification
    assert thread.state.ntp_detail == "Clock status: synchronized"


def test_ensure_ntp_unsynced_with_server_still_unsynced_after_recheck(monkeypatch):
    """Best-effort : toujours pas synchronisé après configuration -> avertissement, pas d'exception."""
    monkeypatch.setattr(time_module, "sleep", lambda _s: None)
    thread = make_thread(make_config(ensure_ntp=True, ntp_server="10.0.0.9"))
    conn = FakeConn({"display ntp-service status": "Clock status: unsynchronized\n"})

    thread._ensure_ntp(conn)  # ne doit pas lever

    assert thread.state.ntp_synced is False


# --------------------------------------------------------------------- #
# _activate_feature — isolée (déjà installée / confirmation / pas de confirmation)
# --------------------------------------------------------------------- #


def test_activate_feature_already_installed_never_connects(monkeypatch):
    thread = make_thread()
    thread.state.feature_already_installed = True
    connect_calls = patch_connect(monkeypatch, FakeConn())

    thread._activate_feature()

    assert connect_calls["count"] == 0


def test_activate_feature_sends_confirmation_when_prompted(monkeypatch):
    cfg = make_config(feature_bin_path="/tmp/packet-capture-5130.bin", slot=3)
    thread = make_thread(cfg)
    conn = FakeConn(confirm_activate=True)
    patch_connect(monkeypatch, conn)

    thread._activate_feature()

    assert conn.timing_commands == [
        "install activate feature flash:/packet-capture-5130.bin slot 3",
        "y",
    ]
    assert conn.disconnected is True


def test_activate_feature_no_extra_confirmation_when_not_prompted(monkeypatch):
    cfg = make_config(feature_bin_path="/tmp/packet-capture-5130.bin")
    thread = make_thread(cfg)
    conn = FakeConn(confirm_activate=False)
    patch_connect(monkeypatch, conn)

    thread._activate_feature()

    assert conn.timing_commands == ["install activate feature flash:/packet-capture-5130.bin slot 1"]
    assert "y" not in conn.timing_commands


# --------------------------------------------------------------------- #
# run() — délégation à prepare()/start_capture_blocking(), gestion d'erreur
# --------------------------------------------------------------------- #


def test_run_calls_prepare_then_start_capture_blocking_in_order(monkeypatch):
    thread = make_thread()
    order: list[str] = []
    monkeypatch.setattr(thread, "prepare", lambda: order.append("prepare"))
    monkeypatch.setattr(thread, "start_capture_blocking", lambda: order.append("start_capture_blocking"))

    thread.run()

    assert order == ["prepare", "start_capture_blocking"]
    assert thread.state.stop_event.is_set() is False


def test_run_exception_in_prepare_sets_stop_and_unblocks_capture_started(monkeypatch):
    thread = make_thread()

    def _boom():
        raise RuntimeError("échec simulé de prepare")

    monkeypatch.setattr(thread, "prepare", _boom)
    monkeypatch.setattr(thread, "start_capture_blocking", lambda: pytest.fail("ne doit jamais être appelé"))

    thread.run()  # ne doit jamais laisser l'exception remonter (voir docstring de run())

    assert thread.state.stop_event.is_set() is True
    assert thread.state.capture_started.is_set() is True  # débloque un éventuel thread 2 en attente


def test_run_exception_in_start_capture_blocking_sets_stop_too(monkeypatch):
    thread = make_thread()
    monkeypatch.setattr(thread, "prepare", lambda: None)

    def _boom():
        raise RuntimeError("échec simulé de start_capture_blocking")

    monkeypatch.setattr(thread, "start_capture_blocking", _boom)

    thread.run()

    assert thread.state.stop_event.is_set() is True
    assert thread.state.capture_started.is_set() is True
