# INSTALL — switch-capture (Rocky/RHEL/CentOS Stream 8 & 9)

## Dépendances

### Interpréteur Python : différence importante entre el8 et el9

Le script utilise des fonctionnalités Python >= 3.8 (`Path.unlink(missing_ok=...)`,
dataclasses, annotations différées). Or :

| Distro                              | `python3` par défaut | Suffisant ? |
|---------------------------------------|------------------------|--------------|
| Rocky/RHEL/CentOS Stream **9**        | 3.9                    | oui          |
| Rocky/RHEL/CentOS Stream **8**        | 3.6                    | **non**      |

Sur el8, il faut donc un interpréteur alternatif. Depuis RHEL/Rocky **8.9**,
le paquet non-modulaire `python3.11` est disponible directement (plus
besoin de jongler avec `dnf module enable python39`) :

```bash
# el8 (Rocky/RHEL/CentOS Stream 8, >= 8.9)
sudo dnf install python3.11 python3.11-pip

# el9 (Rocky/RHEL/CentOS Stream 9) : python3 système suffit
sudo dnf install python3 python3-pip
```

Le `.rpm` fourni gère cette différence automatiquement (macro `%{python3_bin}`
dans le spec, résolue au moment du build sur la machine cible) : le paquet
construit sur un el8 dépend de `python3.11`, celui construit sur un el9
dépend de `python3`.

**Cette différence d'interpréteur a une conséquence importante sur la façon
dont netmiko/loguru/PyYAML et GTK4 sont installés — voir les deux sections
suivantes.**

### Paquets système (DNF)

| Paquet          | Rôle                                                     | Dépôt                          |
|------------------|------------------------------------------------------------|----------------------------------|
| `python3` (el9) ou `python3.11` (el8) | interpréteur                          | BaseOS/AppStream                 |
| `python3-pip` (el9) ou `python3.11-pip` (el8) | filet de sécurité si un paquet dnf manque | BaseOS/AppStream        |
| `fuse-sshfs`     | montage de la flash du switch (le binaire s'appelle bien `sshfs`, mais le **paquet** RPM est `fuse-sshfs`, pas `sshfs`) | **EPEL** |
| `wireshark`      | lecture live du flux réassemblé (paquet GUI, Qt)            | AppStream (el9) / EPEL selon variante |
| `openssh-clients` (recommandé) | test/débogage SSH indépendant                | BaseOS                           |

### Activer EPEL (nécessaire pour `fuse-sshfs`, et parfois `wireshark` GUI)

```bash
sudo dnf install epel-release
sudo dnf config-manager --set-enabled crb   # el9 : CodeReady Builder, requis par certaines deps EPEL
# sur el8, l'équivalent est le dépôt "PowerTools" :
# sudo dnf config-manager --set-enabled powertools
```

Vérifiez la disponibilité de `wireshark` avec GUI avant d'installer, les
installations minimales (serveur) n'ont parfois que `wireshark-cli`
(tshark/dumpcap, sans interface) :

```bash
dnf info wireshark
```

Si seul `wireshark-cli` est disponible sur votre variante, la réinjection
en direct (`wireshark -k -i <fifo>`) ne fonctionnera pas telle quelle : soit
installez le paquet GUI complet (dépôt AppStream/EPEL selon la version),
soit adaptez `_launch_wireshark()` dans `switch_capture_core.py` pour
utiliser `tshark -i <fifo>` en remplacement (pas de fenêtre, sortie texte).

### netmiko / loguru / PyYAML : DNF d'abord, pip seulement en repli — sauf sur el8

**Sur el9**, `python3-netmiko`, `python3-loguru` et `python3-pyyaml` sont
essayés en premier via `dnf`. C'est le `%post` du `.rpm` qui s'en charge
(ou `install.sh`) :

```bash
# el9
for pkg in python3-netmiko python3-loguru python3-pyyaml; do
    sudo dnf install -y "$pkg" || echo "repli pip pour $pkg"
done
```

Si un paquet est absent des dépôts configurés (EPEL incomplet selon la
version), repli automatique sur pip pour celui-là uniquement :

```bash
python3 -m pip install netmiko    # ou loguru, ou PyYAML — selon ce qui a échoué
```

**Sur el8**, ce n'est **pas** le même mécanisme, et c'est important à
comprendre si vous adaptez le packaging : l'interpréteur retenu est
`python3.11` (voir plus haut), alors que les paquets RPM `python3-netmiko`/
`python3-loguru`/`python3-pyyaml` sont construits pour le `python3` système
(3.6) — ils installent leurs modules dans les site-packages de *ce*
`python3`, invisibles depuis `python3.11` (interpréteurs et arborescences
de paquets totalement séparés sous RHEL/Rocky). Tenter `dnf install
python3-netmiko` puis exécuter le code sous `python3.11` ne fonctionnerait
donc pas : le `.rpm` (et `install.sh`) utilisent directement pip sous
`python3.11` sur el8, sans passer par dnf pour ces trois paquets :

```bash
# el8 uniquement
sudo python3.11 -m pip install netmiko loguru PyYAML
```

Contrairement à Debian/Ubuntu, RHEL/Rocky/CentOS n'imposent pas
`--break-system-packages` : `pip install` système fonctionne directement,
avec ou sans le venv.

### GTK4 : dépendance optionnelle, et uniquement proposée sur el9

`python3-gobject` (le module `gi`) et `gtk4` sont en `Recommends` (faible,
non bloquant) — **uniquement sur el9**. Deux raisons combinées expliquent
l'absence de GTK4 sur el8 :

1. le même problème d'interpréteur que ci-dessus : `python3-gobject`
   construit pour le `python3` système (3.6) n'est pas visible depuis
   `python3.11`, et il n'existe pas de variante `python3.11-gobject` dans
   les dépôts standards ;
2. `gtk4` lui-même n'est pas toujours empaqueté sur el8 (la version 8 de
   RHEL est sortie avant GTK4) et peut nécessiter des dépôts tiers.

Sur el8, seule la CLI (`-c`) est donc disponible. Sur el9, si
`python3-gobject`/`gtk4` sont présents, l'app démarre en mode graphique
par défaut sans argument — voir USAGE.md pour le détail de la bascule
automatique CLI/GUI (`-c`/`-g`).

## Option A — paquet `.rpm` (recommandé)

### Construire le paquet

**Important** : construisez sur (ou avec un chroot `mock` ciblant) la
même version majeure que la cible — le spec adapte automatiquement la
dépendance Python et la disponibilité de GTK4 (`python3.11` + pas de GTK4
sur el8, `python3` + GTK4 en Recommends sur el9) via la macro `%{rhel}`,
résolue au moment du build.

```bash
chmod +x packaging-rpm/build_rpm.sh
./packaging-rpm/build_rpm.sh
```

Produit `packaging-rpm/RPMS/noarch/switch-capture-1.0.0-1.<dist>.noarch.rpm`.

Pour construire un `.rpm` el8 depuis une machine el9 (ou l'inverse), utilisez
`mock` plutôt que `rpmbuild` natif :

```bash
sudo dnf install mock
mock -r rocky+epel-8-x86_64 --buildsrpm --spec packaging-rpm/switch-capture.spec \
     --sources packaging-rpm/SOURCES --resultdir /tmp/srpm-el8
mock -r rocky+epel-8-x86_64 --rebuild /tmp/srpm-el8/*.src.rpm --resultdir /tmp/rpm-el8
```

(adapter le nom de la config mock : `rocky+epel-9-x86_64` pour el9, etc. —
`dnf install mock` puis `mock -l` liste les configurations disponibles.)

### Installer

```bash
sudo dnf install ./switch-capture-1.0.0-1.el9.noarch.rpm
```

`dnf install ./fichier.rpm` (plutôt que `rpm -i`) résout les dépendances
via les dépôts configurés (EPEL doit déjà être activé pour `fuse-sshfs`).
Le `%post` prend ensuite le relais pour netmiko/loguru/PyYAML (dnf puis
repli pip sur el9, pip direct sur el8 — voir ci-dessus) et crée le groupe
système `switch-capture` + `/etc/switch-capture/`, `/var/lib/switch-capture/`.

### Vérifier

```bash
switch-capture --help
switch-capture              # GUI si GTK4 dispo (el9 uniquement), sinon aide CLI
switch-capture -c capture --help
```

### Où sont les fichiers installés

| Chemin                                  | Contenu                                          |
|-------------------------------------------|-----------------------------------------------------|
| `/usr/bin/switch-capture`                 | exécutable (lanceur CLI/GUI)                         |
| `/usr/lib/switch-capture/`                | code Python (`*_core.py`, `*_cli.py`, `*_launcher.py`, `*_gtk.py`) |
| `/etc/switch-capture/feature-bin/`        | dépôt local des `.bin` par modèle/version            |
| `/var/lib/switch-capture/{mount,spool,archive}/` | données runtime, groupe `switch-capture` en écriture |
| `/usr/share/doc/switch-capture/`          | INSTALL.md, USAGE.md, config.yaml.example            |

### Désinstaller

```bash
sudo dnf remove switch-capture
```

`/etc/switch-capture/` et `/var/lib/switch-capture/` (potentiellement des
`.bin`/captures de plusieurs Mo) ne sont **pas** supprimés automatiquement
— un message vous le rappelle :

```bash
sudo rm -rf /etc/switch-capture /var/lib/switch-capture
sudo groupdel switch-capture   # si plus aucun usage n'en dépend
```

Pour désinstaller la feature *packet-capture côté switch*, voir USAGE.md
(`switch-capture -c uninstall`) — sans lien avec la désinstallation du
paquet sur la machine locale.

## Option B — installation manuelle (sans `.rpm`)

```bash
# el9
sudo dnf install epel-release
sudo dnf config-manager --set-enabled crb
sudo dnf install python3 python3-pip fuse-sshfs wireshark
sudo dnf install python3-netmiko python3-loguru python3-pyyaml python3-gobject gtk4   # best-effort

python3 -c "import netmiko, loguru, yaml" || \
    python3 -m pip install netmiko loguru pyyaml   # repli pour ce qui manque

python3 switch-capture --help
```

Sur el8, remplacez `python3`/`python3-pip` par `python3.11`/`python3.11-pip`,
n'installez pas `python3-netmiko`/`python3-loguru`/`python3-pyyaml`/
`python3-gobject`/`gtk4` (inutiles, voir plus haut) et passez directement
par pip :

```bash
sudo dnf install python3.11 python3.11-pip fuse-sshfs wireshark
sudo python3.11 -m pip install netmiko loguru PyYAML
python3.11 switch-capture --help   # pas de GTK4 sur el8
```

## Vérification post-install

```bash
sshfs --version
which wireshark
python3 -c "import netmiko, loguru, yaml; print('OK')"          # el9
python3.11 -c "import netmiko, loguru, yaml; print('OK')"       # el8
python3 -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk; print('GTK4 OK')"   # el9 uniquement
```

## Accès au switch (prérequis côté infra, pas côté paquet)

- Compte RADIUS existant, autorisé pour les services `ssh` **et** `sftp`
  côté serveur RADIUS (le script n'active jamais localement un utilisateur).
- Droits suffisants sur ce compte pour : `display version`,
  `display current-configuration`, `sftp server enable`,
  `install activate/deactivate feature`, `packet-capture`.

## SELinux

Aucune règle spécifique n'est fournie avec ce paquet. Si SELinux est en
mode `enforcing` (par défaut sur Rocky/RHEL) et que `sshfs`/le FIFO posent
problème (AVC denials sur le montage FUSE ou l'accès au named pipe dans un
répertoire non standard), consultez `journalctl` filtré sur `avc` :

```bash
sudo ausearch -m avc -ts recent
```

Éviter les montages sous `/etc`, `/var/lib` par défaut et préférer un
`mount_point`/`spool_dir`/`fifo_path` sous le `$HOME` de l'utilisateur de
service réduit généralement les frictions SELinux pour du FUSE utilisateur.
