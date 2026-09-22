# Session 17 — 28/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Mode non-root pour le mode TAP — `switch-capture-taphelper` (28/08/2026, suite)

Traite le point 17 (« Priorité 000 — urgent ») de `features.md`. Détail
complet côté fonctionnalité/tests dans `features.md` (section datée du
même jour) — ici, le comment technique + les pièges rencontrés.

**Contexte** : `ensure_tap_interface` créait/activait l'interface TAP via
`ip tuntap add`/`ip link set up`, ce qui exige `CAP_NET_ADMIN` — jusqu'ici
seulement obtenu en lançant tout `switch-capture` en root, alors que
c'est le **seul** besoin de privilège de l'application (SSH/SCP vers le
switch, écriture de fichiers, tout le reste tourne très bien sous
l'utilisateur courant).

**Mécanisme retenu (le point clé) : `TUNSETOWNER`.** Le nouveau binaire
`src/helpers/switch-capture-taphelper.c` ne fait *que* trois choses en
ioctl direct sur `/dev/net/tun` (`add`/`del`) et une socket `AF_INET`
(`up`) — jamais d'`execve`/`system`, jamais de dépendance à `ip` ou à
netlink. La créature d'interface (`add`) positionne `TUNSETOWNER` sur
l'UID **réel** de l'appelant (`getuid()` — le process n'est jamais
setuid, il porte seulement `cap_net_admin+ep` en effectif via `setcap`,
donc son UID réel reste celui de l'utilisateur non-root qui l'a lancé).
C'est cette capability noyau (documentée dans `Documentation/networking/tuntap.rst` :
un utilisateur non privilégié peut rouvrir/s'attacher à un tap persistant
dont il est le propriétaire déclaré) qui permet ensuite à
`TapFrameWriter` (`switch_capture_core.py`, complètement inchangé,
aucune modification requise) de s'attacher à cette même interface *sans
aucun privilège*. Sans ce détail, il aurait fallu soit garder
`switch-capture` privilégié pour toute la durée de la capture (pas
mieux qu'avant), soit faire porter à l'aide elle-même l'écriture
continue des trames (bien plus de surface de code privilégié qu'un
aller simple `add`/`up`/`del`).

**Pourquoi pas `ip tuntap add`/exec depuis l'aide** : envisagé puis
écarté — faire exécuter `ip` par un process porteur de capability pose
un problème de propagation : sans capabilities *ambiantes*
(`PR_CAP_AMBIENT`, en plus de capabilities *fichier inheritable* sur le
binaire `ip` lui-même, jamais posées par défaut), `execve` d'un binaire
non root/non capability-aware **perd** la capability effective avant
même son premier ioctl — `ip` échouerait avec `Operation not permitted`
malgré l'aide elle-même privilégiée. Faire tout l'ioctl directement dans
l'aide évite ce piège entièrement (même processus du début à la fin,
capability jamais perdue) et réduit la surface (pas de sous-processus,
pas de `PATH`, rien à injecter).

**Validation du nom d'interface** (`valid_ifname()`), défense en
profondeur : le champ `tap_interface` du formulaire est saisi librement
par l'utilisateur (`switch_capture_gtk.py`, `switch_capture_cli.py`),
sans préfixe imposé — donc pas de allowlist par préfixe possible côté
aide privilégiée. Validation générique à la place : 1 à `IFNAMSIZ-1` (15)
caractères, alphanumérique/`_`/`-`/`.` uniquement, jamais commençant par
`-`. Rejeté avant tout ioctl si invalide.

**Résolution du chemin de l'aide côté Python** (`_taphelper_path()`,
`switch_capture_core.py`) : `SWITCH_CAPTURE_TAPHELPER` (env, tests/dev),
puis `/usr/lib/switch-capture/switch-capture-taphelper` (chemin
d'installation standard, identique dans les 3 méthodes), puis à côté de
`switch_capture_core.py` lui-même (usage direct depuis `src/`, non
installé). `ensure_tap_interface`/`delete_tap_interface` n'utilisent
l'aide que si le process n'est **pas** root (`os.geteuid() != 0`) — un
usage root historique (cron, ancien service systemd) continue de
fonctionner à l'identique via `ip` directement, aucune régression.

**Piège de packaging repéré et corrigé en écrivant `build_deb.sh`/le
`.spec`, pas après coup** : un binaire compilé rend le paquet
spécifique à l'architecture de build — `Architecture: all` (`.deb`) et
`BuildArch: noarch` (`.rpm`) étaient corrects tant que switch-capture
n'était que Python+docs, mais seraient devenus **incorrects** dès l'ajout
d'un binaire ELF (un `.deb` « all » s'installe sans vérification
d'architecture, y compris sur une architecture où le binaire ne
tournerait pas). Corrections :
- `.deb` : `packaging/debian/DEBIAN/control` porte désormais
  `Architecture: __BUILD_ARCH__`, un placeholder substitué par
  `build_deb.sh` via `dpkg --print-architecture` juste avant
  `dpkg-deb --build` (`sed -i` sur le fichier copié dans `$BUILD_DIR`,
  jamais sur le fichier source du dépôt). Nom de sortie aligné :
  `switch-capture_<version>_<arch>.deb` au lieu de `..._all.deb`.
  Digression notée en écrivant ceci : les fichiers `control` Debian
  n'acceptent **pas** de lignes de commentaire (`#`) — l'explication du
  placeholder est donc dans `build_deb.sh`, pas dans `control` lui-même
  (une première tentative de commentaire inline a fait échouer
  `dpkg-deb` avec *"field name '#' must be followed by colon"*).
- `.rpm` : `BuildArch: noarch` simplement retiré du `.spec` — rpmbuild
  retient alors l'architecture de la machine de build (`x86_64` dans ce
  sandbox), `RPMS/<arch>/` au lieu de `RPMS/noarch/`. `build_rpm.sh`
  ajusté en conséquence (message de fin, plus de `ls RPMS/noarch/`
  supposé).

**`setcap` posé après packaging, pas avant, pour `.deb`/`.rpm`** : les
capabilities (xattr `security.capability`) ne survivent pas de façon
fiable à `dpkg-deb --build`/l'extraction du paquet sur la machine cible —
pratique Debian/RPM standard pour les binaires ayant besoin de
capabilities (ex. `ping`) : les poser dans `postinst`/`%post`, jamais
dans l'arbre `%install`/`$BUILD_DIR` avant construction du paquet. Suivi
ici : `libcap2-bin`/`libcap` ajoutés en dépendance (`Recommends` côté
`.deb`, `Requires` ferme côté `.rpm` — cohérent avec le reste du `.spec`
qui préfère des dépendances strictes là où `install.sh`/`control` sont
plus best-effort), `setcap cap_net_admin+ep` appelé en toute fin de
`postinst`/`%post`, jamais bloquant (juste un statut affiché dans le
récapitulatif final si `setcap` est absent ou échoue).

**Testé réellement, les 3 méthodes, de bout en bout, non-root réel** —
pas de mock pour cette partie-là (contrairement aux tests unitaires
d'aiguillage, mockés eux, voir `tests/test_tap_helper_nonroot.py`) :

1. `./install.sh -y` exécuté pour de vrai dans ce sandbox (root
   disponible) : installe `gcc`/`libcap2-bin` réellement, compile,
   `setcap`, rapporte « Mode TAP … : OK ». Vérifié ensuite avec un
   utilisateur `useradd -m` dédié (`su -`) : `add`/`up` de l'interface,
   `ip -d link show` confirme `persist on user <utilisateur>`,
   `TapFrameWriter` s'attache et écrit une trame sans aucun privilège,
   `del` fait disparaître l'interface. `userdel -r` en nettoyage.
2. `./packaging/build_deb.sh` puis `apt-get install ./*.deb` réel (après
   désinstallation propre de l'état laissé par `install.sh`) : même
   séquence de vérification non-root, capability bien préservée par
   `postinst`.
3. `./packaging-rpm/build_rpm.sh` (nécessite `--nodeps` **dans ce
   sandbox précis** : `gcc` y est installé via APT, invisible à la base
   RPM qui vérifie `BuildRequires: gcc` — artefact de ce sandbox Ubuntu
   utilisé pour construire un `.rpm`, sans rapport avec la validité du
   `.spec` sur une vraie machine RHEL/Rocky, où `dnf install gcc`
   satisferait normalement la dépendance) puis `rpm -i --nodeps` (ce
   sandbox n'a pas `dnf`, seulement `rpm` — la résolution de dépendances
   `python3-netmiko`/etc. du `%post` échoue donc bruyamment sur cet hôte
   Debian, **attendu et sans rapport** avec cette session : ces
   avertissements pip/dnf existaient déjà avant ce changement). Même
   séquence de vérification non-root, capability bien préservée par
   `%post`.

**`/dev/net/tun` à `0600` dans ce sandbox précis** (`crw-------`, root
uniquement) — corrigé manuellement (`chmod 666`) avant chaque étape de
test non-root, **à chaque fois** (le mode semble se réinitialiser entre
certains blocs de commandes de ce sandbox — pas creusé plus avant, pas
le sujet). Sur un système cible réel, ce device est normalement déjà
`0666` par une règle udev standard livrée avec le pilote tun/tap du
noyau — si un déploiement réel rencontre un `/dev/net/tun` restrictif,
ce sera un réglage udev/système à corriger, pas un défaut de
`switch-capture-taphelper` lui-même (qui, lui, n'a jamais eu besoin de
`CAP_DAC_OVERRIDE` — volontairement **pas** demandé, seul
`CAP_NET_ADMIN` est nécessaire pour les ioctls utilisés).

**Nouvelle suite `tests/test_tap_helper_nonroot.py` (9 tests)** :
résolution `_taphelper_path` (override env valide/invalide/absent),
aiguillage `ensure_tap_interface`/`delete_tap_interface` avec
`subprocess.run` substitué (`monkeypatch`) pour les 4 combinaisons
root/non-root × aide présente/absente, propagation d'échec de l'aide en
`RuntimeError`, **plus** un test d'intégration non mocké
(`test_taphelper_end_to_end_as_real_nonroot_user`, `@pytest.mark.skipif`
propre si root/`gcc`/`setcap`/`/dev/net/tun` manquent) qui rejoue
exactement la séquence manuelle ci-dessus automatiquement — compile
l'aide dans un répertoire `/tmp/...` dédié explicitement `chmod 755`
(le fixture `tmp_path` de pytest crée des répertoires `0700`, non
traversables par l'utilisateur non-root créé ensuite via `su -` : piège
repéré au premier passage, corrigé en n'utilisant pas `tmp_path` pour
cette partie précise). Suite complète rejouée : **184 tests réels
passés, 0 échec** (175 non-GUI + ces 9 nouveaux ; `test_gui_new_fields.py`
et `test_install_guard_while_running.py` ignorés cette session, GTK4/
PyGObject absents de **cet** environnement précis — présent lors des
deux sessions précédentes du même jour, absent cette fois : ne jamais
supposer qu'un environnement constaté persiste, y compris au sein d'une
même journée). `ruff check --line-length 120` sur
`switch_capture_core.py` et le nouveau fichier de test : aucune erreur
nouvelle (mêmes lignes pré-existantes qu'avant ce changement dans
`switch_capture_core.py`, fichier de test propre).

**Non fait cette session** : le point 18 (sélection
packet-capture/mirroring/rpcap dans le formulaire GTK) reste entier —
périmètre déjà large pour une réponse (aide C + core + 3×packaging +
tests, chacun vérifié réellement plutôt que livré en aveugle), et de
toute façon non testable en GUI dans **cet** environnement précis
(GTK4/Xvfb absents cette fois). **Seul point encore marqué urgent** par
l'utilisateur — à traiter en priorité dès qu'un environnement GTK4/Xvfb
sera de nouveau disponible.

