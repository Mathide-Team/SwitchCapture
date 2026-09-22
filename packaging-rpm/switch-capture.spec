%global debug_package %{nil}

%if 0%{?rhel} == 8
%global python3_bin /usr/bin/python3.11
%global python3_req python3.11
%global python3_pip_req python3.11-pip
%global el8_build 1
%else
%global python3_bin /usr/bin/python3
%global python3_req python3 >= 3.8
%global python3_pip_req python3-pip
%global el8_build 0
%endif

Name:           switch-capture
Version:        1.0.0
Release:        1%{?dist}
Summary:        Orchestrateur de capture packet-capture pour switches HPE Comware
License:        Proprietary
URL:            https://example.invalid/switch-capture
Source0:        %{name}-%{version}.tar.gz
# Architecture-spécifique depuis l'ajout de switch-capture-taphelper (binaire
# compilé, voir %build/%install/%post) : ne peut plus être noarch. rpmbuild
# retient l'architecture de la machine de build (x86_64 dans la plupart des
# cas) — RPMS/<arch>/ au lieu de RPMS/noarch/, voir build_rpm.sh.
BuildRequires:  gcc

Requires:       %{python3_req}
Requires:       %{python3_pip_req}
Requires:       wireshark
Requires:       iproute
Requires:       libcap
Recommends:     openssh-clients
Recommends:     fuse-sshfs
%if !%{el8_build}
# GTK4/PyGObject : uniquement proposable sur el9 (même interpréteur système
# que netmiko/loguru/pyyaml). Sur el8, l'interpréteur retenu est python3.11,
# différent du python3 système pour lequel ces paquets sont construits :
# voir la note el8 plus bas et INSTALL.md. Weak dep (Recommends) : leur
# absence n'empêche pas l'installation, seule la CLI (-c) reste utilisable.
Recommends:     python3-gobject
Recommends:     gtk4
%endif

%description
Automatise, sur un switch HPE Comware 7 (5130/5140/5510/5520), la mise en
place et le suivi d'une capture packet-capture : activation SCP (transfert
fiable, sans montage FUSE -- fuse-sshfs reste disponible en repli),
installation de la feature si necessaire (5130/5140/5510/5520 -- tous
requierent la feature, aucun n'est natif a l'image), verification/
configuration NTP (timestamps comparables entre traces), lancement de la
capture avec rotation de fichiers et filtre optionnel, rapatriement et
reinjection en direct dans Wireshark (FIFO) ou une interface TAP dediee
(captures multiples simultanees ; switch-capture-taphelper, cap_net_admin+ep,
evite d'avoir a lancer switch-capture lui-meme en root pour ce mode). Alternative :
port mirroring (SPAN local ou ERSPAN/GRE distant) pousse directement sur le
switch. Voir /usr/share/doc/switch-capture/CAPTURE-METHODS.md.

Deux interfaces, un seul exécutable (/usr/bin/switch-capture) : CLI
(arguments/YAML) et GTK4 (formulaire), avec bascule automatique -- CLI
directe si les paramètres fournis suffisent, GUI sinon si disponible.
-c force la CLI, -g force la GUI.

Sur el8, dépend de python3.11 (paquet non-modulaire disponible depuis
RHEL/Rocky 8.9) ; la GUI GTK4 n'est alors PAS proposée (voir INSTALL.md).
Sur el9, le python3 système (3.9) suffit et GTK4 est disponible en
Recommends.

fuse-sshfs (le paquet, le binaire s'appelle "sshfs") et parfois wireshark
GUI nécessitent EPEL. Voir /usr/share/doc/switch-capture/INSTALL.md.

%prep
%setup -q

%build
%{python3_bin} -m py_compile switch_capture_core.py switch_capture_cli.py switch-capture switch_capture_gtk.py
gcc -O2 -o switch-capture-taphelper helpers/switch-capture-taphelper.c

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_bindir}
install -d %{buildroot}/usr/lib/switch-capture
install -d %{buildroot}/usr/share/doc/%{name}
install -d %{buildroot}/etc/switch-capture/feature-bin
install -d %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
install -d %{buildroot}%{_datadir}/applications

install -m 644 switch_capture_core.py %{buildroot}/usr/lib/switch-capture/switch_capture_core.py
install -m 644 switch_capture_cli.py %{buildroot}/usr/lib/switch-capture/switch_capture_cli.py
install -m 644 switch_capture_gtk.py %{buildroot}/usr/lib/switch-capture/switch_capture_gtk.py
install -m 644 docs/INSTALL.md %{buildroot}/usr/share/doc/%{name}/INSTALL.md
install -m 644 docs/USAGE.md %{buildroot}/usr/share/doc/%{name}/USAGE.md
install -m 644 docs/README-feature-bin.md %{buildroot}/usr/share/doc/%{name}/README-feature-bin.md
install -m 644 docs/CAPTURE-METHODS.md %{buildroot}/usr/share/doc/%{name}/CAPTURE-METHODS.md
install -m 644 docs/config.yaml.example %{buildroot}/usr/share/doc/%{name}/config.yaml.example
install -m 644 icons/hicolor/scalable/apps/org.transcende.switch_capture.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/org.transcende.switch_capture.svg
install -m 644 org.transcende.switch_capture.desktop \
    %{buildroot}%{_datadir}/applications/org.transcende.switch_capture.desktop

# switch-capture EST le point d'entree (CLI + GTK4) : simple copie, seule
# la ligne shebang est reecrite pour pointer vers %{python3_bin} (important
# sur el8, ou ce n'est pas /usr/bin/python3) -- pas de wrapper regenere.
install -m 755 switch-capture %{buildroot}%{_bindir}/switch-capture
sed -i "1s|^#!.*|#!%{python3_bin}|" %{buildroot}%{_bindir}/switch-capture

# switch-capture-taphelper : seul morceau de switch-capture qui a besoin de
# privilèges (CAP_NET_ADMIN, jamais setuid/root), pour le mode TAP sans
# root. cap_net_admin+ep positionné dans %post (setcap, via Requires:
# libcap) — jamais fiable de préserver une capability à travers rpmbuild/
# rpm lui-même, même en la positionnant ici dans %install.
install -m 755 switch-capture-taphelper %{buildroot}/usr/lib/switch-capture/switch-capture-taphelper

%post
# Principe : dnf est TOUJOURS essayé en premier pour netmiko/loguru/PyYAML,
# pip n'est qu'un repli si le paquet est absent des dépôts (EPEL incomplet
# selon la version). SAUF sur el8, où l'interpréteur retenu (python3.11)
# est différent du python3 système pour lequel les paquets python3-* sont
# construits (3.6) : dnf install de ces paquets ne les rendrait pas
# visibles depuis %{python3_bin}. Sur el8, on va donc directement en pip
# sans tenter dnf.
%if %{el8_build}
echo "el8 : netmiko/loguru/PyYAML/paramiko/scp via pip (%{python3_bin}, python3-* systeme ne conviendrait pas)"
%{python3_bin} -m pip install --no-warn-script-location \
    "netmiko>=4.3" "loguru>=0.7" "PyYAML>=6.0" "paramiko>=2.7" "scp>=0.14" \
    || echo "AVERTISSEMENT : echec pip. Lancez manuellement : sudo %{python3_bin} -m pip install netmiko loguru PyYAML paramiko scp"
echo "GTK4 non propose sur el8 (pas de python3.11-gobject dans les depots standards) -- seule la CLI (-c) fonctionnera."
%else
for pair in "python3-netmiko:netmiko>=4.3" "python3-loguru:loguru>=0.7" "python3-pyyaml:PyYAML>=6.0" "python3-paramiko:paramiko>=2.7" "python3-scp:scp>=0.14"; do
    dnf_pkg="${pair%%:*}"
    pip_pkg="${pair##*:}"
    if ! rpm -q "$dnf_pkg" >/dev/null 2>&1; then
        if ! dnf install -y "$dnf_pkg" >/dev/null 2>&1; then
            echo "AVERTISSEMENT : $dnf_pkg indisponible via DNF (EPEL incomplet ?) -- repli sur pip ($pip_pkg)."
            %{python3_bin} -m pip install --no-warn-script-location "$pip_pkg" \
                || echo "AVERTISSEMENT : echec pip pour $pip_pkg. Lancez manuellement : sudo %{python3_bin} -m pip install $pip_pkg"
        fi
    fi
done
%endif

# Groupe systeme + arborescence, alignes sur install.sh (voir ce script pour
# l'installation "sans paquet" equivalente).
groupadd -f -r switch-capture
mkdir -p /etc/switch-capture
install -d -m 2775 -o root -g switch-capture /etc/switch-capture/feature-bin
install -d -m 2775 -o root -g switch-capture /var/lib/switch-capture
install -d -m 2775 -o root -g switch-capture /var/lib/switch-capture/mount
install -d -m 2775 -o root -g switch-capture /var/lib/switch-capture/spool
install -d -m 2775 -o root -g switch-capture /var/lib/switch-capture/archive

# switch-capture-taphelper : cap_net_admin+ep, jamais setuid/root -- le
# process garde l'UID reel de l'utilisateur qui l'invoque. Requires: libcap
# garantit que setcap est present ; on reste best-effort quand meme (jamais
# bloquant pour le reste de l'installation).
if command -v setcap >/dev/null 2>&1; then
    if setcap cap_net_admin+ep /usr/lib/switch-capture/switch-capture-taphelper; then
        TAPHELPER_STATUS="disponible (mode TAP sans root)"
    else
        TAPHELPER_STATUS="setcap a echoue -- mode TAP necessitera root (sudo setcap cap_net_admin+ep /usr/lib/switch-capture/switch-capture-taphelper)"
    fi
else
    TAPHELPER_STATUS="setcap introuvable (paquet libcap) -- mode TAP necessitera root en attendant"
fi

# Best-effort : hicolor-icon-theme/desktop-file-utils fournissent des file
# triggers qui font déjà ce rafraîchissement automatiquement sur el9+ --
# ceci reste un filet pour les cas où ils seraient absents (jamais
# bloquant, comme dans postinst/postrm du paquet .deb équivalent).
command -v gtk-update-icon-cache >/dev/null 2>&1 && { gtk-update-icon-cache -q -t -f %{_datadir}/icons/hicolor >/dev/null 2>&1 || true; }
command -v update-desktop-database >/dev/null 2>&1 && { update-desktop-database -q %{_datadir}/applications >/dev/null 2>&1 || true; }

if %{python3_bin} -c "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk" >/dev/null 2>&1; then
    GTK_STATUS="disponible (demarrage graphique par defaut sans argument)"
else
    GTK_STATUS="absente (CLI uniquement)"
fi

cat <<MSG_EOF

switch-capture est installe. Interface graphique : $GTK_STATUS
Mode TAP sans root (switch-capture-taphelper) : $TAPHELPER_STATUS

  - Depot des .bin packet-capture : /etc/switch-capture/feature-bin/
    Pour y importer un depot deja prepare (structure <modele>/<version>/*.bin) :
      switch-capture -c import-bin /chemin/vers/votre/feature-bin
  - Donnees runtime (mount/spool/archive) : /var/lib/switch-capture/
  - Documentation : /usr/share/doc/switch-capture/

Le groupe systeme 'switch-capture' possede ces dossiers en ecriture (setgid).
Pour qu'un utilisateur non-root puisse y ecrire :
  sudo usermod -aG switch-capture <votre_utilisateur>

Test rapide :
  switch-capture --help
  switch-capture              # GUI si dispo, sinon aide CLI
  switch-capture -c capture --help
MSG_EOF

%postun
# Best-effort, sur toute désinstallation (comme dans %post) : rpm supprime
# déjà l'icône/le .desktop eux-mêmes, ceci ne fait que rafraîchir les caches.
command -v gtk-update-icon-cache >/dev/null 2>&1 && { gtk-update-icon-cache -q -t -f %{_datadir}/icons/hicolor >/dev/null 2>&1 || true; }
command -v update-desktop-database >/dev/null 2>&1 && { update-desktop-database -q %{_datadir}/applications >/dev/null 2>&1 || true; }

if [ "$1" = "0" ]; then
  echo "switch-capture desinstalle. /etc/switch-capture/ et /var/lib/switch-capture/"
  echo "sont conserves (peuvent contenir des .bin/captures) :"
  echo "  sudo rm -rf /etc/switch-capture /var/lib/switch-capture"
  echo "  sudo groupdel switch-capture   # si plus aucun usage n'en depend"
fi

%files
%{_bindir}/switch-capture
/usr/lib/switch-capture/switch_capture_core.py
/usr/lib/switch-capture/switch_capture_cli.py
/usr/lib/switch-capture/switch_capture_gtk.py
/usr/lib/switch-capture/switch-capture-taphelper
%dir /etc/switch-capture
%dir /etc/switch-capture/feature-bin
%{_datadir}/icons/hicolor/scalable/apps/org.transcende.switch_capture.svg
%{_datadir}/applications/org.transcende.switch_capture.desktop
%doc /usr/share/doc/%{name}/INSTALL.md
%doc /usr/share/doc/%{name}/USAGE.md
%doc /usr/share/doc/%{name}/README-feature-bin.md
%doc /usr/share/doc/%{name}/CAPTURE-METHODS.md
%doc /usr/share/doc/%{name}/config.yaml.example

%changelog
* Wed Aug 12 2026 Mathilde Deuscher <mathilde.deuscher@example.com> - 1.0.0-1
- Version initiale RPM (Rocky/RHEL/CentOS Stream 8 et 9)
