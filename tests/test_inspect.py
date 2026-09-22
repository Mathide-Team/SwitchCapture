"""Tests du mode dry run (« Inspecter » — modèle/version/features sans rien modifier).

Couvre la piste d'amélioration « Mode "dry run" : bouton qui se contente de
détecter modèle/version/features actives sans rien modifier », listée dans
CLAUDE.md.

Comme pour `test_uninstall_confirm.py`, tout est testé sans switch réel :
`connect_switch` est remplacée par une fausse connexion (`FakeConn`) qui
répond à `send_command()` avec des sorties « display » canned et ne modifie
jamais rien (pas de config_mode ici — `inspect_switch` n'en appelle de
toute façon aucun, c'est justement ce que ce module vérifie indirectement :
aucune méthode d'écriture n'existe sur `FakeConn`, donc tout appel à une
commande de configuration ferait planter le test avec une AttributeError).

Le bouton GTK "Inspecter (dry run)" (`_on_inspect_session`), qui appelle la
même `inspect_switch`/`format_inspect_report`, a été validé par
introspection de widgets sous Xvfb au moment de ce changement (voir
features.md) mais volontairement pas ajouté ici — `tests/` reste
indépendant de GTK4/PyGObject (conftest.py, CLAUDE.md).
"""

from __future__ import annotations

import switch_capture_cli as cli_mod
from switch_capture_core import (
    InspectConfig,
    format_inspect_report,
    inspect_switch,
    is_ntp_synchronized,
)

VERSION_5130 = (
    "HPE Comware Software, Version 7.1.070, Release 6555P05\n"
    "HPE 5130-28-EI Switch\n"
    "Copyright (c) 2010-2026 Hewlett Packard Enterprise Development LP\n"
)

VERSION_3600V2 = "HPE Comware Software, Version 5.20.99, Release 2513\nHPE A3600-24 3600 V2 EI Switch\n"

VERSION_UNKNOWN = "HPE Comware Software, Version 9.9.99, Release 9999\nHPE MystereSwitch\n"

NTP_SYNCED = "Clock status: synchronized\nClock stratum: 3\n"
NTP_UNSYNCED = "Clock status: unsynchronized\n"


class FakeConn:
    """Simule une session netmiko en lecture seule.

    `send_command(cmd)` fait correspondre `cmd` à la première clé de
    `responses` qu'elle contient (mêmes sous-chaînes que les commandes
    envoyées par `inspect_switch`, ex. "display version"). Aucune méthode
    d'écriture (config_mode, exit_config_mode...) n'est fournie : si
    `inspect_switch` tentait d'en appeler une, le test échouerait avec une
    AttributeError — preuve indirecte que le mode dry run ne configure
    jamais rien.
    """

    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.sent_commands: list[str] = []
        self.disconnected = False

    def send_command(self, cmd: str, **_kwargs) -> str:
        self.sent_commands.append(cmd)
        for key, value in self.responses.items():
            if key in cmd:
                return value
        return ""

    def disconnect(self) -> None:
        self.disconnected = True


def make_inspect_config(**overrides) -> InspectConfig:
    base = {"switch_ip": "10.0.0.1", "ssh_user": "mathilde", "ssh_password": "secret"}
    base.update(overrides)
    return InspectConfig(**base)


def patch_connect(monkeypatch, fake_conn: FakeConn):
    """Remplace switch_capture_core.connect_switch pour qu'il retourne fake_conn."""
    import switch_capture_core as core_mod

    monkeypatch.setattr(core_mod, "connect_switch", lambda _cfg: fake_conn)


# --------------------------------------------------------------------- #
# is_ntp_synchronized (pure)
# --------------------------------------------------------------------- #


def test_is_ntp_synchronized_true():
    assert is_ntp_synchronized(NTP_SYNCED) is True


def test_is_ntp_synchronized_false():
    assert is_ntp_synchronized(NTP_UNSYNCED) is False


def test_is_ntp_synchronized_no_match():
    assert is_ntp_synchronized("sortie inattendue, aucune ligne clock status") is False


# --------------------------------------------------------------------- #
# InspectConfig — validation
# --------------------------------------------------------------------- #


def test_inspect_config_missing_switch_ip_raises():
    try:
        InspectConfig(switch_ip="", ssh_user="mathilde", ssh_password="x")
        raise AssertionError("devrait lever ValueError")
    except ValueError as exc:
        assert "switch_ip" in str(exc)


def test_inspect_config_missing_password_raises(monkeypatch):
    monkeypatch.delenv("SWITCH_SSH_PASSWORD", raising=False)
    try:
        InspectConfig(switch_ip="10.0.0.1", ssh_user="mathilde", ssh_password="")
        raise AssertionError("devrait lever ValueError")
    except ValueError as exc:
        assert "mot de passe" in str(exc).lower() or "password" in str(exc).lower()


def test_inspect_config_password_from_env(monkeypatch):
    monkeypatch.setenv("SWITCH_SSH_PASSWORD", "depuis-env")
    cfg = InspectConfig(switch_ip="10.0.0.1", ssh_user="mathilde")
    assert cfg.ssh_password == "depuis-env"


def test_inspect_config_invalid_model_raises():
    try:
        InspectConfig(switch_ip="10.0.0.1", ssh_user="mathilde", ssh_password="x", model="inconnu-9999")
        raise AssertionError("devrait lever ValueError")
    except ValueError as exc:
        assert "modèle" in str(exc).lower()


def test_inspect_config_invalid_transfer_mode_raises():
    try:
        InspectConfig(switch_ip="10.0.0.1", ssh_user="mathilde", ssh_password="x", transfer_mode="ftp")
        raise AssertionError("devrait lever ValueError")
    except ValueError as exc:
        assert "transfer_mode" in str(exc)


def test_inspect_config_default_transfer_mode_is_scp():
    cfg = make_inspect_config()
    assert cfg.transfer_mode == "scp"


# --------------------------------------------------------------------- #
# inspect_switch — modèle installable, feature pas encore active
# --------------------------------------------------------------------- #


def test_inspect_switch_installable_not_active(monkeypatch):
    fake = FakeConn(
        {
            "display version": VERSION_5130,
            "display install active": "aucune feature listée ici",
            "display current-configuration": "scp server enable\n",
            "display ntp-service status": NTP_SYNCED,
        }
    )
    patch_connect(monkeypatch, fake)

    cfg = make_inspect_config(feature_bin_path="/tmp/packet-capture-5130-6555p05.bin")
    report = inspect_switch(cfg)

    assert report["model"] == "5130EI"
    assert report["model_known"] is True
    assert report["software_version"] == "6555P05"
    assert report["packet_capture_support"] == "installable"
    assert report["feature_bin_checked"] == "packet-capture-5130-6555p05.bin"
    assert report["feature_already_active"] is False
    assert report["transfer_service_enabled"] is True
    assert report["ntp_synced"] is True
    assert fake.disconnected is True


def test_inspect_switch_installable_already_active(monkeypatch):
    fake = FakeConn(
        {
            "display version": VERSION_5130,
            "display install active": "packet-capture-5130-6555p05.bin actif depuis...",
            "display current-configuration": "",
            "display ntp-service status": NTP_UNSYNCED,
        }
    )
    patch_connect(monkeypatch, fake)

    cfg = make_inspect_config(feature_bin_path="/tmp/packet-capture-5130-6555p05.bin")
    report = inspect_switch(cfg)

    assert report["feature_already_active"] is True
    assert report["transfer_service_enabled"] is False
    assert report["ntp_synced"] is False


def test_inspect_switch_unsupported_model(monkeypatch):
    fake = FakeConn(
        {
            "display version": VERSION_3600V2,
            "display current-configuration": "sftp server enable\n",
            "display ntp-service status": NTP_SYNCED,
        }
    )
    patch_connect(monkeypatch, fake)

    cfg = make_inspect_config(transfer_mode="sshfs")
    report = inspect_switch(cfg)

    assert report["model"] == "3600v2"
    assert report["packet_capture_support"] == "unsupported"
    assert report["feature_already_active"] is None
    # Aucune commande d'install/summary ne doit avoir été envoyée pour un modèle non supporté.
    assert not any("install active" in c or "packet-capture summary" in c for c in fake.sent_commands)


def test_inspect_switch_unknown_model(monkeypatch):
    fake = FakeConn(
        {
            "display version": VERSION_UNKNOWN,
            "display current-configuration": "",
            "display ntp-service status": NTP_UNSYNCED,
        }
    )
    patch_connect(monkeypatch, fake)

    report = inspect_switch(make_inspect_config())

    assert report["model"] is None
    assert report["model_known"] is False
    assert report["packet_capture_support"] is None
    assert report["feature_already_active"] is None


def test_inspect_switch_builtin_model(monkeypatch):
    """Modèle avec packet-capture "builtin" (MSR4000, seul modèle de
    MODEL_PROFILES dans ce cas — voir sa docstring) : branche jamais
    exercée jusqu'ici (lignes 1924-1929, audit coverage.py de session 54).
    `packet-capture ?` est interrogée à la place de `display install
    active`, et une réponse mentionnant "local" bascule `packet_capture_cmd`."""
    fake = FakeConn(
        {
            "display version": "HPE Comware Software, Version 7.1.070\nHPE MSR4000 Router\n",
            "packet-capture ?": "  local    Capture packets on local interface\n  remote   Capture packets remotely\n",
            "display current-configuration": "scp server enable\n",
            "display ntp-service status": NTP_SYNCED,
        }
    )
    patch_connect(monkeypatch, fake)

    cfg = make_inspect_config()
    report = inspect_switch(cfg)

    assert report["model"] == "MSR4000"
    assert report["packet_capture_support"] == "builtin"
    assert report["feature_already_active"] is True
    assert report["packet_capture_summary"] == (
        "local    Capture packets on local interface\n  remote   Capture packets remotely"
    )
    assert cfg.packet_capture_cmd == "packet-capture local"
    # Aucune commande d'installation envoyée pour un modèle "builtin".
    assert not any("install active" in c for c in fake.sent_commands)


# --------------------------------------------------------------------- #
# inspect_switch — display packet-capture status (disponibilité rpcap)
# --------------------------------------------------------------------- #


def test_inspect_switch_rpcap_status_present(monkeypatch):
    fake = FakeConn(
        {
            "display version": VERSION_5130,
            "display install active": "",
            "display current-configuration": "",
            "display ntp-service status": NTP_SYNCED,
            "display packet-capture status": "packet-capture remote : enabled\ninterface GE1/0/1 : idle\n",
        }
    )
    patch_connect(monkeypatch, fake)

    report = inspect_switch(make_inspect_config())

    assert report["rpcap_status_raw"] == ("packet-capture remote : enabled\ninterface GE1/0/1 : idle")
    assert "display packet-capture status" in fake.sent_commands


def test_inspect_switch_rpcap_status_absent_is_none(monkeypatch):
    """Commande non reconnue par ce switch (ou modèle qui ne la supporte pas) : `None`, pas une chaîne vide."""
    fake = FakeConn(
        {
            "display version": VERSION_3600V2,
            "display current-configuration": "",
            "display ntp-service status": NTP_UNSYNCED,
            # Pas de clé "display packet-capture status" -> FakeConn renvoie "".
        }
    )
    patch_connect(monkeypatch, fake)

    report = inspect_switch(make_inspect_config(transfer_mode="sshfs"))

    assert report["rpcap_status_raw"] is None


def test_inspect_switch_rpcap_status_never_configures_anything(monkeypatch):
    """Garde-fou : la vérification rpcap reste un `display`, jamais de config_mode."""
    fake = FakeConn(
        {
            "display version": VERSION_5130,
            "display install active": "",
            "display current-configuration": "",
            "display ntp-service status": NTP_UNSYNCED,
            "display packet-capture status": "packet-capture remote : disabled\n",
        }
    )
    patch_connect(monkeypatch, fake)

    inspect_switch(make_inspect_config())

    assert all(cmd.startswith("display") for cmd in fake.sent_commands)


def test_inspect_switch_never_sends_config_command(monkeypatch):
    """Garde-fou explicite : aucune commande de configuration n'est jamais émise."""
    fake = FakeConn(
        {
            "display version": VERSION_5130,
            "display install active": "",
            "display current-configuration": "",
            "display ntp-service status": NTP_UNSYNCED,
        }
    )
    patch_connect(monkeypatch, fake)

    inspect_switch(make_inspect_config())

    assert all(cmd.startswith("display") for cmd in fake.sent_commands)


def test_inspect_switch_forced_model_skips_autodetection(monkeypatch):
    fake = FakeConn(
        {
            "display version": VERSION_UNKNOWN,  # ne matcherait aucun modèle seul
            "display install active": "",
            "display current-configuration": "",
            "display ntp-service status": NTP_SYNCED,
        }
    )
    patch_connect(monkeypatch, fake)

    report = inspect_switch(make_inspect_config(model="5140EI"))

    assert report["model"] == "5140EI"
    assert report["model_known"] is True
    assert report["packet_capture_support"] == "installable"


# --------------------------------------------------------------------- #
# format_inspect_report (pure)
# --------------------------------------------------------------------- #


def test_format_inspect_report_contains_key_fields():
    report = {
        "model": "5130EI",
        "model_known": True,
        "model_notes": "note de test",
        "software_version": "6555P05",
        "packet_capture_support": "installable",
        "feature_bin_checked": "packet-capture-5130-6555p05.bin",
        "feature_already_active": False,
        "transfer_service_enabled": True,
        "ntp_synced": True,
        "ntp_detail": "Clock status: synchronized",
    }
    text = format_inspect_report("10.0.0.1", "scp", report)

    assert "10.0.0.1" in text
    assert "5130EI" in text
    assert "6555P05" in text
    assert "packet-capture-5130-6555p05.bin" in text
    assert "scp server enable : oui" in text
    assert "NTP synchronisé : oui" in text
    assert "Aucune modification" in text


def test_format_inspect_report_unknown_model():
    report = {
        "model": None,
        "model_known": False,
        "packet_capture_support": None,
        "software_version": None,
        "transfer_service_enabled": False,
        "ntp_synced": False,
        "ntp_detail": "",
    }
    text = format_inspect_report("10.0.0.9", "scp", report)

    assert "non détecté automatiquement" in text
    assert "indéterminé" in text


def test_format_inspect_report_model_detected_but_unknown_to_profiles():
    """`model` renseigné (ex. appelant tiers, ou dict construit à la main —
    fonction pure indépendante de `inspect_switch`) mais `model_known`
    False : branche distincte du cas "aucun modèle détecté" ci-dessus,
    jamais exercée jusqu'ici (ligne 1989, audit coverage.py de session 54).
    `detect_model`/`InspectConfig` garantissent que ce cas ne se produit
    jamais en pratique via `inspect_switch` lui-même (un modèle détecté est
    toujours une clé de MODEL_PROFILES) — seulement via un dict construit
    à la main, comme le reste de cette section de tests."""
    report = {
        "model": "SwitchDuFutur-9999",
        "model_known": False,
        "packet_capture_support": None,
        "software_version": None,
        "transfer_service_enabled": False,
        "ntp_synced": False,
        "ntp_detail": "",
    }
    text = format_inspect_report("10.0.0.9", "scp", report)

    assert "SwitchDuFutur-9999 (non reconnu dans MODEL_PROFILES)" in text


def test_format_inspect_report_builtin_support():
    report = {
        "model": "MSR4000",
        "model_known": True,
        "model_notes": "Feature packet-capture préinstallée'.",
        "software_version": "6555P05",
        "packet_capture_support": "builtin",
        "packet_capture_summary": "local    Capture packets on local interface",
        "transfer_service_enabled": True,
        "ntp_synced": True,
        "ntp_detail": "Clock status: synchronized",
    }
    text = format_inspect_report("10.0.0.1", "scp", report)

    assert "packet-capture : natif" in text
    assert "local    Capture packets on local interface" in text


def test_format_inspect_report_unsupported_support():
    report = {
        "model": "3600v2",
        "model_known": True,
        "model_notes": "Comware 5 : pas de mécanisme 'install activate feature'.",
        "software_version": "2513",
        "packet_capture_support": "unsupported",
        "transfer_service_enabled": False,
        "ntp_synced": False,
        "ntp_detail": "",
    }
    text = format_inspect_report("10.0.0.1", "sshfs", report)

    assert "packet-capture : non supporté" in text
    assert "pas de mécanisme 'install activate feature'" in text


def test_format_inspect_report_rpcap_status_present():
    report = {
        "model": "5130EI",
        "model_known": True,
        "model_notes": "",
        "software_version": "6555P05",
        "packet_capture_support": "installable",
        "feature_bin_checked": None,
        "feature_already_active": None,
        "transfer_service_enabled": True,
        "ntp_synced": True,
        "ntp_detail": "Clock status: synchronized",
        "rpcap_status_raw": "packet-capture remote : enabled\ninterface GE1/0/1 : idle",
    }
    text = format_inspect_report("10.0.0.1", "scp", report)

    assert "Disponibilité rpcap" in text
    assert "  packet-capture remote : enabled" in text
    assert "  interface GE1/0/1 : idle" in text


def test_format_inspect_report_rpcap_status_absent():
    report = {
        "model": None,
        "model_known": False,
        "packet_capture_support": None,
        "software_version": None,
        "transfer_service_enabled": False,
        "ntp_synced": False,
        "ntp_detail": "",
        "rpcap_status_raw": None,
    }
    text = format_inspect_report("10.0.0.9", "scp", report)

    assert "à vérifier manuellement avant d'utiliser --output-mode rpcap" in text


def test_format_inspect_report_rpcap_status_key_missing_defaults_gracefully():
    """`report.get(...)` : une clé absente (ancien appelant, dict incomplet) ne doit pas planter."""
    report = {
        "model": None,
        "model_known": False,
        "packet_capture_support": None,
        "software_version": None,
        "transfer_service_enabled": False,
        "ntp_synced": False,
        "ntp_detail": "",
    }
    text = format_inspect_report("10.0.0.9", "scp", report)

    assert "Disponibilité rpcap" in text


# --------------------------------------------------------------------- #
# CLI — run_inspect (bout en bout, FakeConn)
# --------------------------------------------------------------------- #


def test_run_inspect_success(monkeypatch, capsys):
    fake = FakeConn(
        {
            "display version": VERSION_5130,
            "display install active": "",
            "display current-configuration": "",
            "display ntp-service status": NTP_SYNCED,
        }
    )
    patch_connect(monkeypatch, fake)

    args = cli_mod.build_arg_parser().parse_args(
        ["inspect", "--switch-ip", "10.0.0.1", "--ssh-user", "mathilde", "--ssh-password", "x"]
    )
    rc = cli_mod.run_inspect(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "10.0.0.1" in out
    assert "5130EI" in out


def test_run_inspect_invalid_config_returns_2():
    args = cli_mod.build_arg_parser().parse_args(
        ["inspect", "--switch-ip", "10.0.0.1", "--ssh-user", "mathilde", "--model", "5130EI", "--transfer-mode", "scp"]
    )
    args.ssh_password = None  # pas de mot de passe fourni

    import os

    old = os.environ.pop("SWITCH_SSH_PASSWORD", None)
    try:
        rc = cli_mod.run_inspect(args)
        assert rc == 2
    finally:
        if old is not None:
            os.environ["SWITCH_SSH_PASSWORD"] = old


def test_run_inspect_connection_failure_returns_1(monkeypatch):
    import switch_capture_core as core_mod

    def _boom(_cfg):
        raise RuntimeError("connexion refusée (simulée)")

    monkeypatch.setattr(core_mod, "connect_switch", _boom)

    args = cli_mod.build_arg_parser().parse_args(
        ["inspect", "--switch-ip", "10.0.0.1", "--ssh-user", "mathilde", "--ssh-password", "x"]
    )
    rc = cli_mod.run_inspect(args)

    assert rc == 1
