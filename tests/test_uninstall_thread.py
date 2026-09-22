"""`UninstallThread` — séquence de désinstallation de la feature packet-capture.

Poursuite du point 4 de `CLAUDE.md` (audit de couverture de
`switch_capture_core.py`), premier bloc du triage établi en
[session 62](../docs/sessions/session-62.md) : `UninstallThread.run` était le
plus gros bloc jamais exercé du fichier — **50 des 291 lignes non couvertes**,
soit 17 % de la dette restante dans une seule méthode.

Pourquoi elle n'était pas couverte : `tests/test_uninstall_confirm.py`
**remplace délibérément `UninstallThread` par un faux thread**, pour vérifier
qu'aucune connexion SSH n'est tentée quand la confirmation d'IP échoue. C'est
le bon choix pour ce test-là, mais il laisse le contenu réel de `run()` jamais
exécuté. Les deux fichiers sont complémentaires : celui-ci teste ce que
l'autre remplace.

Enjeu particulier de ce bloc : c'est la seule séquence du projet qui envoie
des commandes **destructrices** à un switch de production (`install
deactivate`, `install commit`, `delete /unreserved`, suppression des `.pcap`
restants). Les tests ci-dessous portent donc autant sur *ce qui est envoyé*
que sur *ce qui ne l'est pas* — d'où un `FakeConn` qui journalise l'intégralité
des commandes reçues, et des assertions explicites d'absence sur les chemins
où rien ne doit être détruit.

Sans switch réel : `connect_switch` est monkeypatché, `FakeConn` local
(même convention que `test_setup_and_capture_thread.py` et
`test_prepare_switch_model_invariant.py` — chaque fichier garde le sien).
"""

from __future__ import annotations

import pytest

import switch_capture_core as core
from switch_capture_core import MODEL_PROFILES, Config, SharedState, UninstallThread

VERSION_5130 = "HPE Comware Software, Version 7.1.070\nHPE 5130-28-EI Switch\n"
VERSION_MSR = "HPE Comware Software, Version 7.1.070\nHPE MSR4000 Router\n"
VERSION_UNKNOWN = "HPE Comware Software, Version 9.9.99\nHPE MystereSwitch\n"

INSTALL_ACTIVE_WITH_BIN = (
    "Active packages on slot 1:\n  flash:/boot-a7510.bin\n  flash:/system-a7510.bin\n  flash:/packet-capture-1.0.bin\n"
)
INSTALL_ACTIVE_NO_PREFIX = "packet-capture-1.0.bin actif depuis le 01/09/2026\n"
INSTALL_ACTIVE_EMPTY = "Active packages on slot 1:\n  flash:/boot-a7510.bin\n"

DIR_TWO_PCAP = "  1  -rw-  1024  Sep 15 2026  capture_0001.pcap\n  2  -rw-  2048  Sep 15 2026  capture_0002.pcap\n"
DIR_NO_PCAP = "  1  -rw-  1024  Sep 15 2026  startup.cfg\n"


def make_config(**overrides) -> Config:
    """Config valide minimale (mêmes défauts que les autres fichiers de tests)."""
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "capture_interface": "GigabitEthernet1/0/1",
    }
    base.update(overrides)
    return Config(**base)


class FakeConn:
    """Session netmiko simulée qui **journalise toutes les commandes reçues**.

    `commands` conserve l'ordre exact des envois (`send_command` et
    `send_command_timing` confondus) : c'est ce qui permet d'affirmer non
    seulement que `install deactivate` a été envoyé, mais qu'il l'a été
    *avant* `install commit`, et qu'aucun `delete` n'a été émis sur les
    chemins où rien ne doit être supprimé.
    """

    def __init__(
        self,
        version_output: str = VERSION_5130,
        install_active: str = INSTALL_ACTIVE_EMPTY,
        dir_output: str = DIR_NO_PCAP,
        deactivate_output: str = "",
        delete_output: str = "",
    ):
        # Clés = fragment de commande à reconnaître, dans l'ordre de priorité.
        self.responses = {
            "display version": version_output,
            "display install active": install_active,
            "dir flash:": dir_output,
            "install deactivate": deactivate_output,
            "delete /unreserved": delete_output,
        }
        self.commands: list[str] = []
        self.disconnected = False
        self.raise_on: str | None = None

    def _answer(self, cmd: str) -> str:
        self.commands.append(cmd)
        if self.raise_on is not None and self.raise_on in cmd:
            raise OSError(f"liaison interrompue pendant : {cmd}")
        for key, value in self.responses.items():
            if key in cmd:
                return value
        return ""

    def send_command(self, cmd: str, **_kwargs) -> str:
        return self._answer(cmd)

    def send_command_timing(self, cmd: str, **_kwargs) -> str:
        return self._answer(cmd)

    def disconnect(self) -> None:
        self.disconnected = True


class DoneRecorder:
    """Enregistre les appels au callback `on_done(success, message)`."""

    def __init__(self):
        self.calls: list[tuple[bool, str]] = []

    def __call__(self, success: bool, message: str) -> None:
        self.calls.append((success, message))

    @property
    def success(self) -> bool:
        assert len(self.calls) == 1, f"on_done appelé {len(self.calls)} fois au lieu d'une"
        return self.calls[0][0]

    @property
    def message(self) -> str:
        assert len(self.calls) == 1, f"on_done appelé {len(self.calls)} fois au lieu d'une"
        return self.calls[0][1]


def run_uninstall_thread(monkeypatch, conn: FakeConn, cfg: Config | None = None, state=None, **kwargs):
    """Exécute `UninstallThread.run()` avec `connect_switch` neutralisé."""
    monkeypatch.setattr(core, "connect_switch", lambda _cfg: conn)
    done = DoneRecorder()
    thread = UninstallThread(cfg or make_config(), state or SharedState(), on_done=done, **kwargs)
    thread.run()
    return done


def sent(conn: FakeConn, fragment: str) -> list[str]:
    """Commandes journalisées contenant `fragment`."""
    return [cmd for cmd in conn.commands if fragment in cmd]


# --------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------- #


def test_thread_defaults():
    """Valeurs par défaut : le `.bin` reste en flash et aucun callback n'est
    exigé. Le défaut prudent compte ici — `remove_bin_from_flash=True` par
    défaut supprimerait un fichier sans que l'appelant l'ait demandé."""
    thread = UninstallThread(make_config(), SharedState())

    assert thread.remove_bin_from_flash is False
    assert thread.on_done is None
    assert thread.name == "uninstall-feature"
    assert thread.daemon is True


def test_finish_without_callback_does_not_raise(monkeypatch):
    """`on_done` est optionnel : `_finish` ne doit pas supposer sa présence
    (chemin réellement emprunté quand l'appelant est la CLI et non la GUI)."""
    conn = FakeConn(install_active=INSTALL_ACTIVE_WITH_BIN)
    monkeypatch.setattr(core, "connect_switch", lambda _cfg: conn)
    thread = UninstallThread(make_config(feature_bin_path="/opt/switch-capture/packet-capture-1.0.bin"), SharedState())

    thread.run()  # ne doit pas lever

    assert sent(conn, "install deactivate")


def test_run_works_inside_a_real_thread(monkeypatch):
    """`run()` est aussi exercé via `start()`/`join()` et pas seulement appelé
    directement : le corps de la méthode est le même, mais ce test vérifie que
    rien n'y dépend du thread appelant (le callback est invoqué depuis le
    thread de travail, la GUI le repasse ensuite par `GLib.idle_add`)."""
    conn = FakeConn(install_active=INSTALL_ACTIVE_WITH_BIN)
    monkeypatch.setattr(core, "connect_switch", lambda _cfg: conn)
    done = DoneRecorder()
    thread = UninstallThread(
        make_config(feature_bin_path="/opt/switch-capture/packet-capture-1.0.bin"), SharedState(), on_done=done
    )

    thread.start()
    thread.join(timeout=5)

    assert thread.is_alive() is False
    assert done.success is True


# --------------------------------------------------------------------- #
# Résolution du modèle
# --------------------------------------------------------------------- #


def test_config_model_takes_precedence_over_state_and_detection(monkeypatch):
    """`cfg.model` prime : le modèle forcé par l'utilisateur ne doit pas être
    écrasé par une détection automatique divergente."""
    conn = FakeConn(VERSION_MSR, install_active=INSTALL_ACTIVE_WITH_BIN)
    state = SharedState()
    state.model = "5140EI"

    done = run_uninstall_thread(monkeypatch, conn, make_config(model="5130EI"), state)

    # MSR4000 (détecté) aurait court-circuité la désinstallation ; 5130EI la poursuit.
    assert sent(conn, "install deactivate")
    assert done.success is True


def test_state_model_used_when_config_model_absent(monkeypatch):
    """`state.model` (modèle déjà détecté par la phase de capture) évite une
    seconde détection quand `cfg.model` n'est pas renseigné."""
    conn = FakeConn(VERSION_UNKNOWN, install_active=INSTALL_ACTIVE_WITH_BIN)
    state = SharedState()
    state.model = "5510"

    done = run_uninstall_thread(monkeypatch, conn, make_config(), state)

    assert done.success is True
    assert sent(conn, "install deactivate")


def test_detect_model_used_as_last_resort(monkeypatch):
    """Ni `cfg.model` ni `state.model` : la sortie de `display version` sert
    de dernier recours."""
    conn = FakeConn(VERSION_5130, install_active=INSTALL_ACTIVE_WITH_BIN)

    done = run_uninstall_thread(monkeypatch, conn, make_config(), SharedState())

    assert sent(conn, "display version")
    assert done.success is True


def test_undetermined_model_aborts_without_destructive_command(monkeypatch):
    """Modèle indéterminable : échec propre, et surtout **aucune commande
    destructrice émise**. C'est le garde-fou principal de cette méthode — sans
    modèle, on ne sait pas s'il y a une feature à retirer, donc on ne touche à
    rien."""
    conn = FakeConn(VERSION_UNKNOWN)

    done = run_uninstall_thread(monkeypatch, conn, make_config(), SharedState())

    assert done.success is False
    assert "Modèle non déterminé" in done.message
    assert sent(conn, "install deactivate") == []
    assert sent(conn, "install commit") == []
    assert sent(conn, "delete") == []
    assert conn.disconnected is True


# --------------------------------------------------------------------- #
# Modèles sans feature installable
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("model", [key for key, p in MODEL_PROFILES.items() if p["packet_capture"] != "installable"])
def test_non_installable_models_clean_captures_without_deactivating(monkeypatch, model):
    """MSR4000 (`builtin`) et 3600v2 (`unsupported`) : rien à désinstaller, mais
    les `.pcap` résiduels sont tout de même nettoyés. Aucun `install
    deactivate`/`commit` ne doit partir — ces commandes n'auraient aucun sens
    sur ces plateformes."""
    conn = FakeConn(install_active=INSTALL_ACTIVE_WITH_BIN, dir_output=DIR_TWO_PCAP)

    done = run_uninstall_thread(monkeypatch, conn, make_config(model=model), SharedState())

    assert done.success is True
    assert model in done.message
    assert sent(conn, "install deactivate") == []
    assert sent(conn, "install commit") == []
    assert sent(conn, "delete flash:/capture_0001.pcap")
    assert sent(conn, "delete flash:/capture_0002.pcap")


def test_unsupported_model_message_says_native(monkeypatch):
    """Constat documenté en session 62, **comportement inchangé** : le message
    annonce « packet-capture natif » y compris pour `3600v2`, dont le profil
    est `unsupported` et non `builtin`. La conclusion (« aucune feature à
    désinstaller ») reste exacte, seule la justification affichée est
    trompeuse. Ce test fige l'état actuel pour que la correction éventuelle
    soit un choix explicite et non un effet de bord."""
    conn = FakeConn()

    done = run_uninstall_thread(monkeypatch, conn, make_config(model="3600v2"), SharedState())

    assert done.success is True
    assert "packet-capture natif" in done.message
    assert MODEL_PROFILES["3600v2"]["packet_capture"] == "unsupported"


# --------------------------------------------------------------------- #
# Découverte du nom de fichier à désactiver
# --------------------------------------------------------------------- #


def test_configured_filename_skips_discovery(monkeypatch):
    """`feature_filename` connu : pas d'interrogation de `display install
    active`, et pas de nettoyage préalable des captures (celui-ci n'a lieu que
    sur le chemin de découverte)."""
    cfg = make_config(model="5130EI", feature_bin_path="/opt/switch-capture/packet-capture-2.0.bin")
    conn = FakeConn()

    done = run_uninstall_thread(monkeypatch, conn, cfg, SharedState())

    assert sent(conn, "display install active") == []
    assert sent(conn, "install deactivate feature flash:/packet-capture-2.0.bin slot 1")
    assert done.success is True


def test_filename_discovered_from_install_active(monkeypatch):
    """Sans `feature_filename`, le nom est extrait de `display install active`
    et réutilisé tel quel dans la commande de désactivation."""
    conn = FakeConn(install_active=INSTALL_ACTIVE_WITH_BIN, dir_output=DIR_TWO_PCAP)

    done = run_uninstall_thread(monkeypatch, conn, make_config(model="5130EI"), SharedState())

    assert sent(conn, "display install active")
    assert sent(conn, "install deactivate feature flash:/packet-capture-1.0.bin slot 1")
    assert "packet-capture-1.0.bin" in done.message
    assert done.success is True


def test_no_active_feature_stops_before_deactivating(monkeypatch):
    """Rien d'actif : succès (il n'y a effectivement plus rien à retirer), mais
    aucune tentative de désactivation d'un fichier au nom deviné."""
    conn = FakeConn(install_active=INSTALL_ACTIVE_EMPTY)

    done = run_uninstall_thread(monkeypatch, conn, make_config(model="5130EI"), SharedState())

    assert done.success is True
    assert "Aucune feature packet-capture active" in done.message
    assert sent(conn, "install deactivate") == []
    assert sent(conn, "install commit") == []


def test_storage_prefix_is_not_duplicated_in_commands(monkeypatch):
    """**Régression (bug trouvé et corrigé en session 62).** Comware liste les
    paquets actifs préfixés par leur média (`flash:/packet-capture-....bin`,
    format de la command reference HPE Comware 7). L'ancienne expression
    `(\\S*packet-capture\\S*\\.bin)` capturait ce préfixe dans le nom de
    fichier, et la commande devenait
    `install deactivate feature flash:/flash:/packet-capture-1.0.bin` —
    rejetée par le switch, donc désinstallation impossible par ce chemin.

    Jamais vu jusqu'ici parce que ce chemin n'est emprunté que sans
    `feature_bin_path` configuré (typiquement : bouton « Désinstaller » de la
    GUI après un redémarrage de l'application), et que `run()` n'était couvert
    par aucun test.
    """
    conn = FakeConn(install_active=INSTALL_ACTIVE_WITH_BIN)

    run_uninstall_thread(monkeypatch, conn, make_config(model="5130EI"), SharedState(), remove_bin_from_flash=True)

    assert [cmd for cmd in conn.commands if "flash:/flash:" in cmd] == []
    assert sent(conn, "install deactivate feature flash:/packet-capture-1.0.bin slot 1")
    assert sent(conn, "delete /unreserved flash:/packet-capture-1.0.bin")


def test_filename_without_storage_prefix_still_matched(monkeypatch):
    """Non-régression du correctif : une sortie sans préfixe média reste
    reconnue à l'identique (c'est le format qu'utilisaient les jeux d'essai du
    dépôt avant cette session)."""
    conn = FakeConn(install_active=INSTALL_ACTIVE_NO_PREFIX)

    done = run_uninstall_thread(monkeypatch, conn, make_config(model="5130EI"), SharedState())

    assert sent(conn, "install deactivate feature flash:/packet-capture-1.0.bin slot 1")
    assert done.success is True


def test_boot_and_system_packages_are_never_targeted(monkeypatch):
    """Le switch liste aussi `boot-*.bin` et `system-*.bin` : seule l'image
    `packet-capture` doit être désactivée. Une capture trop large ici
    désactiverait l'image système du switch."""
    conn = FakeConn(install_active=INSTALL_ACTIVE_WITH_BIN)

    run_uninstall_thread(monkeypatch, conn, make_config(model="5130EI"), SharedState(), remove_bin_from_flash=True)

    assert sent(conn, "boot-a7510.bin") == []
    assert sent(conn, "system-a7510.bin") == []


def test_slot_is_taken_from_config(monkeypatch):
    """Le slot de `Config` est repris dans la commande — une désactivation sur
    le mauvais slot d'un châssis multi-cartes serait sans effet, ou pire."""
    cfg = make_config(model="5130EI", feature_bin_path="/opt/switch-capture/packet-capture-1.0.bin", slot=3)
    conn = FakeConn()

    run_uninstall_thread(monkeypatch, conn, cfg, SharedState())

    assert sent(conn, "install deactivate feature flash:/packet-capture-1.0.bin slot 3")


# --------------------------------------------------------------------- #
# Séquence de désinstallation
# --------------------------------------------------------------------- #


def test_deactivate_precedes_commit(monkeypatch):
    """L'ordre compte : `install commit` rend la désactivation persistante, le
    lancer avant ne validerait rien."""
    conn = FakeConn()

    run_uninstall_thread(
        monkeypatch,
        conn,
        make_config(model="5130EI", feature_bin_path="/opt/switch-capture/packet-capture-1.0.bin"),
        SharedState(),
    )

    ordre = [cmd for cmd in conn.commands if cmd.startswith("install ")]
    assert ordre == ["install deactivate feature flash:/packet-capture-1.0.bin slot 1", "install commit"]


@pytest.mark.parametrize("prompt", ["Continue? [Y/N]:", "Are you sure? [Y/N]:", "Continue?"])
def test_confirmation_prompt_is_answered(monkeypatch, prompt):
    """Comware demande confirmation selon la version : les deux motifs
    reconnus (`Continue?` et `[Y/N]`) déclenchent l'envoi de `y`."""
    conn = FakeConn(deactivate_output=prompt)

    run_uninstall_thread(
        monkeypatch,
        conn,
        make_config(model="5130EI", feature_bin_path="/opt/switch-capture/packet-capture-1.0.bin"),
        SharedState(),
    )

    assert conn.commands.count("y") == 1


def test_no_stray_confirmation_when_not_prompted(monkeypatch):
    """Sans invite, aucun `y` ne doit partir : un `y` isolé serait interprété
    comme une commande par le CLI Comware."""
    conn = FakeConn(deactivate_output="Deactivation completed.")

    run_uninstall_thread(
        monkeypatch,
        conn,
        make_config(model="5130EI", feature_bin_path="/opt/switch-capture/packet-capture-1.0.bin"),
        SharedState(),
    )

    assert conn.commands.count("y") == 0


# --------------------------------------------------------------------- #
# Suppression optionnelle du .bin
# --------------------------------------------------------------------- #


def test_bin_kept_in_flash_by_default(monkeypatch):
    """Défaut : le `.bin` reste en flash (désactivé mais réinstallable sans
    nouveau transfert)."""
    conn = FakeConn()

    run_uninstall_thread(
        monkeypatch,
        conn,
        make_config(model="5130EI", feature_bin_path="/opt/switch-capture/packet-capture-1.0.bin"),
        SharedState(),
    )

    assert sent(conn, "delete /unreserved") == []


def test_bin_deleted_after_commit_when_requested(monkeypatch):
    """`remove_bin_from_flash=True` : suppression émise **après** le commit,
    jamais avant — supprimer le fichier d'une feature encore active
    échouerait."""
    conn = FakeConn()

    run_uninstall_thread(
        monkeypatch,
        conn,
        make_config(model="5130EI", feature_bin_path="/opt/switch-capture/packet-capture-1.0.bin"),
        SharedState(),
        remove_bin_from_flash=True,
    )

    assert conn.commands.index("install commit") < conn.commands.index(
        "delete /unreserved flash:/packet-capture-1.0.bin"
    )


def test_bin_deletion_confirmation_is_answered(monkeypatch):
    """La suppression a sa propre invite de confirmation, distincte de celle de
    la désactivation."""
    conn = FakeConn(delete_output="Delete flash:/packet-capture-1.0.bin? [Y/N]:")

    run_uninstall_thread(
        monkeypatch,
        conn,
        make_config(model="5130EI", feature_bin_path="/opt/switch-capture/packet-capture-1.0.bin"),
        SharedState(),
        remove_bin_from_flash=True,
    )

    assert conn.commands.count("y") == 1


def test_discovered_filename_is_the_one_deleted(monkeypatch):
    """Nom découvert *et* suppression demandée : c'est bien le fichier trouvé
    dans `display install active` qui est supprimé, pas une valeur par
    défaut — un mauvais nom effacerait un autre fichier de la flash."""
    conn = FakeConn(install_active=INSTALL_ACTIVE_WITH_BIN)

    run_uninstall_thread(monkeypatch, conn, make_config(model="5130EI"), SharedState(), remove_bin_from_flash=True)

    assert sent(conn, "delete /unreserved flash:/packet-capture-1.0.bin")


# --------------------------------------------------------------------- #
# Robustesse et déconnexion
# --------------------------------------------------------------------- #


def test_connection_failure_reported_without_raising(monkeypatch):
    """Échec de connexion : rapporté via `on_done(False, ...)` plutôt que
    propagé — une exception qui remonte d'un thread daemon serait perdue."""

    def boom(_cfg):
        raise OSError("connexion refusée")

    monkeypatch.setattr(core, "connect_switch", boom)
    done = DoneRecorder()

    UninstallThread(make_config(model="5130EI"), SharedState(), on_done=done).run()

    assert done.success is False
    assert "connexion refusée" in done.message


def test_disconnect_happens_on_success(monkeypatch):
    """Chemin nominal : la session est refermée."""
    conn = FakeConn()

    run_uninstall_thread(
        monkeypatch,
        conn,
        make_config(model="5130EI", feature_bin_path="/opt/switch-capture/packet-capture-1.0.bin"),
        SharedState(),
    )

    assert conn.disconnected is True


def test_disconnect_happens_even_when_sequence_fails(monkeypatch):
    """Coupure en plein `install deactivate` : le `finally` referme la session
    malgré tout, et l'échec est remonté. Une session laissée ouverte
    consommerait une des rares VTY du switch."""
    conn = FakeConn()
    conn.raise_on = "install deactivate"

    done = run_uninstall_thread(
        monkeypatch,
        conn,
        make_config(model="5130EI", feature_bin_path="/opt/switch-capture/packet-capture-1.0.bin"),
        SharedState(),
    )

    assert conn.disconnected is True
    assert done.success is False
    assert "liaison interrompue" in done.message
