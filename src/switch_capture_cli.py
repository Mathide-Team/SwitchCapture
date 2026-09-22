#!/usr/bin/env python3
"""CLI pour switch_capture_core (aucune dépendance GTK).

Trois sous-commandes :
    switch-capture capture    ...  lance la capture (bloquant, Ctrl+C pour arrêter)
    switch-capture uninstall  ...  désinstalle la feature packet-capture sur le switch
    switch-capture import-bin ...  copie un dépôt local de .bin vers --feature-bin-dir

Tous les paramètres sont disponibles en argument CLI et/ou dans un YAML
(--config). Les arguments CLI, quand fournis, prennent le pas sur le YAML.

Voir USAGE.md pour la référence complète des options et des exemples.
"""

from __future__ import annotations

import argparse
import dataclasses
import gettext
import os
import shutil
import signal
import sys
from pathlib import Path

from loguru import logger

# i18n (features.md, point 13) : uniquement le texte destiné à
# l'utilisateur final (aide `argparse`/`--help`) — les messages de
# `logger` restent en français, comme le reste de la journalisation de ce
# dépôt (voir CLAUDE.md). `locale/` est cherché à côté de ce fichier
# (mode dev, `src/`) ou dans `/usr/share/locale` (installé), sur le
# modèle des autres ressources partagées de ce dépôt. Langue choisie via
# les variables d'environnement standard gettext (`LANGUAGE`/`LC_ALL`/
# `LANG`) ; `fallback=True` : si aucune traduction n'est trouvée pour la
# langue demandée, retombe silencieusement sur le texte français
# d'origine plutôt que de planter.
_LOCALE_DIR_DEV = Path(__file__).resolve().parent / "locale"
_LOCALE_DIR_INSTALLED = Path("/usr/share/locale")
_LOCALE_DOMAIN = "switch-capture"
_locale_dir = _LOCALE_DIR_DEV if _LOCALE_DIR_DEV.is_dir() else _LOCALE_DIR_INSTALLED
_translation = gettext.translation(_LOCALE_DOMAIN, localedir=str(_locale_dir), fallback=True)
_ = _translation.gettext

from switch_capture_core import (
    KEYRING_AVAILABLE,
    MODEL_PROFILES,
    CaptureRotationThread,
    Config,
    InspectConfig,
    MirrorConfig,
    MirrorThread,
    SetupAndCaptureThread,
    SharedState,
    UninstallThread,
    analyze_pacing_gaps,
    confirm_ip_matches,
    delete_ssh_password_from_keepass,
    delete_ssh_password_from_keyring,
    format_inspect_report,
    format_pacing_analysis_report,
    inspect_switch,
    load_ssh_password_from_keepass,
    load_ssh_password_from_keyring,
    save_ssh_password_to_keepass,
    save_ssh_password_to_keyring,
)

_CONFIG_FIELDS = {f.name for f in dataclasses.fields(Config) if f.init}
_MIRROR_CONFIG_FIELDS = {f.name for f in dataclasses.fields(MirrorConfig) if f.init}
_INSPECT_CONFIG_FIELDS = {f.name for f in dataclasses.fields(InspectConfig) if f.init}
DEFAULT_SYSTEM_FEATURE_BIN_DIR = "/etc/switch-capture/feature-bin"


def _configure_logging(verbose: bool) -> None:
    """Configure loguru pour un usage CLI (console + fichier rotatif).

    Args:
        verbose: si True, niveau DEBUG sur la console ; sinon INFO.
    """
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if verbose else "INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        colorize=True,
    )
    logger.add("switch_capture.log", level="DEBUG", rotation="5 MB", retention="10 days", encoding="utf-8")


def load_yaml(path: str) -> dict:
    """Charge un fichier YAML de configuration.

    Args:
        path: chemin du fichier YAML.

    Returns:
        Le contenu parsé, ou un dict vide si le fichier est vide.
    """
    import yaml

    with open(path) as f:
        return yaml.safe_load(f) or {}


def _resolve_keepass_master_password() -> str | None:
    """Renvoie le mot de passe maître KeePass, jamais accepté en argument CLI en clair.

    Même traitement que `SWITCH_SSH_PASSWORD` : uniquement via variable
    d'environnement, pour ne jamais apparaître dans l'historique shell ou une
    liste de processus (`ps`).
    """
    return os.environ.get("SWITCH_CAPTURE_KEEPASS_PASSWORD") or None


def _maybe_fill_password_from_keyring(
    raw: dict, keepass_path: str | None = None, keepass_keyfile: str | None = None
) -> None:
    """Complète `raw["ssh_password"]` depuis le trousseau système, ou son repli KeePass.

    N'agit que si aucun mot de passe n'a été fourni ni par CLI/YAML ni par
    `SWITCH_SSH_PASSWORD` — même ordre de priorité que celui déjà appliqué
    par `Config.__post_init__`/`InspectConfig.__post_init__` pour la
    variable d'environnement — et si `switch_ip`/`ssh_user` sont connus.
    Le trousseau système est toujours tenté en premier ; le repli KeePass
    (fichier `.kdbx`, voir section dédiée dans `switch_capture_core.py`)
    n'est consulté que si le trousseau n'a rien renvoyé (absent, aucune
    entrée, ou trousseau système inaccessible) et qu'un fichier a été
    indiqué (`--keepass-path`, ou clé `keepass_path` du YAML `--config`).

    Args:
        raw: dict de configuration en cours de construction, modifié en
            place si un mot de passe mémorisé est trouvé.
        keepass_path: chemin du fichier `.kdbx` de repli, si connu (résolu
            par l'appelant depuis `--keepass-path`/le YAML, avant filtrage
            des clés propres à `Config`/`InspectConfig`) ou `None`.
        keepass_keyfile: chemin d'un fichier de clé KeePass additionnel, si
            connu (résolu par l'appelant depuis `--keepass-keyfile`/le YAML,
            même principe que `keepass_path`) ou `None`.
    """
    if raw.get("ssh_password") or os.environ.get("SWITCH_SSH_PASSWORD"):
        return
    switch_ip = raw.get("switch_ip")
    ssh_user = raw.get("ssh_user")
    if not switch_ip or not ssh_user:
        return
    remembered = load_ssh_password_from_keyring(switch_ip, ssh_user)
    if remembered:
        raw["ssh_password"] = remembered
        logger.debug("mot de passe SSH chargé depuis le trousseau système | {}@{}", ssh_user, switch_ip)
        return
    remembered = load_ssh_password_from_keepass(
        switch_ip, ssh_user, keepass_path, _resolve_keepass_master_password(), keepass_keyfile
    )
    if remembered:
        raw["ssh_password"] = remembered
        logger.debug("mot de passe SSH chargé depuis le fichier KeePass (repli) | {}@{}", ssh_user, switch_ip)


def _apply_password_keyring_actions(args: argparse.Namespace, switch_ip: str, ssh_user: str, ssh_password: str) -> None:
    """Applique `--remember-password`/`--forget-password` une fois la config validée.

    Args:
        args: espace de noms argparse (attributs `remember_password`/
            `forget_password`/`keepass_path`/`keepass_keyfile` absents
            traités comme `False`/`None` — sous-parseurs qui n'exposent pas
            ces options, ex. `mirror`).
        switch_ip: IP du switch résolue dans la config validée.
        ssh_user: utilisateur SSH résolu dans la config validée.
        ssh_password: mot de passe résolu (déjà validé non vide par
            `Config`/`InspectConfig`).

    Le trousseau système reste toujours prioritaire quand il est disponible ;
    le repli KeePass n'est utilisé pour `--remember-password`/
    `--forget-password` que si `keyring` n'est pas installé (`--keepass-path`
    fourni et `SWITCH_CAPTURE_KEEPASS_PASSWORD` positionnée). Ne lève jamais :
    un échec est journalisé en warning sans interrompre la commande ;
    `--forget-password` est idempotent par construction. Les deux options
    sont mutuellement exclusives au niveau argparse.
    """
    keepass_path = getattr(args, "keepass_path", None)
    keepass_keyfile = getattr(args, "keepass_keyfile", None)
    keepass_master_password = _resolve_keepass_master_password()
    keepass_fallback_ready = not KEYRING_AVAILABLE and keepass_path and keepass_master_password

    if getattr(args, "forget_password", False):
        delete_ssh_password_from_keyring(switch_ip, ssh_user)
        if keepass_fallback_ready:
            delete_ssh_password_from_keepass(
                switch_ip, ssh_user, keepass_path, keepass_master_password, keepass_keyfile
            )

    if getattr(args, "remember_password", False):
        if KEYRING_AVAILABLE:
            try:
                save_ssh_password_to_keyring(switch_ip, ssh_user, ssh_password)
            except RuntimeError as exc:
                logger.warning("--remember-password demandé mais échec : {}", exc)
        elif keepass_fallback_ready:
            try:
                save_ssh_password_to_keepass(
                    switch_ip, ssh_user, ssh_password, keepass_path, keepass_master_password, keepass_keyfile
                )
            except RuntimeError as exc:
                logger.warning("--remember-password (repli KeePass) demandé mais échec : {}", exc)
        else:
            logger.warning(
                "--remember-password demandé mais ni trousseau système ni repli KeePass disponible "
                "(module 'keyring' absent — fournissez --keepass-path et SWITCH_CAPTURE_KEEPASS_PASSWORD "
                "pour utiliser le repli)"
            )


def build_config(args: argparse.Namespace) -> Config:
    """Fusionne YAML (si fourni) et arguments CLI (prioritaires) en un Config.

    Args:
        args: espace de noms argparse déjà parsé, doit exposer les mêmes
            attributs que les champs de Config, plus `config` (chemin YAML).

    Returns:
        Le Config validé.

    Raises:
        ValueError: relayée depuis Config.__post_init__ si un champ
            obligatoire manque ou si une valeur est invalide.
    """
    raw: dict = {}
    if getattr(args, "config", None):
        raw = load_yaml(args.config)

    for key in _CONFIG_FIELDS:
        value = getattr(args, key, None)
        if value is not None:
            raw[key] = value

    # `keepass_path`/`keepass_keyfile` ne sont pas des champs de Config (ce
    # sont des réglages du mécanisme de mémorisation du mot de passe, pas de
    # la capture elle-même, même statut que --remember-password/
    # --forget-password) : on les récupère avant le filtrage ci-dessous, qui
    # les éliminerait sinon.
    keepass_path = raw.get("keepass_path") or getattr(args, "keepass_path", None)
    keepass_keyfile = raw.get("keepass_keyfile") or getattr(args, "keepass_keyfile", None)
    raw = {k: v for k, v in raw.items() if k in _CONFIG_FIELDS}
    _maybe_fill_password_from_keyring(raw, keepass_path=keepass_path, keepass_keyfile=keepass_keyfile)
    return Config(**raw)


def build_inspect_config(args: argparse.Namespace) -> InspectConfig:
    """Fusionne YAML (si fourni) et arguments CLI (prioritaires) en un InspectConfig.

    Même logique que `build_config`, avec le sous-ensemble de champs
    d'`InspectConfig` — un fichier `--config` déjà utilisé pour `capture`
    peut donc directement être réutilisé pour `inspect` (les champs en trop,
    ex. capture_interface, sont simplement ignorés).

    Args:
        args: espace de noms argparse déjà parsé (sous-commande `inspect`).

    Returns:
        L'InspectConfig validé.

    Raises:
        ValueError: relayée depuis InspectConfig.__post_init__ si un champ
            obligatoire manque ou si une valeur est invalide.
    """
    raw: dict = {}
    if getattr(args, "config", None):
        raw = load_yaml(args.config)

    for key in _INSPECT_CONFIG_FIELDS:
        value = getattr(args, key, None)
        if value is not None:
            raw[key] = value

    keepass_path = raw.get("keepass_path") or getattr(args, "keepass_path", None)
    keepass_keyfile = raw.get("keepass_keyfile") or getattr(args, "keepass_keyfile", None)
    raw = {k: v for k, v in raw.items() if k in _INSPECT_CONFIG_FIELDS}
    _maybe_fill_password_from_keyring(raw, keepass_path=keepass_path, keepass_keyfile=keepass_keyfile)
    return InspectConfig(**raw)


def _add_common_config_args(parser: argparse.ArgumentParser) -> None:
    """Ajoute à `parser` tous les arguments qui alimentent Config.

    Args:
        parser: sous-parseur argparse (capture ou uninstall) à compléter.
    """
    parser.add_argument("--config", help=_("Chemin d'un fichier YAML de base (surchargé par les autres options)"))

    parser.add_argument("--switch-ip", dest="switch_ip")
    parser.add_argument("--ssh-user", dest="ssh_user")
    parser.add_argument(
        "--ssh-password",
        dest="ssh_password",
        help=_("Déconseillé en clair : préférez la variable d'environnement SWITCH_SSH_PASSWORD"),
    )
    password_group = parser.add_mutually_exclusive_group()
    password_group.add_argument(
        "--remember-password",
        dest="remember_password",
        action="store_true",
        help=_(
            "Mémorise le mot de passe SSH utilisé dans le trousseau système (libsecret/GNOME "
            "Keyring, jamais en clair sur disque) pour ce couple switch/utilisateur — les "
            "prochains lancements le retrouvent automatiquement sans --ssh-password ni "
            "SWITCH_SSH_PASSWORD. Nécessite le module Python 'keyring' (dépendance optionnelle)."
        ),
    )
    password_group.add_argument(
        "--forget-password",
        dest="forget_password",
        action="store_true",
        help=_("Retire du trousseau système le mot de passe précédemment mémorisé pour ce couple switch/utilisateur."),
    )
    parser.add_argument(
        "--keepass-path",
        dest="keepass_path",
        help=_(
            "Repli pour --remember-password/--forget-password/le chargement automatique si le module "
            "'keyring' n'est pas installé (pas de trousseau système, ex. serveur headless) : chemin d'un "
            "fichier KeePass .kdbx existant (jamais créé par cet outil). Nécessite aussi la variable "
            "d'environnement SWITCH_CAPTURE_KEEPASS_PASSWORD (mot de passe maître) et le module Python "
            "'pykeepass' (dépendance optionnelle). Ignoré si un trousseau système est disponible."
        ),
    )
    parser.add_argument(
        "--keepass-keyfile",
        dest="keepass_keyfile",
        help=_(
            "Fichier de clé KeePass additionnel, en complément du mot de passe maître (--keepass-path), "
            "pour les bases protégées par un fichier de clé en plus du mot de passe. Ignoré si "
            "--keepass-path n'est pas fourni."
        ),
    )
    parser.add_argument("--slot", dest="slot", type=int)
    parser.add_argument(
        "--model",
        dest="model",
        choices=sorted(MODEL_PROFILES),
        help=_("Force le profil matériel au lieu de l'auto-détection ('display version')"),
    )
    parser.add_argument(
        "--feature-bin-path",
        dest="feature_bin_path",
        help=_("Chemin exact du .bin à pousser (prioritaire sur --feature-bin-dir)"),
    )
    parser.add_argument(
        "--feature-bin-dir",
        dest="feature_bin_dir",
        help=_("Racine du dépôt local de .bin, organisé par <modèle>/<version>/ (def: ./feature-bin)"),
    )
    parser.add_argument("--mount-point", dest="mount_point")
    parser.add_argument(
        "--transfer-mode",
        dest="transfer_mode",
        choices=("scp", "sshfs"),
        help=_(
            "'scp' (défaut, recommandé) : transferts SCP à la demande, pas de montage FUSE. "
            "'sshfs' (legacy) : montage sshfs persistant de la flash (--mount-point)"
        ),
    )
    parser.add_argument("--capture-interface", dest="capture_interface")
    parser.add_argument("--capture-basename", dest="capture_basename")
    parser.add_argument("--rotation-seconds", dest="rotation_seconds", type=int)
    parser.add_argument("--max-ring-files", dest="max_ring_files", type=int)
    parser.add_argument(
        "--capture-filter",
        dest="capture_filter",
        help=_("Expression tcpdump-like, ex: 'host 10.0.0.5 and tcp port 22'"),
    )
    parser.add_argument("--spool-dir", dest="spool_dir")
    parser.add_argument("--archive-dir", dest="archive_dir")
    parser.add_argument("--fifo-path", dest="fifo_path")
    parser.add_argument("--poll-interval", dest="poll_interval", type=int)

    parser.add_argument(
        "--capture-label",
        dest="capture_label",
        help=_(
            "Étiquette libre du point de capture (ex: 'client', 'routeur-core', "
            "'serveur-web') — écrite dans le sidecar de métadonnées pour "
            "corréler plusieurs traces d'un même trafic prises à des points différents"
        ),
    )
    parser.add_argument(
        "--ntp-server",
        dest="ntp_server",
        help=_("Serveur NTP à configurer sur le switch si son horloge n'est pas déjà synchronisée"),
    )
    parser.add_argument(
        "--no-ensure-ntp",
        dest="ensure_ntp",
        action="store_const",
        const=False,
        default=None,
        help=_("Saute complètement la vérification NTP (active par défaut)"),
    )
    parser.add_argument(
        "--output-mode",
        dest="output_mode",
        choices=("fifo", "tap", "rpcap"),
        help=_(
            "'fifo' (défaut) : FIFO + Wireshark auto-lancé, une capture live à la fois. "
            "'tap' : écrit dans une interface réseau virtuelle TAP (--tap-interface), "
            "pour observer plusieurs captures simultanées dans une même instance Wireshark. "
            "'rpcap' : packet-capture remote natif Comware — Wireshark se connecte "
            "directement au switch en réseau (rpcap://...), sans fichier ni FIFO/TAP local "
            "(disponibilité selon modèle/version, voir CAPTURE-METHODS.md)"
        ),
    )
    parser.add_argument(
        "--tap-interface",
        dest="tap_interface",
        help=_("Nom de l'interface TAP à utiliser en mode --output-mode tap (ex: vcap1)"),
    )
    parser.add_argument(
        "--tap-cleanup-on-stop",
        dest="tap_cleanup_on_stop",
        action="store_true",
        default=None,
        help=_("Supprime l'interface TAP à l'arrêt de la capture (par défaut : laissée en place)"),
    )
    parser.add_argument(
        "--tap-launch-wireshark",
        dest="tap_launch_wireshark",
        action="store_true",
        default=None,
        help=_(
            "Lance automatiquement Wireshark sur l'interface TAP dès qu'elle est prête "
            "(désactivé par défaut, l'utilisateur le fait alors lui-même). N'a d'effet "
            "qu'en --output-mode tap. Avec plusieurs captures simultanées, ouvre une "
            "fenêtre par capture au lieu d'une seule observant toutes les interfaces "
            "— voir USAGE.md"
        ),
    )
    parser.add_argument(
        "--rpcap-port",
        dest="rpcap_port",
        type=int,
        help=_("Port du service RPCAP côté switch en mode --output-mode rpcap (défaut Comware : 2002)"),
    )
    parser.add_argument(
        "--tap-pace-playback",
        dest="tap_pace_playback",
        action="store_true",
        default=None,
        help=_(
            "Réinjecte les trames d'un fichier .pcap rapatrié en respectant "
            "approximativement l'écart de temps d'origine entre elles, au lieu de "
            "les écrire aussi vite que possible. N'a d'effet qu'en --output-mode tap. "
            "Plafonné par --tap-pace-max-gap"
        ),
    )
    parser.add_argument(
        "--tap-pace-max-gap",
        dest="tap_pace_max_gap_seconds",
        type=float,
        help=_("Délai maximal en secondes entre deux trames avec --tap-pace-playback (défaut : 2.0)"),
    )
    parser.add_argument(
        "--no-hide-capture-traffic",
        dest="hide_capture_traffic",
        action="store_const",
        const=False,
        default=None,
        help=_(
            "N'exclut plus le trafic SSH/SCP outil<->switch de la capture "
            "(exclu par défaut, en plus du filtre --capture-filter le cas échéant). "
            "Sans effet en --output-mode rpcap"
        ),
    )
    parser.add_argument(
        "--capture-direction",
        dest="capture_direction",
        choices=("inbound", "outbound", "bidirection"),
        help=_(
            "Sens du trafic capté par packet-capture : 'bidirection' (défaut, "
            "entrant + sortant), 'inbound' (entrant seul, comportement Comware "
            "par défaut sans ce mot-clé) ou 'outbound' (sortant seul). "
            "S'applique à --output-mode fifo/tap/rpcap"
        ),
    )
    parser.add_argument(
        "--no-archive-as-pcapng",
        dest="archive_as_pcapng",
        action="store_const",
        const=False,
        default=None,
        help=_(
            "Archive les fichiers dans --archive-dir au format .pcap classique "
            "d'origine, sans les convertir en .pcapng (conversion activée par "
            "défaut). Sans effet si --archive-dir n'est pas fourni"
        ),
    )


def _default_feature_bin_dir() -> str:
    """Résout le dossier feature-bin cible par défaut pour `import-bin`.

    Returns:
        `/etc/switch-capture/feature-bin` si ce dossier existe (install via
        `.deb`/`.rpm`/`install.sh`), sinon `./feature-bin` (usage dev,
        lancé depuis un clone du dépôt).
    """
    if Path(DEFAULT_SYSTEM_FEATURE_BIN_DIR).is_dir():
        return DEFAULT_SYSTEM_FEATURE_BIN_DIR
    return "./feature-bin"


def build_arg_parser() -> argparse.ArgumentParser:
    """Construit le parseur CLI avec ses trois sous-commandes.

    Returns:
        Le parseur configuré (capture / uninstall / import-bin).
    """
    parser = argparse.ArgumentParser(
        prog="switch-capture",
        description=_("Orchestrateur de capture packet-capture pour switches HPE Comware"),
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    subparsers = parser.add_subparsers(dest="action", required=True)

    capture_parser = subparsers.add_parser("capture", help=_("Lance une capture (bloquant, Ctrl+C pour arrêter)"))
    _add_common_config_args(capture_parser)

    uninstall_parser = subparsers.add_parser("uninstall", help=_("Désinstalle la feature packet-capture sur le switch"))
    _add_common_config_args(uninstall_parser)
    uninstall_parser.add_argument(
        "--remove-bin",
        dest="remove_bin_from_flash",
        action="store_true",
        help=_("Supprime aussi le .bin de la flash après désactivation (sinon il reste présent mais inactif)"),
    )
    uninstall_parser.add_argument(
        "--confirm-ip",
        dest="confirm_ip",
        action="store_true",
        help=_(
            "Demande de retaper --switch-ip de façon interactive avant de poursuivre "
            "(garde-fou supplémentaire pour un lancement manuel en production). "
            "Ne pas utiliser en cron/systemd : la commande attendrait une entrée "
            "standard qui n'arrivera jamais."
        ),
    )

    import_bin_parser = subparsers.add_parser(
        "import-bin",
        help=_("Copie un dépôt local de .bin (structure <modèle>/<version>/*.bin) vers --feature-bin-dir"),
    )
    import_bin_parser.add_argument(
        "source_dir",
        help=_("Dossier source à importer, ex: ./feature-bin à côté de src/ (voir README-feature-bin.md)"),
    )
    import_bin_parser.add_argument(
        "--feature-bin-dir",
        dest="feature_bin_dir",
        help=_(
            "Dossier cible (défaut : /etc/switch-capture/feature-bin s'il "
            "existe déjà, sinon ./feature-bin). Identique quelle que soit "
            "la méthode d'installation (.deb, .rpm, install.sh)."
        ),
    )

    mirror_parser = subparsers.add_parser(
        "mirror",
        help=_(
            "Configure (ou retire) du port mirroring (SPAN local, ERSPAN/GRE distant, ou "
            "VLAN sonde + VXLAN L2) sur le switch, en mirroring de port entier ou filtré "
            "par ACL (--filter-mode)"
        ),
    )
    mirror_parser.add_argument("--switch-ip", dest="switch_ip", required=True)
    mirror_parser.add_argument("--ssh-user", dest="ssh_user", required=True)
    mirror_parser.add_argument("--ssh-password", dest="ssh_password")
    mirror_parser.add_argument(
        "--mode",
        dest="mode",
        choices=("local", "gre", "vxlan"),
        default="local",
        help=_(
            "'local' : SPAN, câble direct vers l'hôte de capture. 'gre' : ERSPAN "
            "tunnel-mode vers un collecteur distant. 'vxlan' : mirroring vers un VLAN "
            "sonde (--remote-probe-vlan), acheminé par extension L2 VXLAN plutôt que par "
            "un trunk physique — combinaison non officiellement documentée par H3C, "
            "imposée par retour d'expérience direct de l'utilisateur (voir features.md)"
        ),
    )
    mirror_parser.add_argument("--group-id", dest="group_id", type=int, default=1)
    mirror_parser.add_argument(
        "--source-interface",
        dest="source_interfaces",
        action="append",
        required=True,
        help=_("Interface source à mirrorer (répétable pour en mirrorer plusieurs)"),
    )
    mirror_parser.add_argument(
        "--direction",
        dest="direction",
        choices=("both", "inbound", "outbound"),
        default="both",
    )
    mirror_parser.add_argument(
        "--monitor-interface",
        dest="monitor_interface",
        help=_("(mode local) interface de destination connectée à l'hôte de capture"),
    )
    mirror_parser.add_argument("--tunnel-id", dest="tunnel_id", type=int, default=1)
    mirror_parser.add_argument(
        "--tunnel-local-ip",
        dest="tunnel_local_ip",
        help=_("(mode gre ou vxlan) IP source du tunnel, déjà portée par une interface du switch"),
    )
    mirror_parser.add_argument(
        "--tunnel-ip",
        dest="tunnel_ip",
        help=_("(mode gre) IP assignée à l'interface Tunnel elle-même"),
    )
    mirror_parser.add_argument("--tunnel-mask", dest="tunnel_mask", default="255.255.255.0")
    mirror_parser.add_argument(
        "--remote-ip",
        dest="remote_ip",
        help=_("(mode gre ou vxlan) IP du collecteur distant"),
    )
    mirror_parser.add_argument(
        "--loopback-interface",
        dest="loopback_interface",
        help=_("(mode gre, optionnel) interface pour le groupe service-loopback tunnel, si requis par la plateforme"),
    )
    mirror_parser.add_argument(
        "--remote-probe-vlan",
        dest="remote_probe_vlan",
        type=int,
        help=_("(mode vxlan, obligatoire) VLAN sonde Comware (mirroring-group ... remote-probe vlan)"),
    )
    mirror_parser.add_argument(
        "--vsi-name",
        dest="vsi_name",
        help=_("(mode vxlan, obligatoire) nom de la VSI Comware associée au VNI et au tunnel"),
    )
    mirror_parser.add_argument(
        "--vxlan-vni",
        dest="vxlan_vni",
        type=int,
        help=_("(mode vxlan, obligatoire) VNI VXLAN associé à --vsi-name (0-16777215)"),
    )
    mirror_parser.add_argument(
        "--service-instance-id",
        dest="service_instance_id",
        type=int,
        help=_(
            "(mode vxlan, optionnel) identifiant du service-instance Comware raccordant "
            "--remote-probe-vlan à --vsi-name sur --reflector-interface — déduit de "
            "--group-id si omis"
        ),
    )
    mirror_parser.add_argument(
        "--reflector-interface",
        dest="reflector_interface",
        help=_(
            "(mode vxlan, obligatoire) port physique dédié au reflector-port du "
            "mirroring-group et au raccordement VSI (service-instance)"
        ),
    )
    mirror_parser.add_argument(
        "--filter-mode",
        dest="filter_mode",
        choices=("port", "acl"),
        default="port",
        help=_(
            "'port' : mirroring-group historique, duplique tout le trafic du/des port(s) "
            "source. 'acl' : flow mirroring filtré par ACL avancée + politique QoS, ne "
            "duplique que les paquets correspondant à --acl-rule"
        ),
    )
    mirror_parser.add_argument(
        "--acl-number",
        dest="acl_number",
        type=int,
        default=3000,
        help=_("(filter-mode acl) numéro d'ACL avancée Comware (3000-3999, 3998/3999 exclus)"),
    )
    mirror_parser.add_argument(
        "--acl-rule",
        dest="acl_rules",
        action="append",
        help=_(
            "(filter-mode acl, obligatoire) règle ACL avancée complète, ex. "
            "'rule 0 permit ip source 10.0.0.5 0' (répétable pour en définir plusieurs)"
        ),
    )
    mirror_parser.add_argument(
        "--classifier-name",
        dest="classifier_name",
        help=_("(filter-mode acl, optionnel) nom du traffic classifier Comware — déduit de --group-id si omis"),
    )
    mirror_parser.add_argument(
        "--behavior-name",
        dest="behavior_name",
        help=_("(filter-mode acl, optionnel) nom du traffic behavior Comware — déduit de --group-id si omis"),
    )
    mirror_parser.add_argument(
        "--qos-policy-name",
        dest="qos_policy_name",
        help=_("(filter-mode acl, optionnel) nom de la qos policy Comware — déduit de --group-id si omis"),
    )
    mirror_parser.add_argument(
        "--teardown",
        dest="teardown",
        action="store_true",
        help=_("Retire la configuration au lieu de la pousser (undo mirroring-group/policy ACL + tunnel éventuel)"),
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help=_(
            "Mode dry run : détecte modèle/version/features actives sur le switch sans rien "
            "modifier (utile avant une première intervention sans accès physique)"
        ),
    )
    inspect_parser.add_argument(
        "--config", help=_("Chemin d'un fichier YAML de base (surchargé par les autres options)")
    )
    inspect_parser.add_argument("--switch-ip", dest="switch_ip")
    inspect_parser.add_argument("--ssh-user", dest="ssh_user")
    inspect_parser.add_argument(
        "--ssh-password",
        dest="ssh_password",
        help=_("Déconseillé en clair : préférez la variable d'environnement SWITCH_SSH_PASSWORD"),
    )
    inspect_password_group = inspect_parser.add_mutually_exclusive_group()
    inspect_password_group.add_argument(
        "--remember-password",
        dest="remember_password",
        action="store_true",
        help=_("Mémorise le mot de passe SSH utilisé dans le trousseau système (voir 'capture --help')."),
    )
    inspect_password_group.add_argument(
        "--forget-password",
        dest="forget_password",
        action="store_true",
        help=_("Retire du trousseau système le mot de passe précédemment mémorisé pour ce couple switch/utilisateur."),
    )
    inspect_parser.add_argument(
        "--keepass-path",
        dest="keepass_path",
        help=_("Repli si 'keyring' est absent (voir 'capture --help') : chemin d'un fichier KeePass .kdbx existant."),
    )
    inspect_parser.add_argument(
        "--keepass-keyfile",
        dest="keepass_keyfile",
        help=_("Fichier de clé KeePass additionnel (voir 'capture --help')."),
    )
    inspect_parser.add_argument(
        "--model",
        dest="model",
        choices=sorted(MODEL_PROFILES),
        help=_("Force le profil matériel au lieu de l'auto-détection ('display version')"),
    )
    inspect_parser.add_argument(
        "--feature-bin-path",
        dest="feature_bin_path",
        help=_("Nom exact du .bin à rechercher dans 'display install active' (prioritaire sur --feature-bin-dir)"),
    )
    inspect_parser.add_argument(
        "--feature-bin-dir",
        dest="feature_bin_dir",
        help=_(
            "Racine du dépôt local de .bin, pour résoudre le nom attendu si --feature-bin-path est omis (def: ./feature-bin)"
        ),
    )
    inspect_parser.add_argument(
        "--transfer-mode",
        dest="transfer_mode",
        choices=("scp", "sshfs"),
        help=_("Service de transfert à vérifier ('scp server enable' vs 'sftp server enable'), défaut : scp"),
    )

    analyze_pacing_parser = subparsers.add_parser(
        "analyze-pacing",
        help=_(
            "Analyse les écarts inter-trames d'un .pcap déjà rapatrié, pour choisir "
            "une valeur de --tap-pace-max-gap (voir features.md, section « Pas fait »)"
        ),
    )
    analyze_pacing_parser.add_argument(
        "pcap_file", help=_("Fichier .pcap classique (pas pcapng) déjà rapatrié à analyser")
    )
    analyze_pacing_parser.add_argument(
        "--candidate-max-gap",
        dest="candidate_max_gaps",
        type=float,
        action="append",
        help=_(
            "Valeur de --tap-pace-max-gap à évaluer sur ce fichier (répétable ; défaut : 0.5, 1, 2, 5, 10 secondes)"
        ),
    )

    return parser


def run_capture(cfg: Config) -> int:
    """Lance la capture et bloque jusqu'à Ctrl+C ou erreur fatale.

    Args:
        cfg: configuration validée.

    Returns:
        Code de sortie du processus (0 si arrêt propre, 1 si erreur).
    """
    state = SharedState()
    t1 = SetupAndCaptureThread(cfg, state)
    # En mode "rpcap", Wireshark se connecte directement au switch en
    # réseau (rpcap://...) : aucun fichier n'est écrit sur la flash, donc
    # rien à rapatrier — CaptureRotationThread ne sert à rien dans ce mode.
    t2 = CaptureRotationThread(cfg, state) if cfg.output_mode != "rpcap" else None

    def handle_sigint(signum, frame):
        logger.info("main | Ctrl+C reçu, arrêt en cours ...")
        state.stop_event.set()

    signal.signal(signal.SIGINT, handle_sigint)

    t1.start()
    if t2:
        t2.start()
    t1.join()
    if t2:
        t2.join()

    logger.info("main | terminé")
    return 0 if not state.stop_event.is_set() or state.capture_started.is_set() else 1


def run_uninstall(cfg: Config, remove_bin_from_flash: bool, confirm_ip: bool = False) -> int:
    """Exécute la désinstallation de façon synchrone (pas de thread nécessaire en CLI).

    Args:
        cfg: configuration validée.
        remove_bin_from_flash: si True, supprime aussi le .bin de la flash.
        confirm_ip: si True, demande de retaper cfg.switch_ip sur l'entrée
            standard avant de poursuivre (--confirm-ip) ; abandonne sans se
            connecter au switch si la saisie ne correspond pas. Si False
            (défaut, inchangé), aucun prompt : compatible cron/systemd.

    Returns:
        Code de sortie du processus (0 si succès, 1 si échec ou
        confirmation d'IP manquante/incorrecte).
    """
    if confirm_ip:
        try:
            typed = input(f"Retapez l'IP du switch pour confirmer la désinstallation ({cfg.switch_ip}) : ")
        except EOFError:
            typed = ""
        if not confirm_ip_matches(typed, cfg.switch_ip):
            logger.error(
                "uninstall | IP non confirmée (attendu : {ip}) — désinstallation annulée avant toute connexion",
                ip=cfg.switch_ip,
            )
            return 1

    state = SharedState()
    result: dict[str, object] = {}

    def on_done(success: bool, message: str) -> None:
        result["success"] = success
        result["message"] = message

    thread = UninstallThread(cfg, state, remove_bin_from_flash, on_done)
    thread.run()  # exécution synchrone volontaire : un seul run() en CLI

    success = bool(result.get("success"))
    message = str(result.get("message", ""))
    if success:
        logger.info("uninstall | {msg}", msg=message)
    else:
        logger.error("uninstall | {msg}", msg=message)
    return 0 if success else 1


def run_import_bin(source_dir: str, feature_bin_dir: str | None) -> int:
    """Copie un dépôt local de .bin vers le dossier feature-bin cible.

    Fusionne (n'écrase que les fichiers en conflit, ne supprime rien côté
    cible) — utilisable comme simple resynchronisation répétée après ajout
    de nouveaux `.bin` dans le dossier source. Identique quelle que soit la
    méthode d'installation : c'est cette commande, et non le packaging
    lui-même, qui donne accès aux `.bin` déjà présents (par ex. dans
    `feature-bin/` à côté de `src/`) une fois l'app installée via `.deb`,
    `.rpm` ou `install.sh`.

    Args:
        source_dir: dossier source (structure `<modèle>/<version>/*.bin`).
        feature_bin_dir: dossier cible ; si None, résolu automatiquement
            via `_default_feature_bin_dir()`.

    Returns:
        Code de sortie du processus (0 si succès, 1 si le dossier source
        est introuvable).
    """
    src = Path(source_dir)
    if not src.is_dir():
        logger.error("import-bin | dossier source introuvable : {src}", src=src)
        return 1

    dst = Path(feature_bin_dir or _default_feature_bin_dir())
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)

    bin_files = sorted(dst.rglob("*.bin"))
    logger.info(
        "import-bin | {src} -> {dst} ({n} fichier(s) .bin présents après import)",
        src=src,
        dst=dst,
        n=len(bin_files),
    )
    for f in bin_files:
        logger.debug("import-bin | {f}", f=f.relative_to(dst))
    if not bin_files:
        logger.warning(
            "import-bin | aucun .bin trouvé après import — vérifiez la structure "
            "<modèle>/<version>/*.bin (voir README-feature-bin.md)"
        )
    return 0


def run_mirror(args: argparse.Namespace) -> int:
    """Construit un MirrorConfig depuis `args` et pousse (ou retire) la configuration.

    Args:
        args: espace de noms argparse de la sous-commande `mirror`.

    Returns:
        Code de sortie du processus (0 si succès, 1 si échec, 2 si
        paramètres invalides).
    """
    raw = {key: getattr(args, key, None) for key in _MIRROR_CONFIG_FIELDS}
    raw = {k: v for k, v in raw.items() if v is not None}
    try:
        mirror_cfg = MirrorConfig(**raw)
    except ValueError as exc:
        logger.error("mirror | configuration invalide : {err}", err=exc)
        return 2

    result: dict[str, object] = {}

    def on_done(success: bool, message: str) -> None:
        result["success"] = success
        result["message"] = message

    thread = MirrorThread(mirror_cfg, teardown=bool(getattr(args, "teardown", False)), on_done=on_done)
    thread.run()  # exécution synchrone volontaire, comme run_uninstall

    success = bool(result.get("success"))
    message = str(result.get("message", ""))
    if success:
        logger.info("mirror | {msg}", msg=message)
    else:
        logger.error("mirror | {msg}", msg=message)
    return 0 if success else 1


def run_inspect(args: argparse.Namespace) -> int:
    """Mode dry run : inspecte le switch en lecture seule et affiche un rapport.

    Args:
        args: espace de noms argparse de la sous-commande `inspect`.

    Returns:
        Code de sortie du processus (0 si succès, 1 si échec de connexion/
        commande, 2 si configuration invalide).
    """
    try:
        cfg = build_inspect_config(args)
    except ValueError as exc:
        logger.error("inspect | configuration invalide : {err}", err=exc)
        return 2

    _apply_password_keyring_actions(args, cfg.switch_ip, cfg.ssh_user, cfg.ssh_password)

    try:
        report = inspect_switch(cfg)
    except Exception as exc:  # noqa: BLE001
        logger.error("inspect | échec de connexion/inspection : {err}", err=exc)
        return 1

    print(format_inspect_report(cfg.switch_ip, cfg.transfer_mode, report))
    return 0


def run_analyze_pacing(args: argparse.Namespace) -> int:
    """Analyse les écarts inter-trames d'un .pcap déjà rapatrié (voir `analyze_pacing_gaps`).

    Sous-commande purement locale : ni connexion SSH ni switch, seulement
    lecture du fichier passé en argument. Couvre le volet analyse du
    point #1 de la section « Pas fait » de features.md.

    Args:
        args: espace de noms argparse de la sous-commande `analyze-pacing`.

    Returns:
        Code de sortie du processus (0 si succès, 1 si le fichier est
        invalide ou ne contient aucune trame).
    """
    pcap_file = Path(args.pcap_file)
    candidate_max_gaps = args.candidate_max_gaps or None  # None -> défaut de analyze_pacing_gaps
    try:
        if candidate_max_gaps is not None:
            report = analyze_pacing_gaps(pcap_file, candidate_max_gaps=candidate_max_gaps)
        else:
            report = analyze_pacing_gaps(pcap_file)
    except (ValueError, OSError) as exc:
        logger.error("analyze-pacing | {err}", err=exc)
        return 1

    print(format_pacing_analysis_report(pcap_file, report))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée CLI.

    Args:
        argv: arguments à parser (sans le nom du programme). Si None,
            utilise sys.argv[1:] — permet au lanceur switch-capture de
            déléguer un sous-ensemble d'arguments sans toucher à sys.argv.

    Returns:
        Code de sortie du processus.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    if args.action == "import-bin":
        return run_import_bin(args.source_dir, args.feature_bin_dir)
    if args.action == "mirror":
        return run_mirror(args)
    if args.action == "inspect":
        return run_inspect(args)
    if args.action == "analyze-pacing":
        return run_analyze_pacing(args)

    try:
        cfg = build_config(args)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    _apply_password_keyring_actions(args, cfg.switch_ip, cfg.ssh_user, cfg.ssh_password)

    if args.action == "capture":
        return run_capture(cfg)
    if args.action == "uninstall":
        return run_uninstall(
            cfg,
            getattr(args, "remove_bin_from_flash", False),
            getattr(args, "confirm_ip", False),
        )

    parser.error(f"action inconnue : {args.action}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
