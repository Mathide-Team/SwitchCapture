# switch-capture

Orchestrateur de capture réseau pour switches HPE Comware (5130/5140/5510/
5520), avec CLI et interface graphique GTK4.

**Auteur :** Mathilde Deuscher

---

## Cinq façons de récupérer du trafic depuis un switch

switch-capture ne mise pas sur une seule méthode de capture : selon le
contexte (diagnostic ponctuel, débit élevé, comparaison de plusieurs points
d'observation, filtrage fin par ACL, collecteur joignable seulement en
IP routé), l'une ou l'autre est la bonne réponse. Le détail complet, avec
les procédures manuelles équivalentes sur Cisco et d'autres
constructeurs, est dans
[`src/docs/CAPTURE-METHODS.md`](src/docs/CAPTURE-METHODS.md).

### 1. `packet-capture` local — fichiers rapatriés en direct

Le switch écrit la capture en ring-buffer sur sa propre flash ; switch-
capture rapatrie chaque fichier clôturé par SCP et le réinjecte en direct :

- **`--output-mode fifo`** (par défaut) : un named pipe + une instance
  Wireshark lancée automatiquement. Simple, une capture à la fois.
- **`--output-mode tap`** : réinjection dans une interface réseau virtuelle
  (TAP) dédiée. Plusieurs captures simultanées (une interface par switch/
  point de capture) observables **dans une seule instance Wireshark**.

```bash
switch-capture capture --switch-ip 10.0.0.1 --ssh-user mathilde \
  --capture-interface GigabitEthernet1/0/1
```

### 2. `packet-capture remote` — RPCAP natif Comware

Certains modèles/versions Comware peuvent exposer le switch directement
comme un **serveur RPCAP** : Wireshark s'y connecte en réseau
(`rpcap://switch-ip:port/interface`), sans fichier ni FIFO/TAP local.
Le plus simple des cinq méthodes quand il est disponible — **la
disponibilité n'est pas garantie sur tous les modèles**, switch-capture le
signale clairement si la commande n'existe pas sur votre plateforme.

```bash
switch-capture capture --switch-ip 10.0.0.1 --ssh-user mathilde \
  --capture-interface GigabitEthernet1/0/1 --output-mode rpcap
```

### 3. Port mirroring (SPAN local / ERSPAN+GRE distant)

Copie le trafic au niveau du plan de données (ASIC), **avant** tout
traitement CPU — débit ligne, sans les limites des deux méthodes
précédentes. switch-capture pousse la configuration ; la capture se fait
côté collecteur (Wireshark/tcpdump), externe à l'outil.

```bash
# SPAN local (câble direct vers l'hôte de capture)
switch-capture mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --mode local --source-interface GigabitEthernet1/0/1 \
  --monitor-interface GigabitEthernet1/0/24

# ERSPAN/GRE distant (routé, pas de câble direct requis)
switch-capture mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --mode gre --source-interface GigabitEthernet1/0/1 \
  --tunnel-local-ip 10.0.0.1 --tunnel-ip 192.168.100.1 --remote-ip 203.0.113.10
```

### 4. Flow mirroring filtré par ACL — `switch-capture mirror --filter-mode acl`

Variante du mirroring de port ci-dessus : au lieu de dupliquer *tout* le
trafic d'un port, ne duplique que les paquets qui correspondent à une
ACL avancée, via une politique QoS (`traffic classifier` + `traffic
behavior` + `qos policy`) — toujours au débit ligne, au niveau de
l'ASIC. Utile pour isoler un hôte ou un protocole précis sans mirrorer
tout un port chargé de trafic non pertinent. Pilotable en CLI comme en
GUI (bloc « Port mirroring », menu déroulant « Mode de filtrage »).

```bash
switch-capture mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --filter-mode acl --acl-number 3000 \
  --acl-rule "rule 0 permit ip source 10.0.0.5 0" \
  --source-interface GigabitEthernet1/0/1 --monitor-interface GigabitEthernet1/0/24
```

### 5. Mirroring vers VLAN sonde + VXLAN L2 — `switch-capture mirror --mode vxlan` ⚠️ expérimental

**Non vérifié contre la doc H3C officielle ni contre un switch réel dans
ce dépôt** — implémenté sur demande explicite d'un utilisateur, qui en
atteste le fonctionnement sur un 5520 HI. À valider vous-même avant tout
déploiement en production ; voir
[`src/docs/CAPTURE-METHODS.md`](src/docs/CAPTURE-METHODS.md) section 5
pour le détail complet des réserves. Utile quand le collecteur n'est
joignable qu'en IP routé (pas d'adjacence L2 possible pour trunker un
VLAN sonde classique) : le VLAN mirroré est raccordé à une VSI VXLAN qui
l'achemine par-dessus le réseau routé. CLI uniquement, GUI pas encore
câblée.

```bash
switch-capture mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --mode vxlan --group-id 10 --source-interface GigabitEthernet1/0/1 \
  --remote-probe-vlan 666 --vsi-name mirror --vxlan-vni 666 \
  --tunnel-id 0 --tunnel-local-ip 10.0.0.1 --remote-ip 203.0.113.10 \
  --reflector-interface GigabitEthernet1/0/24
```

Côté collecteur, une interface VXLAN doit être créée manuellement
(`ip link add ... type vxlan`, hors du périmètre de cet outil) — voir
CAPTURE-METHODS.md pour la commande complète.

### Comparer plusieurs points de capture (client / routeur / serveur)

Pour que des traces prises à différents points du réseau soient
comparables entre elles, les horloges des switches doivent être
synchronisées — switch-capture vérifie et configure NTP automatiquement
(`--ntp-server`) et écrit un sidecar `capture-meta.json` (étiquette du
point de capture, statut NTP, filtre utilisé...) à côté de chaque capture,
pour qu'un outil tiers de comparaison de traces (hors périmètre de ce
projet) puisse s'y raccrocher.

---

## Installation

Trois méthodes équivalentes, au choix :

| Méthode | Commande |
|---|---|
| **Script direct** (Ubuntu/Debian/Rocky/RHEL/CentOS 8-9) | `sudo ./install.sh` |
| **Paquet `.deb`** (Debian/Ubuntu) | `./packaging/build_deb.sh` puis `sudo apt install ./packaging/switch-capture_1.0.0_all.deb` |
| **Paquet `.rpm`** (Rocky/RHEL/CentOS Stream 8/9) | `./packaging-rpm/build_rpm.sh` puis `sudo dnf install ./packaging-rpm/RPMS/noarch/*.rpm` |

Détail complet des prérequis (paquets système, GTK4 optionnel, différences
el8/el9) dans `src/docs/INSTALL.md` (script direct), `packaging/INSTALL-deb.md`
et `packaging-rpm/INSTALL-rpm.md`.

Une fois installé :

```bash
switch-capture --help
switch-capture              # ouvre la GUI si GTK4 est disponible, sinon l'aide CLI
switch-capture -c capture --help
switch-capture -g           # force la GUI
```

## Interface graphique

`switch-capture` (sans argument) ouvre une fenêtre GTK4 pensée pour piloter
**plusieurs captures à la fois** (comparaison client/routeur/serveur),
organisée en 5 pages : **Configuration** (liste des captures + formulaire
d'ajout, avec champs qui s'adaptent au mode choisi), **Installation**
(prépare toutes les captures — préalable obligatoire), **Démarrage**
(disponible une fois toutes les captures installées), **Journal** (statut,
progression, logs en direct, arrêt global) et **Résultats** (fichiers
produits par capture). Le menu ☰ en haut à gauche ouvre les
**Préférences** (slot/modèle/`.bin` forcé, repli KeePass — persistées
dans `config.yaml`, voir USAGE.md) ou quitte l'application. La bascule
CLI/GUI est automatique : si les arguments fournis suffisent à lancer une
capture, tout se passe en ligne de commande, sans jamais ouvrir de
fenêtre — pratique pour un usage cron/systemd même sur une machine qui a
aussi un environnement graphique. `-c` force la CLI, `-g` force la GUI.

## Structure du dépôt

```
switch-capture/
├── install.sh                  # installation directe (sans .deb/.rpm)
├── pyproject.toml               # dépendances (uv) + config ruff/pytest/coverage — pour un venv manuel (`uv sync`, voir CLAUDE.md)
├── src/                         # code source + documentation
│   ├── switch-capture           # point d'entrée unique (CLI + GTK4)
│   ├── switch_capture_core.py   # logique métier (capture, SCP, TAP, NTP, mirroring...)
│   ├── switch_capture_cli.py    # sous-commandes CLI
│   ├── switch_capture_gtk.py    # interface graphique GTK4
│   └── docs/
│       ├── INSTALL.md           # installation via install.sh
│       ├── USAGE.md             # référence complète CLI + GUI
│       ├── CAPTURE-METHODS.md   # comparaison des 5 méthodes de capture, procédures manuelles
│       ├── README-feature-bin.md
│       └── config.yaml.example
├── feature-bin/                 # (optionnel, à créer soi-même, non versionné) dépôt local de .bin HPE
├── packaging/                   # paquet .deb
│   ├── build_deb.sh
│   ├── INSTALL-deb.md
│   └── debian/DEBIAN/           # métadonnées du paquet (control, postinst, postrm)
└── packaging-rpm/                # paquet .rpm
    ├── build_rpm.sh
    ├── INSTALL-rpm.md
    └── switch-capture.spec
```

`src/` est la source unique du code et de la documentation partagée : les
trois méthodes d'installation (`install.sh`, `build_deb.sh`, `build_rpm.sh`)
la lisent de la même façon et construisent l'arborescence finale au moment
de l'installation/du build, plutôt que de la dupliquer. Voir
`docs/architecture.md` pour le détail de l'architecture, les choix
techniques, et les pièges déjà rencontrés et corrigés.

## Dépendances système

Toutes installées automatiquement par `install.sh`/les paquets : Python
≥ 3.8, `netmiko`/`loguru`/`paramiko`/`scp` (paquets système en priorité,
repli `pip` si absents des dépôts), `wireshark`, `iproute2`/`iproute`
(pour le mode TAP). `sshfs`/`fuse-sshfs` et GTK4/PyGObject sont
recommandés mais optionnels (mode `sshfs` legacy, GUI). Détail par
distribution dans les docs d'installation citées plus haut.

## Sécurité

- Le compte switch est un compte RADIUS existant : aucun utilisateur local
  n'est créé. Le mot de passe n'est jamais écrit sur disque (variable
  d'environnement `SWITCH_SSH_PASSWORD` recommandée plutôt que
  `--ssh-password` en clair).
- Le mode TAP nécessite root/CAP_NET_ADMIN — à réserver à un compte de
  service dédié.
- Voir `docs/architecture.md`, section « Sécurité / bonnes pratiques », pour
  le détail.

## État du projet

[`CLAUDE.md`](CLAUDE.md) donne l'état courant en un coup d'œil ;
[`docs/features-backlog.md`](docs/features-backlog.md) tient à jour
l'inventaire de ce qui est réellement fait et testé, et de ce qui reste à
faire — à consulter avant de démarrer une nouvelle session de travail sur
ce dépôt. Détail session par session : [`docs/sessions/`](docs/sessions/index.md).

## Licence

À définir — un fichier `LICENSE` placeholder (MIT) est inclus dans ce
dépôt en attendant un choix définitif.
