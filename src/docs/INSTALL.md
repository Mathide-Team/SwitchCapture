# INSTALL — switch-capture via install.sh (installation directe, sans .deb/.rpm)

`install.sh` installe l'application directement sur le système : détection
de la distribution, installation des prérequis, création de l'arborescence,
copie des fichiers applicatifs. Aucun paquet `.deb`/`.rpm` n'est produit —
pour ça, voir `packaging/` (Debian/Ubuntu) et `packaging-rpm/` (Rocky/RHEL/
CentOS Stream/AlmaLinux/Oracle Linux), qui font le même travail au moment
de l'installation du paquet (mêmes dossiers, même groupe système).

## Distributions supportées

| Famille | Distributions                                              | Gestionnaire |
|---------|---------------------------------------------------------------|----------------|
| Debian  | Ubuntu, Debian                                                 | APT            |
| RHEL    | Rocky Linux, RHEL, CentOS Stream, AlmaLinux, Oracle Linux, 8 & 9 | DNF          |

Sur el8, `python3` système est 3.6 (trop ancien) : le script installe et
utilise `python3.11` à la place (repli automatique sur le module `python39`
si `python3.11` est indisponible, versions el8 antérieures à 8.9). Sur el9
et sur Debian/Ubuntu, le `python3` système suffit.

## Ce que fait le script

1. Détecte la distribution (`/etc/os-release`) et sa version majeure.
2. Installe les paquets système : `sshfs`/`fuse-sshfs`, `wireshark`,
   `python3`(`.11`) + pip, `openssh-client(s)` — via APT ou DNF selon le cas
   (active EPEL + CRB/PowerTools automatiquement côté RHEL).
3. Installe `netmiko`, `loguru`, `PyYAML` — **via le paquet système
   (`python3-netmiko`/`python3-loguru`/`python3-yaml`/`python3-pyyaml`)
   en priorité**, avec repli automatique sur `pip` uniquement si le paquet
   est absent des dépôts configurés (ancienne version de distro, EPEL
   incomplet). Exception : sur el8, l'interpréteur retenu est `python3.11`,
   différent du `python3` système (3.6) pour lequel ces paquets RPM sont
   construits — `pip` y est donc utilisé directement, sans tenter DNF
   d'abord (voir la note el8 plus bas).
4. Installe GTK4/PyGObject en **best-effort** (`python3-gi`/`gir1.2-gtk-4.0`
   sur Debian/Ubuntu, `python3-gobject`/`gtk4` sur el9 — jamais sur el8, où
   le même problème d'interpréteur que ci-dessus s'applique et où `gtk4`
   n'est de toute façon pas toujours empaqueté). Leur absence n'empêche
   pas l'installation : seule la CLI (`-c`) sera alors utilisable.
5. Crée le groupe système `switch-capture` et l'arborescence :
   - `/etc/switch-capture/feature-bin/` — dépôt des `.bin` par modèle/version
   - `/var/lib/switch-capture/{mount,spool,archive}/` — données runtime
   - toutes en mode `2775` (setgid), `root:switch-capture`, pour qu'un
     utilisateur ajouté au groupe puisse y écrire sans être root.
6. Copie `switch_capture_core.py`/`switch_capture_cli.py`/
   `switch_capture_gtk.py` dans `/usr/lib/switch-capture/`, et le fichier
   `switch-capture` (le lanceur CLI+GUI lui-même) vers `/usr/bin/switch-capture`
   (shebang réécrit vers l'interpréteur Python retenu à l'étape 2), ainsi
   que la doc dans `/usr/share/doc/switch-capture/`. `switch_capture_gtk.py`
   est toujours copié, même si GTK4 s'avère indisponible à l'étape 4 — au
   cas où il serait installé manuellement après coup.

Le script est **idempotent** : le relancer ne casse rien (paquets déjà
installés = no-op, dossiers déjà présents = no-op).

## Usage

Depuis la racine du dépôt (là où se trouvent `install.sh` et `src/`) :

```bash
chmod +x install.sh
sudo ./install.sh          # demande confirmation avant de modifier le système
sudo ./install.sh -y       # non-interactif (scripts d'automatisation)
```

## Après installation

```bash
switch-capture --help
switch-capture              # GUI si GTK4 dispo, sinon aide CLI
switch-capture -c capture --help
switch-capture -g           # force la GUI (erreur claire si GTK4 absent)

# donner l'accès en écriture aux dossiers partagés à un utilisateur non-root
sudo usermod -aG switch-capture <votre_utilisateur>
# puis se déconnecter/reconnecter (ou 'newgrp switch-capture' dans le shell courant)
```

## Désinstallation (manuelle, pas de script dédié)

```bash
sudo rm -f /usr/bin/switch-capture
sudo rm -rf /usr/lib/switch-capture /usr/share/doc/switch-capture
# les deux lignes suivantes suppriment aussi les .bin et les captures :
sudo rm -rf /etc/switch-capture /var/lib/switch-capture
sudo groupdel switch-capture   # si plus rien n'en dépend
```

Les paquets système (`sshfs`/`fuse-sshfs`, `wireshark`, ...) ne sont pas
désinstallés automatiquement — ils peuvent être utiles indépendamment de
switch-capture.

## Différence avec les paquets `.deb`/`.rpm`

`install.sh` copie les fichiers directement, sans passer par le gestionnaire
de paquets : pas de suivi par `apt`/`dnf` (`apt remove switch-capture` ou
`dnf remove switch-capture` ne fonctionneront pas), pas de mise à jour
propre en cas de nouvelle version (il faut relancer `install.sh`, qui
écrasera les fichiers existants). Pour un déploiement géré à grande échelle
ou reproductible, préférez `packaging/build_deb.sh` ou
`packaging-rpm/build_rpm.sh`. `install.sh` convient pour une installation
rapide, un poste de test, ou une distribution non couverte par les deux
paquets.

## SELinux (Rocky/RHEL/CentOS)

Idem que pour le paquet `.rpm` : en mode `enforcing`, préférez des chemins
`mount_point`/`spool_dir`/`fifo_path` sous le `$HOME` de l'utilisateur de
service plutôt que sous `/etc` ou `/var/lib` par défaut, pour éviter les
frictions avec le montage FUSE/le FIFO. Voir `ausearch -m avc -ts recent`
en cas de blocage inattendu.
