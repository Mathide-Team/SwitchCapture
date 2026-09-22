# INSTALL — switch-capture (Ubuntu/Debian)

## Dépendances

### Paquets système (APT)

| Paquet                | Rôle                                                        |
|-------------------------|--------------------------------------------------------------|
| `python3`                | >= 3.10 (dataclasses, `X \| Y` union syntax)                  |
| `python3-yaml`           | lecture des fichiers `config.yaml`                            |
| `python3-netmiko`        | connexion SSH aux switches (**paquet APT natif**, voir ci-dessous) |
| `python3-loguru`         | logging (**paquet APT natif**, voir ci-dessous)                |
| `sshfs`                  | montage de la flash du switch (nécessite FUSE)                |
| `wireshark`              | lecture live du flux réassemblé (binaire `wireshark` dans PATH) |
| `openssh-client` (recommandé) | pour tester/déboguer la connexion SSH indépendamment     |
| `python3-gi`, `gir1.2-gtk-4.0` (recommandés) | interface graphique GTK4 (optionnelle)      |

### netmiko / loguru : APT d'abord, pip seulement en repli

Contrairement à une idée reçue, `python3-netmiko` et `python3-loguru`
**existent bel et bien** dans les dépôts Ubuntu/Debian (`universe` sur
Ubuntu) — vérifié sur Ubuntu 24.04 (`python3-netmiko` 4.3.0, `python3-loguru`
0.7.2). Le `.deb` les déclare donc en `Depends` natifs : ils sont installés
par `apt`/`dnf` comme n'importe quel autre paquet système, sans passer par
pip.

Si vous installez **sans** passer par le `.deb` (Option B ci-dessous) sur
une version de distribution où ces paquets seraient absents des dépôts
configurés, repli possible sur pip :

```
pip3 install --break-system-packages netmiko loguru
```

`--break-system-packages` est nécessaire depuis que Debian/Ubuntu protègent
le Python système (PEP 668).

### GTK4 : dépendance optionnelle (Recommends)

`python3-gi` et `gir1.2-gtk-4.0` sont en `Recommends`, pas `Depends` : `apt
install` les installe par défaut, mais leur absence (installation avec
`--no-install-recommends`, ou serveur minimal) n'empêche pas switch-capture
de fonctionner — seule la CLI (`-c`) sera alors utilisable. Voir USAGE.md
pour le détail de la bascule automatique CLI/GUI.

## Option A — paquet `.deb` (recommandé)

### Construire le paquet

Depuis la racine du projet (contenant `packaging/`) :

```bash
chmod +x packaging/build_deb.sh
./packaging/build_deb.sh
```

Produit `packaging/switch-capture_1.0.0_all.deb`.

### Installer

```bash
sudo apt install ./packaging/switch-capture_1.0.0_all.deb
```

`apt install ./fichier.deb` (plutôt que `dpkg -i`) résout automatiquement
toutes les dépendances APT (`sshfs`, `wireshark`, `python3-yaml`,
`python3-netmiko`, `python3-loguru`, et par défaut `python3-gi`/
`gir1.2-gtk-4.0`) et crée `/etc/switch-capture/feature-bin/` au postinst.

### Vérifier

```bash
switch-capture --help
switch-capture              # GUI si GTK4 dispo, sinon aide CLI
switch-capture -c capture --help
```

### Où sont les fichiers installés

| Chemin                                          | Contenu                                              |
|--------------------------------------------------|---------------------------------------------------------|
| `/usr/bin/switch-capture`                         | exécutable (lanceur CLI/GUI)                             |
| `/usr/lib/switch-capture/`                        | code Python (`*_core.py`, `*_cli.py`, `*_launcher.py`, `*_gtk.py`) |
| `/etc/switch-capture/feature-bin/`                | dépôt local des `.bin` par modèle/version                |
| `/var/lib/switch-capture/{mount,spool,archive}/`  | données runtime, groupe `switch-capture` en écriture     |
| `/usr/share/doc/switch-capture/`                  | INSTALL.md, USAGE.md, config.yaml.example                |

### Désinstaller le paquet (pas la feature du switch)

```bash
sudo apt remove switch-capture     # garde /etc/switch-capture et /var/lib/switch-capture (.bin, captures)
sudo apt purge switch-capture      # idem + message de nettoyage manuel
```

Pour désinstaller la feature *packet-capture côté switch*, voir USAGE.md
(`switch-capture -c uninstall`) — sans lien avec la désinstallation du
paquet sur la machine locale.

## Option B — installation manuelle (sans .deb, ex: autre distro)

```bash
sudo apt update
sudo apt install python3 python3-pip python3-yaml python3-netmiko python3-loguru sshfs wireshark
sudo apt install python3-gi gir1.2-gtk-4.0   # optionnel, pour la GUI

git clone <votre-dépôt> switch-capture
cd switch-capture/src
python3 switch-capture --help
```

Si `python3-netmiko`/`python3-loguru` sont absents des dépôts de votre
version (ancienne release) :

```bash
python3 -m venv --system-site-packages ~/.venvs/switch-capture
source ~/.venvs/switch-capture/bin/activate
pip install netmiko loguru pyyaml
```

`--system-site-packages` permet au venv de voir `python3-yaml` installé par
APT sans le réinstaller via pip.

## Vérification post-install

```bash
# sshfs/FUSE disponible ?
sshfs --version

# wireshark dans le PATH ?
which wireshark

# modules Python présents ?
python3 -c "import netmiko, loguru, yaml; print('OK')"

# GTK4 disponible (optionnel) ?
python3 -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk; print('GTK4 OK')"
```

## Accès au switch (prérequis côté infra, pas côté paquet)

- Compte RADIUS existant, autorisé pour les services `ssh` **et** `sftp`
  côté serveur RADIUS (le script n'active jamais localement un utilisateur).
- Droits suffisants sur ce compte pour : `display version`,
  `display current-configuration`, `sftp server enable`,
  `install activate/deactivate feature`, `packet-capture`.
