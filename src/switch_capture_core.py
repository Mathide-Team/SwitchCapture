"""Logique métier de l'orchestrateur packet-capture HPE Comware.

Ce module ne dépend d'aucun toolkit graphique : il expose les classes et
fonctions réutilisées à la fois par l'app GTK4 (switch_capture_gtk.py) et,
si besoin, par un usage scripté/headless. Toute interaction utilisateur
(formulaire, boîtes de dialogue) reste dans la couche GTK.

Voir CLAUDE.md pour l'architecture générale et les limitations connues.
"""

from __future__ import annotations

import fcntl
import itertools
import json
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path

from loguru import logger

try:
    from netmiko import ConnectHandler
except ImportError:  # rendu explicite au lancement plutôt qu'à l'import
    ConnectHandler = None

try:
    import paramiko
    from scp import SCPClient
except ImportError:  # rendu explicite au lancement plutôt qu'à l'import
    paramiko = None
    SCPClient = None

try:
    import keyring
    import keyring.errors
except ImportError:  # dépendance optionnelle (Recommends, jamais Depends) — voir
    # section "Trousseau système" plus bas : son absence ne doit jamais empêcher
    # l'usage du reste de l'outil, seulement désactiver silencieusement la
    # mémorisation du mot de passe.
    keyring = None

try:
    from pykeepass import PyKeePass
    from pykeepass.exceptions import CredentialsError
except ImportError:  # dépendance optionnelle elle aussi (voir section "Repli KeePass"
    # plus bas) : uniquement utile si `keyring` est absent (pas de trousseau système,
    # ex. serveur headless sans Secret Service) et qu'un fichier .kdbx a été indiqué.
    PyKeePass = None
    CredentialsError = Exception

PCAP_GLOBAL_HEADER_LEN = 24  # pcap classique (pas pcapng)
PCAP_MAGICS = (0xA1B2C3D4, 0xD4C3B2A1)
PCAP_RECORD_HEADER_LEN = 16  # ts_sec, ts_usec, incl_len, orig_len (4 octets chacun)

# pcapng (RFC 9292) — constantes minimales pour écrire un fichier valide
# lisible par Wireshark/tshark, sans dépendance externe (pas de scapy/tshark
# ici, comme le reste du parsing pcap de ce module : uniquement `struct`).
PCAPNG_SHB_BLOCK_TYPE = 0x0A0D0D0A  # Section Header Block
PCAPNG_IDB_BLOCK_TYPE = 0x00000001  # Interface Description Block
PCAPNG_EPB_BLOCK_TYPE = 0x00000006  # Enhanced Packet Block
PCAPNG_BYTE_ORDER_MAGIC = 0x1A2B3C4D  # dans le corps du SHB, indique le boutisme

# ioctl TUNSETIFF et flags IFF_* (linux/if_tun.h) — valeurs stables sur toutes
# les architectures Linux courantes, pas besoin d'un binding C pour ça.
TUNSETIFF = 0x400454CA
IFF_TAP = 0x0002
IFF_NO_PI = 0x1000


# --------------------------------------------------------------------------- #
# Profils matériels
# --------------------------------------------------------------------------- #
# "installable"  -> feature package séparée, à pousser en flash puis activer
#                   via 'install activate feature ... slot N' (tous les
#                   modèles ci-dessous : 5130/5140/5510/5520 utilisent ce
#                   mécanisme, aucun n'est actuellement natif à l'image)
# "builtin"      -> packet-capture ferait partie de l'image principale, sans
#                   installation nécessaire — mécanisme conservé au cas où
#                   un modèle futur/non listé serait dans ce cas, mais
#                   aucun modèle ci-dessous n'est actuellement "builtin"
#                   (5510/5520 corrigés : ils nécessitent bien l'installation
#                   de la feature, comme 5130/5140 — ne pas supposer natif)
# "unsupported"  -> pas de mécanisme équivalent (Comware 5, ex: 3600 V2)
MODEL_PROFILES: dict[str, dict] = {
    "MSR4000": {
        "aliases": ("MSR4000 ", "MSR 4000 "),
        "comware": 7,
        "packet_capture": "builtin",
        "notes": "Feature packet-capture préinstallée'.",
    },
    "5130EI": {
        # Régression corrigée le 26/08/2026 : les alias réduits à
        # ("5130ei", "5130EI") lors du renommage 5130 -> 5130EI/5130HI ne
        # matchaient plus la sortie réelle de 'display version', qui place
        # le suffixe de gamme après le numéro de port (ex. « HPE
        # 5130-28-EI Switch »). Ré-élargi sur le même principe que les
        # alias d'origine du modèle "5130" fusionné (qui couvraient
        # "5130-28"/"5130-52" sans distinction EI/HI).
        "aliases": ("5130-28-EI", "5130-52-EI", "5130EI", "5130ei"),
        "comware": 7,
        "packet_capture": "installable",
        "notes": "Feature packet-capture installable via 'install activate feature'.",
    },
    "5130HI": {
        "aliases": ("5130-28-HI", "5130-52-HI", "5130HI", "5130hi"),
        "comware": 7,
        "packet_capture": "installable",
        "notes": "Feature packet-capture installable via 'install activate feature'.",
    },
    "5140EI": {
        "aliases": ("5140-28-EI", "5140-52-EI", "5140EI", "5140ei"),
        "comware": 7,
        "packet_capture": "installable",
        "notes": "Feature packet-capture installable via 'install activate feature'",
    },
    "5140HI": {
        "aliases": ("5140-28-HI", "5140-52-HI", "5140HI", "5140hi"),
        "comware": 7,
        "packet_capture": "installable",
        "notes": "Feature packet-capture installable via 'install activate feature'",
    },
    "5510": {
        "aliases": ("5510hi", "5510HI"),
        "comware": 7,
        "packet_capture": "installable",
        "notes": "Feature packet-capture installable via 'install activate feature'",
    },
    "5520": {
        "aliases": ("5520hi", "5520HI"),
        "comware": 7,
        "packet_capture": "installable",
        "notes": "Feature packet-capture installable via 'install activate feature'",
    },
    "3600v2": {
        "aliases": ("3600", "3600 V2", "3600-V2", "A3600"),
        "comware": 5,
        "packet_capture": "unsupported",
        "notes": (
            "Comware 5 : pas de mécanisme 'install activate feature' ni de "
            "commande packet-capture à ring-buffer. Alternative : port "
            "monitor / RSPAN vers un hôte de capture externe (tcpdump)."
        ),
    },
}


def detect_model(version_output: str) -> str | None:
    """Devine le profil matériel à partir de la sortie 'display version'.

    Args:
        version_output: sortie brute de la commande 'display version'.

    Returns:
        La clé de MODEL_PROFILES correspondante, ou None si non reconnue.
    """
    text = version_output.upper()
    logger.debug(text)
    for key, profile in MODEL_PROFILES.items():
        for alias in profile["aliases"]:
            logger.debug(f"key {key} - Alias {alias.upper()}")
            if alias.upper() in text:
                logger.debug(f"Modèle {key}")
                return key
    logger.debug("Modèle non trouvé")
    return None


def detect_software_version(version_output: str) -> str | None:
    """Extrait l'identifiant de release logicielle depuis 'display version'.

    Args:
        version_output: sortie brute de la commande 'display version'.

    Returns:
        La chaîne de release (ex: '6555P05'), ou None si non trouvée.
    """
    match = re.search(r"Release\s+(\S+)", version_output)
    if match:
        return match.group(1).rstrip(",")
    return None


def is_ntp_synchronized(status_output: str) -> bool:
    """Interprète la sortie de 'display ntp-service status' (horloge synchronisée ou non).

    Fonction pure, partagée entre la vérification/configuration NTP de
    l'installation (`SetupAndCaptureThread._ensure_ntp`, qui peut modifier
    la config si l'horloge dérive) et le mode dry run (`inspect_switch`,
    qui ne fait qu'observer) — pour que les deux ne divergent jamais sur
    cette lecture.

    Args:
        status_output: sortie brute de 'display ntp-service status'.

    Returns:
        True si "Clock status: synchronized". Un simple `in` casserait ici,
        "unsynchronized" contenant la sous-chaîne "synchronized".
    """
    match = re.search(r"clock status:\s*(\w+)", status_output, re.IGNORECASE)
    return bool(match) and match.group(1).lower() == "synchronized"


def resolve_feature_bin(feature_bin_dir: str, model: str, version: str | None) -> Path | None:
    """Cherche le .bin de la feature packet-capture pour un modèle/version donnés.

    Structure attendue du dépôt local :
        <feature_bin_dir>/<model>/<version>/packet-capture-*.bin
        <feature_bin_dir>/<model>/packet-capture-*.bin   (repli si version
                                                            inconnue ou absente)

    Args:
        feature_bin_dir: racine du dépôt local de .bin, organisée par modèle.
        model: clé de MODEL_PROFILES (ex: '5130').
        version: version logicielle détectée (ex: '6555P05'), ou None.

    Returns:
        Le chemin du premier .bin trouvé, ou None si rien ne correspond.
    """
    logger.debug(f"feature_bin_dir '{feature_bin_dir}' - model '{model}' - version '{version}' ")
    root = Path(feature_bin_dir) / model
    if not root.is_dir():
        return None

    if version:
        versioned = root / version
        logger.debug(f"versioned '{versioned}'  ")
        if versioned.is_dir():
            matches = sorted(versioned.glob("*packet-capture*.bin"))
            if matches:
                return matches[0]

    matches = sorted(root.glob("*packet-capture*.bin"))
    return matches[0] if matches else None


# --------------------------------------------------------------------------- #
# Filtres de capture (inline, sans ACL)
# --------------------------------------------------------------------------- #
# packet-capture accepte directement une expression 'capture-filter' façon
# tcpdump/BPF, sans passer par une ACL sur le switch. Voir CLAUDE.md pour
# la syntaxe complète et d'autres exemples.
CAPTURE_FILTER_PRESETS: dict[str, str] = {
    "Un hôte": "host 10.0.0.5",
    "Un hôte + port TCP": "host 10.0.0.5 and tcp port 22",
    "GRE (tunnel)": "proto gre",
    "Exclure le bruit L2/mgmt": "ip and not port 161 and not port 123",
    "Exclure OSPF/VRRP, garder le reste": "not proto ospf and not proto vrrp",
}


# --------------------------------------------------------------------------- #
# Interfaces virtuelles TAP (mode "tap", captures multiples simultanées)
# --------------------------------------------------------------------------- #
# Le mode "fifo" historique (un FIFO nommé + une instance Wireshark lancée
# automatiquement) ne permet qu'une seule capture "live" à la fois : chaque
# FIFO ne peut avoir qu'un lecteur pcap cohérent. Pour observer plusieurs
# captures simultanément (ex: même trafic vu au client, au routeur et au
# serveur) dans une unique instance Wireshark/tcpdump, on écrit directement
# les trames Ethernet brutes (pas le format pcap : juste la trame, sans
# en-tête pcap/record) dans une interface réseau virtuelle TAP dédiée par
# capture — Wireshark/tcpdump la voit alors comme une interface normale.
#
# Mode non-root (features.md, priorité 000 — urgente, traitée le 28/08/2026) :
# créer/activer une interface TAP nécessite CAP_NET_ADMIN, que switch-capture
# lui-même n'a jamais besoin d'avoir pour le reste de son fonctionnement (SSH,
# SCP, écriture de fichiers). `install.sh`/`build_deb.sh`/`build_rpm.sh`
# installent désormais une aide privilégiée minimale,
# `switch-capture-taphelper` (src/helpers/, voir son en-tête pour le détail),
# avec `cap_net_admin+ep` positionné via `setcap` — jamais de bit setuid,
# jamais de root. Si cette aide est présente, `ensure_tap_interface`/
# `delete_tap_interface` s'appuient dessus et switch-capture peut tourner
# entièrement sous l'utilisateur courant. Sinon (aide absente, ou process déjà
# root — cron/systemd historique), on retombe sur `ip` directement, comme
# avant.
def _taphelper_path() -> Path | None:
    """Localise l'aide privilégiée `switch-capture-taphelper`, si présente.

    Recherche, dans l'ordre : la variable d'environnement
    `SWITCH_CAPTURE_TAPHELPER` (tests, usage depuis un checkout non
    installé), le chemin d'installation standard, puis à côté de ce fichier
    (`switch_capture_core.py`) — utile quand l'app tourne directement depuis
    `src/` sans passer par `install.sh`.

    Returns:
        Le chemin de l'aide si trouvée ET exécutable, sinon None (l'appelant
        retombe alors sur `ip` directement, ce qui nécessite root).
    """
    candidates = []
    env_override = os.environ.get("SWITCH_CAPTURE_TAPHELPER")
    if env_override:
        candidates.append(Path(env_override))
    candidates.append(Path("/usr/lib/switch-capture/switch-capture-taphelper"))
    candidates.append(Path(__file__).resolve().parent / "switch-capture-taphelper")
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _ensure_tap_interface_via_helper(helper: Path, name: str) -> None:
    """Crée et active une interface TAP via l'aide privilégiée non-root.

    Args:
        helper: chemin de `switch-capture-taphelper` (voir `_taphelper_path`).
        name: nom de l'interface TAP.

    Raises:
        RuntimeError: si l'une des deux étapes (création, activation) échoue.
    """
    logger.info(
        "ensure_tap_interface | via aide privilégiée non-root ({helper}) pour {name}",
        helper=helper,
        name=name,
    )
    add = subprocess.run([str(helper), "add", name], capture_output=True, text=True, check=False)
    if add.returncode != 0:
        raise RuntimeError(
            f"Aide privilégiée : impossible de créer l'interface TAP {name!r} : {(add.stderr or add.stdout).strip()}"
        )
    up = subprocess.run([str(helper), "up", name], capture_output=True, text=True, check=False)
    if up.returncode != 0:
        raise RuntimeError(
            f"Aide privilégiée : impossible d'activer l'interface TAP {name!r} : {(up.stderr or up.stdout).strip()}"
        )


def ensure_tap_interface(name: str) -> None:
    """Crée (si besoin) et active une interface TAP persistante.

    Sans root : utilise l'aide privilégiée `switch-capture-taphelper` si
    elle est installée (voir `_taphelper_path`) — c'est le cas normal après
    `install.sh`/`.deb`/`.rpm`. En root (ex: cron/systemd), ou si l'aide est
    absente, retombe sur `ip` directement, qui nécessite alors root ou
    CAP_NET_ADMIN sur le process appelant lui-même.

    Args:
        name: nom de l'interface TAP (ex: "vcap1").

    Raises:
        RuntimeError: si la création/activation échoue (droits insuffisants,
            `ip`/l'aide absents, nom déjà pris par une interface d'un autre
            type...).
    """
    helper = None if os.geteuid() == 0 else _taphelper_path()
    if helper is not None:
        _ensure_tap_interface_via_helper(helper, name)
        return

    exists = (
        subprocess.run(
            ["ip", "link", "show", name],
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )

    if not exists:
        logger.info("ensure_tap_interface | création de {name}", name=name)
        result = subprocess.run(
            ["ip", "tuntap", "add", "dev", name, "mode", "tap"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Impossible de créer l'interface TAP {name!r} : {result.stderr.strip()} "
                "(droits root/CAP_NET_ADMIN requis ; réinstallez via install.sh/.deb/.rpm "
                "pour obtenir switch-capture-taphelper et éviter d'avoir à lancer "
                "switch-capture en root, voir INSTALL.md)"
            )
    else:
        logger.info("ensure_tap_interface | {name} existe déjà, réutilisation", name=name)

    result = subprocess.run(["ip", "link", "set", name, "up"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Impossible d'activer l'interface TAP {name!r} : {result.stderr.strip()}")


def delete_tap_interface(name: str) -> None:
    """Supprime une interface TAP créée par `ensure_tap_interface`.

    Non bloquant : une interface déjà absente ou appartenant à un autre
    processus n'est pas considérée comme une erreur (juste loggée). Utilise
    l'aide privilégiée non-root si disponible, comme `ensure_tap_interface`
    (voir sa docstring).

    Args:
        name: nom de l'interface TAP à supprimer.
    """
    helper = None if os.geteuid() == 0 else _taphelper_path()
    if helper is not None:
        result = subprocess.run([str(helper), "del", name], capture_output=True, text=True, check=False)
    else:
        result = subprocess.run(
            ["ip", "link", "delete", name],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        logger.warning(
            "delete_tap_interface | {name} : {err}",
            name=name,
            err=(result.stderr or result.stdout).strip(),
        )
    else:
        logger.info("delete_tap_interface | {name} supprimée", name=name)


class TapFrameWriter:
    """Écrit des trames Ethernet brutes dans une interface TAP via /dev/net/tun.

    Une trame écrite ici (via `write_frame`) apparaît immédiatement comme un
    paquet reçu sur l'interface TAP correspondante, visible par n'importe
    quel outil de capture qui l'écoute (Wireshark, tcpdump, tshark...). Pas
    de décodage/reconstruction : on réinjecte exactement les octets de la
    trame telle qu'elle était dans le fichier pcap d'origine.
    """

    def __init__(self, ifname: str) -> None:
        """Ouvre /dev/net/tun et s'attache à l'interface TAP `ifname`.

        Args:
            ifname: nom de l'interface TAP, déjà créée via
                `ensure_tap_interface`.

        Raises:
            OSError: si /dev/net/tun est inaccessible (droits, module tun
                non chargé) ou si l'ioctl TUNSETIFF échoue.
        """
        self._fd = os.open("/dev/net/tun", os.O_RDWR)
        ifr = struct.pack("16sH", ifname.encode("ascii"), IFF_TAP | IFF_NO_PI)
        fcntl.ioctl(self._fd, TUNSETIFF, ifr)
        self.ifname = ifname

    def write_frame(self, frame: bytes) -> None:
        """Injecte une trame Ethernet brute dans l'interface TAP.

        Args:
            frame: octets bruts de la trame (tels que stockés dans un
                enregistrement pcap, sans l'en-tête d'enregistrement).
        """
        os.write(self._fd, frame)

    def close(self) -> None:
        """Ferme le descripteur /dev/net/tun (l'interface reste, elle)."""
        try:
            os.close(self._fd)
        except OSError:
            pass


def iter_pcap_frames(pcap_file: Path, with_timestamps: bool = False):
    """Extrait les trames brutes d'un fichier pcap classique, une à une.

    Args:
        pcap_file: chemin du fichier .pcap (format classique, pas pcapng).
        with_timestamps: si True, yield des tuples ``(timestamp, frame)`` —
            `timestamp` reconstruit en secondes epoch (float) depuis
            `ts_sec`/`ts_usec` de l'enregistrement pcap — au lieu des seules
            trames. Par défaut False : comportement historique inchangé
            (les timestamps sont lus mais ignorés). Utilisé par le lissage
            de réinjection TAP, voir `compute_pacing_delays` et
            `Config.tap_pace_playback`.

    Yields:
        Les octets bruts de chaque trame (payload de chaque enregistrement,
        sans l'en-tête pcap global ni les en-têtes d'enregistrement) si
        `with_timestamps` est False (défaut), ou `(timestamp, frame)` si
        True.

    Raises:
        ValueError: si le fichier est trop petit ou n'a pas un magic pcap
            classique reconnu.
    """
    with open(pcap_file, "rb") as f:
        header = f.read(PCAP_GLOBAL_HEADER_LEN)
        if len(header) < PCAP_GLOBAL_HEADER_LEN:
            raise ValueError(f"{pcap_file} trop petit / pcap invalide")
        magic = struct.unpack("<I", header[:4])[0]
        if magic not in PCAP_MAGICS:
            raise ValueError(f"{pcap_file} : magic pcap inattendu ({magic:#x}), probablement pcapng")

        while True:
            record_header = f.read(PCAP_RECORD_HEADER_LEN)
            if len(record_header) < PCAP_RECORD_HEADER_LEN:
                break
            ts_sec, ts_usec, incl_len, _orig_len = struct.unpack("<IIII", record_header)
            frame = f.read(incl_len)
            if len(frame) < incl_len:
                break
            if with_timestamps:
                yield ts_sec + ts_usec / 1_000_000, frame
            else:
                yield frame


def _pcapng_block(block_type: int, body: bytes) -> bytes:
    """Construit un bloc pcapng générique complet (type + longueur + corps + longueur).

    Chaque bloc pcapng est encadré par sa longueur totale répétée en début
    et en fin de bloc (permet un parcours dans les deux sens) ; le corps est
    complété par du bourrage nul jusqu'à un multiple de 4 octets, comme
    l'exige le format (RFC 9292).

    Args:
        block_type: type de bloc (`PCAPNG_SHB_BLOCK_TYPE`,
            `PCAPNG_IDB_BLOCK_TYPE` ou `PCAPNG_EPB_BLOCK_TYPE`).
        body: contenu spécifique au bloc, sans les champs Block Type ni
            Block Total Length (ajoutés ici).

    Returns:
        Le bloc complet, prêt à être écrit tel quel dans un fichier .pcapng.
    """
    padded_body = body + b"\x00" * (-len(body) % 4)
    total_length = 12 + len(padded_body)  # type(4) + longueur(4) + corps + longueur(4)
    return struct.pack("<II", block_type, total_length) + padded_body + struct.pack("<I", total_length)


def convert_pcap_to_pcapng(pcap_path: Path, pcapng_path: Path) -> Path:
    """Convertit un fichier .pcap classique (rapatrié) en .pcapng.

    Réécrit les mêmes trames, dans le même ordre et avec les mêmes
    timestamps, au format pcapng moderne (Section Header Block + une
    Interface Description Block + une Enhanced Packet Block par trame) —
    aucune donnée n'est modifiée, seule l'enveloppe change. Réutilise
    `iter_pcap_frames` (déjà utilisé pour la réinjection TAP) pour le
    parsing, et n'ajoute aucune dépendance externe (pas de scapy/tshark) :
    uniquement `struct`, sur le même principe que le reste de ce module.

    Args:
        pcap_path: fichier .pcap classique source, déjà rapatrié et clôturé.
        pcapng_path: fichier .pcapng à écrire (écrasé s'il existe déjà).

    Returns:
        `pcapng_path`.

    Raises:
        ValueError: propagée par `iter_pcap_frames` si `pcap_path` n'a pas
            un magic pcap classique reconnu (fichier trop petit, corrompu,
            ou déjà au format pcapng).
    """
    with open(pcap_path, "rb") as f:
        header = f.read(PCAP_GLOBAL_HEADER_LEN)
    if len(header) < PCAP_GLOBAL_HEADER_LEN:
        raise ValueError(f"{pcap_path} trop petit / pcap invalide")
    magic = struct.unpack("<I", header[:4])[0]
    if magic not in PCAP_MAGICS:
        raise ValueError(f"{pcap_path} : magic pcap inattendu ({magic:#x})")
    # Champ "network" du global header pcap classique = LinkType pcapng
    # (mêmes valeurs numériques dans les deux formats, ex: 1 = Ethernet).
    linktype = struct.unpack("<I", header[20:24])[0]

    # Section Header Block : boutisme, version 1.0, longueur de section
    # inconnue (-1, valeur conventionnelle quand on écrit en flux).
    shb = _pcapng_block(
        PCAPNG_SHB_BLOCK_TYPE,
        struct.pack("<IHHq", PCAPNG_BYTE_ORDER_MAGIC, 1, 0, -1),
    )
    # Interface Description Block : LinkType repris du pcap source, pas de
    # limite de capture (SnapLen=0), aucune option (pas nécessaire pour
    # produire un fichier valide).
    idb = _pcapng_block(PCAPNG_IDB_BLOCK_TYPE, struct.pack("<HHI", linktype, 0, 0))

    blocks = [shb, idb]
    for ts, frame in iter_pcap_frames(pcap_path, with_timestamps=True):
        ts_units = round(ts * 1_000_000)  # résolution microseconde, comme le pcap source
        epb_body = (
            struct.pack(
                "<IIIII",
                0,  # Interface ID (une seule interface déclarée : 0)
                (ts_units >> 32) & 0xFFFFFFFF,
                ts_units & 0xFFFFFFFF,
                len(frame),
                len(frame),
            )
            + frame
        )
        blocks.append(_pcapng_block(PCAPNG_EPB_BLOCK_TYPE, epb_body))

    pcapng_path.write_bytes(b"".join(blocks))
    return pcapng_path


def archive_capture_file(pcap_file: Path, archive_dir: Path, as_pcapng: bool = True) -> Path:
    """Déplace un fichier .pcap clôturé vers `archive_dir`, en pcapng si demandé.

    Factorise le comportement d'archivage partagé par `_feed_into_tap` et
    `_feed_into_fifo` (jusqu'ici un simple `shutil.move`), pour y ajouter la
    conversion optionnelle vers pcapng (`Config.archive_as_pcapng`, voir
    `convert_pcap_to_pcapng`) sans dupliquer la logique dans les deux
    méthodes.

    Args:
        pcap_file: fichier .pcap local déjà rapatrié et déjà exploité (déjà
            réinjecté en TAP/FIFO) — c'est la copie qui part à l'archive.
        archive_dir: dossier d'archivage (`Config.archive_dir`), créé si
            besoin.
        as_pcapng: si True (défaut), le fichier archivé est converti en
            `.pcapng` (extension changée en conséquence) plutôt que déplacé
            tel quel. Si la conversion échoue (fichier déjà corrompu par
            exemple), repli sur un déplacement classique du `.pcap` — ne
            jamais perdre le fichier source pour une erreur de conversion.

    Returns:
        Le chemin final du fichier archivé.
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    if as_pcapng:
        pcapng_target = archive_dir / (pcap_file.stem + ".pcapng")
        try:
            convert_pcap_to_pcapng(pcap_file, pcapng_target)
            pcap_file.unlink(missing_ok=True)
            return pcapng_target
        except (ValueError, OSError) as exc:
            logger.warning(
                "archive_capture_file | conversion pcapng échouée pour {f} ({err}), archivage en .pcap classique",
                f=pcap_file,
                err=exc,
            )
    target = archive_dir / pcap_file.name
    shutil.move(str(pcap_file), target)
    return target


def compute_pacing_delays(timestamps: list[float], max_gap_seconds: float) -> list[float]:
    """Calcule le délai d'attente avant chaque trame pour un rejeu lissé en TAP.

    Fonction pure (aucun `time.sleep` ici, aucun effet de bord), testable en
    isolation — utilisée par `CaptureRotationThread._feed_into_tap` quand
    `Config.tap_pace_playback` est activé, pour réinjecter les trames d'un
    fichier .pcap rapatrié en respectant approximativement l'écart de temps
    d'origine entre elles, plutôt que de les écrire aussi vite que possible
    (comportement par défaut, `tap_pace_playback=False`).

    Args:
        timestamps: horodatages (secondes epoch) de chaque trame, dans
            l'ordre du fichier pcap d'origine — voir
            `iter_pcap_frames(..., with_timestamps=True)`.
        max_gap_seconds: délai maximal appliqué entre deux trames
            consécutives. Sans ce plafond, un silence réel de plusieurs
            minutes dans la capture d'origine bloquerait la réinjection
            d'autant — le lissage vise à fluidifier l'arrivée des données
            côté TAP, pas à reproduire fidèlement de longs silences.

    Returns:
        Une liste de même longueur que `timestamps` : le délai (secondes,
        toujours >= 0) à attendre avant d'injecter la trame correspondante.
        Le premier délai est toujours 0.0. Un écart négatif ou nul entre
        deux trames consécutives (horloge switch imprécise, trames
        réordonnées) est traité comme 0, jamais négatif.
    """
    delays: list[float] = []
    previous: float | None = None
    for ts in timestamps:
        if previous is None:
            delays.append(0.0)
        else:
            gap = ts - previous
            if gap < 0:
                gap = 0.0
            delays.append(min(gap, max_gap_seconds))
        previous = ts
    return delays


@dataclass
class PacingCandidateEffect:
    """Effet d'une valeur candidate de `max_gap_seconds` sur une capture donnée.

    Attributes:
        clamped_gap_count: nombre d'écarts bruts strictement supérieurs à
            cette valeur (donc raccourcis par le plafond lors du rejeu
            lissé).
        clamped_gap_fraction: `clamped_gap_count / gap_count`, entre 0.0 et
            1.0 (0.0 si `gap_count` est nul — capture à une seule trame ou
            vide).
        total_playback_seconds: durée totale du rejeu lissé avec cette
            valeur de plafond (`sum(compute_pacing_delays(...))`) — à
            comparer à `capture_duration_seconds` du même
            `PacingGapAnalysis` : plus les deux sont proches, plus le rejeu
            respecte fidèlement le rythme d'origine ; plus
            `total_playback_seconds` est petit, plus le plafond « compresse »
            les silences longs de la capture d'origine.
    """

    clamped_gap_count: int
    clamped_gap_fraction: float
    total_playback_seconds: float


@dataclass
class PacingGapAnalysis:
    """Statistiques sur les écarts inter-trames d'un fichier .pcap rapatrié.

    Produite par `analyze_pacing_gaps` — sert à choisir empiriquement une
    valeur de `Config.tap_pace_max_gap_seconds`/`--tap-pace-max-gap` à
    partir d'une capture réelle représentative, une fois celle-ci
    rapatriée. Couvre le volet « quel effet aurait tel ou tel plafond sur
    CETTE capture » du point 1 de la section « Pas fait » de features.md
    (« mesure réelle du timing spool → injection TAP ») ; ne couvre PAS le
    volet durée SCP elle-même, qui nécessite un switch réel en train de
    capturer, pas seulement un fichier .pcap déjà rapatrié — voir
    features.md pour ce qui reste ouvert.

    Attributes:
        frame_count: nombre de trames dans le fichier.
        capture_duration_seconds: écart entre le timestamp de la première
            et de la dernière trame.
        gap_count: nombre d'écarts inter-trames considérés
            (`frame_count - 1`, 0 si une seule trame ou moins).
        min_gap_seconds, median_gap_seconds, p90_gap_seconds,
            p95_gap_seconds, p99_gap_seconds, max_gap_seconds: distribution
            des écarts bruts entre trames consécutives, avant tout
            plafonnement (0.0 pour tous si `gap_count` est nul).
        candidate_effects: pour chaque valeur de `max_gap_seconds` candidate
            fournie à `analyze_pacing_gaps`, l'effet qu'aurait ce plafond
            sur cette capture précise — voir `PacingCandidateEffect`.
    """

    frame_count: int
    capture_duration_seconds: float
    gap_count: int
    min_gap_seconds: float
    median_gap_seconds: float
    p90_gap_seconds: float
    p95_gap_seconds: float
    p99_gap_seconds: float
    max_gap_seconds: float
    candidate_effects: dict[float, PacingCandidateEffect] = field(default_factory=dict)


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Percentile par interpolation linéaire, sans dépendance externe.

    Cohérent avec le reste du parsing pcap de ce module (uniquement
    `struct`/stdlib, jamais numpy/scapy/dpkt — voir commentaire en tête de
    fichier sur `PCAP_GLOBAL_HEADER_LEN`).

    Args:
        sorted_values: valeurs déjà triées par ordre croissant.
        pct: percentile souhaité, entre 0 et 100.

    Returns:
        La valeur interpolée. 0.0 si `sorted_values` est vide.
    """
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (pct / 100)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[int(rank)]
    lower_value = sorted_values[int(lower)] * (upper - rank)
    upper_value = sorted_values[int(upper)] * (rank - lower)
    return lower_value + upper_value


DEFAULT_PACING_CANDIDATE_MAX_GAPS: tuple[float, ...] = (0.5, 1.0, 2.0, 5.0, 10.0)


def analyze_pacing_gaps(
    pcap_file: Path,
    candidate_max_gaps: Sequence[float] = DEFAULT_PACING_CANDIDATE_MAX_GAPS,
) -> PacingGapAnalysis:
    """Analyse les écarts inter-trames d'un .pcap rapatrié pour choisir un `--tap-pace-max-gap`.

    Fonction pure de lecture seule (aucun effet de bord, aucun accès
    réseau/switch) : à faire tourner sur un fichier .pcap déjà rapatrié
    (voir `switch-capture capture`), format classique (pas pcapng — même
    contrainte que `iter_pcap_frames`). Elle ne mesure donc pas la durée
    SCP elle-même (voir docstring de `PacingGapAnalysis`), mais permet dès
    maintenant, sur une capture réelle déjà obtenue, de répondre à
    « quelle valeur de `--tap-pace-max-gap` serait raisonnable pour ce
    trafic ? » sans attendre un accès switch dédié à cette seule question.

    Args:
        pcap_file: fichier .pcap classique à analyser.
        candidate_max_gaps: valeurs de `--tap-pace-max-gap` à évaluer sur
            cette capture (par défaut `DEFAULT_PACING_CANDIDATE_MAX_GAPS`).

    Returns:
        Un `PacingGapAnalysis` complet.

    Raises:
        ValueError: fichier trop petit/magic pcap invalide (propagée par
            `iter_pcap_frames`), ou fichier ne contenant aucune trame.
    """
    frames = list(iter_pcap_frames(pcap_file, with_timestamps=True))
    if not frames:
        raise ValueError(f"{pcap_file} ne contient aucune trame")

    timestamps = [ts for ts, _ in frames]
    gaps = [max(0.0, b - a) for a, b in itertools.pairwise(timestamps)]
    sorted_gaps = sorted(gaps)

    candidate_effects: dict[float, PacingCandidateEffect] = {}
    for max_gap in candidate_max_gaps:
        delays = compute_pacing_delays(timestamps, max_gap)
        clamped = sum(1 for g in gaps if g > max_gap)
        candidate_effects[max_gap] = PacingCandidateEffect(
            clamped_gap_count=clamped,
            clamped_gap_fraction=(clamped / len(gaps)) if gaps else 0.0,
            total_playback_seconds=sum(delays),
        )

    return PacingGapAnalysis(
        frame_count=len(frames),
        capture_duration_seconds=timestamps[-1] - timestamps[0],
        gap_count=len(gaps),
        min_gap_seconds=sorted_gaps[0] if sorted_gaps else 0.0,
        median_gap_seconds=_percentile(sorted_gaps, 50),
        p90_gap_seconds=_percentile(sorted_gaps, 90),
        p95_gap_seconds=_percentile(sorted_gaps, 95),
        p99_gap_seconds=_percentile(sorted_gaps, 99),
        max_gap_seconds=sorted_gaps[-1] if sorted_gaps else 0.0,
        candidate_effects=candidate_effects,
    )


@dataclass
class Config:
    """Paramètres d'une session de capture.

    Args:
        switch_ip: adresse IP ou nom du switch.
        ssh_user: compte RADIUS existant (aucun compte local n'est créé).
        ssh_password: mot de passe SSH. Si vide, lu depuis
            SWITCH_SSH_PASSWORD au moment de la validation.
        slot: slot IRF/châssis cible pour l'install/désinstall de la feature.
        model: clé de MODEL_PROFILES, ou None pour auto-détection.
        feature_bin_path: chemin exact du .bin à pousser (prioritaire sur
            feature_bin_dir).
        feature_bin_dir: racine du dépôt local de .bin par modèle/version.
        mount_point: point de montage local sshfs de la flash du switch
            (uniquement utilisé si transfer_mode == "sshfs").
        transfer_mode: "scp" (par défaut, recommandé — pas de montage FUSE,
            juste des transferts SCP à la demande, plus fiable que sshfs
            en cas de lien instable/distant) ou "sshfs" (comportement
            historique : montage FUSE persistant de la flash, requiert le
            paquet sshfs). En mode "scp", le switch doit avoir
            `scp server enable` (pas `sftp server enable`).
        capture_interface: interface Comware à capturer (ex: GigabitEthernet1/0/1).
        capture_basename: nom de base des fichiers .pcap sur la flash.
        rotation_seconds: durée de chaque fichier du ring-buffer.
        max_ring_files: nombre de fichiers conservés dans le ring-buffer switch.
        capture_filter: expression de filtre inline (tcpdump-like), sans ACL.
        spool_dir: dossier local de rapatriement des .pcap clôturés.
        archive_dir: dossier d'archivage après fusion (None -> suppression).
        fifo_path: chemin du FIFO nommé lu par Wireshark en mode live (mode "fifo").
        poll_interval: intervalle de scrutation du montage sshfs, en secondes.
        capture_label: étiquette libre du point de capture (ex: "client",
            "routeur-core", "serveur-web") — écrite dans le sidecar de
            métadonnées pour permettre à un outil tiers de corréler
            plusieurs traces du même trafic prises à des points différents.
        ntp_server: serveur NTP à configurer sur le switch si son horloge
            n'est pas déjà synchronisée. None -> vérification seule, pas de
            configuration automatique (juste un avertissement loggé).
        ensure_ntp: si False, saute complètement la vérification NTP.
        output_mode: "fifo" (comportement historique : FIFO nommé + une
            instance Wireshark lancée automatiquement, une seule capture
            "live" à la fois), "tap" (écrit les trames dans une interface
            réseau virtuelle TAP persistante — plusieurs captures
            simultanées observables dans une unique instance Wireshark/
            tcpdump, au prix de la création d'une interface réseau donc de
            privilèges root/CAP_NET_ADMIN), ou "rpcap" (utilise
            `packet-capture remote` — une fonctionnalité native Comware qui
            fait du switch lui-même un serveur RPCAP : Wireshark se
            connecte directement en réseau via `rpcap://<switch_ip>:<port>/
            <interface>`, sans transfert de fichier ni FIFO/TAP local. Pas
            de rotation de fichiers dans ce mode : `CaptureRotationThread`
            n'est pas utilisé. Disponibilité selon modèle/version — comme
            packet-capture local, voir `MODEL_PROFILES`).
        tap_interface: nom de l'interface TAP à utiliser en mode "tap"
            (ex: "vcap1"). Obligatoire si output_mode == "tap".
        tap_cleanup_on_stop: si True, supprime l'interface TAP à l'arrêt de
            la capture. Par défaut False : l'interface reste disponible
            après coup (pour inspection, ou pour la laisser à un outil tiers
            de comparaison de traces).
        tap_launch_wireshark: si True (défaut False), lance automatiquement
            une instance Wireshark attachée à `tap_interface` dès que
            celle-ci est prête (voir `_launch_wireshark_tap`), plutôt que
            de laisser l'utilisateur le faire lui-même. N'a d'effet qu'en
            mode "tap" ; ignoré en "fifo" (qui lance déjà Wireshark
            automatiquement et inconditionnellement, voir
            `_launch_wireshark`) et en "rpcap" (Wireshark s'y connecte
            directement en réseau, aucun processus local à lancer).
            Désactivé par défaut : chaque `CaptureRotationThread` ignore
            les autres, donc l'activer sur plusieurs captures simultanées
            ouvre une fenêtre par capture plutôt que la fenêtre unique
            observant toutes les interfaces que permet ce mode quand
            Wireshark est lancé manuellement (voir docstring de
            `CaptureRotationThread`) — ce dernier reste le mieux adapté à
            ce scénario.
        rpcap_port: port du service RPCAP côté switch en mode "rpcap"
            (défaut Comware : 2002).
        tap_pace_playback: si True (défaut False), réinjecte les trames
            d'un fichier .pcap rapatrié en respectant approximativement
            l'écart de temps d'origine entre elles (voir
            `compute_pacing_delays`) plutôt que de les écrire aussi vite
            que possible. N'a d'effet qu'en mode "tap" ; ignoré en "fifo"/
            "rpcap".
        tap_pace_max_gap_seconds: délai maximal (secondes) entre deux
            trames consécutives quand `tap_pace_playback` est activé —
            évite qu'un silence réel de plusieurs minutes dans la capture
            d'origine bloque la réinjection d'autant. Doit être
            strictement positif.
        hide_capture_traffic: si True (défaut), exclut le trafic SSH/SCP
            entre la machine qui exécute l'outil et le switch
            (`host {switch_ip} and port 22`) de la capture, en plus du
            filtre saisi dans `capture_filter` le cas échéant — voir
            `build_capture_filter`. N'a d'effet qu'en `output_mode`
            "fifo"/"tap" (packet-capture local) ; sans effet en "rpcap".
        archive_as_pcapng: si True (défaut), les fichiers archivés dans
            `archive_dir` sont convertis en `.pcapng` (voir
            `convert_pcap_to_pcapng`/`archive_capture_file`) plutôt que
            conservés au format `.pcap` classique d'origine — pcapng est le
            format moderne recommandé par Wireshark (métadonnées
            d'interface, horodatage plus précis, extensible). Sans effet si
            `archive_dir` n'est pas défini (rien n'est archivé dans ce cas).
            La réinjection live (FIFO/TAP) elle-même n'est pas concernée :
            elle continue de lire les `.pcap` classiques rapatriés, la
            conversion n'intervient qu'au moment de l'archivage, après coup.
        capture_direction: "bidirection" (défaut), "inbound" ou "outbound"
            — sens du trafic capté par `packet-capture` (point 6,
            features.md). D'après la doc H3C officielle, `packet-capture
            local`/`packet-capture remote` ne capturent que le trafic
            entrant par défaut si ni `bidirection` ni `outbound` n'est
            précisé sur la ligne de commande ; l'hypothèse d'origine
            (« semble ne pas capter les trames émises par le switch
            lui-même ») est donc confirmée, pas un artefact de ce dépôt.
            Défaut changé à "bidirection" ici (plutôt que de reproduire le
            défaut Comware "inbound") pour capter les deux sens par
            défaut, conformément à l'objectif explicitement formulé dans
            features.md. S'applique aux deux modes qui parlent directement
            `packet-capture` (local : "fifo"/"tap" ; "rpcap" : `packet-
            capture remote`) — voir `build_capture_direction_clause`.
    """

    switch_ip: str = ""
    ssh_user: str = ""
    ssh_password: str = ""
    slot: int = 1
    model: str | None = None
    feature_bin_path: str | None = None
    feature_bin_dir: str = "./feature-bin"
    mount_point: str = "./mount"
    transfer_mode: str = "scp"
    capture_interface: str = ""
    capture_basename: str = "capture.pcap"
    rotation_seconds: int = 20
    max_ring_files: int = 10
    capture_filter: str = ""
    packet_capture_cmd: str = "packet-capture"
    spool_dir: str = "./spool"
    archive_dir: str | None = None
    fifo_path: str = "./capture_live.fifo"
    poll_interval: int = 5
    capture_label: str = ""
    ntp_server: str | None = None
    ensure_ntp: bool = True
    output_mode: str = "fifo"
    tap_interface: str | None = None
    tap_cleanup_on_stop: bool = False
    tap_launch_wireshark: bool = False
    rpcap_port: int = 2002
    tap_pace_playback: bool = False
    tap_pace_max_gap_seconds: float = 2.0
    hide_capture_traffic: bool = True
    archive_as_pcapng: bool = True
    capture_direction: str = "bidirection"

    feature_filename: str | None = field(default=None, init=False, repr=False)
    capture_prefix: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        """Normalise les champs dérivés et valide les champs obligatoires."""
        if not self.ssh_password:
            self.ssh_password = os.environ.get("SWITCH_SSH_PASSWORD", "")
        if self.feature_bin_path:
            self.feature_filename = Path(self.feature_bin_path).name
        self.capture_prefix = Path(self.capture_basename).stem

        missing = [
            name
            for name, value in (
                ("switch_ip", self.switch_ip),
                ("ssh_user", self.ssh_user),
                ("capture_interface", self.capture_interface),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Champs obligatoires manquants : {', '.join(missing)}")
        if not self.ssh_password:
            raise ValueError("Mot de passe SSH manquant (champ 'ssh_password' ou variable SWITCH_SSH_PASSWORD)")
        if self.model and self.model not in MODEL_PROFILES:
            raise ValueError(f"Modèle invalide : {self.model!r} (choix : {', '.join(sorted(MODEL_PROFILES))})")
        if self.output_mode not in ("fifo", "tap", "rpcap"):
            raise ValueError(f"output_mode invalide : {self.output_mode!r} (choix : fifo, tap, rpcap)")
        if self.output_mode == "tap" and not self.tap_interface:
            raise ValueError("tap_interface requis quand output_mode == 'tap'")
        if self.transfer_mode not in ("scp", "sshfs"):
            raise ValueError(f"transfer_mode invalide : {self.transfer_mode!r} (choix : scp, sshfs)")
        if self.tap_pace_max_gap_seconds <= 0:
            raise ValueError("tap_pace_max_gap_seconds doit être strictement positif")
        if self.capture_direction not in ("inbound", "outbound", "bidirection"):
            raise ValueError(
                f"capture_direction invalide : {self.capture_direction!r} (choix : inbound, outbound, bidirection)"
            )

    def resolve_default_mount_point(self) -> None:
        """Fixe mount_point à './<switch_ip>' si l'utilisateur a laissé le défaut vide."""
        if not self.mount_point or self.mount_point == "./mount":
            self.mount_point = f"./{self.switch_ip}"


# --------------------------------------------------------------------- #
# Modèles de capture réutilisables (YAML, sans mot de passe)
# --------------------------------------------------------------------- #
#
# Un "modèle" est un sous-ensemble des champs de Config, sérialisé en YAML
# dans un dossier dédié (par défaut ./models), permettant de retrouver
# rapidement les réglages d'un site donné sans ressaisir tout le
# formulaire. `ssh_password` est explicitement exclu à chaque étape
# (sérialisation ET désérialisation) : un modèle ne contient jamais de
# secret, y compris si un dict contenant `ssh_password` lui est passé par
# erreur (voir `template_dict_to_config_kwargs`).

TEMPLATE_EXCLUDED_FIELDS = {
    "ssh_password",
    # Réglages devenus globaux à l'outil, retirés du formulaire de capture
    # principal au profit de la page Préférences GTK4 (menu hamburger,
    # voir PREFERENCES_FIELDS plus bas et features.md, point 1 « Menu et
    # préférences ») : ce ne sont plus des réglages "par capture", un
    # modèle de capture réutilisable n'a donc plus à les embarquer.
    "slot",
    "model",
    "feature_bin_path",
}

_TEMPLATE_FIELDS = {f.name for f in fields(Config) if f.init} - TEMPLATE_EXCLUDED_FIELDS

_FORBIDDEN_TEMPLATE_CHARS = ("/", "\\", "\0")


def sanitize_template_name(name: str) -> str:
    """Valide/normalise un nom de modèle fourni par l'utilisateur.

    Accepte les accents et la ponctuation courante (nom libre, ex: « labo
    5130 - client »), rejette uniquement ce qui permettrait de sortir du
    dossier `models/` (séparateurs de chemin) ou un nom vide.

    Args:
        name: nom saisi, utilisé ensuite comme nom de fichier `<nom>.yaml`.

    Returns:
        Le nom nettoyé (espaces en début/fin retirés).

    Raises:
        ValueError: si le nom est vide, ou contient un séparateur de
            chemin (`/`, `\\`) — protection contre la traversée de
            dossier, ex: "../../etc/passwd".
    """
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Nom de modèle vide")
    if any(c in cleaned for c in _FORBIDDEN_TEMPLATE_CHARS):
        raise ValueError(f"Nom de modèle invalide : {cleaned!r} (les séparateurs de chemin '/' et '\\' sont interdits)")
    return cleaned


def config_to_template_dict(cfg: Config) -> dict:
    """Extrait d'un Config les champs à sérialiser dans un modèle.

    Args:
        cfg: configuration source (déjà validée ou non).

    Returns:
        Un dict des champs `init=True` de Config, `ssh_password` exclu.
    """
    return {name: getattr(cfg, name) for name in _TEMPLATE_FIELDS}


def template_dict_to_config_kwargs(data: dict) -> dict:
    """Filtre un dict (chargé depuis un YAML, ou construit à la main) aux

    seuls champs valides d'un modèle de capture.

    Args:
        data: dict brut, potentiellement avec des clés inconnues ou
            `ssh_password` (ex: si le formulaire entier est passé par
            erreur) — toutes deux sont silencieusement écartées.

    Returns:
        Un dict ne contenant que des clés parmi les champs `init=True` de
        Config, `ssh_password` toujours exclu.
    """
    return {k: v for k, v in (data or {}).items() if k in _TEMPLATE_FIELDS}


def list_capture_templates(models_dir: str | Path) -> list[str]:
    """Liste les modèles de capture disponibles dans un dossier.

    Args:
        models_dir: dossier contenant les fichiers `<nom>.yaml`.

    Returns:
        Les noms de modèles (sans extension `.yaml`), triés par ordre
        alphabétique. Liste vide si le dossier n'existe pas encore.
    """
    directory = Path(models_dir)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.yaml"))


def save_capture_template(models_dir: str | Path, name: str, data: dict) -> Path:
    """Enregistre un dict de configuration comme modèle YAML réutilisable.

    Args:
        models_dir: dossier de destination (créé si absent).
        name: nom du modèle (voir `sanitize_template_name`), utilisé comme
            nom de fichier.
        data: valeurs à enregistrer (typiquement le retour de
            `config_to_template_dict`, ou un dict équivalent construit à
            la main depuis un formulaire) — filtré par
            `template_dict_to_config_kwargs` avant écriture, donc
            `ssh_password` n'est **jamais** écrit sur disque même s'il est
            présent dans `data`.

    Returns:
        Le chemin du fichier YAML écrit.

    Raises:
        ValueError: si `name` est invalide.
    """
    import yaml

    clean_name = sanitize_template_name(name)
    directory = Path(models_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{clean_name}.yaml"
    payload = template_dict_to_config_kwargs(data)
    with open(target, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=True, allow_unicode=True)
    logger.info("modèle de capture enregistré | {} -> {}", clean_name, target)
    return target


def load_capture_template(models_dir: str | Path, name: str) -> dict:
    """Charge un modèle de capture YAML et renvoie des kwargs prêts pour Config.

    Args:
        models_dir: dossier contenant les modèles.
        name: nom du modèle (sans extension `.yaml`).

    Returns:
        Un dict filtré (voir `template_dict_to_config_kwargs`), sans
        `ssh_password` — à compléter avec le mot de passe saisi séparément
        par l'utilisateur avant de construire un `Config`.

    Raises:
        FileNotFoundError: si le modèle n'existe pas.
    """
    import yaml

    target = Path(models_dir) / f"{name}.yaml"
    if not target.is_file():
        raise FileNotFoundError(f"Modèle introuvable : {target}")
    with open(target, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return template_dict_to_config_kwargs(raw)


# --------------------------------------------------------------------- #
# Préférences GUI persistées (config.yaml, page Préférences GTK4)
# --------------------------------------------------------------------- #
#
# Sous-ensemble restreint de réglages, retirés du formulaire de capture
# principal (features.md, point 1 « Menu et préférences ») car ce sont des
# réglages globaux à l'outil plutôt que propres à UNE capture donnée :
# slot IRF/châssis, modèle forcé, .bin forcé, plus `keepass_path` (jamais
# un champ de `Config`, voir plus haut, mais un réglage transversal qui se
# ressaisissait jusqu'ici à chaque lancement, faute de page où le
# persister). Chargés au démarrage de la fenêtre GTK4, modifiables
# uniquement depuis la page Préférences (menu hamburger), enregistrés dans
# `config.yaml` après un clic explicite sur « Enregistrer » — jamais
# écrits ailleurs, jamais automatiquement.
#
# Volontairement PAS l'utilisateur SSH par défaut / le dépôt `.bin` / NTP /
# « Sortie live » : ces réglages, un temps envisagés pour cette page (voir
# demande d'origine du 26/08/2026), sont restés dans le formulaire
# principal lors des sessions du 28/08/2026 (câblage direct de
# `hide_capture_traffic`/`capture_direction`/`archive_as_pcapng`/
# `tap_launch_wireshark`, puis choix documenté de ne pas aller plus loin —
# voir CLAUDE.md) : ne pas les déplacer ici sans revisiter ce choix.
#
# `config_path` n'est volontairement PAS fixé en dur à un seul emplacement
# ici : c'est l'appelant (GTK4) qui décide du chemin (voir
# `DEFAULT_PREFS_CONFIG_PATH` dans `switch_capture_gtk.py`, `./config.yaml`
# par défaut — même convention "relatif au dossier de lancement" que
# `spool_dir`/`mount_point`/`DEFAULT_MODELS_DIR`). Choix délibéré de
# réutiliser le même nom de fichier que celui documenté pour
# `switch-capture capture --config config.yaml` (voir
# `docs/config.yaml.example`) : les fonctions ci-dessous ne touchent
# jamais qu'aux clés de PREFERENCES_FIELDS et préservent explicitement
# toute autre clé déjà présente (switch_ip, ssh_user, capture_interface…)
# pour rester compatibles avec un fichier déjà utilisé côté CLI.

PREFERENCES_FIELDS: tuple[str, ...] = ("slot", "model", "feature_bin_path", "keepass_path")


def load_gui_preferences(config_path: str | Path) -> dict:
    """Charge les préférences GUI depuis un fichier config.yaml.

    Lecture seule : ne modifie jamais le fichier. Ne lit que les clés de
    `PREFERENCES_FIELDS` — toute autre clé éventuellement présente
    (switch_ip, ssh_user, capture_interface... utilisées par ailleurs via
    `switch-capture capture --config`) est simplement ignorée.

    Args:
        config_path: chemin du fichier config.yaml. Peut ne pas exister
            (rien n'a encore été enregistré depuis la page Préférences).

    Returns:
        Un dict ne contenant que les clés de `PREFERENCES_FIELDS`
        effectivement présentes dans le fichier — dict vide si le fichier
        n'existe pas encore, ou si aucune des clés gérées n'y figure.
    """
    import yaml

    path = Path(config_path)
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return {key: raw[key] for key in PREFERENCES_FIELDS if key in raw}


def save_gui_preferences(config_path: str | Path, data: dict) -> Path:
    """Enregistre les préférences GUI dans config.yaml, **en fusion**.

    Lit d'abord le fichier existant s'il y en a un et préserve TOUTES ses
    clés, y compris celles hors `PREFERENCES_FIELDS` (ex: switch_ip/
    ssh_user/capture_interface d'un usage `switch-capture capture
    --config` sur ce même fichier) : ne met à jour que les clés de
    `PREFERENCES_FIELDS` présentes dans `data`, jamais un écrasement
    complet du fichier. Une valeur `None`/vide (`""`) dans `data` retire la
    clé du fichier plutôt que d'y écrire un `null`/une chaîne vide — le
    réglage redevient "non défini", comme s'il n'avait jamais été
    enregistré (ex: modèle remis sur "Auto").

    Args:
        config_path: chemin du fichier config.yaml (créé si absent, dossier
            parent créé si besoin).
        data: dict des préférences à enregistrer — seules les clés de
            `PREFERENCES_FIELDS` sont prises en compte, le reste est
            ignoré (protection si le formulaire entier était passé par
            erreur, même principe que `template_dict_to_config_kwargs`).

    Returns:
        Le chemin du fichier écrit.
    """
    import yaml

    path = Path(config_path)
    existing: dict = {}
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}

    updated_keys = [key for key in PREFERENCES_FIELDS if key in data]
    for key in updated_keys:
        value = data[key]
        if value in (None, ""):
            existing.pop(key, None)
        else:
            existing[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(existing, f, sort_keys=True, allow_unicode=True)
    logger.info("préférences GUI enregistrées | {} -> {}", updated_keys, path)
    return path


# --------------------------------------------------------------------- #
# Trousseau système (libsecret/GNOME Keyring, via le module `keyring`)
# --------------------------------------------------------------------- #
#
# Mémorise le mot de passe SSH entre deux lancements sans le stocker en
# clair sur disque (contrairement à un modèle de capture, voir section
# ci-dessus, qui exclut délibérément `ssh_password`) — piste listée dans
# CLAUDE.md (« Pistes d'amélioration envisagées »), désormais traitée.
# `keyring` choisit automatiquement le meilleur backend disponible sur la
# plateforme (GNOME Keyring/libsecret sous Linux via le service D-Bus
# "Secret Service", identique à l'écosystème déjà utilisé pour GCM) ;
# aucun backend écrivant en clair n'est forcé ici.
#
# Dépendance strictement optionnelle (voir import en tête de fichier) :
# son absence, ou l'absence d'un trousseau système déverrouillé (headless
# sans session de bureau, par exemple), ne doit jamais empêcher un usage
# CLI avec `--ssh-password`/`SWITCH_SSH_PASSWORD` — seule la mémorisation
# est désactivée, silencieusement pour la lecture, avec une exception
# explicite pour l'écriture (l'appelant a demandé une action précise,
# elle ne doit pas échouer sans un message clair).

KEYRING_SERVICE_NAME = "switch-capture"

KEYRING_AVAILABLE = keyring is not None


def keyring_account_id(switch_ip: str, ssh_user: str) -> str:
    """Construit l'identifiant de compte utilisé comme clé dans le trousseau.

    Fonction pure, testable sans trousseau réel — une entrée par couple
    switch/utilisateur, pour ne pas mélanger les mots de passe de deux
    switches différents ou de deux comptes sur le même switch.

    Args:
        switch_ip: adresse IP (ou nom d'hôte) du switch.
        ssh_user: nom d'utilisateur SSH.

    Returns:
        L'identifiant de compte, ex. ``"admin@10.0.0.1"``.
    """
    return f"{ssh_user}@{switch_ip}"


def save_ssh_password_to_keyring(switch_ip: str, ssh_user: str, password: str) -> None:
    """Enregistre un mot de passe SSH dans le trousseau système.

    Args:
        switch_ip: adresse IP (ou nom d'hôte) du switch.
        ssh_user: nom d'utilisateur SSH.
        password: mot de passe à mémoriser.

    Raises:
        RuntimeError: si le module `keyring` n'est pas installé, ou si le
            trousseau système refuse l'écriture (verrouillé, service
            Secret Service absent, etc.) — jamais avalée silencieusement :
            l'utilisateur a explicitement demandé à mémoriser ce mot de
            passe, il doit savoir si ça a échoué.
    """
    if not KEYRING_AVAILABLE:
        raise RuntimeError(
            "Le module 'keyring' n'est pas installé — impossible de mémoriser le mot de passe. "
            "Installez-le (paquet système python3-keyring, ou 'pip install keyring')."
        )
    account = keyring_account_id(switch_ip, ssh_user)
    try:
        keyring.set_password(KEYRING_SERVICE_NAME, account, password)
    except keyring.errors.KeyringError as exc:
        raise RuntimeError(f"Échec de l'écriture dans le trousseau système : {exc}") from exc
    logger.info("mot de passe SSH mémorisé dans le trousseau système | {}", account)


def load_ssh_password_from_keyring(switch_ip: str, ssh_user: str) -> str | None:
    """Relit un mot de passe SSH précédemment mémorisé dans le trousseau.

    Args:
        switch_ip: adresse IP (ou nom d'hôte) du switch.
        ssh_user: nom d'utilisateur SSH.

    Returns:
        Le mot de passe mémorisé, ou `None` si absent, si `keyring` n'est
        pas installé, ou si le trousseau système est inaccessible
        (verrouillé, pas de session de bureau...). Volontairement
        silencieux dans ces trois derniers cas : une lecture qui échoue ne
        doit jamais bloquer un usage CLI disposant d'un autre moyen de
        fournir le mot de passe (--ssh-password, SWITCH_SSH_PASSWORD).
    """
    if not KEYRING_AVAILABLE:
        return None
    account = keyring_account_id(switch_ip, ssh_user)
    try:
        return keyring.get_password(KEYRING_SERVICE_NAME, account)
    except keyring.errors.KeyringError:
        return None


def delete_ssh_password_from_keyring(switch_ip: str, ssh_user: str) -> bool:
    """Supprime un mot de passe SSH précédemment mémorisé dans le trousseau.

    Opération idempotente : appeler cette fonction sur un compte qui n'a
    rien de mémorisé (ou sans trousseau disponible) n'est pas une erreur.

    Args:
        switch_ip: adresse IP (ou nom d'hôte) du switch.
        ssh_user: nom d'utilisateur SSH.

    Returns:
        `True` si une entrée a effectivement été supprimée, `False` si
        rien n'était mémorisé ou si `keyring`/le trousseau système est
        indisponible.
    """
    if not KEYRING_AVAILABLE:
        return False
    account = keyring_account_id(switch_ip, ssh_user)
    try:
        keyring.delete_password(KEYRING_SERVICE_NAME, account)
        logger.info("mot de passe SSH retiré du trousseau système | {}", account)
        return True
    except keyring.errors.KeyringError:
        return False


# --------------------------------------------------------------------- #
# Repli KeePass (fichier .kdbx) si aucun trousseau système n'est installé
# --------------------------------------------------------------------- #
#
# Traite la partie « repli sur un fichier KeePass si aucun trousseau système
# n'est installé » de la piste "Trousseau système" listée dans features.md
# (section « Menu et préférences », point 4). N'intervient qu'en dernier
# recours, quand `keyring` (ci-dessus) n'a rien pu fournir — jamais à la
# place d'un trousseau système fonctionnel.
#
# Portée volontairement restreinte : la base `.kdbx` doit déjà exister (créée
# au préalable par l'utilisateur avec KeePassXC ou équivalent) — cette
# fonction ne crée jamais de nouvelle base. Le mot de passe maître de cette
# base n'est, comme `ssh_password`, jamais écrit sur disque par cet outil ;
# il doit être fourni via `SWITCH_CAPTURE_KEEPASS_PASSWORD` (même logique que
# `SWITCH_SSH_PASSWORD`).

KEEPASS_AVAILABLE = PyKeePass is not None


def _open_keepass_db(keepass_path: str, keepass_master_password: str, keepass_keyfile: str | None = None) -> PyKeePass:
    """Ouvre la base KeePass, avec des erreurs explicites plutôt qu'un plantage brut.

    Args:
        keepass_path: chemin du fichier `.kdbx` (doit déjà exister).
        keepass_master_password: mot de passe maître de la base.
        keepass_keyfile: chemin d'un fichier de clé KeePass additionnel, ou
            `None` si la base n'utilise que le mot de passe maître (cas le
            plus courant — confirmé contre la documentation pykeepass à jour
            via Context7, session 56 : `keyfile` est un paramètre optionnel
            de `PyKeePass.__init__`, combinable avec `password`).

    Returns:
        L'objet `PyKeePass` ouvert.

    Raises:
        RuntimeError: fichier absent, mot de passe maître incorrect, ou toute
            autre erreur d'ouverture — jamais l'exception brute de pykeepass.
    """
    if not Path(keepass_path).is_file():
        raise RuntimeError(
            f"Fichier KeePass introuvable : {keepass_path} — cet outil n'en crée jamais, "
            "créez la base au préalable (ex. avec KeePassXC)."
        )
    try:
        return PyKeePass(keepass_path, password=keepass_master_password, keyfile=keepass_keyfile)
    except CredentialsError as exc:
        raise RuntimeError(f"Mot de passe maître KeePass incorrect pour {keepass_path}") from exc
    except Exception as exc:  # format de fichier invalide, base corrompue, etc.
        raise RuntimeError(f"Impossible d'ouvrir le fichier KeePass {keepass_path} : {exc}") from exc


def save_ssh_password_to_keepass(
    switch_ip: str,
    ssh_user: str,
    password: str,
    keepass_path: str,
    keepass_master_password: str,
    keepass_keyfile: str | None = None,
) -> None:
    """Enregistre (ou met à jour) un mot de passe SSH dans une base KeePass locale.

    Une entrée par couple switch/utilisateur, même identifiant que le
    trousseau système (`keyring_account_id`) utilisé comme titre de l'entrée,
    pour rester cohérent entre les deux mécanismes.

    Args:
        switch_ip: adresse IP (ou nom d'hôte) du switch.
        ssh_user: nom d'utilisateur SSH.
        password: mot de passe à mémoriser.
        keepass_path: chemin du fichier `.kdbx` (doit déjà exister).
        keepass_master_password: mot de passe maître de la base.
        keepass_keyfile: chemin d'un fichier de clé KeePass additionnel, ou
            `None` (voir `_open_keepass_db`).

    Raises:
        RuntimeError: si `pykeepass` n'est pas installé, si la base ne peut
            pas être ouverte (voir `_open_keepass_db`), ou si l'écriture
            échoue — comme pour le trousseau système, jamais avalée
            silencieusement : l'utilisateur a explicitement demandé cette
            mémorisation.
    """
    if not KEEPASS_AVAILABLE:
        raise RuntimeError(
            "Le module 'pykeepass' n'est pas installé — impossible d'utiliser le repli KeePass. "
            "Installez-le ('pip install pykeepass')."
        )
    account = keyring_account_id(switch_ip, ssh_user)
    kp = _open_keepass_db(keepass_path, keepass_master_password, keepass_keyfile)
    try:
        entry = kp.find_entries(title=account, first=True)
        if entry is not None:
            entry.username = ssh_user
            entry.password = password
        else:
            kp.add_entry(kp.root_group, account, ssh_user, password)
        kp.save()
    except Exception as exc:
        raise RuntimeError(f"Échec de l'écriture dans le fichier KeePass {keepass_path} : {exc}") from exc
    logger.info("mot de passe SSH mémorisé dans le fichier KeePass | {} | {}", keepass_path, account)


def load_ssh_password_from_keepass(
    switch_ip: str,
    ssh_user: str,
    keepass_path: str | None,
    keepass_master_password: str | None,
    keepass_keyfile: str | None = None,
) -> str | None:
    """Relit un mot de passe SSH précédemment mémorisé dans une base KeePass locale.

    Args:
        switch_ip: adresse IP (ou nom d'hôte) du switch.
        ssh_user: nom d'utilisateur SSH.
        keepass_path: chemin du fichier `.kdbx`, ou `None`/vide (repli désactivé).
        keepass_master_password: mot de passe maître de la base, ou `None`/vide.
        keepass_keyfile: chemin d'un fichier de clé KeePass additionnel, ou
            `None` (voir `_open_keepass_db`).

    Returns:
        Le mot de passe mémorisé, ou `None` si absent, si `pykeepass` n'est
        pas installé, si `keepass_path`/`keepass_master_password` ne sont pas
        fournis, ou si la base est inaccessible (fichier absent, mot de passe
        maître incorrect...). Volontairement silencieux dans tous ces cas,
        même principe que `load_ssh_password_from_keyring` : une lecture de
        repli qui échoue ne doit jamais bloquer un usage disposant d'un autre
        moyen de fournir le mot de passe.
    """
    if not KEEPASS_AVAILABLE or not keepass_path or not keepass_master_password:
        return None
    account = keyring_account_id(switch_ip, ssh_user)
    try:
        kp = _open_keepass_db(keepass_path, keepass_master_password, keepass_keyfile)
        entry = kp.find_entries(title=account, first=True)
    except RuntimeError:
        return None
    return entry.password if entry is not None else None


def delete_ssh_password_from_keepass(
    switch_ip: str,
    ssh_user: str,
    keepass_path: str | None,
    keepass_master_password: str | None,
    keepass_keyfile: str | None = None,
) -> bool:
    """Supprime un mot de passe SSH précédemment mémorisé dans une base KeePass locale.

    Opération idempotente, même principe que `delete_ssh_password_from_keyring`.

    Args:
        switch_ip: adresse IP (ou nom d'hôte) du switch.
        ssh_user: nom d'utilisateur SSH.
        keepass_path: chemin du fichier `.kdbx`, ou `None`/vide (repli désactivé).
        keepass_master_password: mot de passe maître de la base, ou `None`/vide.
        keepass_keyfile: chemin d'un fichier de clé KeePass additionnel, ou
            `None` (voir `_open_keepass_db`).

    Returns:
        `True` si une entrée a effectivement été supprimée, `False` si rien
        n'était mémorisé ou si le repli KeePass est indisponible/inaccessible.
    """
    if not KEEPASS_AVAILABLE or not keepass_path or not keepass_master_password:
        return False
    account = keyring_account_id(switch_ip, ssh_user)
    try:
        kp = _open_keepass_db(keepass_path, keepass_master_password, keepass_keyfile)
        entry = kp.find_entries(title=account, first=True)
        if entry is None:
            return False
        kp.delete_entry(entry)
        kp.save()
    except RuntimeError:
        return False
    logger.info("mot de passe SSH retiré du fichier KeePass | {} | {}", keepass_path, account)
    return True


def write_capture_metadata(cfg: Config, state: SharedState) -> None:
    """Écrit un sidecar JSON avec les métadonnées de la capture en cours.

    Destiné à être consommé par un outil tiers de comparaison de traces
    (hors périmètre de switch-capture) : label du point de capture,
    switch/interface/filtre utilisés, et statut de synchronisation NTP —
    sans quoi les timestamps entre plusieurs traces d'un même trafic prises
    à des points différents (client/routeur/serveur) ne sont pas fiablement
    comparables entre elles.

    Args:
        cfg: configuration de la capture en cours.
        state: état partagé (statut NTP, modèle détecté, horodatage de
            démarrage).
    """
    target_dir = Path(cfg.archive_dir or cfg.spool_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "capture_label": cfg.capture_label,
        "switch_ip": cfg.switch_ip,
        "capture_interface": cfg.capture_interface,
        "capture_filter": cfg.capture_filter,
        "model": state.model,
        "started_at_epoch": state.started_at,
        "started_at_iso": (
            time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(state.started_at)) if state.started_at else None
        ),
        "ntp_synced": state.ntp_synced,
        "ntp_detail": state.ntp_detail,
        "output_mode": cfg.output_mode,
        "tap_interface": cfg.tap_interface,
    }
    meta_path = target_dir / "capture-meta.json"
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("write_capture_metadata | écrit={path}", path=meta_path)


# --------------------------------------------------------------------------- #
# Débit de transfert moyen en direct
# --------------------------------------------------------------------------- #
# Piste listée dans CLAUDE.md ("Compteur de paquets/débit en direct dans
# l'UI"). Portée volontairement réduite par rapport à l'idée d'origine : le
# texte de CLAUDE.md envisageait de parser la sortie CLI brute de
# `packet-capture` pendant la capture (`conn.read_channel()`, actuellement
# seulement loguée en `trace`, voir `_run_capture_blocking_local`) — mais le
# format exact de cette sortie n'a jamais été vérifié contre un switch réel
# dans ce dépôt, et l'écrire "à l'aveugle" contredirait la rigueur du reste
# du projet (voir méthodologie de test dans CLAUDE.md : rien n'est marqué
# fait sans validation réelle). `SharedState.bytes_merged`/`started_at`,
# eux, sont déjà alimentés par `CaptureRotationThread` à partir de tailles de
# fichier réellement rapatriées (SCP/sshfs) — donc un débit *moyen* calculé
# à partir de ces deux compteurs déjà fiables, plutôt qu'un débit
# instantané extrait du CLI switch, est la version de cette fonctionnalité
# qui peut être implémentée et testée honnêtement dans cette session.
def compute_average_throughput(
    bytes_merged: int,
    started_at: float | None,
    now: float,
) -> float | None:
    """Débit moyen (octets/s) depuis le début de la capture.

    Args:
        bytes_merged: total d'octets rapatriés jusqu'ici (`SharedState.
            bytes_merged`).
        started_at: epoch du démarrage de la capture (`SharedState.
            started_at`), ou `None` si la capture n'a pas encore démarré.
        now: epoch courant (paramètre explicite plutôt que `time.time()`
            interne, pour que la fonction reste pure et testable sans
            monkeypatcher l'horloge).

    Returns:
        Le débit moyen en octets/s, ou `None` si non calculable (capture
        pas démarrée, horodatage incohérent, ou écart de temps nul/négatif
        — horloge locale imprécise plutôt qu'une division par zéro ou un
        débit négatif trompeur).
    """
    if started_at is None:
        return None
    elapsed = now - started_at
    if elapsed <= 0:
        return None
    return bytes_merged / elapsed


def format_transfer_rate(bytes_per_second: float | None) -> str:
    """Formate un débit en octets/s en chaîne lisible (o/s, Ko/s, Mo/s, Go/s).

    Args:
        bytes_per_second: débit en octets/s, typiquement la sortie de
            `compute_average_throughput` — `None` accepté directement (pas
            encore calculable) pour que l'appelant n'ait pas à tester le
            cas à part.

    Returns:
        Une chaîne prête à afficher, par ex. `"128,0 Ko/s"`. `"—"` si
        `bytes_per_second` est `None`.
    """
    if bytes_per_second is None:
        return "—"
    if bytes_per_second < 0:
        bytes_per_second = 0.0
    value = float(bytes_per_second)
    if value < 1024:
        return f"{value:.0f} o/s"
    if value < 1024**2:
        return f"{value / 1024:.1f} Ko/s"
    if value < 1024**3:
        return f"{value / 1024**2:.1f} Mo/s"
    return f"{value / 1024**3:.1f} Go/s"


@dataclass(frozen=True)
class ScpProgress:
    """Palier de progression d'un transfert SCP (issue #70)."""

    context: str
    name: str
    percent: int
    sent: int
    size: int


def _format_bytes(num_bytes: int) -> str:
    """Taille lisible, mêmes paliers que `format_transfer_rate` (sans « /s »)."""
    return format_transfer_rate(num_bytes).removesuffix("/s")


def format_scp_progress(progress: ScpProgress | None) -> str:
    """Texte de la page « Journal » pour un palier SCP (vide sans palier).

    Exemple : ``"SCP cap_00003.pcap : 40 % (4.0 Mo / 10.0 Mo)"``.
    """
    if progress is None:
        return ""
    return (
        f"SCP {progress.name} : {progress.percent} % ({_format_bytes(progress.sent)} / {_format_bytes(progress.size)})"
    )


@dataclass
class SharedState:
    """État partagé entre les threads de préparation/capture et de rotation."""

    stop_event: threading.Event = field(default_factory=threading.Event)
    capture_started: threading.Event = field(default_factory=threading.Event)
    feature_already_installed: bool = False
    needs_feature_install: bool = True
    model: str | None = None

    # Progression, consultée par l'UI (page "Travail" de la GUI, ou tout
    # autre consommateur) — mise à jour par CaptureRotationThread au fil de
    # la capture. Simples compteurs, pas de verrou : lectures/écritures
    # d'entiers/floats sont atomiques sous le GIL, suffisant pour de
    # l'affichage de progression (pas une garantie de cohérence forte).
    started_at: float | None = None
    files_merged: int = 0
    bytes_merged: int = 0
    last_activity: float | None = None
    last_file_name: str | None = None
    # Dernier palier de progression SCP atteint (issue #70) : rapatriement
    # d'un fichier de rotation ou envoi de la feature. Remplacé d'un bloc
    # (un tuple immuable, affectation atomique sous le GIL) par le callback
    # de `make_scp_progress_logger(on_progress=...)`, lu par la page
    # « Journal » à chaque rafraîchissement — jamais d'appel GTK depuis le
    # thread de transfert. None tant qu'aucun palier n'est atteint.
    scp_progress: ScpProgress | None = None

    # NTP : renseigné par _ensure_ntp(), consultable par l'UI et écrit dans
    # le sidecar de métadonnées (write_capture_metadata) — important pour
    # toute comparaison de traces prises à des points différents (client/
    # routeur/serveur) : sans horloges synchronisées entre les switches, les
    # timestamps ne sont pas comparables entre les traces.
    ntp_synced: bool | None = None  # None = pas encore vérifié
    ntp_detail: str = ""


# --------------------------------------------------------------------------- #
# Mode dry run — inspection en lecture seule (`InspectConfig` + `inspect_switch`)
# --------------------------------------------------------------------------- #
@dataclass
class InspectConfig:
    """Paramètres de connexion + options du mode dry run (`inspect_switch`).

    Volontairement plus légère que `Config` (sur le même principe que
    `MirrorConfig`) : le mode dry run n'a besoin d'aucun des champs propres
    à une capture (interface, rotation, filtre, sortie...), donc pas de
    `capture_interface` obligatoire ici — contrairement à `Config`.

    Args:
        switch_ip: adresse IP ou nom du switch.
        ssh_user: compte RADIUS existant.
        ssh_password: mot de passe SSH. Si vide, lu depuis SWITCH_SSH_PASSWORD.
        model: force le profil matériel au lieu de l'auto-détection.
        feature_bin_path: si fourni, seul son nom de fichier est utilisé
            pour vérifier sa présence dans 'display install active'
            (prioritaire sur feature_bin_dir, comme dans Config).
        feature_bin_dir: racine du dépôt local de .bin, pour résoudre le
            nom de fichier attendu si feature_bin_path est vide.
        transfer_mode: "scp" (défaut) ou "sshfs" — détermine quel service
            de transfert est vérifié ('scp server enable' vs 'sftp server
            enable').
    """

    switch_ip: str = ""
    ssh_user: str = ""
    ssh_password: str = ""
    model: str | None = None
    feature_bin_path: str | None = None
    feature_bin_dir: str = "./feature-bin"
    transfer_mode: str = "scp"

    def __post_init__(self) -> None:
        """Normalise et valide les champs obligatoires (mêmes règles que Config, sans capture_interface)."""
        if not self.ssh_password:
            self.ssh_password = os.environ.get("SWITCH_SSH_PASSWORD", "")
        missing = [n for n, v in (("switch_ip", self.switch_ip), ("ssh_user", self.ssh_user)) if not v]
        if missing:
            raise ValueError(f"Champs obligatoires manquants : {', '.join(missing)}")
        if not self.ssh_password:
            raise ValueError("Mot de passe SSH manquant (champ 'ssh_password' ou SWITCH_SSH_PASSWORD)")
        if self.model and self.model not in MODEL_PROFILES:
            raise ValueError(f"Modèle invalide : {self.model!r} (choix : {', '.join(sorted(MODEL_PROFILES))})")
        if self.transfer_mode not in ("scp", "sshfs"):
            raise ValueError(f"transfer_mode invalide : {self.transfer_mode!r} (choix : scp, sshfs)")


# Intervalle (en secondes) des paquets de maintien de connexion SSH envoyés
# par netmiko (paramètre natif `keepalive` de `ConnectHandler`, désactivé
# par défaut côté netmiko : `keepalive=0`). Vise en particulier la
# connexion de polling `_poll_conn` (`SetupAndCaptureThread`), qui peut
# rester ouverte bien plus longtemps qu'une connexion SCP par fichier
# (déjà réouverte à chaque transfert depuis la correction du 23/08/2026)
# — même famille de risque que ce bug SCP déjà corrigé (le switch semble
# fermer les sessions SSH inactives). Valeur choisie par analogie avec
# `ServerAliveInterval` d'OpenSSH (30 s, valeur usuelle contre des
# pare-feux/NAT à état qui coupent les connexions TCP inactives) — non
# vérifiée empiriquement contre un switch réel (voir features-backlog.md,
# section « Fait », entrée du 12/09/2026, pour le détail de ce choix).
NETMIKO_KEEPALIVE_SECONDS = 30


def connect_switch(cfg: Config | InspectConfig):
    """Ouvre une session SSH netmiko vers le switch (device_type hp_comware).

    Args:
        cfg: configuration de la session (`Config` ou `InspectConfig`), doit
            exposer switch_ip/ssh_user/ssh_password.

    Returns:
        Un objet ConnectHandler netmiko connecté, avec des paquets de
        maintien de connexion SSH envoyés toutes les
        `NETMIKO_KEEPALIVE_SECONDS` secondes (paramètre natif `keepalive`
        de netmiko — `0` par défaut côté netmiko, c'est-à-dire désactivé).

    Raises:
        RuntimeError: si netmiko n'est pas installé.
    """
    if ConnectHandler is None:
        raise RuntimeError("netmiko manquant : pip install netmiko")
    device = {
        "device_type": "hp_comware",
        "host": cfg.switch_ip,
        "username": cfg.ssh_user,
        "password": cfg.ssh_password,
        "fast_cli": False,
        "keepalive": NETMIKO_KEEPALIVE_SECONDS,
    }
    logger.info("connect_switch | host={host}", host=cfg.switch_ip)
    return ConnectHandler(**device)


def inspect_switch(cfg: InspectConfig) -> dict:
    """Interroge un switch en lecture seule : modèle, version, features actives, NTP.

    Mode dry run : uniquement des commandes 'display', jamais de
    `config_mode()` ni de commande de configuration — contrairement à
    `SetupAndCaptureThread._prepare_switch`, qui peut activer scp/sftp
    server ou configurer NTP au passage si besoin. Utile avant une première
    intervention sur un switch distant sans accès physique : on sait ce qui
    s'y trouve avant de risquer d'y toucher.

    Args:
        cfg: paramètres de connexion + options d'inspection.

    Returns:
        dict avec les clés :
            model (str | None), model_known (bool), model_notes (str),
            software_version (str | None),
            packet_capture_support ("installable" | "unsupported" |
                "builtin" | None si modèle non reconnu),
            feature_bin_checked (str | None, nom de fichier vérifié),
            feature_already_active (bool | None, None si non pertinent
                pour ce modèle ou nom de .bin non résolu),
            packet_capture_summary (str | None, modèle "builtin" seulement),
            transfer_service_enabled (bool),
            ntp_synced (bool), ntp_detail (str),
            rpcap_status_raw (str | None, sortie brute non interprétée de
                `display packet-capture status` — la disponibilité réelle
                de `packet-capture remote`/rpcap varie selon modèle/version
                et n'est pas garantie par `packet_capture_support` ; voir
                features.md, section « Autres limites connues ». Volontairement
                non parsé en booléen faute d'un exemple de sortie réelle
                vérifié contre un switch physique — affiché tel quel pour que
                l'utilisateur juge par lui-même. `None` si la commande ne
                renvoie rien (non reconnue par ce switch, ou modèle qui ne
                supporte pas cette commande)).

    Raises:
        Exception: toute erreur de connexion/commande SSH, laissée remonter
            à l'appelant (CLI ou GUI décident comment la reporter).
    """
    conn = connect_switch(cfg)
    try:
        report: dict = {
            "feature_bin_checked": None,
            "feature_already_active": None,
            "packet_capture_summary": None,
        }

        logger.debug("inspect | display version")
        version_output = conn.send_command("display version")
        model = cfg.model or detect_model(version_output)
        report["model"] = model
        report["model_known"] = bool(model) and model in MODEL_PROFILES
        report["software_version"] = detect_software_version(version_output)

        if report["model_known"]:
            profile = MODEL_PROFILES[model]
            report["packet_capture_support"] = profile["packet_capture"]
            report["model_notes"] = profile["notes"]
        else:
            report["packet_capture_support"] = None
            report["model_notes"] = ""

        if report["packet_capture_support"] == "installable":
            logger.debug("inspect | display install active")
            installed = conn.send_command("display install active")
            filename = Path(cfg.feature_bin_path).name if cfg.feature_bin_path else None
            if not filename:
                resolved = resolve_feature_bin(cfg.feature_bin_dir, model, report["software_version"])
                filename = resolved.name if resolved else None
            report["feature_bin_checked"] = filename
            report["feature_already_active"] = (filename in installed) if filename else None
        elif report["packet_capture_support"] == "builtin":
            # MSR4000
            logger.debug("inspect | packet-capture ?")
            summary = conn.send_command("packet-capture ?")
            if "local" in summary:
                cfg.packet_capture_cmd = "packet-capture local"
            report["packet_capture_summary"] = summary.strip()
            report["feature_already_active"] = True

        service_label = "scp" if cfg.transfer_mode == "scp" else "sftp"
        command = "scp server enable" if cfg.transfer_mode == "scp" else "sftp server enable"
        check_cmd = f"display current-configuration | include {service_label}"
        logger.debug("inspect | {cmd}", cmd=check_cmd)
        current_cfg = conn.send_command(check_cmd)
        report["transfer_service_enabled"] = command in current_cfg

        logger.debug("inspect | display ntp-service status")
        ntp_status = conn.send_command("display ntp-service status")
        report["ntp_synced"] = is_ntp_synchronized(ntp_status)
        report["ntp_detail"] = next((line.strip() for line in ntp_status.splitlines() if line.strip()), "")

        logger.debug("inspect | display packet-capture status")
        rpcap_status = conn.send_command("display packet-capture status")
        report["rpcap_status_raw"] = rpcap_status.strip() or None

        logger.info(
            "inspect | modèle={model} version={version} packet_capture={pc} feature_active={fa} "
            "transfert={ts} ntp={ntp} rpcap_status={rpcap}",
            model=report["model"] or "<inconnu>",
            version=report["software_version"] or "<inconnue>",
            pc=report["packet_capture_support"] or "<modèle non reconnu>",
            fa=report["feature_already_active"],
            ts=report["transfer_service_enabled"],
            ntp=report["ntp_synced"],
            rpcap="<vide>" if report["rpcap_status_raw"] is None else "<présente>",
        )
        return report
    finally:
        conn.disconnect()


def format_inspect_report(switch_ip: str, transfer_mode: str, report: dict) -> str:
    """Formate le rapport de `inspect_switch` en texte lisible, pour CLI et GUI.

    Fonction pure (aucun accès réseau) partagée par `switch-capture inspect`
    (print direct) et le bouton GTK "Inspecter (dry run)" (passé tel quel à
    la boîte de dialogue de résultat) — pour que les deux ne divergent
    jamais dans ce qu'ils rapportent.

    Args:
        switch_ip: IP du switch inspecté (pour l'en-tête).
        transfer_mode: "scp" ou "sshfs" (détermine le libellé affiché).
        report: dict retourné par `inspect_switch`.

    Returns:
        Texte multi-lignes prêt à afficher.
    """
    lines = [f"Switch : {switch_ip}"]

    model = report.get("model")
    if report.get("model_known"):
        lines.append(f"Modèle : {model}")
    elif model:
        lines.append(f"Modèle : {model} (non reconnu dans MODEL_PROFILES)")
    else:
        lines.append("Modèle : non détecté automatiquement (--model pour le forcer)")

    lines.append(f"Version logicielle : {report.get('software_version') or 'non détectée'}")

    support = report.get("packet_capture_support")
    notes = report.get("model_notes") or ""
    if support == "installable":
        active = report.get("feature_already_active")
        active_text = "oui" if active else "non" if active is False else "indéterminé"
        lines.append(f"packet-capture : à installer — {notes}")
        lines.append(f"  .bin vérifié : {report.get('feature_bin_checked') or '<non résolu>'}")
        lines.append(f"  déjà active : {active_text}")
    elif support == "builtin":
        lines.append(f"packet-capture : natif — {notes}")
        lines.append(f"  résumé : {report.get('packet_capture_summary') or '<vide>'}")
    elif support == "unsupported":
        lines.append(f"packet-capture : non supporté — {notes}")
    else:
        lines.append("packet-capture : indéterminé (modèle non reconnu)")

    service_label = "scp" if transfer_mode == "scp" else "sftp"
    enabled = report.get("transfer_service_enabled")
    lines.append(f"{service_label} server enable : {'oui' if enabled else 'non'}")

    ntp_synced = report.get("ntp_synced")
    ntp_detail = report.get("ntp_detail") or "<pas de détail>"
    lines.append(f"NTP synchronisé : {'oui' if ntp_synced else 'non'} ({ntp_detail})")

    rpcap_raw = report.get("rpcap_status_raw")
    lines.append(
        "Disponibilité rpcap (packet-capture remote) — non garantie selon "
        "modèle/version, sortie brute de `display packet-capture status` :"
    )
    if rpcap_raw:
        for status_line in rpcap_raw.splitlines():
            lines.append(f"  {status_line}")
    else:
        lines.append(
            "  <vide ou commande non reconnue par ce switch — à vérifier "
            "manuellement avant d'utiliser --output-mode rpcap>"
        )

    lines.append("")
    lines.append("Aucune modification n'a été effectuée sur ce switch (mode dry run).")
    return "\n".join(lines)


def format_pacing_analysis_report(pcap_file: Path, report: PacingGapAnalysis) -> str:
    """Formate un `PacingGapAnalysis` en texte lisible, pour `switch-capture analyze-pacing`.

    Fonction pure (aucun accès réseau/fichier au-delà de ce qui a déjà été
    lu par `analyze_pacing_gaps`) — même principe que `format_inspect_report` :
    séparer le calcul (testable en isolation) de la présentation.

    Args:
        pcap_file: fichier .pcap analysé (pour l'en-tête).
        report: résultat de `analyze_pacing_gaps`.

    Returns:
        Texte multi-lignes prêt à afficher.
    """
    lines = [f"Fichier : {pcap_file}"]
    lines.append(f"Trames : {report.frame_count}")
    lines.append(f"Durée de la capture d'origine : {report.capture_duration_seconds:.3f} s")

    if report.gap_count == 0:
        lines.append("Une seule trame (ou aucune) : pas d'écart inter-trames à analyser.")
        return "\n".join(lines)

    lines.append(f"Écarts inter-trames ({report.gap_count}) :")
    lines.append(f"  min    : {report.min_gap_seconds:.3f} s")
    lines.append(f"  médian : {report.median_gap_seconds:.3f} s")
    lines.append(f"  p90    : {report.p90_gap_seconds:.3f} s")
    lines.append(f"  p95    : {report.p95_gap_seconds:.3f} s")
    lines.append(f"  p99    : {report.p99_gap_seconds:.3f} s")
    lines.append(f"  max    : {report.max_gap_seconds:.3f} s")

    lines.append("")
    lines.append("Effet de différentes valeurs de --tap-pace-max-gap sur CE fichier :")
    for max_gap in sorted(report.candidate_effects):
        effect = report.candidate_effects[max_gap]
        lines.append(
            f"  {max_gap:>6.2f} s -> {effect.clamped_gap_count}/{report.gap_count} écarts "
            f"raccourcis ({effect.clamped_gap_fraction * 100:.1f} %), "
            f"rejeu total {effect.total_playback_seconds:.3f} s "
            f"(capture d'origine : {report.capture_duration_seconds:.3f} s)"
        )

    lines.append("")
    lines.append(
        "Rappel : ceci n'évalue que l'effet du plafonnement sur les écarts déjà "
        "présents dans ce fichier — pas la durée SCP de rapatriement elle-même, "
        "qui nécessite un switch réel (voir features.md, section « Pas fait »)."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Transfert SCP (mode "scp", par défaut — remplace le montage sshfs)
# --------------------------------------------------------------------------- #
# Connexion paramiko indépendante de la session netmiko utilisée pour les
# commandes CLI : SCP a besoin d'un canal dédié, pas du canal interactif
# déjà utilisé par send_command/send_command_timing.
def open_scp_ssh_client(cfg: Config):
    """Ouvre une connexion SSH paramiko dédiée aux transferts SCP.

    Args:
        cfg: configuration de la session (switch_ip/ssh_user/ssh_password).

    Returns:
        Un paramiko.SSHClient déjà connecté.

    Raises:
        RuntimeError: si paramiko/scp ne sont pas installés.
    """
    if paramiko is None or SCPClient is None:
        raise RuntimeError("paramiko/scp manquants : pip install paramiko scp")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        cfg.switch_ip,
        username=cfg.ssh_user,
        password=cfg.ssh_password,
        timeout=15,
        look_for_keys=False,
        allow_agent=False,
    )
    return client


def scp_get(
    ssh_client, remote_path: str, local_path: Path, progress_callback: Callable[[bytes, int, int], None] | None = None
) -> None:
    """Rapatrie un fichier du switch via SCP.

    Args:
        ssh_client: connexion paramiko déjà ouverte (`open_scp_ssh_client`).
        remote_path: chemin distant côté serveur SCP (racine = flash), ex:
            "/capture2_00001.pcap" — sans le préfixe "flash:" (syntaxe CLI
            Comware, pas SCP, voir _process_closed_file_scp).
        local_path: chemin local de destination.
        progress_callback: callback optionnel `(filename, size, sent) ->
            None` transmis tel quel à `SCPClient(progress=...)` (signature
            du paquet `scp`, confirmée contre son code source/README —
            `scp` n'étant pas indexé sur Context7, session 56), appelé à
            chaque bloc envoyé pendant le transfert. `None` par défaut
            (aucun changement de comportement pour les appelants existants).
            Voir `make_scp_progress_logger` pour une implémentation prête à
            l'emploi qui journalise sans spammer les logs.
    """
    with SCPClient(ssh_client.get_transport(), progress=progress_callback) as scp_client:
        scp_client.get(remote_path, str(local_path))


def scp_put(
    ssh_client, local_path: Path, remote_path: str, progress_callback: Callable[[bytes, int, int], None] | None = None
) -> None:
    """Pousse un fichier local vers le switch via SCP.

    Args:
        ssh_client: connexion paramiko déjà ouverte (`open_scp_ssh_client`).
        local_path: chemin du fichier local à envoyer.
        remote_path: chemin distant côté serveur SCP (racine = flash), ex:
            "/feature.bin" — sans le préfixe "flash:" (voir _push_feature_file).
        progress_callback: voir `scp_get` — même signature, même transmission
            telle quelle à `SCPClient(progress=...)`.
    """
    with SCPClient(ssh_client.get_transport(), progress=progress_callback) as scp_client:
        scp_client.put(str(local_path), remote_path)


def make_scp_progress_logger(
    context: str,
    threshold_percent: int = 10,
    on_progress: Callable[[ScpProgress], None] | None = None,
) -> Callable[[bytes, int, int], None]:
    """Construit un callback de progression SCP prêt pour `scp_get`/`scp_put`.

    Le paquet `scp` appelle son callback `progress(filename, size, sent)` à
    chaque bloc envoyé — potentiellement des dizaines de fois par fichier
    pour un transfert volumineux (voir candidat #6, audit Context7 session
    56). Journaliser à chaque appel noierait le journal ; cette fonction ne
    journalise qu'au franchissement d'un nouveau palier de
    `threshold_percent` (10% par défaut), par fichier (un même callback
    peut légitimement être réutilisé pour plusieurs fichiers successifs, ex.
    plusieurs rapatriements de rotation par la même boucle de polling —
    chaque nom de fichier a son propre dernier palier atteint, indépendant
    des autres).

    Args:
        context: préfixe libre inclus dans chaque ligne de log (ex.
            "process_closed_file_scp"), pour identifier l'appelant sans
            avoir à inspecter la pile d'appels dans le journal.
        threshold_percent: écart minimal (en points de pourcentage) entre
            deux lignes de log pour un même fichier. Doit diviser 100 pour
            un comportement prévisible (10, 20, 25... par défaut 10) — une
            valeur qui ne divise pas 100 reste sans danger (juste des
            paliers de largeur inégale) mais n'est pas le cas prévu.

    Returns:
        Un callable `(filename, size, sent) -> None`, à passer tel quel en
        `progress_callback` à `scp_get`/`scp_put`. `filename` peut être
        `bytes` ou `str` selon la version de `paramiko`/`scp` (confirmé
        contre leur code source, jamais garanti par leur documentation) —
        décodé en `str` avant journalisation dans les deux cas. Aucune
        ligne n'est produite avant que le premier palier (`threshold_percent`)
        soit réellement atteint — un fichier qui vient de démarrer son
        transfert (0%, ou en dessous du premier palier) n'a rien
        d'informatif à journaliser.
    """
    last_logged_threshold: dict[str, int] = {}

    def _progress(filename: bytes | str, size: int, sent: int) -> None:
        name = filename.decode() if isinstance(filename, bytes) else filename
        if size <= 0:
            return  # fichier vide : aucun pourcentage de progression n'a de sens.
        percent = min(int(sent * 100 / size), 100)
        threshold = (percent // threshold_percent) * threshold_percent
        if threshold == 0:
            return  # rien à signaler avant le premier palier réellement atteint.
        if threshold <= last_logged_threshold.get(name, -1):
            return
        last_logged_threshold[name] = threshold
        logger.debug(
            "{context} | {name} : {pct}% ({sent}/{size} o)",
            context=context,
            name=name,
            pct=threshold,
            sent=sent,
            size=size,
        )
        if on_progress is not None:
            try:
                on_progress(ScpProgress(context=context, name=name, percent=threshold, sent=sent, size=size))
            except Exception:  # noqa: BLE001 -- l'affichage ne doit jamais casser le transfert
                logger.exception("{context} | callback de progression en échec", context=context)

    return _progress


def list_remote_pcap_files(conn, prefix: str) -> list[str]:
    """Liste les fichiers .pcap présents sur la flash, via une commande CLI.

    Utilise `dir flash:/<prefix>*.pcap` plutôt qu'un montage : le dernier
    token de chaque ligne se terminant par `.pcap` est pris comme nom de
    fichier — plus robuste qu'un découpage par colonnes fixes, dont la
    largeur varie selon les versions Comware.

    Args:
        conn: session netmiko déjà connectée.
        prefix: préfixe des fichiers de capture (`Config.capture_prefix`).

    Returns:
        La liste des noms de fichiers trouvés, triée (donc par ordre
        chronologique grâce à l'horodatage Comware dans le nom).
    """
    cmd = f"dir flash:/{prefix}*.pcap"
    logger.debug("list_remote_pcap_files | {cmd}", cmd=cmd)
    output = conn.send_command(cmd)
    filenames = [line.strip().split()[-1] for line in output.splitlines() if line.strip().endswith(".pcap")]
    return sorted(filenames)


def delete_remote_all_file_capture(conn, capture_prefix) -> None:
    """Supprime les fichiers captures restantes de la flash via une commande CLI (pas SCP).

    Args:
        conn: session netmiko déjà connectée.
        capture_prefix: prefixe de capture
    """
    try:
        files = list_remote_pcap_files(conn, capture_prefix)
    except Exception:  # noqa: BLE001
        logger.exception("delete_remote_all_file_capture | échec de la liste des fichiers distants")
        return

    if len(files) <= 0:
        return  # rien à faire : 0

    # on efface tous les fichiers de capture encore présent
    for filename in files:
        delete_remote_file(conn, filename)
    logger.info("delete_remote_all_file_capture | fin de nettoyage des fichiers captures distants")
    return


def delete_remote_file(conn, filename: str) -> None:
    """Supprime un fichier de la flash via une commande CLI (pas SCP).

    Args:
        conn: session netmiko déjà connectée.
        filename: nom du fichier à supprimer (sans le préfixe `flash:/`).
    """
    cmd = f"delete flash:/{filename}"
    logger.info("delete_remote_file | {cmd}", cmd=cmd)
    output = conn.send_command_timing(cmd, read_timeout=15)
    if "Continue?" in output or "[Y/N]" in output or "?" in output:
        logger.debug("delete_remote_file | confirmation envoyée (y)")
        conn.send_command_timing("y", read_timeout=15)


def build_capture_filter(switch_ip: str, capture_filter: str, hide_capture_traffic: bool = True) -> str:
    """Construit la clause `capture-filter "..."` envoyée au switch (point 5, features.md).

    Fonction pure (aucun accès réseau, aucun effet de bord), pour être
    testable en isolation et partagée avec un éventuel appelant GUI futur.

    Args:
        switch_ip: adresse IP du switch, utilisée pour exclure son propre
            trafic SSH/SCP de la capture quand `hide_capture_traffic` est
            actif (évite de polluer les traces avec le trafic de gestion
            de l'outil lui-même).
        capture_filter: filtre inline (tcpdump-like) saisi par
            l'utilisateur, éventuellement vide.
        hide_capture_traffic: si True (défaut, comportement historique de
            ce dépôt depuis le patch utilisateur intégré le 26/08/2026),
            exclut `host {switch_ip} and port 22` de la capture. Si False,
            le trafic SSH/SCP vers le switch n'est plus exclu — seul le
            filtre utilisateur (le cas échéant) s'applique.

    Returns:
        La clause complète `'capture-filter "..." '` (espace final inclus,
        comme le reste de la commande construite par
        `_run_capture_blocking_local`), ou une chaîne vide si ni
        l'exclusion ni un filtre utilisateur ne s'appliquent — auquel cas
        `packet-capture` tourne sans aucune clause `capture-filter`.
    """
    clauses = []
    if hide_capture_traffic:
        clauses.append(f"not (host {switch_ip} and port 22)")
    if capture_filter:
        clauses.append(capture_filter)
    if not clauses:
        return ""
    return f'capture-filter "{" and ".join(clauses)}" '


def build_capture_direction_clause(capture_direction: str) -> str:
    """Construit le mot-clé de sens de capture pour `packet-capture` (point 6, features.md).

    Fonction pure, testable en isolation. D'après la doc H3C officielle
    (`packet-capture local interface ... [ bidirection | outbound ] ...` et
    `packet-capture remote interface ... [ bidirection | outbound ] ...`),
    Comware ne capture que le trafic **entrant** si ni `bidirection` ni
    `outbound` n'est précisé — il n'existe pas de mot-clé `inbound`
    explicite, l'absence des deux autres mots-clés EST le sens "inbound".

    Args:
        capture_direction: "bidirection", "outbound" ou "inbound" (voir
            `Config.capture_direction`).

    Returns:
        `"bidirection "` ou `"outbound "` (espace final inclus, comme
        `build_capture_filter`), ou une chaîne vide pour "inbound" — dans
        ce dernier cas, aucun mot-clé n'est envoyé, ce qui correspond
        exactement au comportement "inbound" côté switch (pas une clause
        `inbound` qui n'existe pas dans la syntaxe Comware).

    Raises:
        ValueError: si `capture_direction` n'est pas l'une des trois
            valeurs reconnues (défense en profondeur : `Config.__post_init__`
            valide déjà ce champ, cette fonction peut aussi être appelée
            directement, ex: en test).
    """
    if capture_direction == "inbound":
        return ""
    if capture_direction in ("outbound", "bidirection"):
        return f"{capture_direction} "
    raise ValueError(f"capture_direction invalide : {capture_direction!r} (choix : inbound, outbound, bidirection)")


# --------------------------------------------------------------------------- #
# Thread 1 : préparation switch + lancement de la capture
# --------------------------------------------------------------------------- #
class SetupAndCaptureThread(threading.Thread):
    """Prépare le switch (SCP/sshfs, feature, NTP) puis lance la capture bloquante.

    Deux phases distinctes, appelables séparément (utile pour un pilotage
    multi-captures où la préparation de toutes les captures doit être
    terminée avant que l'une d'entre elles ne démarre réellement) :
        - `prepare()` : détection modèle, activation SCP/sshfs, NTP,
          installation de la feature si nécessaire. Ne lance rien.
        - `start_capture_blocking()` : lance la capture elle-même (bloquant
          jusqu'à `state.stop_event`). Suppose `prepare()` déjà appelé.

    `run()` (usage `.start()`/Thread classique, CLI) enchaîne les deux à la
    suite, comme avant — inchangé pour la CLI. Pour un pilotage en deux
    temps (GUI multi-captures), n'appelez jamais `.start()` sur l'objet
    lui-même : appelez `prepare()` et `start_capture_blocking()`
    directement, chacun depuis son propre `threading.Thread(target=...)`
    (un objet Thread ne peut être démarré qu'une fois, d'où l'appel direct
    aux méthodes plutôt qu'au mécanisme Thread intégré pour ce cas d'usage).
    """

    def __init__(self, cfg: Config, state: SharedState) -> None:
        super().__init__(name="setup-capture", daemon=True)
        self.cfg = cfg
        self.state = state
        self._prepared = False

    def run(self) -> None:
        """Point d'entrée Thread classique : `prepare()` puis capture bloquante."""
        try:
            self.prepare()
            self.start_capture_blocking()
        except Exception:  # noqa: BLE001
            logger.exception("setup-capture | échec du thread")
            self.state.stop_event.set()
            self.state.capture_started.set()  # débloque le thread 2 s'il attend

    def prepare(self) -> None:
        """Phase « installation » seule : modèle, SCP/NTP, feature. Ne lance pas la capture.

        Raises:
            Exception: toute erreur de connexion/configuration switch,
                laissée remonter à l'appelant (qui décide comment la
                reporter — logs, callback GUI, etc.).
        """
        self._prepare_switch()
        if self.state.needs_feature_install:
            self._push_feature_file()
            self._activate_feature()
        self._prepared = True

    def start_capture_blocking(self) -> None:
        """Phase « démarrage » seule : lance la capture, bloque jusqu'à l'arrêt.

        Raises:
            RuntimeError: si `prepare()` n'a pas été appelé avant.
        """
        if not self._prepared:
            raise RuntimeError("prepare() doit être appelé avant start_capture_blocking()")
        self.state.started_at = time.time()
        self.state.capture_started.set()
        self._run_capture_blocking()

    def _prepare_switch(self) -> None:
        """Détecte le modèle, active SFTP si besoin, vérifie NTP, résout le .bin si nécessaire."""
        conn = connect_switch(self.cfg)
        try:
            logger.debug("prepare_switch | display version")
            version_output = conn.send_command("display version")
            model = self.cfg.model or detect_model(version_output)
            if not model:
                raise RuntimeError(
                    "Modèle switch non reconnu automatiquement depuis 'display version'. "
                    f"Sélectionnez-le manuellement (choix : {', '.join(sorted(MODEL_PROFILES))})"
                )
            if model not in MODEL_PROFILES:
                raise RuntimeError(f"Modèle inconnu : {model!r}")

            profile = MODEL_PROFILES[model]
            self.state.model = model
            logger.info(
                "prepare_switch | modèle={model} comware={comware} note={note}",
                model=model,
                comware=profile["comware"],
                note=profile["notes"],
            )

            if profile["packet_capture"] == "unsupported":
                raise RuntimeError(f"packet-capture non supporté sur {model} : {profile['notes']}")

            self.state.needs_feature_install = profile["packet_capture"] == "installable"

            self._ensure_transfer_service(conn)
            self._ensure_ntp(conn)

            if not self.state.needs_feature_install:
                logger.debug("prepare_switch | packet-capture ?")
                summary = conn.send_command("packet-capture ?")

                logger.info(
                    "prepare_switch | packet-capture installé sur {model}, résumé={summary}",
                    model=model,
                    summary=summary.strip() or "<vide>",
                )
                self.state.feature_already_installed = True
                return

            logger.debug("prepare_switch | display install active")
            installed = conn.send_command("display install active")
            logger.debug("prepare_switch | features actives={installed}", installed=installed)

            software_version = detect_software_version(version_output)
            logger.info(
                "prepare_switch | version logicielle détectée={version}",
                version=software_version or "<inconnue>",
            )

            if not self.cfg.feature_bin_path:
                resolved = resolve_feature_bin(self.cfg.feature_bin_dir, model, software_version)
                if resolved is None:
                    raise RuntimeError(
                        f"Aucun .bin packet-capture trouvé sous {self.cfg.feature_bin_dir}/{model} "
                        f"(version {software_version or '?'}). Déposez-y le fichier adapté, ou "
                        "renseignez un chemin exact dans le formulaire."
                    )
                self.cfg.feature_bin_path = str(resolved)
                logger.info("prepare_switch | feature bin résolu={path}", path=resolved)

            self.cfg.feature_filename = Path(self.cfg.feature_bin_path).name
            self.state.feature_already_installed = self.cfg.feature_filename in installed
            if self.state.feature_already_installed:
                logger.info("prepare_switch | feature déjà installée, activation sautée")
        finally:
            conn.disconnect()

    def _ensure_transfer_service(self, conn) -> None:
        """Active le service de transfert de fichiers requis (SCP ou SFTP).

        Le service dépend de `Config.transfer_mode` :
            - "scp" (par défaut) : `scp server enable`.
            - "sshfs" (legacy) : `sftp server enable` (sshfs a besoin de SFTP
              côté serveur, même si le protocole de transport est SSH).

        Args:
            conn: session netmiko déjà connectée.
        """
        command = "scp server enable" if self.cfg.transfer_mode == "scp" else "sftp server enable"
        service_label = "scp" if self.cfg.transfer_mode == "scp" else "sftp"

        check_cmd = f"display current-configuration | include {service_label}"
        logger.debug("ensure_transfer_service | {cmd}", cmd=check_cmd)
        current_cfg = conn.send_command(check_cmd)
        logger.debug(
            "ensure_transfer_service | conf {label}={cfg}",
            label=service_label,
            cfg=current_cfg.strip() or "<aucune>",
        )
        if command not in current_cfg:
            logger.info("ensure_transfer_service | activation : {cmd}", cmd=command)
            conn.config_mode()
            conn.send_command(command, expect_string=r"\]")
            conn.exit_config_mode()
        else:
            logger.info("ensure_transfer_service | {cmd} déjà actif", cmd=command)

    def _ensure_ntp(self, conn) -> None:
        """Vérifie la synchronisation NTP du switch, la configure si besoin.

        Important pour toute comparaison de traces prises à des points
        différents (client/routeur/serveur) : sans horloges synchronisées
        entre les switches capturant chacun un point du même trafic, les
        timestamps ne sont pas comparables d'une trace à l'autre. Ce module
        se contente de vérifier/configurer NTP côté switch — la corrélation
        des traces elle-même est hors de son périmètre.

        Args:
            conn: session netmiko déjà connectée (réutilisée, pas de
                nouvelle connexion SSH).
        """
        if not self.cfg.ensure_ntp:
            logger.info("ensure_ntp | vérification désactivée (ensure_ntp=False)")
            return

        logger.debug("ensure_ntp | display ntp-service status")
        status = conn.send_command("display ntp-service status")
        synced = is_ntp_synchronized(status)
        self.state.ntp_synced = synced
        self.state.ntp_detail = next((line.strip() for line in status.splitlines() if line.strip()), "")

        if synced:
            logger.info(
                "ensure_ntp | horloge synchronisée : {detail}",
                detail=self.state.ntp_detail,
            )
            return

        logger.warning("ensure_ntp | horloge non synchronisée sur ce switch")
        if not self.cfg.ntp_server:
            logger.warning(
                "ensure_ntp | pas de ntp_server configuré : les timestamps de ce switch "
                "peuvent dériver et ne seront pas fiablement comparables avec d'autres "
                "points de capture (client/routeur/serveur)"
            )
            return

        logger.info(
            "ensure_ntp | configuration du serveur NTP {server}",
            server=self.cfg.ntp_server,
        )
        conn.config_mode()
        logger.debug("ensure_ntp | ntp-service enable")
        conn.send_command("ntp-service enable", expect_string=r"\]")
        ntp_server_cmd = f"ntp-service unicast-server {self.cfg.ntp_server}"
        logger.debug("ensure_ntp | {cmd}", cmd=ntp_server_cmd)
        conn.send_command(ntp_server_cmd, expect_string=r"\]")
        conn.exit_config_mode()

        # Laisse un peu de temps à la première synchro, puis revérifie une
        # fois. Best-effort : la synchro complète peut prendre plusieurs
        # minutes selon le serveur ; on ne bloque pas la capture pour
        # l'attendre, juste un avertissement si toujours pas synchronisé.
        time.sleep(3)
        logger.debug("ensure_ntp | display ntp-service status (revérification)")
        status_after = conn.send_command("display ntp-service status")
        synced_after = is_ntp_synchronized(status_after)
        self.state.ntp_synced = synced_after
        self.state.ntp_detail = next((line.strip() for line in status_after.splitlines() if line.strip()), "")
        if synced_after:
            logger.info("ensure_ntp | synchronisation confirmée après configuration")
        else:
            logger.warning(
                "ensure_ntp | serveur NTP configuré mais pas encore synchronisé (normal, "
                "la synchro initiale peut prendre plusieurs minutes) — la capture démarre quand même"
            )

    def _mount_sshfs(self) -> None:
        """Monte la flash du switch en local via sshfs (idempotent, mode "sshfs" seulement)."""
        mnt = Path(self.cfg.mount_point)
        mnt.mkdir(parents=True, exist_ok=True)

        if self._is_mounted(mnt):
            logger.info("mount_sshfs | {mnt} déjà monté", mnt=mnt)
            return

        cmd = [
            "sshfs",
            f"{self.cfg.ssh_user}@{self.cfg.switch_ip}:/",
            str(mnt),
            "-o",
            "reconnect",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
        ]
        logger.info("mount_sshfs | {cmd}", cmd=" ".join(cmd))
        subprocess.run(cmd, check=True)

    @staticmethod
    def _is_mounted(path: Path) -> bool:
        """Indique si `path` est un point de montage actif."""
        return subprocess.run(["mountpoint", "-q", str(path)], check=False).returncode == 0

    def _record_scp_progress(self, progress: ScpProgress) -> None:
        """Publie le palier SCP dans l'état partagé (page « Journal », issue #70)."""
        self.state.scp_progress = progress

    def _push_feature_file(self) -> None:
        """Pousse le .bin de la feature sur la flash, sauf si déjà installée.

        Via SCP (mode par défaut) ou via le montage sshfs (mode legacy),
        selon `Config.transfer_mode`.
        """
        if self.state.feature_already_installed:
            return
        src = Path(self.cfg.feature_bin_path)

        if self.cfg.transfer_mode == "sshfs":
            self._mount_sshfs()
            dst = Path(self.cfg.mount_point) / "flash" / self.cfg.feature_filename
            logger.info("push_feature_file | (sshfs) {src} -> {dst}", src=src, dst=dst)
            shutil.copy(src, dst)
            return

        # Chemin SCP réel (protocole de transfert de fichier) : la racine "/"
        # du serveur SCP du switch EST la flash, "flash:" est une syntaxe
        # propre à la CLI Comware (dir/delete/install...), pas au SCP lui-même.
        # La passer ici casse le transfert (le switch ne trouve pas
        # "flash:/<fichier>" en tant que chemin SCP).
        remote_path = f"{self.cfg.feature_filename}"
        logger.info("push_feature_file | (scp) {src} -> {dst}", src=src, dst=remote_path)
        ssh_client = open_scp_ssh_client(self.cfg)
        try:
            scp_put(
                ssh_client,
                src,
                remote_path,
                progress_callback=make_scp_progress_logger("push_feature_file", on_progress=self._record_scp_progress),
            )
        finally:
            ssh_client.close()

    def _activate_feature(self) -> None:
        """Active la feature packet-capture via 'install activate feature'."""
        if self.state.feature_already_installed:
            return
        conn = connect_switch(self.cfg)
        try:
            cmd = f"install activate feature flash:/{self.cfg.feature_filename} slot {self.cfg.slot}"
            logger.info("activate_feature | {cmd}", cmd=cmd)
            output = conn.send_command_timing(cmd, read_timeout=60)
            if "Continue?" in output or "[Y/N]" in output:
                logger.debug("activate_feature | confirmation envoyée (y)")
                output += conn.send_command_timing("y", read_timeout=120)
            logger.debug("activate_feature | sortie={output}", output=output)
        finally:
            conn.disconnect()

    def _run_capture_blocking(self) -> None:
        """Dispatch vers l'implémentation correspondant à `output_mode`."""
        if self.cfg.output_mode == "rpcap":
            self._run_rpcap_blocking()
        else:
            self._run_capture_blocking_local()

    def _run_capture_blocking_local(self) -> None:
        """Lance packet-capture local (avec filtre inline optionnel) dans sa propre session SSH.

        Utilisé pour output_mode "fifo" et "tap" : le switch écrit dans des
        fichiers .pcap en ring-buffer sur sa flash, rapatriés par
        `CaptureRotationThread`.
        """
        conn = connect_switch(self.cfg)

        delete_remote_all_file_capture(conn, self.cfg.capture_prefix)
        try:
            filter_clause = build_capture_filter(
                self.cfg.switch_ip, self.cfg.capture_filter, self.cfg.hide_capture_traffic
            )
            direction_clause = build_capture_direction_clause(self.cfg.capture_direction)
            cmd = (
                f"{self.cfg.packet_capture_cmd} interface {self.cfg.capture_interface} "
                f"{direction_clause}"
                f"{filter_clause}"
                f"limit-captured-frames 0 "
                f"capture-ring-buffer duration {self.cfg.rotation_seconds} "
                f"capture-ring-buffer files {self.cfg.max_ring_files} "
                f"write flash:/{self.cfg.capture_basename}"
            )
            logger.info("run_capture | {cmd}", cmd=cmd)
            conn.write_channel(cmd + "\n")
            time.sleep(1)

            while not self.state.stop_event.is_set():
                data = conn.read_channel()
                if data:
                    logger.trace("run_capture | switch: {data}", data=data.strip())
                time.sleep(1)

            logger.info("run_capture | arrêt de la capture (Ctrl+C)")
            conn.write_channel("\x03")
            time.sleep(2)
        finally:
            conn.disconnect()

    def _run_rpcap_blocking(self) -> None:
        """Démarre `packet-capture remote` (RPCAP natif Comware) et attend l'arrêt.

        Contrairement au mode local, cette commande ne bloque pas le CLI de
        façon persistante (d'après la doc H3C, elle démarre la capture en
        arrière-plan et rend la main) : on l'envoie via
        `send_command_timing`, on attend `stop_event`, puis on envoie
        explicitement `packet-capture stop` — plutôt qu'un Ctrl+C dans un
        canal resté bloqué comme pour le mode local. Aucun fichier n'est
        écrit sur la flash ni rapatrié : Wireshark se connecte directement
        au switch via `rpcap://<switch_ip>:<port>/<interface>`.
        """
        conn = connect_switch(self.cfg)
        try:
            direction_clause = build_capture_direction_clause(self.cfg.capture_direction)
            cmd = (
                f"packet-capture remote interface {self.cfg.capture_interface} "
                f"{direction_clause}"
                f"port {self.cfg.rpcap_port}"
            )
            logger.info("run_rpcap | {cmd}", cmd=cmd)
            output = conn.send_command_timing(cmd, read_timeout=20)
            logger.debug("run_rpcap | sortie démarrage={output}", output=output.strip())
            logger.info(
                "run_rpcap | connectez Wireshark à rpcap://{ip}:{port}/{iface} "
                "(Capture > Options > Manage Interfaces > Remote Interfaces, ou -i rpcap://...)",
                ip=self.cfg.switch_ip,
                port=self.cfg.rpcap_port,
                iface=self.cfg.capture_interface,
            )

            while not self.state.stop_event.is_set():
                time.sleep(1)

            stop_cmd = "packet-capture stop"
            logger.info("run_rpcap | arrêt de la capture : {cmd}", cmd=stop_cmd)
            stop_output = conn.send_command_timing(stop_cmd, read_timeout=15)
            logger.debug("run_rpcap | sortie arrêt={output}", output=stop_output.strip())
        finally:
            conn.disconnect()


# --------------------------------------------------------------------------- #
# Thread 2 : rotation + réassemblage live vers Wireshark
# --------------------------------------------------------------------------- #
class CaptureRotationThread(threading.Thread):
    """Rapatrie les fichiers .pcap clôturés et les réinjecte en direct.

    Deux modes de sortie (`Config.output_mode`) :
        - "fifo" (historique) : FIFO nommé + une instance Wireshark lancée
          automatiquement. Une seule capture "live" à la fois — un FIFO ne
          peut avoir qu'un seul lecteur pcap cohérent.
        - "tap" : écrit les trames Ethernet brutes dans une interface
          réseau virtuelle TAP dédiée (`Config.tap_interface`), sans lancer
          Wireshark soi-même. Plusieurs captures simultanées (une par
          `CaptureRotationThread`, chacune sa propre interface TAP) sont
          alors observables ensemble dans une unique instance Wireshark ou
          `tcpdump`, lancée séparément et écoutant plusieurs interfaces à
          la fois — typiquement une capture par point de mesure (client,
          routeur, serveur) sur le même trafic.
    """

    def __init__(self, cfg: Config, state: SharedState) -> None:
        super().__init__(name="capture-rotation", daemon=True)
        self.cfg = cfg
        self.state = state
        self.spool_dir = Path(cfg.spool_dir)
        self.spool_dir.mkdir(parents=True, exist_ok=True)

        # Mode "fifo"
        self.fifo_path = Path(f"{cfg.fifo_path}-{cfg.switch_ip}")
        self._wrote_global_header = False
        self._wireshark_proc: subprocess.Popen | None = None
        self._fifo_fd = None

        # Mode "tap" : file d'attente + thread dédié, pour découpler
        # rapatriement (ce thread même, run()/_poll_once) et réinjection
        # (_injector_loop, sur son propre thread) — un fichier déposé par
        # _dispatch_for_injection n'attend jamais la fin de l'injection
        # (avec son éventuel délai de lissage, tap_pace_playback) avant que
        # le polling ne reprenne. Créés dans _setup_tap ; restent None en
        # mode "fifo", qui ne s'en sert jamais (pas de lissage à découpler).
        self._tap_writer: TapFrameWriter | None = None
        self._tap_queue: queue.Queue[Path | None] | None = None
        self._injector_thread: threading.Thread | None = None

        # transfer_mode == "scp" (par défaut) : connexion dédiée au polling
        # (netmiko, pour 'dir'/'delete') — ouverte une fois dans run(),
        # réutilisée à chaque cycle. La connexion SCP elle-même (paramiko/scp,
        # pour 'scp_get') est en revanche ouverte/fermée à chaque fichier
        # rapatrié (voir _process_closed_file_scp) : le switch ferme
        # apparemment la session SSH dédiée au SCP après un transfert, la
        # réutiliser provoquait un "Bad file descriptor" au fichier suivant.
        self._poll_conn = None
        # Un seul callback de progression réutilisé pour chaque fichier
        # rapatrié par ce thread (voir make_scp_progress_logger : les
        # paliers loggués sont suivis par nom de fichier, donc son état
        # interne reste correct d'un fichier à l'autre sans recréation).
        self._scp_progress_logger = make_scp_progress_logger(
            "process_closed_file_scp", on_progress=self._record_scp_progress
        )

    def _record_scp_progress(self, progress: ScpProgress) -> None:
        """Publie le palier SCP dans l'état partagé (page « Journal », issue #70)."""
        self.state.scp_progress = progress

    def run(self) -> None:
        """Point d'entrée du thread : attend la capture, puis poll en boucle."""
        self.state.capture_started.wait(timeout=120)
        if self.state.stop_event.is_set():
            return

        if self.cfg.output_mode == "tap":
            self._setup_tap()
        else:
            self._setup_fifo()
            self._launch_wireshark()

        if self.cfg.transfer_mode == "scp":
            self._poll_conn = connect_switch(self.cfg)

        try:
            write_capture_metadata(self.cfg, self.state)
        except OSError:
            logger.exception("run | échec écriture du sidecar de métadonnées (non bloquant)")

        try:
            while not self.state.stop_event.is_set():
                self._poll_once()
                time.sleep(self.cfg.poll_interval)
        finally:
            self._cleanup()

    def _setup_tap(self) -> None:
        """Crée/active l'interface TAP configurée et s'y attache en écriture.

        Démarre aussi le thread dédié à la réinjection (_injector_loop),
        seul consommateur de self._tap_queue — voir _dispatch_for_injection.
        Lance également Wireshark sur l'interface si
        `Config.tap_launch_wireshark` est activé (voir
        `_launch_wireshark_tap`).
        """
        ensure_tap_interface(self.cfg.tap_interface)
        if self.cfg.tap_launch_wireshark:
            self._launch_wireshark_tap()
        self._tap_writer = TapFrameWriter(self.cfg.tap_interface)
        self._tap_queue = queue.Queue()
        self._injector_thread = threading.Thread(
            target=self._injector_loop,
            name="tap-injector",
            daemon=True,
        )
        self._injector_thread.start()
        logger.info("setup_tap | attaché à {iface}", iface=self.cfg.tap_interface)

    def _injector_loop(self) -> None:
        """Boucle du thread dédié à la réinjection TAP (démarré par _setup_tap).

        Dépile self._tap_queue et réinjecte chaque fichier via
        _feed_into_tap (logique de lissage inchangée) sur son propre
        thread, indépendamment du thread de polling/téléchargement (run) —
        qui peut ainsi rapatrier le fichier suivant sans attendre qu'une
        éventuelle pause de lissage (tap_pace_playback) se termine ici.
        Voir features.md pour le contexte de ce découplage.

        S'arrête dès que stop_event est positionné, sans drainer une
        éventuelle file restante — cohérent avec le reste de la classe, qui
        n'essaie pas non plus de "finir" un cycle de poll en cours à
        l'arrêt — ou dès réception de la sentinelle None posée par
        _cleanup (réveil immédiat, sans attendre le timeout ci-dessous).
        """
        while True:
            try:
                pcap_file = self._tap_queue.get(timeout=0.5)
            except queue.Empty:
                if self.state.stop_event.is_set():
                    return
                continue
            if pcap_file is None:  # sentinelle de fin explicite, voir _cleanup
                return
            try:
                self._feed_into_tap(pcap_file)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "injector_loop | échec réinjection de {f}, fichier ignoré (reste sur disque dans spool_dir)",
                    f=pcap_file,
                )
            finally:
                self._tap_queue.task_done()

    def _setup_fifo(self) -> None:
        """Crée (ou recrée) le FIFO nommé utilisé pour le flux live."""
        if self.fifo_path.exists():
            self.fifo_path.unlink()
        os.mkfifo(self.fifo_path)
        logger.info("setup_fifo | créé={path}", path=self.fifo_path)

    def _launch_wireshark(self) -> None:
        """Lance Wireshark en lecture sur le FIFO et ouvre le FIFO en écriture."""
        logger.info("launch_wireshark | fifo={path}", path=self.fifo_path)
        self._wireshark_proc = subprocess.Popen(["wireshark", "-k", "-i", str(self.fifo_path)])
        logger.info("launch_wireshark | en attente que Wireshark ouvre le FIFO")
        # bloque jusqu'à ce qu'un lecteur (wireshark) ouvre l'autre bout
        # Le descripteur est conservé sur self._fifo_fd et utilisé par
        # d'autres méthodes (écriture des trames), fermé explicitement
        # dans _cleanup() : un context manager `with` ne conviendrait pas
        # ici, la durée de vie dépasse cette fonction — d'où le noqa.
        self._fifo_fd = open(self.fifo_path, "wb", buffering=0)  # noqa: SIM115
        logger.info("launch_wireshark | fifo ouvert en écriture")

    def _launch_wireshark_tap(self) -> None:
        """Lance Wireshark en écoute sur l'interface TAP déjà créée.

        Contrairement à `_launch_wireshark` (mode "fifo"), aucune poignée
        de main n'est nécessaire : l'interface existe déjà comme
        périphérique réseau noyau au moment de l'appel (`ensure_tap_interface`,
        toujours appelée avant dans `_setup_tap`) et Wireshark s'y attache
        via pcap comme sur n'importe quelle interface réseau — cet appel ne
        bloque donc jamais, contrairement à l'ouverture du FIFO en mode
        "fifo". Les éventuelles trames écrites par `TapFrameWriter` avant
        que Wireshark n'ait fini de démarrer ne sont simplement pas vues
        (comme pour toute capture réseau qui démarre après le début du
        trafic).
        """
        logger.info("launch_wireshark_tap | interface={iface}", iface=self.cfg.tap_interface)
        self._wireshark_proc = subprocess.Popen(["wireshark", "-k", "-i", self.cfg.tap_interface])

    def _poll_once(self) -> None:
        """Scrute la flash (SCP ou sshfs, selon transfer_mode) et traite les fichiers clôturés."""
        if self.cfg.transfer_mode == "scp":
            self._poll_once_scp()
        else:
            self._poll_once_sshfs()

    def _poll_once_scp(self) -> None:
        """Liste les .pcap via SSH ('dir') et traite tous les fichiers clôturés."""
        try:
            files = list_remote_pcap_files(self._poll_conn, self.cfg.capture_prefix)
        except Exception:  # noqa: BLE001
            logger.exception("poll_once_scp | échec de la liste des fichiers distants")
            return

        if len(files) <= 1:
            return  # rien à faire : 0 ou seulement le fichier en cours d'écriture

        # Le dernier (tri = plus récent grâce à l'horodatage Comware dans le
        # nom) est encore en cours d'écriture par le switch : on n'y touche pas.
        for filename in files[:-1]:
            self._process_closed_file_scp(filename)

    def _poll_once_sshfs(self) -> None:
        """Scrute le montage sshfs et traite tous les fichiers clôturés trouvés."""
        flash_dir = Path(self.cfg.mount_point) / "flash"
        try:
            files = sorted(flash_dir.glob(f"{self.cfg.capture_prefix}*.pcap"))
        except FileNotFoundError:
            logger.warning("poll_once_sshfs | point de montage inaccessible pour l'instant")
            return

        if len(files) <= 1:
            return  # rien à faire : 0 ou seulement le fichier en cours d'écriture

        # Le dernier (nom trié = plus récent grâce à l'horodatage Comware)
        # est encore en cours d'écriture par le switch : on n'y touche pas.
        for f in files[:-1]:
            self._process_closed_file_sshfs(f)

    def _process_closed_file_scp(self, filename: str) -> None:
        """Rapatrie via SCP, supprime côté switch, puis réinjecte un fichier clôturé.

        Args:
            filename: nom du fichier .pcap clôturé (tel que retourné par
                `list_remote_pcap_files`, sans le préfixe `flash:/`).
        """
        local_copy = self.spool_dir / filename
        # Chemin SCP réel, sans "flash:" (voir _push_feature_file) : seule la
        # commande CLI 'dir'/'delete' (list_remote_pcap_files/delete_remote_file,
        # via _poll_conn) utilise encore le préfixe "flash:/".
        remote_path = f"{filename}"
        # Connexion SCP dédiée, ouverte puis refermée pour CE fichier
        # uniquement (au lieu de réutiliser une connexion ouverte une seule
        # fois en début de capture) : le switch ferme apparemment la session
        # SSH utilisée pour le SCP après un transfert, ce qui provoquait un
        # "Bad file descriptor" dès le deuxième fichier en réutilisant un
        # transport devenu invalide. Coûte une reconnexion par fichier
        # rapatrié, mais fiabilise le rapatriement.
        try:
            scp_ssh_client = open_scp_ssh_client(self.cfg)
        except Exception:  # noqa: BLE001
            logger.exception(
                "process_closed_file_scp | échec de connexion SCP, nouvel essai au prochain poll",
            )
            return
        try:
            logger.info(
                "process_closed_file_scp | {src} -> {dst}",
                src=remote_path,
                dst=local_copy,
            )
            scp_get(scp_ssh_client, remote_path, local_copy, progress_callback=self._scp_progress_logger)
        except Exception:  # noqa: BLE001
            logger.exception(
                "process_closed_file_scp | échec scp de {f}, nouvel essai au prochain poll",
                f=filename,
            )
            return
        finally:
            try:
                scp_ssh_client.close()
            except Exception:  # noqa: BLE001
                logger.debug("process_closed_file_scp | échec fermeture connexion SCP dédiée (ignoré)")

        try:
            delete_remote_file(self._poll_conn, filename)
            logger.info("process_closed_file_scp | supprimé côté switch={f}", f=filename)
        except Exception:  # noqa: BLE001
            logger.exception(
                "process_closed_file_scp | échec suppression de {f} (non bloquant)",
                f=filename,
            )

        self._dispatch_for_injection(local_copy)

    def _process_closed_file_sshfs(self, remote_file: Path) -> None:
        """Copie, supprime côté switch, puis réinjecte un fichier .pcap clôturé.

        Args:
            remote_file: chemin (vu via sshfs) du fichier .pcap clôturé.
        """
        local_copy = self.spool_dir / remote_file.name
        try:
            logger.info(
                "process_closed_file_sshfs | {src} -> {dst}",
                src=remote_file,
                dst=local_copy,
            )
            shutil.copy(remote_file, local_copy)
        except Exception:  # noqa: BLE001
            logger.exception(
                "process_closed_file_sshfs | échec copie de {f}, nouvel essai au prochain poll",
                f=remote_file,
            )
            return

        try:
            remote_file.unlink()
            logger.info("process_closed_file_sshfs | supprimé côté switch={f}", f=remote_file)
        except Exception:  # noqa: BLE001
            logger.exception(
                "process_closed_file_sshfs | échec suppression de {f} (non bloquant)",
                f=remote_file,
            )

        self._dispatch_for_injection(local_copy)

    def _dispatch_for_injection(self, local_copy: Path) -> None:
        """Envoie un fichier .pcap fraîchement rapatrié vers la réinjection.

        Mode "tap" : dépose le fichier dans self._tap_queue plutôt que
        d'appeler _feed_into_tap directement — ne bloque donc jamais
        l'appelant (le thread de polling/téléchargement), même si
        l'injection réelle (avec son éventuel délai de lissage,
        tap_pace_playback) prend du temps. C'est _injector_loop, sur son
        propre thread, qui dépile et appelle _feed_into_tap.

        Mode "fifo" : réinjection directe et synchrone, comportement
        inchangé — pas de lissage en mode fifo, donc rien à découpler ici.
        """
        if self.cfg.output_mode == "tap":
            self._tap_queue.put(local_copy)
        else:
            self._feed_into_fifo(local_copy)

    def _feed_into_tap(self, pcap_file: Path) -> None:
        """Réinjecte chaque trame d'un fichier .pcap clôturé dans l'interface TAP.

        Contrairement au mode FIFO (concaténation d'octets pcap bruts, lus
        comme un flux par Wireshark), l'interface TAP est une interface
        réseau : il faut lui présenter des trames Ethernet une par une,
        exactement comme un pilote de carte réseau le ferait — d'où le
        passage par `iter_pcap_frames` (extraction, pas de décodage) plutôt
        que par une simple concaténation d'octets.

        Si `Config.tap_pace_playback` est activé, les trames sont écrites
        avec un délai entre elles (`compute_pacing_delays`, plafonné à
        `Config.tap_pace_max_gap_seconds`) reproduisant approximativement
        leur écart de temps d'origine, plutôt que d'être injectées aussi
        vite que possible (comportement par défaut).

        Args:
            pcap_file: fichier .pcap local déjà rapatrié.
        """
        if self._tap_writer is None:
            logger.warning(
                "feed_into_tap | interface TAP pas encore prête, {f} ignoré",
                f=pcap_file,
            )
            return

        file_size = pcap_file.stat().st_size
        frame_count = 0
        try:
            if self.cfg.tap_pace_playback:
                frames = list(iter_pcap_frames(pcap_file, with_timestamps=True))
                delays = compute_pacing_delays(
                    [ts for ts, _ in frames],
                    self.cfg.tap_pace_max_gap_seconds,
                )
                for delay, (_ts, frame) in zip(delays, frames):
                    if delay:
                        time.sleep(delay)
                    self._tap_writer.write_frame(frame)
                    frame_count += 1
            else:
                for frame in iter_pcap_frames(pcap_file):
                    self._tap_writer.write_frame(frame)
                    frame_count += 1
        except ValueError as exc:
            logger.warning("feed_into_tap | {f} ignoré : {err}", f=pcap_file, err=exc)
            return

        logger.info(
            "feed_into_tap | {n} trame(s) réinjectée(s) dans {iface} (depuis {f})",
            n=frame_count,
            iface=self.cfg.tap_interface,
            f=pcap_file,
        )
        self.state.files_merged += 1
        self.state.bytes_merged += file_size
        self.state.last_activity = time.time()
        self.state.last_file_name = pcap_file.name

        if self.cfg.archive_dir:
            archive_capture_file(pcap_file, Path(self.cfg.archive_dir), self.cfg.archive_as_pcapng)
        else:
            pcap_file.unlink(missing_ok=True)

    def _feed_into_fifo(self, pcap_file: Path) -> None:
        """Concatène les trames d'un fichier .pcap clôturé dans le flux FIFO live.

        Met aussi à jour les compteurs de progression de `self.state`
        (`files_merged`, `bytes_merged`, `last_activity`, `last_file_name`),
        consultés par l'UI (page "Travail" de la GUI notamment).

        Args:
            pcap_file: fichier .pcap local déjà rapatrié.
        """
        if self._fifo_fd is None:
            logger.warning("feed_into_fifo | fifo pas encore prêt, {f} ignoré", f=pcap_file)
            return

        file_size = pcap_file.stat().st_size

        with open(pcap_file, "rb") as f:
            header = f.read(PCAP_GLOBAL_HEADER_LEN)
            if len(header) < PCAP_GLOBAL_HEADER_LEN:
                logger.warning(
                    "feed_into_fifo | {f} trop petit / pcap invalide, ignoré",
                    f=pcap_file,
                )
                return

            magic = struct.unpack("<I", header[:4])[0]
            if magic not in PCAP_MAGICS:
                logger.warning(
                    "feed_into_fifo | {f} magic inattendu ({magic:#x}), probablement pcapng, ignoré",
                    f=pcap_file,
                    magic=magic,
                )
                return

            if not self._wrote_global_header:
                self._fifo_fd.write(header)
                self._wrote_global_header = True
                logger.info("feed_into_fifo | en-tête global écrit (depuis {f})", f=pcap_file)

            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self._fifo_fd.write(chunk)

        logger.info("feed_into_fifo | fusionné dans le flux live={f}", f=pcap_file)
        self.state.files_merged += 1
        self.state.bytes_merged += file_size
        self.state.last_activity = time.time()
        self.state.last_file_name = pcap_file.name

        if self.cfg.archive_dir:
            archive_capture_file(pcap_file, Path(self.cfg.archive_dir), self.cfg.archive_as_pcapng)
        else:
            pcap_file.unlink(missing_ok=True)

    def _cleanup(self) -> None:
        """Ferme le FIFO/TAP (output_mode) et les connexions SCP/SSH (transfer_mode)."""
        logger.info(
            "cleanup | nettoyage du thread de rotation (output={out}, transfer={trans})",
            out=self.cfg.output_mode,
            trans=self.cfg.transfer_mode,
        )

        if self._poll_conn:
            try:
                self._poll_conn.disconnect()
            except Exception:  # noqa: BLE001
                logger.debug("cleanup | échec déconnexion connexion de poll (ignoré)")

        if self.cfg.output_mode == "tap":
            # Arrêter _injector_loop avant de fermer self._tap_writer
            # ci-dessous : sinon le thread injecteur pourrait encore être en
            # train d'écrire dessus (ou sur l'interface, si tap_cleanup_on_stop
            # la supprime juste après) au moment de la fermeture. Sentinelle
            # pour un réveil immédiat (sans attendre le timeout de get() dans
            # _injector_loop), puis join() borné : seul join() de cette
            # classe (les autres threads sont "fire-and-forget", stoppés via
            # stop_event sans attendre leur fin — mais celui-ci partage
            # spécifiquement self._tap_writer avec le thread qui le ferme,
            # d'où cette unique synchronisation, bornée pour ne jamais
            # bloquer l'arrêt indéfiniment même avec un gros arriéré lissé).
            if self._tap_queue is not None:
                self._tap_queue.put(None)
            if self._injector_thread is not None:
                self._injector_thread.join(timeout=5.0)
            if self._tap_writer:
                self._tap_writer.close()
            if self.cfg.tap_cleanup_on_stop and self.cfg.tap_interface:
                delete_tap_interface(self.cfg.tap_interface)
            return

        if self._fifo_fd:
            try:
                self._fifo_fd.close()
            except Exception:  # noqa: BLE001
                logger.debug("cleanup | échec fermeture du FIFO (ignoré)")
        if self.fifo_path.exists():
            try:
                self.fifo_path.unlink()
            except Exception:  # noqa: BLE001
                logger.debug("cleanup | échec suppression du FIFO (ignoré)")


# --------------------------------------------------------------------------- #
# Désinstallation de la feature côté switch
# --------------------------------------------------------------------------- #
def confirm_ip_matches(entered: str, expected: str) -> bool:
    """Compare une IP retapée par l'utilisateur à l'IP attendue.

    Garde-fou utilisé avant une désinstallation en production (CLI
    ``--confirm-ip`` et bouton GTK) : sans dépendance CLI/GTK, testable en
    isolation, pour que les deux interfaces appliquent exactement la même
    règle de correspondance.

    Args:
        entered: texte tel que saisi (``input()`` CLI ou ``Gtk.Entry``) ;
            les espaces de début/fin sont ignorés.
        expected: ``cfg.switch_ip`` attendu.

    Returns:
        True si la saisie correspond exactement (après ``strip()``) à
        l'IP attendue.
    """
    return entered.strip() == expected


class UninstallThread(threading.Thread):
    """Désactive (et retire) la feature packet-capture sur le switch.

    Séquence Comware standard :
        1. install deactivate feature flash:/<fichier>.bin slot <N>
        2. install commit  (sinon la feature redevient active au reboot)
        3. delete /unreserved flash:/<fichier>.bin  (optionnel, libère la flash)

    Sans effet sur les plateformes où packet-capture serait nativement
    intégré à l'image (mécanisme "builtin" de `MODEL_PROFILES`, non utilisé
    par aucun modèle actuellement listé — 5130/5140/5510/5520 nécessitent
    tous l'installation de la feature) : rien n'a été installé, donc rien à
    désinstaller.
    """

    def __init__(
        self,
        cfg: Config,
        state: SharedState,
        remove_bin_from_flash: bool = False,
        on_done=None,
    ) -> None:
        """Initialise le thread de désinstallation.

        Args:
            cfg: configuration (switch_ip/ssh_user/ssh_password/slot/feature_filename).
            state: état partagé, utilisé pour connaître le modèle déjà détecté.
            remove_bin_from_flash: si True, supprime aussi le .bin de la flash
                après désactivation (sinon il reste présent mais inactif).
            on_done: callback optionnel `(success: bool, message: str) -> None`,
                appelé en fin de thread (à invoquer depuis l'UI via GLib.idle_add).
        """
        super().__init__(name="uninstall-feature", daemon=True)
        self.cfg = cfg
        self.state = state
        self.remove_bin_from_flash = remove_bin_from_flash
        self.on_done = on_done

    def run(self) -> None:
        """Point d'entrée du thread : exécute la séquence de désinstallation."""
        try:
            conn = connect_switch(self.cfg)
            try:
                logger.debug("uninstall | display version")
                version_output = conn.send_command("display version")
                model = self.cfg.model or self.state.model or detect_model(version_output)
                if not model or model not in MODEL_PROFILES:
                    raise RuntimeError("Modèle non déterminé, impossible de savoir s'il y a une feature à retirer")

                profile = MODEL_PROFILES[model]
                if profile["packet_capture"] != "installable":
                    message = f"{model} : packet-capture natif, aucune feature à désinstaller"
                    logger.info("uninstall | {msg}", msg=message)
                    delete_remote_all_file_capture(conn, self.cfg.capture_prefix)
                    self._finish(True, message)
                    return

                filename = self.cfg.feature_filename
                if not filename:
                    delete_remote_all_file_capture(conn, self.cfg.capture_prefix)
                    logger.debug("uninstall | display install active")
                    installed = conn.send_command("display install active")
                    # `[\w.-]` et non `\S` : Comware liste les paquets actifs préfixés par
                    # leur média (`flash:/packet-capture-....bin`, cf. HPE Comware 7 command
                    # reference). Avec `\S*`, le préfixe était capturé dans le nom de
                    # fichier et la commande construite plus bas devenait
                    # `install deactivate feature flash:/flash:/...` — rejetée par le switch.
                    # Corrigé en session 62 ; voir docs/sessions/session-62.md.
                    match = re.search(r"([\w.-]*packet-capture[\w.-]*\.bin)", installed)
                    if not match:
                        message = "Aucune feature packet-capture active trouvée sur ce slot"
                        logger.info("uninstall | {msg}", msg=message)
                        self._finish(True, message)
                        return
                    filename = match.group(1)

                deactivate_cmd = f"install deactivate feature flash:/{filename} slot {self.cfg.slot}"
                logger.info("uninstall | {cmd}", cmd=deactivate_cmd)
                output = conn.send_command_timing(deactivate_cmd, read_timeout=90)
                if "Continue?" in output or "[Y/N]" in output:
                    logger.debug("uninstall | confirmation envoyée (y)")
                    output += conn.send_command_timing("y", read_timeout=120)
                logger.debug("uninstall | sortie deactivate={output}", output=output)

                logger.info("uninstall | install commit")
                commit_output = conn.send_command_timing("install commit", read_timeout=90)
                logger.debug("uninstall | sortie commit={output}", output=commit_output)

                if self.remove_bin_from_flash:
                    delete_cmd = f"delete /unreserved flash:/{filename}"
                    logger.info("uninstall | {cmd}", cmd=delete_cmd)
                    delete_output = conn.send_command_timing(delete_cmd, read_timeout=30)
                    if "Continue?" in delete_output or "[Y/N]" in delete_output:
                        logger.debug("uninstall | confirmation envoyée (y)")
                        delete_output += conn.send_command_timing("y", read_timeout=30)
                    logger.debug("uninstall | sortie delete={output}", output=delete_output)

                self._finish(True, f"Feature {filename} désinstallée sur le slot {self.cfg.slot}")
            finally:
                conn.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.exception("uninstall | échec")
            self._finish(False, str(exc))

    def _finish(self, success: bool, message: str) -> None:
        """Invoque le callback de fin, s'il a été fourni.

        Args:
            success: True si la désinstallation s'est bien déroulée.
            message: message à afficher à l'utilisateur.
        """
        if self.on_done:
            self.on_done(success, message)


# --------------------------------------------------------------------------- #
# Port mirroring (SPAN local ou ERSPAN/GRE distant) — alternative à
# packet-capture pour de la capture à débit ligne, sans limite CPU. Pousse
# uniquement la configuration switch ; la capture elle-même se fait côté
# collecteur (Wireshark/tcpdump), hors du périmètre de ce module. Voir
# CAPTURE-METHODS.md pour la comparaison avec packet-capture/rpcap et les
# procédures manuelles (sans switch-capture) multi-constructeurs.
# --------------------------------------------------------------------------- #
@dataclass
class MirrorConfig:
    """Paramètres de configuration du port mirroring.

    Args:
        switch_ip: adresse IP ou nom du switch.
        ssh_user: compte RADIUS existant.
        ssh_password: mot de passe SSH. Si vide, lu depuis
            SWITCH_SSH_PASSWORD.
        mode: "local" (SPAN — source et destination sur le même switch, un
            câble direct vers l'hôte de capture), "gre" (ERSPAN en mode
            tunnel — les ports sources sont mirrorés vers un tunnel GRE
            routé vers un collecteur distant, pas de câble direct requis)
            ou "vxlan" (mirroring vers un VLAN sonde, acheminé jusqu'au
            collecteur par extension L2 VXLAN plutôt que par un trunk
            physique — voir plus bas ; combinaison non officiellement
            documentée par H3C, imposée par retour d'expérience direct
            de l'utilisateur sur un 5520 HI, voir features.md).
        group_id: numéro du groupe de mirroring Comware (`mirroring-group N`).
        source_interfaces: interfaces sources à mirrorer (au moins une).
        direction: "both" | "inbound" | "outbound".
        monitor_interface: (mode "local" uniquement, obligatoire) interface
            de destination connectée à l'hôte de capture.
        tunnel_id: (mode "gre" ou "vxlan") numéro de l'interface Tunnel à
            créer.
        tunnel_local_ip: (mode "gre" ou "vxlan", obligatoire) IP source du
            tunnel — une IP déjà portée par une interface du switch (ex:
            IP de management), routable jusqu'au collecteur.
        tunnel_ip: (mode "gre", obligatoire) IP assignée à l'interface
            Tunnel elle-même (réseau dédié au tunnel, pas de trafic dessus
            en pratique). Sans objet en mode "vxlan" (l'interface Tunnel y
            est un simple transport L2 sans IP propre, voir plus bas).
        tunnel_mask: (mode "gre") masque associé à `tunnel_ip`.
        remote_ip: (mode "gre" ou "vxlan", obligatoire) IP du collecteur
            distant (destination de l'encapsulation GRE, ou destination du
            tunnel VXLAN).
        loopback_interface: (mode "gre", optionnel) interface physique à
            assigner à un groupe `service-loopback type tunnel`, requis sur
            certaines plateformes pour que le trafic tunnel soit traité
            correctement (voir doc H3C « Mirroring configuration »). Sans
            objet si `filter_mode == "acl"` ou si `mode == "vxlan"`.
        filter_mode: "port" (par défaut — mirroring-group historique,
            duplique tout le trafic du/des port(s) source) ou "acl" (flow
            mirroring filtré : seuls les paquets qui correspondent à une
            ACL avancée sont dupliqués, via une politique QoS — voir
            CAPTURE-METHODS.md section 4, « Flow mirroring (QoS) »). En
            mode "acl", `group_id` sert uniquement à dériver les noms par
            défaut de classifier/behavior/policy ci-dessous ; aucun
            `mirroring-group` n'est créé et `loopback_interface` n'est pas
            utilisé (l'encapsulation ERSPAN, en mode "gre", est inline
            dans le `mirror-to`, sans interface Tunnel dédiée). Pas encore
            combinable avec `mode == "vxlan"` (voir plus bas).
        acl_number: (filter_mode "acl") numéro d'ACL avancée Comware —
            plage valide 3000-3999, 3998/3999 exclus (réservés au cluster
            management, voir doc H3C « ACL commands »). Défaut 3000.
        acl_rules: (filter_mode "acl", obligatoire) règles ACL complètes,
            telles qu'attendues en vue ACL avancée (ex. "rule 0 permit ip
            source 10.0.0.5 0") — envoyées telles quelles au switch, une
            par commande, dans l'ordre fourni.
        classifier_name: (filter_mode "acl", optionnel) nom du traffic
            classifier Comware créé pour référencer `acl_number`. Défaut
            dérivé de `group_id` si omis (ex. "SWCAP_CLS_1").
        behavior_name: (filter_mode "acl", optionnel) nom du traffic
            behavior Comware créé pour l'action `mirror-to`. Défaut dérivé
            de `group_id` si omis (ex. "SWCAP_BEH_1").
        qos_policy_name: (filter_mode "acl", optionnel) nom de la qos
            policy Comware appliquée sur `source_interfaces`. Défaut
            dérivé de `group_id` si omis (ex. "SWCAP_POL_1").
        remote_probe_vlan: (mode "vxlan", obligatoire) VLAN sonde Comware
            (`mirroring-group ... remote-probe vlan`) dans lequel le
            trafic mirroré est réinjecté via `reflector_interface`, avant
            d'être raccordé à `vsi_name` pour transport VXLAN. Distinct de
            `vxlan_vni` (numérotation indépendante, même si égaux dans
            l'exemple fourni par l'utilisateur : VLAN 666 / VNI 666).
        vsi_name: (mode "vxlan", obligatoire) nom de la VSI Comware (`vsi
            <nom>`) associée à `vxlan_vni` et au tunnel `tunnel_id`.
        vxlan_vni: (mode "vxlan", obligatoire) VNI VXLAN (0-16777215)
            associé à `vsi_name` (`vxlan <vni>` dans le contexte `vsi`).
        service_instance_id: (mode "vxlan", optionnel) identifiant du
            `service-instance` Comware créé sur `reflector_interface` pour
            raccorder `remote_probe_vlan` à `vsi_name` (`encapsulation
            s-vid <remote_probe_vlan>` + `xconnect vsi <vsi_name>`).
            Référence purement locale au switch (pas échangée avec quoi
            que ce soit d'externe) — défaut : `group_id` si omis.
        reflector_interface: (mode "vxlan", obligatoire) port physique
            dédié servant à la fois de reflector-port pour le mécanisme
            Comware classique de mirroring vers VLAN sonde
            (`mirroring-group ... reflector-port`, voir doc H3C « remote
            port mirroring ») et de point de raccordement du VLAN sonde à
            la VSI VXLAN (`service-instance`). **Important** : cette
            fonction combine un mécanisme H3C officiellement documenté
            (remote-probe VLAN + reflector port) avec un autre
            (VSI/VXLAN/service-instance) documenté séparément — la
            combinaison précise des deux (notamment l'usage du reflector
            port comme point d'accès VSI) n'a pas été retrouvée telle
            quelle dans un exemple H3C officiel unique. Elle est traitée
            comme valide sur la foi du retour d'expérience direct de
            l'utilisateur (voir features.md, 04-05/09/2026), mais la
            séquence de commandes ci-dessous reste une reconstruction best
            effort, non confirmée commande par commande — à vérifier
            contre le switch réel avant tout déploiement en production.
    """

    switch_ip: str = ""
    ssh_user: str = ""
    ssh_password: str = ""
    mode: str = "local"
    group_id: int = 1
    source_interfaces: list[str] = field(default_factory=list)
    direction: str = "both"
    monitor_interface: str | None = None
    tunnel_id: int = 1
    tunnel_local_ip: str | None = None
    tunnel_ip: str | None = None
    tunnel_mask: str = "255.255.255.0"
    remote_ip: str | None = None
    loopback_interface: str | None = None
    filter_mode: str = "port"
    acl_number: int = 3000
    acl_rules: list[str] = field(default_factory=list)
    classifier_name: str | None = None
    behavior_name: str | None = None
    qos_policy_name: str | None = None
    remote_probe_vlan: int | None = None
    vsi_name: str | None = None
    vxlan_vni: int | None = None
    service_instance_id: int | None = None
    reflector_interface: str | None = None

    def __post_init__(self) -> None:
        """Normalise et valide les champs obligatoires selon `mode`/`filter_mode`."""
        if not self.ssh_password:
            self.ssh_password = os.environ.get("SWITCH_SSH_PASSWORD", "")
        missing = [n for n, v in (("switch_ip", self.switch_ip), ("ssh_user", self.ssh_user)) if not v]
        if missing:
            raise ValueError(f"Champs obligatoires manquants : {', '.join(missing)}")
        if not self.ssh_password:
            raise ValueError("Mot de passe SSH manquant (champ 'ssh_password' ou SWITCH_SSH_PASSWORD)")
        if self.mode not in ("local", "gre", "vxlan"):
            raise ValueError(f"mode invalide : {self.mode!r} (choix : local, gre, vxlan)")
        if self.filter_mode not in ("port", "acl"):
            raise ValueError(f"filter_mode invalide : {self.filter_mode!r} (choix : port, acl)")
        if self.direction not in ("both", "inbound", "outbound"):
            raise ValueError(f"direction invalide : {self.direction!r} (choix : both, inbound, outbound)")
        if not self.source_interfaces:
            raise ValueError("au moins une interface source (source_interfaces) est requise")
        if self.mode == "local" and not self.monitor_interface:
            raise ValueError("monitor_interface requis en mode 'local'")
        if self.mode == "gre":
            gre_required = [
                ("tunnel_local_ip", self.tunnel_local_ip),
                ("remote_ip", self.remote_ip),
            ]
            if self.filter_mode != "acl":
                # Mode "port" seul : crée une vraie interface Tunnel GRE, qui a
                # besoin de sa propre IP. En "acl", l'encapsulation ERSPAN est
                # inline dans le mirror-to (destination-ip/source-ip), sans
                # interface Tunnel à créer — voir configure_acl_mirror.
                gre_required.append(("tunnel_ip", self.tunnel_ip))
            gre_missing = [n for n, v in gre_required if not v]
            if gre_missing:
                raise ValueError(f"champs requis en mode 'gre' manquants : {', '.join(gre_missing)}")
        if self.mode == "vxlan":
            if self.filter_mode == "acl":
                raise ValueError("mode 'vxlan' non combinable avec filter_mode 'acl' pour l'instant")
            vxlan_required = [
                ("remote_probe_vlan", self.remote_probe_vlan),
                ("vsi_name", self.vsi_name),
                ("vxlan_vni", self.vxlan_vni),
                ("tunnel_local_ip", self.tunnel_local_ip),
                ("remote_ip", self.remote_ip),
                ("reflector_interface", self.reflector_interface),
            ]
            vxlan_missing = [n for n, v in vxlan_required if v is None or v == ""]
            if vxlan_missing:
                raise ValueError(f"champs requis en mode 'vxlan' manquants : {', '.join(vxlan_missing)}")
            if not (1 <= self.remote_probe_vlan <= 4094):
                raise ValueError(f"remote_probe_vlan invalide : {self.remote_probe_vlan!r} (1-4094)")
            if not (0 <= self.vxlan_vni <= 16777215):
                raise ValueError(f"vxlan_vni invalide : {self.vxlan_vni!r} (0-16777215)")
            if self.service_instance_id is None:
                self.service_instance_id = self.group_id
        if self.filter_mode == "acl":
            if not self.acl_rules:
                raise ValueError("au moins une règle ACL (acl_rules) est requise en filter_mode 'acl'")
            if not (3000 <= self.acl_number <= 3999) or self.acl_number in (3998, 3999):
                raise ValueError(
                    f"acl_number invalide : {self.acl_number!r} (ACL avancée "
                    "Comware : 3000-3999, 3998/3999 exclus — réservés cluster management)"
                )
            if self.classifier_name is None:
                self.classifier_name = f"SWCAP_CLS_{self.group_id}"
            if self.behavior_name is None:
                self.behavior_name = f"SWCAP_BEH_{self.group_id}"
            if self.qos_policy_name is None:
                self.qos_policy_name = f"SWCAP_POL_{self.group_id}"


def configure_local_mirror(conn, cfg: MirrorConfig) -> None:
    """Configure un mirroring local (SPAN) : source(s) -> port de destination.

    Args:
        conn: session netmiko déjà connectée.
        cfg: paramètres de mirroring (`mode == "local"`).
    """
    ports = " ".join(cfg.source_interfaces)
    conn.config_mode()
    commands = [
        f"mirroring-group {cfg.group_id} local",
        f"mirroring-group {cfg.group_id} mirroring-port {ports} {cfg.direction}",
        f"mirroring-group {cfg.group_id} monitor-port {cfg.monitor_interface}",
        f"interface {cfg.monitor_interface}",
        "undo stp enable",
        "quit",
    ]
    for command in commands:
        logger.debug("configure_local_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")
    conn.exit_config_mode()
    logger.info(
        "configure_local_mirror | groupe {gid} : {srcs} ({dir}) -> {mon}",
        gid=cfg.group_id,
        srcs=ports,
        dir=cfg.direction,
        mon=cfg.monitor_interface,
    )


def configure_gre_mirror(conn, cfg: MirrorConfig) -> None:
    """Configure un mirroring distant en tunnel GRE (ERSPAN tunnel-mode), côté source.

    Pousse uniquement la configuration côté source (là où sont les ports à
    mirrorer) : interface Tunnel en mode GRE + groupe de mirroring local
    avec le tunnel comme destination. Le collecteur distant reçoit le
    trafic GRE encapsulé (ERSPAN, protocole GRE 0x88BE) directement sur son
    interface physique — Wireshark le décode nativement (dissecteur ERSPAN
    intégré), aucune interface de réception à créer côté collecteur. Voir
    CAPTURE-METHODS.md.

    Args:
        conn: session netmiko déjà connectée.
        cfg: paramètres de mirroring (`mode == "gre"`).
    """
    conn.config_mode()

    if cfg.loopback_interface:
        loopback_commands = [
            "service-loopback group 1 type tunnel",
            f"interface {cfg.loopback_interface}",
        ]
        for command in loopback_commands:
            logger.debug("configure_gre_mirror | {cmd}", cmd=command)
            conn.send_command(command, expect_string=r"\]")
        logger.debug("configure_gre_mirror | port service-loopback group 1")
        output = conn.send_command_timing("port service-loopback group 1", read_timeout=15)
        if "Continue?" in output or "[Y/N]" in output:
            logger.debug("configure_gre_mirror | confirmation envoyée (y)")
            conn.send_command_timing("y", read_timeout=15)
        logger.debug("configure_gre_mirror | quit")
        conn.send_command("quit", expect_string=r"\]")

    ports = " ".join(cfg.source_interfaces)
    tunnel_and_mirror_commands = [
        f"interface tunnel {cfg.tunnel_id} mode gre",
        f"ip address {cfg.tunnel_ip} {cfg.tunnel_mask}",
        f"source {cfg.tunnel_local_ip}",
        f"destination {cfg.remote_ip}",
        "quit",
        f"mirroring-group {cfg.group_id} local",
        f"mirroring-group {cfg.group_id} mirroring-port {ports} {cfg.direction}",
        f"mirroring-group {cfg.group_id} monitor-port tunnel {cfg.tunnel_id}",
    ]
    for command in tunnel_and_mirror_commands:
        logger.debug("configure_gre_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")
    conn.exit_config_mode()
    logger.info(
        "configure_gre_mirror | groupe {gid} : {srcs} ({dir}) -> tunnel{tid} (GRE vers {remote})",
        gid=cfg.group_id,
        srcs=ports,
        dir=cfg.direction,
        tid=cfg.tunnel_id,
        remote=cfg.remote_ip,
    )


def configure_vxlan_mirror(conn, cfg: MirrorConfig) -> None:
    """Configure un mirroring distant vers un VLAN sonde, transporté en VXLAN L2.

    Combine deux mécanismes Comware documentés séparément : le mirroring
    classique vers un VLAN sonde (`mirroring-group ... remote-probe vlan`
    + `reflector-port`, H3C « remote port mirroring ») et une extension
    L2 VXLAN (VSI + interface Tunnel en `mode vxlan` + `service-instance`
    pour raccorder le VLAN sonde à la VSI). Au lieu de trunker le VLAN
    sonde de proche en proche sur un réseau L2 classique (adjacence L2
    bout en bout requise), la VSI l'achemine par-dessus un réseau routé
    jusqu'au collecteur — qui reçoit le trafic décapsulé en créant
    lui-même une interface `vxlan` native (`ip link add ... type vxlan`,
    hors du périmètre de cet outil, voir CAPTURE-METHODS.md).

    **Important** : cette combinaison précise n'a pas été retrouvée telle
    quelle dans un exemple H3C officiel unique (voir docstring de
    `MirrorConfig.reflector_interface` et features.md, 04-05/09/2026) —
    traitée comme valide sur la foi du retour d'expérience direct de
    l'utilisateur, mais la séquence ci-dessous reste une reconstruction
    best-effort à vérifier contre le switch réel avant tout déploiement
    en production.

    Args:
        conn: session netmiko déjà connectée.
        cfg: paramètres de mirroring (`mode == "vxlan"`).
    """
    conn.config_mode()

    vlan_commands = [f"vlan {cfg.remote_probe_vlan}", "quit"]
    for command in vlan_commands:
        logger.debug("configure_vxlan_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    vsi_vni_commands = [f"vsi {cfg.vsi_name}", f"vxlan {cfg.vxlan_vni}", "quit"]
    for command in vsi_vni_commands:
        logger.debug("configure_vxlan_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    tunnel_commands = [
        f"interface tunnel {cfg.tunnel_id} mode vxlan",
        f"source {cfg.tunnel_local_ip}",
        f"destination {cfg.remote_ip}",
        "quit",
    ]
    for command in tunnel_commands:
        logger.debug("configure_vxlan_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    vsi_tunnel_commands = [f"vsi {cfg.vsi_name}", f"tunnel {cfg.tunnel_id}", "quit"]
    for command in vsi_tunnel_commands:
        logger.debug("configure_vxlan_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    reflector_commands = [
        f"interface {cfg.reflector_interface}",
        f"service-instance {cfg.service_instance_id}",
        f"encapsulation s-vid {cfg.remote_probe_vlan}",
        f"xconnect vsi {cfg.vsi_name}",
        "quit",
        "quit",
    ]
    for command in reflector_commands:
        logger.debug("configure_vxlan_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    ports = " ".join(cfg.source_interfaces)
    mirror_commands = [
        f"mirroring-group {cfg.group_id} remote-probe vlan {cfg.remote_probe_vlan}",
        f"mirroring-group {cfg.group_id} mirroring-port {ports} {cfg.direction}",
        f"mirroring-group {cfg.group_id} reflector-port {cfg.reflector_interface}",
    ]
    for command in mirror_commands:
        logger.debug("configure_vxlan_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    conn.exit_config_mode()
    logger.info(
        "configure_vxlan_mirror | groupe {gid} : {srcs} ({dir}) -> vlan sonde {vlan} "
        "-> vsi {vsi}/vni {vni} -> tunnel{tid} (VXLAN vers {remote})",
        gid=cfg.group_id,
        srcs=ports,
        dir=cfg.direction,
        vlan=cfg.remote_probe_vlan,
        vsi=cfg.vsi_name,
        vni=cfg.vxlan_vni,
        tid=cfg.tunnel_id,
        remote=cfg.remote_ip,
    )


def configure_acl_mirror(conn, cfg: MirrorConfig) -> None:
    """Configure un flow mirroring filtré par ACL (mirror-to piloté par QoS policy).

    Contrairement à `configure_local_mirror`/`configure_gre_mirror` (qui
    dupliquent tout le trafic d'un port via `mirroring-group`), cette
    fonction ne duplique que les paquets qui correspondent à
    `cfg.acl_rules` : ACL avancée + `traffic classifier` (`if-match acl`)
    + `traffic behavior` (action `mirror-to`) + `qos policy`, appliquée
    sur `cfg.source_interfaces` dans le(s) sens de `cfg.direction`. Voir
    `CAPTURE-METHODS.md` section 4 pour la syntaxe vérifiée contre la doc
    H3C officielle et ses pièges — notamment `qos apply policy` qui,
    contrairement à `mirroring-group ... mirroring-port ... both`, ne
    prend pas de mot-clé `both` : une commande par sens.

    Args:
        conn: session netmiko déjà connectée.
        cfg: paramètres de mirroring (`filter_mode == "acl"`).
    """
    conn.config_mode()

    acl_commands = [f"acl advanced {cfg.acl_number}", *cfg.acl_rules, "quit"]
    for command in acl_commands:
        logger.debug("configure_acl_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    classifier_commands = [
        f"traffic classifier {cfg.classifier_name}",
        f"if-match acl {cfg.acl_number}",
        "quit",
    ]
    for command in classifier_commands:
        logger.debug("configure_acl_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    if cfg.mode == "local":
        mirror_to_cmd = f"mirror-to interface {cfg.monitor_interface}"
    else:
        mirror_to_cmd = f"mirror-to interface destination-ip {cfg.remote_ip} source-ip {cfg.tunnel_local_ip}"
    behavior_commands = [f"traffic behavior {cfg.behavior_name}", mirror_to_cmd, "quit"]
    for command in behavior_commands:
        logger.debug("configure_acl_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    policy_commands = [
        f"qos policy {cfg.qos_policy_name}",
        f"classifier {cfg.classifier_name} behavior {cfg.behavior_name}",
        "quit",
    ]
    for command in policy_commands:
        logger.debug("configure_acl_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    directions = ("inbound", "outbound") if cfg.direction == "both" else (cfg.direction,)
    for iface in cfg.source_interfaces:
        interface_commands = [f"interface {iface}"]
        interface_commands.extend(f"qos apply policy {cfg.qos_policy_name} {direction}" for direction in directions)
        interface_commands.append("quit")
        for command in interface_commands:
            logger.debug("configure_acl_mirror | {cmd}", cmd=command)
            conn.send_command(command, expect_string=r"\]")

    conn.exit_config_mode()
    logger.info(
        "configure_acl_mirror | ACL {acl} -> classifier {cls} -> behavior {beh} "
        "-> policy {pol} appliquée sur {ifaces} ({dir})",
        acl=cfg.acl_number,
        cls=cfg.classifier_name,
        beh=cfg.behavior_name,
        pol=cfg.qos_policy_name,
        ifaces=", ".join(cfg.source_interfaces),
        dir=cfg.direction,
    )


def teardown_acl_mirror(conn, cfg: MirrorConfig) -> None:
    """Retire un flow mirroring filtré par ACL poussé par `configure_acl_mirror`.

    Retire d'abord l'application de la qos policy sur chaque interface
    source (dans le(s) sens de `cfg.direction`, comme à la configuration),
    puis la policy elle-même, le behavior, le classifier et enfin l'ACL —
    dans cet ordre, requis par Comware (une qos policy encore appliquée
    sur une interface ne peut pas être supprimée, voir doc H3C).

    Args:
        conn: session netmiko déjà connectée.
        cfg: paramètres identifiant les éléments à retirer (mêmes
            `source_interfaces`/`direction`/`acl_number`/`classifier_name`/
            `behavior_name`/`qos_policy_name` qu'à la configuration).
    """
    conn.config_mode()

    directions = ("inbound", "outbound") if cfg.direction == "both" else (cfg.direction,)
    for iface in cfg.source_interfaces:
        interface_commands = [f"interface {iface}"]
        interface_commands.extend(f"undo qos apply policy {direction}" for direction in directions)
        interface_commands.append("quit")
        for command in interface_commands:
            logger.debug("teardown_acl_mirror | {cmd}", cmd=command)
            conn.send_command(command, expect_string=r"\]")

    cleanup_commands = [
        f"undo qos policy {cfg.qos_policy_name}",
        f"undo traffic behavior {cfg.behavior_name}",
        f"undo traffic classifier {cfg.classifier_name}",
        f"undo acl advanced {cfg.acl_number}",
    ]
    for command in cleanup_commands:
        logger.debug("teardown_acl_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    conn.exit_config_mode()
    logger.info(
        "teardown_acl_mirror | ACL {acl} / classifier {cls} / behavior {beh} / "
        "policy {pol} retirés (interfaces : {ifaces})",
        acl=cfg.acl_number,
        cls=cfg.classifier_name,
        beh=cfg.behavior_name,
        pol=cfg.qos_policy_name,
        ifaces=", ".join(cfg.source_interfaces),
    )


def teardown_vxlan_mirror(conn, cfg: MirrorConfig) -> None:
    """Retire un mirroring vers VLAN sonde + VXLAN L2 poussé par `configure_vxlan_mirror`.

    Ordre inverse de la configuration, en retirant d'abord le groupe de
    mirroring (dépend du reflector port), puis le raccordement VSI du
    reflector port, puis le tunnel et son association à la VSI, puis la
    VSI et enfin le VLAN sonde — un élément encore référencé ne peut pas
    être supprimé (même logique que `teardown_acl_mirror`).

    Args:
        conn: session netmiko déjà connectée.
        cfg: paramètres identifiant les éléments à retirer (mêmes
            `group_id`/`reflector_interface`/`service_instance_id`/
            `tunnel_id`/`vsi_name`/`remote_probe_vlan` qu'à la
            configuration).
    """
    conn.config_mode()

    undo_mirror_cmd = f"undo mirroring-group {cfg.group_id}"
    logger.debug("teardown_vxlan_mirror | {cmd}", cmd=undo_mirror_cmd)
    conn.send_command(undo_mirror_cmd, expect_string=r"\]")

    reflector_commands = [
        f"interface {cfg.reflector_interface}",
        f"undo service-instance {cfg.service_instance_id}",
        "quit",
    ]
    for command in reflector_commands:
        logger.debug("teardown_vxlan_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    vsi_tunnel_commands = [f"vsi {cfg.vsi_name}", f"undo tunnel {cfg.tunnel_id}", "quit"]
    for command in vsi_tunnel_commands:
        logger.debug("teardown_vxlan_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    undo_tunnel_cmd = f"undo interface tunnel {cfg.tunnel_id}"
    logger.debug("teardown_vxlan_mirror | {cmd}", cmd=undo_tunnel_cmd)
    output = conn.send_command_timing(undo_tunnel_cmd, read_timeout=15)
    if "Continue?" in output or "[Y/N]" in output:
        logger.debug("teardown_vxlan_mirror | confirmation envoyée (y)")
        conn.send_command_timing("y", read_timeout=15)

    cleanup_commands = [
        f"undo vsi {cfg.vsi_name}",
        f"undo vlan {cfg.remote_probe_vlan}",
    ]
    for command in cleanup_commands:
        logger.debug("teardown_vxlan_mirror | {cmd}", cmd=command)
        conn.send_command(command, expect_string=r"\]")

    conn.exit_config_mode()
    logger.info(
        "teardown_vxlan_mirror | groupe {gid} / vsi {vsi} / tunnel{tid} / vlan sonde {vlan} retirés",
        gid=cfg.group_id,
        vsi=cfg.vsi_name,
        tid=cfg.tunnel_id,
        vlan=cfg.remote_probe_vlan,
    )


def teardown_mirror(conn, cfg: MirrorConfig) -> None:
    """Retire la configuration de mirroring poussée (groupe + tunnel éventuel).

    Args:
        conn: session netmiko déjà connectée.
        cfg: paramètres identifiant le groupe/tunnel à retirer (mêmes
            `group_id`/`tunnel_id`/`mode` qu'à la configuration).
    """
    conn.config_mode()
    undo_mirror_cmd = f"undo mirroring-group {cfg.group_id}"
    logger.debug("teardown_mirror | {cmd}", cmd=undo_mirror_cmd)
    conn.send_command(undo_mirror_cmd, expect_string=r"\]")
    if cfg.mode == "gre":
        undo_tunnel_cmd = f"undo interface tunnel {cfg.tunnel_id}"
        logger.debug("teardown_mirror | {cmd}", cmd=undo_tunnel_cmd)
        output = conn.send_command_timing(undo_tunnel_cmd, read_timeout=15)
        if "Continue?" in output or "[Y/N]" in output:
            logger.debug("teardown_mirror | confirmation envoyée (y)")
            conn.send_command_timing("y", read_timeout=15)
    conn.exit_config_mode()
    logger.info("teardown_mirror | groupe {gid} retiré", gid=cfg.group_id)


class MirrorThread(threading.Thread):
    """Pousse (ou retire) une configuration de mirroring, en tâche de fond.

    Contrairement à `SetupAndCaptureThread`, ce thread ne bloque pas
    indéfiniment : il pousse la configuration puis se termine — le
    mirroring continue de fonctionner sur le switch sans supervision une
    fois configuré (ce n'est pas un flux à rapatrier/rotater comme
    packet-capture).
    """

    def __init__(self, mirror_cfg: MirrorConfig, teardown: bool = False, on_done=None) -> None:
        """Initialise le thread.

        Args:
            mirror_cfg: paramètres de mirroring à pousser (ou à retirer).
            teardown: si True, retire la configuration au lieu de la pousser.
            on_done: callback optionnel `(success: bool, message: str) -> None`.
        """
        super().__init__(name="mirror-config", daemon=True)
        self.mirror_cfg = mirror_cfg
        self.teardown = teardown
        self.on_done = on_done

    def run(self) -> None:
        """Point d'entrée du thread : connexion, action, déconnexion."""
        device = {
            "device_type": "hp_comware",
            "host": self.mirror_cfg.switch_ip,
            "username": self.mirror_cfg.ssh_user,
            "password": self.mirror_cfg.ssh_password,
            "fast_cli": False,
        }
        if ConnectHandler is None:
            self._finish(False, "netmiko manquant : pip install netmiko")
            return
        try:
            conn = ConnectHandler(**device)
            try:
                if self.teardown:
                    if self.mirror_cfg.filter_mode == "acl":
                        teardown_acl_mirror(conn, self.mirror_cfg)
                        self._finish(
                            True,
                            f"Flow mirroring ACL {self.mirror_cfg.acl_number} retiré",
                        )
                    elif self.mirror_cfg.mode == "vxlan":
                        teardown_vxlan_mirror(conn, self.mirror_cfg)
                        self._finish(
                            True,
                            f"Mirroring VXLAN groupe {self.mirror_cfg.group_id} retiré",
                        )
                    else:
                        teardown_mirror(conn, self.mirror_cfg)
                        self._finish(True, f"Mirroring groupe {self.mirror_cfg.group_id} retiré")
                elif self.mirror_cfg.filter_mode == "acl":
                    configure_acl_mirror(conn, self.mirror_cfg)
                    self._finish(
                        True,
                        f"Flow mirroring ACL {self.mirror_cfg.acl_number} configuré "
                        f"(policy {self.mirror_cfg.qos_policy_name})",
                    )
                elif self.mirror_cfg.mode == "local":
                    configure_local_mirror(conn, self.mirror_cfg)
                    self._finish(
                        True,
                        f"Mirroring local configuré (groupe {self.mirror_cfg.group_id})",
                    )
                elif self.mirror_cfg.mode == "vxlan":
                    configure_vxlan_mirror(conn, self.mirror_cfg)
                    self._finish(
                        True,
                        f"Mirroring VXLAN configuré (groupe {self.mirror_cfg.group_id}, "
                        f"vlan sonde {self.mirror_cfg.remote_probe_vlan} -> vsi "
                        f"{self.mirror_cfg.vsi_name} -> tunnel{self.mirror_cfg.tunnel_id} "
                        f"-> {self.mirror_cfg.remote_ip})",
                    )
                else:
                    configure_gre_mirror(conn, self.mirror_cfg)
                    self._finish(
                        True,
                        f"Mirroring GRE configuré (groupe {self.mirror_cfg.group_id}, "
                        f"tunnel{self.mirror_cfg.tunnel_id} -> {self.mirror_cfg.remote_ip})",
                    )
            finally:
                conn.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.exception("mirror | échec")
            self._finish(False, str(exc))

    def _finish(self, success: bool, message: str) -> None:
        """Invoque le callback de fin, s'il a été fourni.

        Args:
            success: True si l'opération s'est bien déroulée.
            message: message à afficher à l'utilisateur.
        """
        if self.on_done:
            self.on_done(success, message)
