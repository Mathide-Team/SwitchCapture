#!/usr/bin/env bash
# install.sh — installation complète de switch-capture, sans passer par un
# paquet .deb/.rpm : détecte la distribution, installe les prérequis
# système + Python, crée l'arborescence, copie l'application.
#
# Distributions supportées :
#   - Ubuntu / Debian                          (APT)
#   - Rocky Linux / RHEL / CentOS Stream / AlmaLinux / Oracle Linux, 8 & 9
#     (DNF ; el8 utilise python3.11, el9 utilise le python3 système)
#
# Usage :
#   sudo ./install.sh [-y|--yes] [--prefix DIR]
#
#   -y, --yes      n'affiche pas la confirmation avant de modifier le système
#   --prefix DIR   racine d'installation (def: /) — utile pour un test en
#                  chroot/conteneur, PAS pour un usage courant
#
# Doit être exécuté depuis la racine du dépôt (à côté de src/, qui contient
# switch_capture_core.py / switch_capture_cli.py / docs/) — c'est la même
# racine src/ que celle utilisée par packaging/build_deb.sh et
# packaging-rpm/build_rpm.sh : une seule copie du code et des docs
# partagées, jamais trois.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"
ASSUME_YES=0
PREFIX=""

# --------------------------------------------------------------------------- #
# Arguments
# --------------------------------------------------------------------------- #
while [ $# -gt 0 ]; do
    case "$1" in
        -y|--yes) ASSUME_YES=1 ;;
        --prefix) PREFIX="${2:-}"; shift ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *)
            echo "Option inconnue : $1" >&2
            exit 2
            ;;
    esac
    shift
done

# --------------------------------------------------------------------------- #
# Chemins d'installation
# --------------------------------------------------------------------------- #
BIN_DIR="${PREFIX}/usr/bin"
LIB_DIR="${PREFIX}/usr/lib/switch-capture"
DOC_DIR="${PREFIX}/usr/share/doc/switch-capture"
ETC_DIR="${PREFIX}/etc/switch-capture"
FEATURE_BIN_DIR="${ETC_DIR}/feature-bin"
VAR_DIR="${PREFIX}/var/lib/switch-capture"
ICON_DIR="${PREFIX}/usr/share/icons/hicolor/scalable/apps"
DESKTOP_DIR="${PREFIX}/usr/share/applications"
GROUP_NAME="switch-capture"

log()  { printf '==> %s\n' "$1"; }
warn() { printf 'AVERTISSEMENT : %s\n' "$1" >&2; }
die()  { printf 'ERREUR : %s\n' "$1" >&2; exit 1; }

# --------------------------------------------------------------------------- #
# Pré-vérifications
# --------------------------------------------------------------------------- #
if [ "$(id -u)" -ne 0 ]; then
    die "ce script doit être lancé en root (sudo ./install.sh)."
fi

for f in switch_capture_core.py switch_capture_cli.py; do
    [ -f "$SRC_DIR/$f" ] || die "fichier manquant : src/$f (lancez le script depuis la racine du dépôt)"
done
[ -d "$SRC_DIR/docs" ] || die "dossier 'src/docs/' manquant à côté de install.sh"

# --------------------------------------------------------------------------- #
# Détection de la distribution
# --------------------------------------------------------------------------- #
FAMILY=""
MAJOR=""

if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    ID="${ID:-}"
    ID_LIKE="${ID_LIKE:-}"
    VERSION_ID="${VERSION_ID:-}"

    case "$ID" in
        ubuntu|debian) FAMILY="debian" ;;
        rocky|rhel|centos|almalinux|ol) FAMILY="rhel" ;;
        *)
            case "$ID_LIKE" in
                *debian*) FAMILY="debian" ;;
                *rhel*|*fedora*) FAMILY="rhel" ;;
            esac
            ;;
    esac
    MAJOR="${VERSION_ID%%.*}"
fi

[ -n "$FAMILY" ] || die "distribution non reconnue (/etc/os-release absent ou ID inconnu : ${ID:-?}). Support : Ubuntu, Debian, Rocky, RHEL, CentOS Stream, AlmaLinux, Oracle Linux."

log "Distribution détectée : ${PRETTY_NAME:-$ID} (famille=$FAMILY${MAJOR:+, majeure=$MAJOR})"

if [ "$FAMILY" = "rhel" ] && [ "$MAJOR" != "8" ] && [ "$MAJOR" != "9" ]; then
    warn "version majeure '$MAJOR' non testée (seules el8/el9 le sont) — poursuite sur la base d'el9."
    MAJOR="9"
fi

# --------------------------------------------------------------------------- #
# Confirmation
# --------------------------------------------------------------------------- #
if [ "$ASSUME_YES" -ne 1 ]; then
    cat <<SUMMARY

Ce script va :
  - installer les paquets système requis (sshfs/fuse-sshfs, wireshark,
    python3 + pip, ...) via ${FAMILY}
  - installer netmiko/loguru(/PyYAML) via pip
  - créer /etc/switch-capture, /var/lib/switch-capture et le groupe
    système '${GROUP_NAME}'
  - installer l'application dans /usr/lib/switch-capture et
    /usr/bin/switch-capture

SUMMARY
    printf 'Continuer ? [o/N] '
    read -r reply
    case "$reply" in
        o|O|oui|Oui|y|Y|yes) ;;
        *) echo "Annulé."; exit 0 ;;
    esac
fi

# --------------------------------------------------------------------------- #
# Dépendances système + choix de l'interpréteur Python
# --------------------------------------------------------------------------- #
# Principe : les paquets système (APT/DNF) sont TOUJOURS essayés en premier
# pour netmiko/loguru/PyYAML — pip n'est qu'un repli si le paquet n'existe
# pas dans les dépôts configurés (ancienne version de distro, EPEL
# incomplet...). GTK4/PyGObject sont toujours installés en best-effort
# (jamais de pip pour PyGObject : ça ne fonctionne pas proprement hors
# gestionnaire système) ; leur absence n'empêche pas l'installation, la CLI
# (-c) reste utilisable.
PYTHON_BIN=""
PIP_EXTRA_ARGS=""
GTK_AVAILABLE=0
TAPHELPER_TOOLCHAIN_AVAILABLE=0

apt_install_or_pip_fallback() {
    # $1 = paquet APT, $2 = spec pip de repli
    if DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$1"; then
        return 0
    fi
    warn "$1 indisponible via APT — repli sur pip ($2)."
    # shellcheck disable=SC2086
    "$PYTHON_BIN" -m pip install --no-warn-script-location $PIP_EXTRA_ARGS "$2" \
        || die "échec d'installation de $2 (ni APT ni pip)."
}

dnf_install_or_pip_fallback() {
    # $1 = paquet DNF, $2 = spec pip de repli
    if dnf install -y "$1" >/dev/null 2>&1; then
        return 0
    fi
    warn "$1 indisponible via DNF (EPEL incomplet ?) — repli sur pip ($2)."
    "$PYTHON_BIN" -m pip install --no-warn-script-location "$2" \
        || die "échec d'installation de $2 (ni DNF ni pip)."
}

install_debian_deps() {
    log "APT : mise à jour des index"
    if ! DEBIAN_FRONTEND=noninteractive apt-get update -qq; then
        warn "'apt-get update' a échoué sur au moins un dépôt (dépôt tiers cassé ?) — poursuite avec le cache existant."
    fi

    # wireshark demande en interactif si dumpcap doit être installé setuid
    # (accès capture sans root) : on préseed sur "non" par défaut, à
    # ajuster ensuite avec 'sudo dpkg-reconfigure wireshark-common' si
    # un accès non-root est souhaité.
    echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections || true

    log "APT : installation des paquets système de base"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        python3 python3-pip python3-yaml wireshark openssh-client iproute2

    PYTHON_BIN="$(command -v python3)"
    PIP_EXTRA_ARGS="--break-system-packages"

    log "APT : netmiko / loguru / paramiko / scp (repli pip si absents des dépôts)"
    apt_install_or_pip_fallback python3-netmiko "netmiko>=4.3"
    apt_install_or_pip_fallback python3-loguru "loguru>=0.7"
    apt_install_or_pip_fallback python3-paramiko "paramiko>=2.7"
    apt_install_or_pip_fallback python3-scp "scp>=0.14"

    log "APT : sshfs (optionnel — seulement pour --transfer-mode sshfs, legacy)"
    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y -qq sshfs; then
        warn "sshfs indisponible — sans effet par défaut (transfer_mode=scp), seul --transfer-mode sshfs serait impacté."
    fi

    log "APT : GTK4/PyGObject (optionnel — interface graphique)"
    if DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-gi gir1.2-gtk-4.0; then
        GTK_AVAILABLE=1
    else
        warn "python3-gi/gir1.2-gtk-4.0 indisponibles — seule la CLI (-c) sera utilisable."
    fi

    log "APT : gcc/libcap2-bin (optionnel — mode TAP sans root, voir switch-capture-taphelper)"
    if DEBIAN_FRONTEND=noninteractive apt-get install -y -qq gcc libcap2-bin; then
        TAPHELPER_TOOLCHAIN_AVAILABLE=1
    else
        warn "gcc/setcap indisponibles — le mode TAP (--output-mode tap) nécessitera de lancer switch-capture en root."
    fi
}

install_rhel_deps() {
    log "DNF : activation d'EPEL"
    if ! dnf install -y epel-release >/dev/null 2>&1; then
        dnf install -y "https://dl.fedoraproject.org/pub/epel/epel-release-latest-${MAJOR}.noarch.rpm" \
            || warn "impossible d'activer EPEL automatiquement (RHEL enregistré ? réseau ?) — fuse-sshfs pourrait échouer."
    fi

    if [ "$MAJOR" = "9" ]; then
        dnf config-manager --set-enabled crb >/dev/null 2>&1 || warn "impossible d'activer le dépôt CRB (non bloquant)."
    else
        dnf config-manager --set-enabled powertools >/dev/null 2>&1 \
            || dnf config-manager --set-enabled powertools-source >/dev/null 2>&1 \
            || warn "impossible d'activer le dépôt PowerTools (non bloquant)."
    fi

    log "DNF : installation des paquets système de base"
    dnf install -y wireshark openssh-clients iproute
    if ! dnf install -y fuse-sshfs; then
        warn "fuse-sshfs indisponible — sans effet par défaut (transfer_mode=scp), seul --transfer-mode sshfs serait impacté."
    fi

    if [ "$MAJOR" = "8" ]; then
        if dnf install -y python3.11 python3.11-pip 2>/dev/null; then
            PYTHON_BIN="/usr/bin/python3.11"
        else
            warn "python3.11 indisponible (el8 < 8.9 ?) — repli sur le module python39."
            dnf module enable -y python39
            dnf install -y python39 python39-pip
            PYTHON_BIN="/usr/bin/python3.9"
        fi
        PIP_EXTRA_ARGS=""

        # IMPORTANT : sur el8, l'interpréteur retenu (python3.11/3.9) est
        # DIFFÉRENT du python3 système (3.6) pour lequel les paquets
        # python3-netmiko/python3-loguru/python3-pyyaml/python3-paramiko/
        # python3-scp/python3-gobject sont construits. dnf install de ces
        # paquets ne les rendrait PAS visibles depuis python3.11
        # (site-packages séparés). Sur el8, on utilise donc directement pip
        # pour ceux-là, et GTK4 n'est pas proposé (pas de python3.11-gobject
        # dans les dépôts standards).
        log "el8 : netmiko/loguru/PyYAML/paramiko/scp via pip (python3-* système ne conviendrait pas à $PYTHON_BIN)"
        "$PYTHON_BIN" -m pip install --no-warn-script-location \
            "netmiko>=4.3" "loguru>=0.7" "PyYAML>=6.0" "paramiko>=2.7" "scp>=0.14" \
            || die "échec pip. Relancez manuellement : $PYTHON_BIN -m pip install netmiko loguru PyYAML paramiko scp"
        warn "GTK4 non proposé sur el8 (pas de python3.11-gobject dans les dépôts standards) — seule la CLI (-c) sera utilisable."
    else
        dnf install -y python3 python3-pip
        PYTHON_BIN="/usr/bin/python3"
        PIP_EXTRA_ARGS=""

        log "DNF : netmiko / loguru / PyYAML / paramiko / scp (repli pip si absents des dépôts EPEL)"
        dnf_install_or_pip_fallback python3-netmiko "netmiko>=4.3"
        dnf_install_or_pip_fallback python3-loguru "loguru>=0.7"
        dnf_install_or_pip_fallback python3-pyyaml "PyYAML>=6.0"
        dnf_install_or_pip_fallback python3-paramiko "paramiko>=2.7"
        dnf_install_or_pip_fallback python3-scp "scp>=0.14"

        log "DNF : GTK4/PyGObject (optionnel — interface graphique)"
        if dnf install -y python3-gobject gtk4 >/dev/null 2>&1; then
            GTK_AVAILABLE=1
        else
            warn "python3-gobject/gtk4 indisponibles — seule la CLI (-c) sera utilisable."
        fi
    fi

    log "DNF : gcc/libcap (optionnel — mode TAP sans root, voir switch-capture-taphelper)"
    if dnf install -y gcc libcap >/dev/null 2>&1; then
        TAPHELPER_TOOLCHAIN_AVAILABLE=1
    else
        warn "gcc/setcap indisponibles — le mode TAP (--output-mode tap) nécessitera de lancer switch-capture en root."
    fi
}
case "$FAMILY" in
    debian) install_debian_deps ;;
    rhel)   install_rhel_deps ;;
esac

[ -x "$PYTHON_BIN" ] || die "interpréteur Python introuvable après installation ($PYTHON_BIN)."
PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
log "Interpréteur retenu : $PYTHON_BIN (Python $PY_VERSION)"
if [ "$GTK_AVAILABLE" = "1" ]; then
    log "GTK4/PyGObject disponibles : l'app démarrera en mode graphique par défaut (sans args)."
else
    log "GTK4/PyGObject absents : CLI uniquement (-c), c'est aussi ce que fait le mode auto sans args."
fi
if [ "$TAPHELPER_TOOLCHAIN_AVAILABLE" = "1" ]; then
    log "gcc/setcap disponibles : le mode TAP (--output-mode tap) pourra tourner sans root, voir switch-capture-taphelper plus bas."
else
    log "gcc/setcap absents : le mode TAP (--output-mode tap) nécessitera de lancer switch-capture en root (ip tuntap/ip link directement)."
fi

# --------------------------------------------------------------------------- #
# Groupe système + arborescence
# --------------------------------------------------------------------------- #
log "Création du groupe système '${GROUP_NAME}' (si absent)"
groupadd -f -r "$GROUP_NAME"

log "Création de l'arborescence"
install -d -m 755 "$ETC_DIR"
install -d -m 2775 -o root -g "$GROUP_NAME" "$FEATURE_BIN_DIR"
install -d -m 2775 -o root -g "$GROUP_NAME" "$VAR_DIR"
install -d -m 2775 -o root -g "$GROUP_NAME" "$VAR_DIR/mount"
install -d -m 2775 -o root -g "$GROUP_NAME" "$VAR_DIR/spool"
install -d -m 2775 -o root -g "$GROUP_NAME" "$VAR_DIR/archive"
# BIN_DIR (${PREFIX}/usr/bin) existe toujours déjà sur une vraie install
# (PREFIX="") : ce install -d n'était donc jusqu'ici jamais nécessaire en
# usage réel, mais son absence faisait échouer un --prefix pointant vers un
# répertoire réellement vide (pas un chroot/conteneur déjà pourvu d'un
# usr/bin) — trouvé en testant ce script avec --prefix ainsi. Corrigé ici
# indépendamment du reste de cette session (aucun lien avec l'icône/le
# découplage TAP), voir CLAUDE.md.
install -d -m 755 "$BIN_DIR"
install -d -m 755 "$LIB_DIR"
install -d -m 755 "$DOC_DIR"
install -d -m 755 "$ICON_DIR"
install -d -m 755 "$DESKTOP_DIR"

# --------------------------------------------------------------------------- #
# Import d'un dépôt de .bin préparé localement (à côté de src/)
# --------------------------------------------------------------------------- #
# Convention : un dossier "feature-bin/" à la racine du dépôt (sibling de
# src/), avec l'arborescence <modèle>/<version>/*.bin décrite dans
# src/docs/README-feature-bin.md. S'il existe, on l'importe automatiquement
# dans $FEATURE_BIN_DIR à chaque exécution du script (fusion, rien n'est
# supprimé côté cible) : pas besoin de recopier les .bin à la main après
# chaque install/mise à jour.
LOCAL_FEATURE_BIN_DIR="$SCRIPT_DIR/feature-bin"
if [ -d "$LOCAL_FEATURE_BIN_DIR" ]; then
    log "Import de $LOCAL_FEATURE_BIN_DIR/ vers $FEATURE_BIN_DIR/"
    cp -a "$LOCAL_FEATURE_BIN_DIR/." "$FEATURE_BIN_DIR/"
    chown -R "root:$GROUP_NAME" "$FEATURE_BIN_DIR"
    find "$FEATURE_BIN_DIR" -type d -exec chmod 2775 {} \;
    find "$FEATURE_BIN_DIR" -type f -exec chmod 664 {} \;
elif [ -d "$SCRIPT_DIR/features-bin" ]; then
    warn "dossier 'features-bin' trouvé (avec un 's') à la racine du dépôt — le nom attendu est 'feature-bin' (sans 's'), voir src/docs/README-feature-bin.md. Renommez-le pour qu'il soit importé automatiquement : mv features-bin feature-bin"
fi

# --------------------------------------------------------------------------- #
# Installation de l'application
# --------------------------------------------------------------------------- #
log "Vérification syntaxique du code"
"$PYTHON_BIN" -m py_compile \
    "$SRC_DIR/switch_capture_core.py" \
    "$SRC_DIR/switch_capture_cli.py" \
    "$SRC_DIR/switch-capture" \
    "$SRC_DIR/switch_capture_gtk.py"

log "Copie des fichiers applicatifs"
install -m 644 "$SRC_DIR/switch_capture_core.py" "$LIB_DIR/switch_capture_core.py"
install -m 644 "$SRC_DIR/switch_capture_cli.py" "$LIB_DIR/switch_capture_cli.py"
install -m 644 "$SRC_DIR/switch_capture_gtk.py" "$LIB_DIR/switch_capture_gtk.py"
install -m 644 "$SRC_DIR/docs/USAGE.md" "$DOC_DIR/USAGE.md"
install -m 644 "$SRC_DIR/docs/README-feature-bin.md" "$DOC_DIR/README-feature-bin.md"
install -m 644 "$SRC_DIR/docs/CAPTURE-METHODS.md" "$DOC_DIR/CAPTURE-METHODS.md"
install -m 644 "$SRC_DIR/docs/config.yaml.example" "$DOC_DIR/config.yaml.example"
install -m 644 "$SRC_DIR/docs/INSTALL.md" "$DOC_DIR/INSTALL.md"

log "Installation du lanceur $BIN_DIR/switch-capture"
# src/switch-capture EST le point d'entrée (CLI + GTK4) : simple copie, pas
# de wrapper régénéré à la main — seule la ligne shebang est réécrite pour
# pointer vers l'interpréteur retenu à l'étape précédente (important sur
# el8, où ce n'est pas /usr/bin/python3).
install -m 755 "$SRC_DIR/switch-capture" "$BIN_DIR/switch-capture"
sed -i "1s|^#!.*|#!${PYTHON_BIN}|" "$BIN_DIR/switch-capture"

# --------------------------------------------------------------------------- #
# Aide privilégiée switch-capture-taphelper (mode TAP sans root)
# --------------------------------------------------------------------------- #
# Seul morceau de switch-capture qui a besoin de privilèges (CAP_NET_ADMIN,
# jamais setuid/root) : créer/activer une interface TAP. Compilée puis
# installée dans $LIB_DIR à côté du code applicatif, avec cap_net_admin+ep
# positionné via setcap. Best-effort : si gcc/setcap sont absents
# (TAPHELPER_TOOLCHAIN_AVAILABLE=0), on l'indique clairement et on continue
# sans bloquer l'installation — switch_capture_core.py retombe alors sur
# `ip` directement (root requis pour le mode TAP uniquement, comme avant
# cette fonctionnalité). Voir CLAUDE.md/features.md pour le détail.
if [ "$TAPHELPER_TOOLCHAIN_AVAILABLE" = "1" ]; then
    log "Compilation de switch-capture-taphelper (mode TAP sans root)"
    if gcc -O2 -o "$LIB_DIR/switch-capture-taphelper" "$SRC_DIR/helpers/switch-capture-taphelper.c"; then
        chmod 755 "$LIB_DIR/switch-capture-taphelper"
        if setcap cap_net_admin+ep "$LIB_DIR/switch-capture-taphelper"; then
            log "switch-capture-taphelper installé avec cap_net_admin+ep : le mode TAP n'exige plus root."
        else
            warn "setcap a échoué sur switch-capture-taphelper — le mode TAP nécessitera root tant que la capability n'est pas positionnée manuellement :"
            warn "  sudo setcap cap_net_admin+ep $LIB_DIR/switch-capture-taphelper"
        fi
    else
        warn "échec de compilation de switch-capture-taphelper — le mode TAP nécessitera de lancer switch-capture en root."
    fi
else
    warn "gcc/setcap absents : switch-capture-taphelper non installé, le mode TAP nécessitera de lancer switch-capture en root."
fi

log "Installation de l'icône et de l'entrée menu applications"
# Icône dans le thème hicolor standard (résolue via Icon=org.transcende.
# switch_capture dans le .desktop, et via _GTK_APPLICATION_ID pour les
# environnements qui font la correspondance directement — voir
# switch_capture_gtk.py, _register_app_icon). gtk-update-icon-cache et
# update-desktop-database sont best-effort : absents sur certains systèmes
# minimaux, et de toute façon généralement redéclenchés par le gestionnaire
# de paquets sur les installations via .deb/.rpm — jamais bloquant ici.
install -m 644 "$SRC_DIR/icons/hicolor/scalable/apps/org.transcende.switch_capture.svg" \
    "$ICON_DIR/org.transcende.switch_capture.svg"
install -m 644 "$SRC_DIR/org.transcende.switch_capture.desktop" \
    "$DESKTOP_DIR/org.transcende.switch_capture.desktop"
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "${PREFIX}/usr/share/icons/hicolor" 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q "$DESKTOP_DIR" 2>/dev/null || true
fi

# --------------------------------------------------------------------------- #
# Résumé
# --------------------------------------------------------------------------- #
cat <<SUMMARY

Installation terminée.

  - Exécutable          : $BIN_DIR/switch-capture
  - Code applicatif      : $LIB_DIR/
  - Dépôt des .bin        : $FEATURE_BIN_DIR/
  - Données runtime       : $VAR_DIR/{mount,spool,archive}/
  - Documentation         : $DOC_DIR/
  - Icône / menu apps     : $ICON_DIR/, $DESKTOP_DIR/

Le groupe système '${GROUP_NAME}' possède ces dossiers en écriture (setgid).
Pour qu'un utilisateur non-root puisse y écrire (déposer un .bin, lancer une
capture avec ces dossiers comme spool/mount par défaut) :

  sudo usermod -aG ${GROUP_NAME} <votre_utilisateur>
  # puis se déconnecter/reconnecter (ou 'newgrp ${GROUP_NAME}')

Mode TAP (--output-mode tap) sans root : $( [ -f "$LIB_DIR/switch-capture-taphelper" ] && getcap "$LIB_DIR/switch-capture-taphelper" 2>/dev/null | grep -q cap_net_admin && echo "OK ($LIB_DIR/switch-capture-taphelper, cap_net_admin+ep)." || echo "indisponible cette fois — switch-capture devra tourner en root pour ce mode (voir avertissements ci-dessus)." )

Test rapide :
  switch-capture --help
  switch-capture              # GUI si GTK4 dispo, sinon aide CLI
  switch-capture -c capture --help
  switch-capture -g           # force la GUI

SUMMARY
