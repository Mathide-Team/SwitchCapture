#!/bin/sh
# build_deb.sh — génère switch-capture_<version>_<arch>.deb
#
# Ne contient QUE les métadonnées .deb (packaging/debian/DEBIAN/). Le code
# applicatif et les docs partagées sont lus depuis ../src/ (source unique,
# aussi utilisée par install.sh et packaging-rpm/build_rpm.sh) et copiés
# dans l'arborescence FHS ici, au moment du build — exactement le même
# principe que build_rpm.sh (spec %install) et install.sh.
#
# Utilise uniquement dpkg-deb (paquet dpkg-dev), pas de dépendance à
# devscripts/debuild.
#
# Usage :
#   chmod +x packaging/build_deb.sh
#   ./packaging/build_deb.sh
#
# Produit : packaging/switch-capture_<version>_<arch>.deb (architecture de
# la machine de build, ex: amd64 -- plus "_all" depuis l'ajout de
# switch-capture-taphelper, binaire compilé, voir DEBIAN/postinst)

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$ROOT_DIR/src"
META_DIR="$SCRIPT_DIR/debian/DEBIAN"
INSTALL_DOC="$SCRIPT_DIR/INSTALL-deb.md"

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "dpkg-deb introuvable. Installez-le avec : sudo apt install dpkg-dev" >&2
    exit 1
fi
if ! command -v dpkg >/dev/null 2>&1; then
    echo "dpkg introuvable (nécessaire pour déterminer l'architecture de build)." >&2
    exit 1
fi
BUILD_ARCH="$(dpkg --print-architecture)"

VERSION="$(awk '/^Version:/ {print $2}' "$META_DIR/control")"
PKG_NAME="switch-capture_${VERSION}_${BUILD_ARCH}"
BUILD_DIR="$SCRIPT_DIR/build/${PKG_NAME}"
OUT_FILE="$SCRIPT_DIR/${PKG_NAME}.deb"

for f in "$SRC_DIR/switch_capture_core.py" "$SRC_DIR/switch_capture_cli.py" "$SRC_DIR/switch-capture" "$SRC_DIR/switch_capture_gtk.py" "$SRC_DIR/icons/hicolor/scalable/apps/org.transcende.switch_capture.svg" "$SRC_DIR/org.transcende.switch_capture.desktop" "$SRC_DIR/helpers/switch-capture-taphelper.c" "$INSTALL_DOC"; do
    [ -f "$f" ] || { echo "fichier source manquant : $f" >&2; exit 1; }
done
if ! command -v gcc >/dev/null 2>&1; then
    echo "gcc introuvable (nécessaire pour compiler switch-capture-taphelper, mode TAP sans root). Installez-le avec : sudo apt install gcc" >&2
    exit 1
fi

echo "==> Nettoyage de $BUILD_DIR"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

echo "==> Métadonnées du paquet (packaging/debian/DEBIAN/)"
mkdir -p "$BUILD_DIR/DEBIAN"
cp "$META_DIR/control" "$META_DIR/postinst" "$META_DIR/postrm" "$BUILD_DIR/DEBIAN/"
# debian/DEBIAN/control contient "Architecture: __BUILD_ARCH__" : les
# fichiers control n'acceptent pas de lignes de commentaire ("#") pour
# expliquer ce placeholder in situ, d'où l'explication ici. dpkg-deb exige
# une architecture concrète dans le control d'un paquet binaire (pas "any",
# valide seulement dans un debian/control *source* résolu par
# dpkg-buildpackage — non utilisé ici, ce script appelle dpkg-deb
# directement). Ne peut plus être "all" depuis switch-capture-taphelper
# (binaire compilé) : le paquet est désormais spécifique à l'architecture
# de build.
sed -i "s/__BUILD_ARCH__/${BUILD_ARCH}/" "$BUILD_DIR/DEBIAN/control"

echo "==> Arborescence applicative (depuis ../src/)"
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/lib/switch-capture"
mkdir -p "$BUILD_DIR/usr/share/doc/switch-capture"
mkdir -p "$BUILD_DIR/etc/switch-capture/feature-bin"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$BUILD_DIR/usr/share/applications"

cp "$SRC_DIR/switch_capture_core.py" "$BUILD_DIR/usr/lib/switch-capture/switch_capture_core.py"
cp "$SRC_DIR/switch_capture_cli.py" "$BUILD_DIR/usr/lib/switch-capture/switch_capture_cli.py"
cp "$SRC_DIR/switch_capture_gtk.py" "$BUILD_DIR/usr/lib/switch-capture/switch_capture_gtk.py"
cp "$SRC_DIR/docs/USAGE.md" "$BUILD_DIR/usr/share/doc/switch-capture/USAGE.md"
cp "$SRC_DIR/docs/README-feature-bin.md" "$BUILD_DIR/usr/share/doc/switch-capture/README-feature-bin.md"
cp "$SRC_DIR/docs/CAPTURE-METHODS.md" "$BUILD_DIR/usr/share/doc/switch-capture/CAPTURE-METHODS.md"
cp "$SRC_DIR/docs/config.yaml.example" "$BUILD_DIR/usr/share/doc/switch-capture/config.yaml.example"
cp "$INSTALL_DOC" "$BUILD_DIR/usr/share/doc/switch-capture/INSTALL.md"   # doc spécifique .deb, pas la générique

echo "==> Compilation de switch-capture-taphelper (mode TAP sans root ; cap_net_admin+ep positionné par DEBIAN/postinst)"
gcc -O2 -o "$BUILD_DIR/usr/lib/switch-capture/switch-capture-taphelper" "$SRC_DIR/helpers/switch-capture-taphelper.c"

# src/switch-capture EST le point d'entrée (CLI + GTK4) : simple copie, la
# ligne shebang du fichier source (#!/usr/bin/env python3) convient déjà
# telle quelle pour Debian/Ubuntu (python3 système, pas d'alternative comme
# sur el8) — pas de wrapper régénéré à la main.
cp "$SRC_DIR/switch-capture" "$BUILD_DIR/usr/bin/switch-capture"
sed -i "1s|^#!.*|#!/usr/bin/python3|" "$BUILD_DIR/usr/bin/switch-capture"

# Icône (thème hicolor) + entrée menu applications — voir switch_capture_gtk.py
# (_register_app_icon) pour la résolution en lancement non installé.
cp "$SRC_DIR/icons/hicolor/scalable/apps/org.transcende.switch_capture.svg" \
    "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps/org.transcende.switch_capture.svg"
cp "$SRC_DIR/org.transcende.switch_capture.desktop" \
    "$BUILD_DIR/usr/share/applications/org.transcende.switch_capture.desktop"

echo "==> Vérification syntaxique du code embarqué"
python3 -m py_compile \
    "$BUILD_DIR/usr/lib/switch-capture/switch_capture_core.py" \
    "$BUILD_DIR/usr/lib/switch-capture/switch_capture_cli.py" \
    "$BUILD_DIR/usr/bin/switch-capture" \
    "$BUILD_DIR/usr/lib/switch-capture/switch_capture_gtk.py"
find "$BUILD_DIR" -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

echo "==> Permissions"
chmod 755 "$BUILD_DIR/DEBIAN/postinst" "$BUILD_DIR/DEBIAN/postrm"
chmod 755 "$BUILD_DIR/usr/bin/switch-capture"
chmod 755 "$BUILD_DIR/usr/lib/switch-capture/switch-capture-taphelper"
find "$BUILD_DIR/usr/lib/switch-capture" -name '*.py' -exec chmod 644 {} \;
find "$BUILD_DIR/usr/share/doc/switch-capture" -type f -exec chmod 644 {} \;
chmod 644 "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps/org.transcende.switch_capture.svg" \
    "$BUILD_DIR/usr/share/applications/org.transcende.switch_capture.desktop"

echo "==> Construction du paquet"
dpkg-deb --build --root-owner-group "$BUILD_DIR" "$OUT_FILE"

echo
echo "Paquet généré : $OUT_FILE"
echo "Installation  : sudo apt install $OUT_FILE"
