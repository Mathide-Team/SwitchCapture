# USAGE — switch-capture (CLI et GTK4)

Un seul exécutable, `switch-capture`, avec deux interfaces derrière :

| Invocation                      | Comportement                                                      |
|-----------------------------------|-----------------------------------------------------------------------|
| `switch-capture`                  | GUI GTK4 si disponible, sinon aide CLI                                |
| `switch-capture capture --switch-ip ... --ssh-user ... --capture-interface ...` | arguments suffisants -> CLI directe, **aucune fenêtre ouverte** |
| `switch-capture -c ...`           | force la CLI, quels que soient les autres arguments                   |
| `switch-capture -g`               | force la GUI (erreur claire si GTK4/PyGObject absents)                |

La bascule automatique regarde si les arguments (et/ou le `--config`
YAML qu'ils référencent, et/ou `SWITCH_SSH_PASSWORD`) suffisent à
construire une configuration complète pour `capture` ou `uninstall`. Si
oui, tout se passe en CLI, sans jamais afficher de fenêtre — utile pour
cron/systemd même si GTK4 est installé sur la machine. Si les arguments
sont absents ou incomplets, ou si `-g` est explicitement demandé sans
GTK4 disponible, un message d'erreur clair s'affiche (pas de fenêtre
silencieuse, pas de plantage muet).

GTK4/PyGObject sont une dépendance **optionnelle** (Recommends, pas
Depends/Requires) : un serveur sans environnement graphique peut
installer et utiliser switch-capture en CLI uniquement.

### GUI GTK4 : 5 pages, multi-captures simultanées, menu Préférences

`switch-capture` (sans argument, ou `-g`) ouvre une fenêtre organisée en
5 pages, accessibles via le sélecteur en haut de la fenêtre — pensées pour
piloter **plusieurs captures à la fois** (comparaison client/routeur/
serveur, voir `CAPTURE-METHODS.md`), pas une seule. Le menu ☰ en haut à
gauche (visible sur les 5 pages) ouvre les **Préférences** (voir plus bas)
ou quitte l'application :

1. **Configuration** — liste des captures déjà ajoutées (« Inspecter
   (dry run) », « Désinstaller la feature » et « Supprimer » par ligne),
   et un formulaire pour en ajouter une nouvelle (« + Ajouter
   cette capture à la liste »). Les champs affichés s'adaptent au mode
   choisi : `transfer_mode: sshfs` fait apparaître `mount_point` (masqué
   en `scp`, le défaut) ; `output_mode: rpcap` masque tout ce qui touche
   au ring-buffer/rapatriement de fichiers (inutile dans ce mode, voir
   `CAPTURE-METHODS.md`) et ne garde que le port RPCAP ; `output_mode: tap`
   affiche l'interface TAP à la place du FIFO. Un bouton « Importer un
   dépôt .bin... » reste disponible, indépendant des captures. Le slot
   IRF/châssis, le modèle forcé et le `.bin` forcé ne sont plus dans ce
   formulaire : voir Préférences ci-dessous. Bouton « Modifier » par
   ligne pour corriger une capture déjà ajoutée (repeuple le formulaire,
   y compris ses Préférences d'origine — voir plus bas — puis il suffit
   de soumettre à nouveau).
2. **Installation** — bouton « Lancer l'installation de toutes les
   captures » : prépare (détection modèle, SCP/sshfs, NTP, feature) chaque
   capture de la liste, statut affiché en direct par ligne
   (pending/running/ok/failed).
3. **Démarrage** — le bouton « Démarrer toutes les captures » n'est
   disponible **que si toutes les captures sont installées avec succès** —
   l'installation complète de toutes les captures planifiées est un
   préalable obligatoire au démarrage de n'importe laquelle.
4. **Journal** — statut et progression de chaque capture en cours
   (fichiers fusionnés/volume pour fifo/tap, "streaming réseau direct"
   pour rpcap), bouton « Arrêter toutes les captures », et la console de
   logs en direct (partagée par toutes les captures).
5. **Résultats** — liste des `.pcap` de toutes les captures, étiquetés par
   point de capture (`[client/Spool]`, `[routeur/Archive]`...), bouton
   « Rafraîchir ».

Les zones à contenu variable (formulaire, listes, logs) utilisent des
scrollbars classiques toujours visibles quand il y a plus à voir (pas de
barre flottante qui se cache).

#### Préférences (menu ☰ → Préférences)

Réglages globaux à l'outil plutôt que propres à une capture donnée,
enregistrés dans `./config.yaml` (dossier de lancement) après un clic sur
« Enregistrer », rechargés automatiquement au démarrage suivant — plus
besoin de les ressaisir à chaque capture ajoutée ni à chaque lancement :

- **Slot IRF/châssis** et **Modèle** (auto-détection par défaut, ou
  imposé) — retirés du formulaire « + Ajouter cette capture » (point 1
  ci-dessus).
- **Forcer un .bin précis** (optionnel) — contourne la résolution
  automatique par modèle/version dans le dépôt local (`feature_bin_dir`,
  resté lui dans le formulaire principal).
- **Fichier KeePass (.kdbx, repli)** — utilisé uniquement si le trousseau
  système (libsecret/GNOME Keyring) est indisponible ; grisé sinon. Le mot
  de passe maître de la base reste exclusivement dans la variable
  d'environnement `SWITCH_CAPTURE_KEEPASS_PASSWORD`, jamais dans un champ
  de l'interface (voir « Mémoriser le mot de passe SSH entre deux
  lancements » plus bas).

Éditer une capture déjà ajoutée (bouton « Modifier », voir point 1
ci-dessus) restaure temporairement les Préférences sur les valeurs de
**cette** capture précise, pour que la soumettre à nouveau ne fasse pas
glisser silencieusement son slot/modèle vers des Préférences changées
entre-temps — sans réécrire `config.yaml` tant que « Enregistrer » n'est
pas cliqué depuis la page Préférences elle-même.

Ce même fichier `config.yaml` peut aussi servir de base pour
`switch-capture capture --config config.yaml` en CLI (voir plus bas) : les
deux usages cohabitent sans conflit, chacun ne touchant qu'à ses propres
clés (voir `config.yaml.example`).



Sous-commandes CLI pour piloter le switch : `capture` (lance une
capture — packet-capture local ou remote/rpcap, bloquant), `uninstall`
(retire la feature packet-capture du switch), `mirror` (configure ou
retire du port mirroring — SPAN local / ERSPAN+GRE distant / VLAN sonde
+ VXLAN L2, port entier ou filtré par ACL via `--filter-mode acl`, non
bloquant), `inspect` (mode dry run : détecte modèle/version/features
actives sans rien modifier, non bloquant), `analyze-pacing` (analyse
hors ligne les écarts inter-trames d'un `.pcap` déjà rapatrié, pour
choisir une valeur de `--tap-pace-max-gap` — voir plus bas) ; plus
`import-bin`, un utilitaire local sans accès au switch. **Voir
`CAPTURE-METHODS.md` pour la comparaison complète des cinq méthodes de
capture (packet-capture, rpcap, mirroring+GRE, flow mirroring QoS,
mirroring VLAN sonde + VXLAN L2) et les procédures manuelles
multi-constructeurs.**

## Aide intégrée

```bash
switch-capture --help
switch-capture -c capture --help
switch-capture -c uninstall --help
switch-capture -c mirror --help
switch-capture -c inspect --help
switch-capture -c analyze-pacing --help
switch-capture -c import-bin --help
```

`-v`/`--verbose` (voir la table `capture`/`uninstall` ci-dessous pour le
détail de l'option) est déclarée sur le parseur racine, avant les
sous-commandes : elle doit donc être placée **avant** le nom de la
sous-commande (`switch-capture -v capture ...`), et fonctionne à
l'identique avec `mirror`/`inspect`/`analyze-pacing`/`import-bin` — pas
seulement `capture`/`uninstall`. Contrairement à `-c`/`-g` (filtrés
séparément par le lanceur `switch-capture`, acceptés n'importe où sur la
ligne de commande), la placer après la sous-commande
(`switch-capture capture ... -v`) échoue avec
`error: unrecognized arguments: -v`.

## Référence des options — `capture` / `uninstall`

| Option                  | Défaut                  | Description                                                        |
|--------------------------|--------------------------|----------------------------------------------------------------------|
| `--config FICHIER`       | —                        | YAML de base, surchargé par les autres options (voir `config.yaml.example`) |
| `--switch-ip`             | *(obligatoire)*          | IP ou nom du switch                                                  |
| `--ssh-user`               | *(obligatoire)*          | compte RADIUS existant                                               |
| `--ssh-password`           | env `SWITCH_SSH_PASSWORD` | déconseillé en clair sur la ligne de commande                        |
| `--slot`                   | 1                        | slot IRF/châssis cible                                                |
| `--model`                  | auto-détecté             | `5130`, `5140`, `5510`, `5520`, `3600v2` (force le profil matériel)   |
| `--feature-bin-path`        | —                        | chemin exact d'un `.bin`, prioritaire sur `--feature-bin-dir`         |
| `--feature-bin-dir`         | `./feature-bin`          | dépôt local organisé par `<modèle>/<version>/`                        |
| `--transfer-mode`           | `scp`                    | `scp` (recommandé, pas de montage) ou `sshfs` (legacy, `--mount-point`) |
| `--mount-point`             | `./<switch_ip>`          | point de montage sshfs (uniquement `--transfer-mode sshfs`)           |
| `--capture-interface`       | *(obligatoire)*          | ex: `GigabitEthernet1/0/1`                                            |
| `--capture-basename`        | `capture.pcap`           | préfixe des fichiers sur la flash (modes fifo/tap uniquement)         |
| `--rotation-seconds`        | 20                       | durée de chaque fichier du ring-buffer (modes fifo/tap)               |
| `--max-ring-files`          | 10                       | nombre de fichiers conservés côté switch (modes fifo/tap)             |
| `--capture-filter`          | *(aucun = tout capturer)*| expression tcpdump-like, voir exemples plus bas                       |
| `--no-hide-capture-traffic` | masquage actif           | n'exclut plus le trafic SSH/SCP outil↔switch de la capture (exclu par défaut, en plus de `--capture-filter` le cas échéant) ; sans effet en `--output-mode rpcap` |
| `--capture-direction`       | `bidirection`            | `bidirection` (entrant + sortant), `inbound` (entrant seul, défaut Comware sans mot-clé) ou `outbound` (sortant seul) |
| `--output-mode`             | `fifo`                   | `fifo` (Wireshark auto-lancé), `tap` (interface virtuelle, captures multiples), `rpcap` (natif Comware, réseau direct) |
| `--tap-interface`           | —                        | nom de l'interface TAP (`--output-mode tap`, ex: `vcap1`)              |
| `--tap-cleanup-on-stop`     | désactivé                | supprime l'interface TAP à l'arrêt (sinon laissée en place)           |
| `--tap-launch-wireshark`    | désactivé                | lance Wireshark sur l'interface TAP dès qu'elle est prête (une fenêtre par capture si plusieurs captures simultanées, voir plus bas) |
| `--tap-pace-playback`       | désactivé                | réinjecte les trames d'un `.pcap` rapatrié en respectant approximativement l'écart de temps d'origine, au lieu de les écrire aussi vite que possible ; n'a d'effet qu'en `--output-mode tap`, plafonné par `--tap-pace-max-gap` (voir `switch-capture analyze-pacing` plus bas pour choisir une valeur) |
| `--tap-pace-max-gap`        | 2.0 (secondes)           | délai maximal entre deux trames avec `--tap-pace-playback`             |
| `--rpcap-port`              | 2002                     | port du service RPCAP côté switch (`--output-mode rpcap`)             |
| `--capture-label`           | —                        | étiquette libre du point de capture (ex: `client`, `routeur-core`)    |
| `--ntp-server`               | —                        | serveur NTP à configurer si l'horloge switch n'est pas synchronisée   |
| `--no-ensure-ntp`            | vérification active      | saute complètement la vérification NTP                                |
| `--spool-dir`               | `./spool`                | dossier local de rapatriement (modes fifo/tap)                        |
| `--archive-dir`             | *(suppression après fusion)* | dossier d'archivage des `.pcap` fusionnés (modes fifo/tap)       |
| `--no-archive-as-pcapng`    | conversion active        | archive au format `.pcap` classique au lieu de `.pcapng` (`--archive-dir` uniquement) |
| `--fifo-path`               | `./capture_live.fifo`    | FIFO nommé lu par Wireshark (`--output-mode fifo`)                    |
| `--poll-interval`           | 5                        | intervalle de scrutation des fichiers distants, en secondes           |
| `--remove-bin` (uninstall)  | désactivé                | supprime aussi le `.bin` de la flash après désactivation              |
| `--confirm-ip` (uninstall)  | désactivé                | demande de retaper l'IP du switch avant de continuer (à ne pas utiliser en cron/systemd) |
| `-v`, `--verbose`           | désactivé                | logs DEBUG sur la console (toujours DEBUG dans `switch_capture.log`) ; option globale, à placer **avant** la sous-commande (voir note sous « Aide intégrée » ci-dessus) |

## Référence des options — `mirror`

| Option                    | Défaut     | Description                                                          |
|-----------------------------|--------------|--------------------------------------------------------------------------|
| `--switch-ip`               | *(obligatoire)* | IP ou nom du switch                                                    |
| `--ssh-user`                 | *(obligatoire)* | compte RADIUS existant                                                 |
| `--ssh-password`             | env `SWITCH_SSH_PASSWORD` | —                                                          |
| `--mode`                     | `local`      | `local` (SPAN, câble direct), `gre` (ERSPAN tunnel-mode, distant) ou `vxlan` (VLAN sonde + extension L2 VXLAN, ⚠️ expérimental, voir `CAPTURE-METHODS.md` section 5) |
| `--group-id`                 | 1            | numéro du groupe `mirroring-group` Comware                              |
| `--source-interface`         | *(obligatoire, répétable)* | interface(s) source à mirrorer                            |
| `--direction`                 | `both`       | `both`, `inbound`, `outbound`                                          |
| `--monitor-interface`        | —            | (mode `local`, obligatoire) interface de destination                    |
| `--tunnel-id`                 | 1            | (mode `gre`) numéro de l'interface Tunnel                              |
| `--tunnel-local-ip`          | —            | (mode `gre` ou `vxlan`, obligatoire) IP source du tunnel, déjà portée par une interface du switch |
| `--tunnel-ip`                 | —            | (mode `gre`, obligatoire) IP assignée à l'interface Tunnel elle-même   |
| `--tunnel-mask`               | `255.255.255.0` | masque de `--tunnel-ip`                                             |
| `--remote-ip`                 | —            | (mode `gre` ou `vxlan`, obligatoire) IP du collecteur distant          |
| `--loopback-interface`        | —            | (mode `gre`, optionnel) port pour `service-loopback type tunnel`, si requis par la plateforme |
| `--remote-probe-vlan`         | —            | (mode `vxlan`, obligatoire) VLAN sonde Comware (`mirroring-group ... remote-probe vlan`) |
| `--vsi-name`                  | —            | (mode `vxlan`, obligatoire) nom de la VSI Comware associée au VNI et au tunnel |
| `--vxlan-vni`                 | —            | (mode `vxlan`, obligatoire) VNI VXLAN associé à `--vsi-name` (0-16777215) |
| `--service-instance-id`       | déduit de `--group-id` | (mode `vxlan`, optionnel) identifiant du service-instance raccordant `--remote-probe-vlan` à `--vsi-name` sur `--reflector-interface` |
| `--reflector-interface`       | —            | (mode `vxlan`, obligatoire) port physique dédié au reflector-port du mirroring-group et au raccordement VSI |
| `--filter-mode`               | `port`       | `port` (mirroring-group, port entier) ou `acl` (flow mirroring filtré, voir `CAPTURE-METHODS.md` section 4) |
| `--acl-number`                 | 3000         | (`--filter-mode acl`) numéro d'ACL avancée Comware (3000-3999, 3998/3999 exclus) |
| `--acl-rule`                   | —            | (`--filter-mode acl`, obligatoire, répétable) règle ACL avancée complète, ex. `rule 0 permit ip source 10.0.0.5 0` |
| `--classifier-name`            | déduit de `--group-id` | (`--filter-mode acl`) nom du traffic classifier Comware              |
| `--behavior-name`              | déduit de `--group-id` | (`--filter-mode acl`) nom du traffic behavior Comware                |
| `--qos-policy-name`            | déduit de `--group-id` | (`--filter-mode acl`) nom de la qos policy Comware                   |
| `--teardown`                   | désactivé    | retire la configuration au lieu de la pousser                          |

## Référence des options — `inspect`

Mode dry run : ne modifie jamais rien sur le switch (uniquement des
commandes `display`). Un fichier `--config` déjà utilisé pour `capture`
peut être réutilisé tel quel (les champs propres à la capture, ex.
`--capture-interface`, sont simplement ignorés).

| Option                  | Défaut                  | Description                                                        |
|--------------------------|--------------------------|----------------------------------------------------------------------|
| `--config FICHIER`       | —                        | YAML de base, surchargé par les autres options                       |
| `--switch-ip`             | *(obligatoire)*          | IP ou nom du switch                                                  |
| `--ssh-user`               | *(obligatoire)*          | compte RADIUS existant                                               |
| `--ssh-password`           | env `SWITCH_SSH_PASSWORD` | déconseillé en clair sur la ligne de commande                        |
| `--remember-password`      | désactivé                | mémorise le mot de passe SSH utilisé dans le trousseau système (voir `capture --help`) |
| `--forget-password`        | désactivé                | retire du trousseau système le mot de passe mémorisé pour ce couple switch/utilisateur |
| `--keepass-path`           | —                        | repli si `keyring` est absent (voir `capture --help`) : chemin d'un fichier KeePass `.kdbx` existant |
| `--keepass-keyfile`        | —                        | fichier de clé KeePass additionnel (voir `capture --help`), ignoré sans `--keepass-path` |
| `--model`                  | auto-détecté             | force le profil matériel au lieu de l'auto-détection                 |
| `--feature-bin-path`       | —                        | nom exact du `.bin` à rechercher dans `display install active`       |
| `--feature-bin-dir`        | `./feature-bin`          | pour résoudre le nom attendu si `--feature-bin-path` est omis         |
| `--transfer-mode`          | `scp`                    | service à vérifier (`scp server enable` vs `sftp server enable`)      |

## Référence des options — `analyze-pacing`

Sous-commande hors ligne : ne se connecte à aucun switch, ne prend que
des arguments. Étant donné un `.pcap` classique déjà rapatrié (réel ou
synthétique), calcule la distribution des écarts inter-trames
(min/médiane/p90/p95/p99/max) et simule l'effet de plusieurs valeurs
candidates de `--tap-pace-max-gap` sur ce fichier précis — voir
`features.md`, section « Pas fait », pour le contexte (mesure de la
durée SCP réelle contre un switch physique, hors de portée sans
matériel, distincte de cette analyse).

| Option                  | Défaut                          | Description                                                        |
|--------------------------|----------------------------------|----------------------------------------------------------------------|
| `pcap_file`               | *(obligatoire, positionnel)*    | fichier `.pcap` classique (pas `pcapng`) déjà rapatrié à analyser     |
| `--candidate-max-gap`    | `0.5, 1, 2, 5, 10` secondes      | valeur de `--tap-pace-max-gap` à évaluer (répétable pour en tester plusieurs) |

## Exemples

### Capture minimale, mot de passe en variable d'environnement

```bash
export SWITCH_SSH_PASSWORD='...'
switch-capture capture \
  --switch-ip 10.0.0.1 \
  --ssh-user mathilde \
  --capture-interface GigabitEthernet1/0/1
```

### Config de base + surcharge ponctuelle du filtre

```bash
switch-capture -v capture --config /etc/switch-capture/site-a.yaml \
  --capture-filter "host 10.10.10.2 and proto gre"
```

### Mémoriser le mot de passe SSH entre deux lancements

Par défaut (`--remember-password`), le mot de passe est mémorisé dans le
trousseau système (libsecret/GNOME Keyring, jamais en clair sur disque) :

```bash
switch-capture capture --switch-ip 10.0.0.1 --ssh-user mathilde \
  --ssh-password '...' --capture-interface GigabitEthernet1/0/1 \
  --remember-password
# les lancements suivants n'ont plus besoin de --ssh-password/SWITCH_SSH_PASSWORD :
switch-capture capture --switch-ip 10.0.0.1 --ssh-user mathilde \
  --capture-interface GigabitEthernet1/0/1
```

`--forget-password` retire l'entrée mémorisée pour ce couple switch/
utilisateur. Sur un serveur headless sans trousseau système (module Python
`keyring` non installé), un fichier KeePass `.kdbx` **existant** (créé au
préalable avec KeePassXC ou équivalent — cet outil n'en crée jamais) peut
servir de repli avec les mêmes options `--remember-password`/
`--forget-password`, en ajoutant `--keepass-path` et la variable
d'environnement `SWITCH_CAPTURE_KEEPASS_PASSWORD` (mot de passe maître de
la base, jamais accepté en argument CLI en clair) :

```bash
export SWITCH_CAPTURE_KEEPASS_PASSWORD='...'
switch-capture capture --switch-ip 10.0.0.1 --ssh-user mathilde \
  --ssh-password '...' --capture-interface GigabitEthernet1/0/1 \
  --remember-password --keepass-path /etc/switch-capture/vault.kdbx
```

Le trousseau système reste toujours prioritaire quand il est disponible ;
`--keepass-path` n'est consulté (en écriture comme en lecture automatique)
que si `keyring` est absent. Nécessite le module Python optionnel
`pykeepass` (`pip install pykeepass`, aucun paquet système équivalent
courant à ce jour).

Si la base `.kdbx` est en plus protégée par un fichier de clé (en
complément du mot de passe maître, pas à sa place — toujours requis par cet
outil), indiquez-le avec `--keepass-keyfile` :

```bash
switch-capture capture --switch-ip 10.0.0.1 --ssh-user mathilde \
  --ssh-password '...' --capture-interface GigabitEthernet1/0/1 \
  --remember-password --keepass-path /etc/switch-capture/vault.kdbx \
  --keepass-keyfile /etc/switch-capture/vault.key
```

`--keepass-keyfile` est ignoré si `--keepass-path` n'est pas fourni.

### Forcer le modèle (auto-détection en échec ou modèle apparenté)

```bash
switch-capture capture --switch-ip 10.0.0.1 --ssh-user mathilde \
  --model 5510 --capture-interface GigabitEthernet1/0/1
```

### Captures multiples simultanées via TAP (comparaison client/routeur/serveur)

```bash
switch-capture -c capture --switch-ip 10.0.0.1 --ssh-user mathilde \
  --capture-interface GigabitEthernet1/0/1 --output-mode tap --tap-interface vcap-client \
  --capture-label client --ntp-server 10.0.0.254

switch-capture -c capture --switch-ip 10.0.0.2 --ssh-user mathilde \
  --capture-interface GigabitEthernet1/0/1 --output-mode tap --tap-interface vcap-routeur \
  --capture-label routeur --ntp-server 10.0.0.254
```
Wireshark ouvre alors `vcap-client` et `vcap-routeur` simultanément. Le
`--ntp-server` commun est essentiel : sans horloges synchronisées entre
les deux switches, les timestamps ne sont pas comparables entre les deux
traces. Voir `CAPTURE-METHODS.md` pour l'alternative `rpcap` (pas
d'interface TAP à créer, si le modèle le supporte).

Ici Wireshark est lancé manuellement, une fois, pour observer les deux
interfaces ensemble dans la même fenêtre — c'est l'usage recommandé pour
des captures simultanées. `--tap-launch-wireshark` n'est utile que pour
une capture TAP isolée : ajouté à chacune des deux commandes ci-dessus,
il ouvrirait deux fenêtres Wireshark séparées au lieu d'une seule.

### RPCAP natif (pas de fichier, connexion réseau directe)

```bash
switch-capture -c capture --switch-ip 10.0.0.1 --ssh-user mathilde \
  --capture-interface GigabitEthernet1/0/1 --output-mode rpcap --rpcap-port 2014
```
Puis, dans Wireshark : **Capture > Options > Manage Interfaces > Remote
Interfaces**, IP du switch, port 2014.

### Port mirroring local (SPAN)

```bash
switch-capture -c mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --mode local --source-interface GigabitEthernet1/0/1 \
  --monitor-interface GigabitEthernet1/0/24
```

### Port mirroring distant via GRE (ERSPAN tunnel-mode)

```bash
switch-capture -c mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --mode gre --source-interface GigabitEthernet1/0/1 \
  --tunnel-local-ip 10.0.0.1 --tunnel-ip 192.168.100.1 --remote-ip 203.0.113.10
```

### Flow mirroring filtré par ACL (isoler un hôte, pas tout le port)

```bash
switch-capture -c mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --filter-mode acl --acl-rule "rule 0 permit ip source 10.0.0.5 0" \
  --source-interface GigabitEthernet1/0/1 --monitor-interface GigabitEthernet1/0/24
```
Voir `CAPTURE-METHODS.md` section 4 pour la variante ERSPAN/GRE distant
(`--mode gre --tunnel-local-ip ... --remote-ip ...`, sans `--tunnel-ip`)
et le détail de ce qui est poussé sur le switch.

### Mirroring vers VLAN sonde + VXLAN L2 (⚠️ expérimental)

```bash
switch-capture -c mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --mode vxlan --group-id 10 --source-interface GigabitEthernet1/0/1 \
  --remote-probe-vlan 666 --vsi-name mirror --vxlan-vni 666 \
  --reflector-interface GigabitEthernet1/0/2 \
  --tunnel-local-ip 10.0.0.1 --remote-ip 203.0.113.10
```
Voir `CAPTURE-METHODS.md` section 5 pour le détail de la config poussée
sur le switch (VSI, service-instance, tunnel VXLAN) et la commande
`ip link add ... type vxlan` à lancer manuellement côté collecteur pour
décapsuler le trafic reçu — combinaison non officiellement documentée
par H3C, à ne considérer que sur un switch de test.

### Désinstaller la feature (5130/5140), en gardant le `.bin` sur la flash

```bash
switch-capture uninstall --switch-ip 10.0.0.1 --ssh-user mathilde --slot 1
```

Sans `--feature-bin-path`, le nom du `.bin` à désactiver est **découvert
sur le switch** : `display install active` est interrogé et la première
image `packet-capture*.bin` active du slot est retenue (les images
`boot-*`/`system-*` listées à côté ne sont jamais touchées). Les `.pcap`
résiduels du préfixe de capture sont supprimés au passage. Si aucune
image `packet-capture` n'est active, la commande le signale et s'arrête
sans rien modifier.

### Désinstaller et libérer la flash

```bash
switch-capture uninstall --switch-ip 10.0.0.1 --ssh-user mathilde \
  --slot 1 --remove-bin
```

### Désinstaller en production, avec confirmation renforcée

Demande de retaper l'IP du switch avant toute connexion SSH — pensé pour
un lancement manuel sur un switch de production, pas pour cron/systemd
(la commande attendrait une entrée standard qui n'arrivera jamais) :

```bash
switch-capture uninstall --switch-ip 10.0.0.1 --ssh-user mathilde \
  --slot 1 --confirm-ip
```

Message informatif si le modèle détecté n'a en fait aucune feature active
(rien à désinstaller) — mais **5510/5520 nécessitent bien l'installation
préalable de la feature**, exactement comme 5130/5140 (pas natifs à
l'image, malgré une hypothèse antérieure de ce dépôt).

### Inspecter un switch avant d'y toucher (mode dry run)

Utile avant une première intervention sur un switch distant sans accès
physique — ne modifie rien, uniquement des commandes `display` :

```bash
switch-capture inspect --switch-ip 10.0.0.1 --ssh-user mathilde
```

```
Switch : 10.0.0.1
Modèle : 5130
Version logicielle : 6555P05
packet-capture : à installer — Feature packet-capture installable via 'install activate feature'.
  .bin vérifié : packet-capture-5130-6555p05.bin
  déjà active : non
scp server enable : oui
NTP synchronisé : oui (Clock status: synchronized, ...)

Aucune modification n'a été effectuée sur ce switch (mode dry run).
```

Un fichier déjà utilisé pour `capture` fonctionne tel quel :

```bash
switch-capture inspect --config site-a.yaml
```

### Analyser le lissage TAP sur un `.pcap` déjà rapatrié

Ne se connecte à aucun switch — utile après une capture réelle, pour
choisir une valeur de `--tap-pace-max-gap` avant la prochaine session
live (voir « Lissage de la réinjection TAP » ci-dessus) :

```bash
switch-capture analyze-pacing capture_2026-09-01.pcap \
  --candidate-max-gap 1 --candidate-max-gap 2 --candidate-max-gap 5
```

Sans `--candidate-max-gap`, les valeurs `0.5, 1, 2, 5, 10` secondes
sont testées par défaut. Le rapport indique la distribution des écarts
inter-trames du fichier (min/médiane/p90/p95/p99/max) puis, pour chaque
valeur candidate, combien d'écarts seraient raccourcis et la durée de
rejeu résultante.

## Filtres de capture (`--capture-filter`), sans ACL

`packet-capture` accepte un filtre inline façon **tcpdump/BPF**, directement
dans la commande — pas besoin de préconfigurer une ACL sur le switch.

1. **Un hôte** : `host 10.0.0.5`
2. **Hôte + port** : `host 10.0.0.5 and tcp port 22`
3. **Un protocole (GRE)** : `proto gre`
   (l'en-tête GRE extérieur uniquement ; affinez le contenu encapsulé
   ensuite côté Wireshark avec un display filter `gre`)
4. **Sous-réseau, bruit L2 exclu** : `net 192.168.99.0/24`
5. **Exclure des protocoles de contrôle bruyants** : `not proto ospf and not proto vrrp`

Voir `CLAUDE.md` du dépôt source, section « Filtres de capture », pour le
détail de la syntaxe et les cas limites.

## Dépôt local des `.bin`

`--feature-bin-dir` (défaut `/etc/switch-capture/feature-bin`, que
l'installation se fasse via `install.sh`, le `.deb` ou le `.rpm` — les
trois créent le même chemin, voir `README-feature-bin.md`) doit contenir
une arborescence `<modèle>/<version>/*.bin` :

```
/etc/switch-capture/feature-bin/
  5130/
    R3113P05/5130ei-cmw710-packet-capture-r3113p05.bin
  5140/
    <version>/...
  5510/
    <version>/...
  5520/
    <version>/...
```

Nécessaire pour 5130/5140/5510/5520 (tous requièrent la feature). Non
applicable pour 3600 V2 (packet-capture non supporté sur cette plateforme).

### Y importer un dépôt déjà préparé (`import-bin`)

Si vous avez rassemblé vos `.bin` dans un dossier respectant cette
structure (par exemple `feature-bin/` à côté de `src/`, dans un clone du
dépôt), inutile de les recopier à la main après installation — la même
commande fonctionne identiquement que switch-capture ait été installé via
`install.sh`, le `.deb` ou le `.rpm` :

```bash
switch-capture import-bin ./feature-bin
# ou en ciblant explicitement un autre dossier :
switch-capture import-bin ./feature-bin --feature-bin-dir /etc/switch-capture/feature-bin
```

Sans `--feature-bin-dir`, la cible est résolue automatiquement :
`/etc/switch-capture/feature-bin` s'il existe déjà (cas normal après
installation), sinon `./feature-bin` (usage dev). L'opération fusionne
(écrase les fichiers en conflit, ne supprime rien côté cible) : peut être
relancée à chaque ajout de nouveaux `.bin` dans le dossier source.

`install.sh` fait cet import automatiquement à chaque exécution s'il
trouve un dossier `feature-bin/` à côté de lui (voir INSTALL.md) — cette
commande `import-bin` est ce qui permet d'obtenir le même résultat après
coup, ou avec un `.deb`/`.rpm` (qui n'embarquent volontairement aucun
`.bin` : ce sont des fichiers propriétaires HPE, pas redistribuables).

## Arrêter une capture en cours

`Ctrl+C` dans le terminal : arrêt propre. En mode `fifo`/`tap`, ferme le
FIFO/l'interface TAP et arrête les deux threads (capture + rotation). En
mode `rpcap`, envoie `packet-capture stop` sur le switch (pas de thread de
rotation dans ce mode, voir `CAPTURE-METHODS.md`).

## Automatisation (capture longue durée, sans surveillance)

Pour un lancement au démarrage ou une capture programmée, un service
systemd simple. Le `-c` est volontaire même si les arguments suffiraient
déjà à déclencher la CLI automatiquement : c'est une ceinture-et-bretelles
qui garantit qu'aucune fenêtre ne sera tentée même si GTK4 est installé
plus tard sur cette machine (service sans session graphique) :

```ini
# /etc/systemd/system/switch-capture@.service
[Unit]
Description=switch-capture sur %i
After=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/switch-capture/%i.env   # doit définir SWITCH_SSH_PASSWORD
ExecStart=/usr/bin/switch-capture -c capture --config /etc/switch-capture/%i.yaml
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now switch-capture@site-a
journalctl -u switch-capture@site-a -f
```

(Non installé automatiquement, quelle que soit la méthode d'installation
— à créer manuellement si besoin ; le fichier `.env` doit être en mode
`600`, lisible uniquement par root. Sur Rocky/RHEL, pensez à `restorecon`
si SELinux se plaint du contexte du fichier unit.)

## Dépannage

### `sudo ./switch-capture` échoue en RDP (mais fonctionne sans sudo)

Symptôme : lancer l'interface graphique avec `sudo` (nécessaire pour le
mode `tap`, seule partie de l'app qui a besoin de root/CAP_NET_ADMIN — voir
CLAUDE.md, section Sécurité) échoue systématiquement sur une session RDP
(xrdp), avec en tête du message :

```
Authorization required, but no authorization protocol specified
```

alors que la même commande fonctionne sans problème sans `sudo`, ou en
session console locale.

**Cause.** `sudo` réinitialise `HOME` par défaut (et donc `XAUTHORITY`) :
root ne trouve alors plus le cookie d'autorisation X11 de votre session
graphique — qui vit dans le `.Xauthority` de VOTRE compte, pas dans celui
de root. Une session console locale bénéficie souvent d'un `xhost`
automatique pour `localuser:root`, mis en place par le gestionnaire de
connexion ; une session xrdp, non — d'où l'écart observé entre RDP et
local. Depuis cette version, l'app détecte ce cas précis et affiche un
message explicite (au lieu d'un traceback Python) avec les mêmes solutions
que ci-dessous.

**Solutions, de la plus simple à la plus propre :**

1. Autoriser root une fois par session, avant `sudo` (à exécuter en tant
   qu'utilisateur normal, PAS avec sudo) :
   ```bash
   xhost +si:localuser:root
   sudo ./switch-capture
   ```
2. Transmettre explicitement `DISPLAY`/`XAUTHORITY` à `sudo` :
   ```bash
   sudo --preserve-env=DISPLAY,XAUTHORITY ./switch-capture
   ```
3. Si vous n'avez besoin que du mode `tap` en ligne de commande, pas de la
   fenêtre : la CLI seule n'a aucun accès X11 à négocier, donc aucun de ces
   problèmes :
   ```bash
   sudo ./switch-capture -c capture --output-mode tap ...
   ```

## Logs

- Console : niveau INFO (DEBUG avec `-v`).
- Fichier : `switch_capture.log` dans le répertoire courant, DEBUG complet,
  rotation à 5 Mo, rétention 10 jours.
