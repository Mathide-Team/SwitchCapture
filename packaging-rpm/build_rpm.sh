#!/bin/sh
# build_rpm.sh — génère le .rpm switch-capture
#
# Ne contient QUE les métadonnées RPM (packaging-rpm/switch-capture.spec +
# INSTALL-rpm.md). Le code applicatif et les docs partagées sont lus
# depuis ../src/ (source unique, aussi utilisée par install.sh et
# packaging/build_deb.sh) puis tarrés — exactement le même principe que
# build_deb.sh (arbre FHS généré au moment du build, jamais commité).
#
# Construit sur (ou via mock ciblant) la distribution voulue : le spec
# adapte automatiquement la dépendance Python selon %{rhel} (python3.11
# sur el8, python3 sur el9), résolue au moment du build.
#
# Usage :
#   chmod +x packaging-rpm/build_rpm.sh
#   ./packaging-rpm/build_rpm.sh
#
# Produit : packaging-rpm/RPMS/<arch>/switch-capture-<version>-<release>.<dist>.<arch>.rpm
# (architecture de la machine de build, ex: x86_64 -- plus "noarch" depuis
# l'ajout de switch-capture-taphelper, binaire compilé, voir le .spec)

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$ROOT_DIR/src"
SPEC_FILE="$SCRIPT_DIR/switch-capture.spec"
INSTALL_DOC="$SCRIPT_DIR/INSTALL-rpm.md"
VERSION="$(awk '/^Version:/ {print $2}' "$SPEC_FILE")"
PKG_DIR_NAME="switch-capture-${VERSION}"

if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "rpmbuild introuvable. Installez-le avec :" >&2
    echo "  Rocky/RHEL/CentOS : sudo dnf install rpm-build rpmdevtools" >&2
    echo "  Debian/Ubuntu     : sudo apt install rpm" >&2
    exit 1
fi
for f in "$SRC_DIR/switch_capture_core.py" "$SRC_DIR/switch_capture_cli.py" "$SRC_DIR/switch-capture" "$SRC_DIR/switch_capture_gtk.py" "$SRC_DIR/icons/hicolor/scalable/apps/org.transcende.switch_capture.svg" "$SRC_DIR/org.transcende.switch_capture.desktop" "$SRC_DIR/helpers/switch-capture-taphelper.c" "$INSTALL_DOC"; do
    [ -f "$f" ] || { echo "fichier source manquant : $f" >&2; exit 1; }
done

TOPDIR="$SCRIPT_DIR"
mkdir -p "$TOPDIR/SOURCES" "$TOPDIR/SPECS" "$TOPDIR/BUILD" "$TOPDIR/RPMS" "$TOPDIR/SRPMS" "$TOPDIR/BUILDROOT"

echo "==> Préparation du tarball source ($PKG_DIR_NAME.tar.gz, depuis ../src/)"
TMP_STAGE="$(mktemp -d)"
trap 'rm -rf "$TMP_STAGE"' EXIT
STAGE_DIR="$TMP_STAGE/$PKG_DIR_NAME"
mkdir -p "$STAGE_DIR/docs"

cp "$SRC_DIR/switch_capture_core.py" "$STAGE_DIR/switch_capture_core.py"
cp "$SRC_DIR/switch_capture_cli.py" "$STAGE_DIR/switch_capture_cli.py"
cp "$SRC_DIR/switch-capture" "$STAGE_DIR/switch-capture"
cp "$SRC_DIR/switch_capture_gtk.py" "$STAGE_DIR/switch_capture_gtk.py"
cp "$SRC_DIR/docs/USAGE.md" "$STAGE_DIR/docs/USAGE.md"
cp "$SRC_DIR/docs/README-feature-bin.md" "$STAGE_DIR/docs/README-feature-bin.md"
cp "$SRC_DIR/docs/CAPTURE-METHODS.md" "$STAGE_DIR/docs/CAPTURE-METHODS.md"
cp "$SRC_DIR/docs/config.yaml.example" "$STAGE_DIR/docs/config.yaml.example"
cp "$INSTALL_DOC" "$STAGE_DIR/docs/INSTALL.md"   # doc spécifique .rpm, pas la générique
mkdir -p "$STAGE_DIR/icons/hicolor/scalable/apps"
cp "$SRC_DIR/icons/hicolor/scalable/apps/org.transcende.switch_capture.svg" \
    "$STAGE_DIR/icons/hicolor/scalable/apps/org.transcende.switch_capture.svg"
cp "$SRC_DIR/org.transcende.switch_capture.desktop" "$STAGE_DIR/org.transcende.switch_capture.desktop"
mkdir -p "$STAGE_DIR/helpers"
cp "$SRC_DIR/helpers/switch-capture-taphelper.c" "$STAGE_DIR/helpers/switch-capture-taphelper.c"

echo "==> Vérification syntaxique du code embarqué (python3 hôte, indicatif)"
python3 -m py_compile "$STAGE_DIR/switch_capture_core.py" "$STAGE_DIR/switch_capture_cli.py" \
    "$STAGE_DIR/switch-capture" "$STAGE_DIR/switch_capture_gtk.py"
find "$TMP_STAGE" -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

tar -C "$TMP_STAGE" -czf "$TOPDIR/SOURCES/${PKG_DIR_NAME}.tar.gz" "$PKG_DIR_NAME"
cp "$SPEC_FILE" "$TOPDIR/SPECS/"

echo "==> rpmbuild -ba"
rpmbuild --define "_topdir $TOPDIR" -ba "$TOPDIR/SPECS/switch-capture.spec"

echo
echo "Paquet(s) généré(s) sous : $TOPDIR/RPMS/"
find "$TOPDIR/RPMS" -name '*.rpm' 2>/dev/null || true
echo "Installation : sudo dnf install <fichier.rpm>"
