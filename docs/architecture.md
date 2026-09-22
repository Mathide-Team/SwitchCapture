# Architecture et choix techniques — switch_capture

> Extrait de l'ancien `CLAUDE.md` (contenu non daté, toujours valide) lors de la restructuration du 08/09/2026. Référence de fonctionnement : comment et pourquoi le système est construit ainsi. Consulté à la demande, pas à chaque démarrage de session — voir `CLAUDE.md` à la racine pour l'état courant.

---

# switch_capture — orchestrateur de capture réseau HPE Comware

## But

Automatiser, sur un switch HPE Comware 7 (5130/5140/5510/5520 ; 3600 V2
explicitement non supporté pour packet-capture), **trois méthodes de
capture distinctes** — voir `src/docs/CAPTURE-METHODS.md` pour la
comparaison complète et les procédures manuelles multi-constructeurs :

1. **packet-capture local** (`--output-mode fifo`/`tap`) : détecte le
   modèle, active SCP (`scp server enable`), installe la feature si besoin
   (5130/5140), vérifie/configure NTP, lance la capture avec rotation de
   fichiers et filtre inline optionnel, rapatrie/réinjecte en direct dans
   Wireshark (FIFO) ou une interface TAP dédiée (captures multiples
   simultanées).
2. **packet-capture remote / RPCAP** (`--output-mode rpcap`) : même moteur,
   mais streamé en direct sur le réseau — Wireshark se connecte
   directement au switch, aucun fichier ni FIFO/TAP local. Disponibilité
   selon modèle/version, pas systématique.
3. **Port mirroring** (`switch-capture mirror`) : SPAN local ou ERSPAN/GRE
   distant, poussé directement sur le switch — capture à débit ligne
   (plan de données ASIC), sans les limites CPU des deux méthodes
   précédentes. Le collecteur (Wireshark/tcpdump) est externe, hors
   périmètre de cet outil.
4. Sur demande, désinstaller proprement la feature `packet-capture`
   poussée en (1)/(2), ou retirer la configuration de mirroring poussée
   en (3).

## Fichiers

```
switch-capture/
├── README.md                    # page d'accueil GitHub
├── CLAUDE.md                    # ce fichier — architecture, choix techniques, pièges rencontrés
├── features.md                  # inventaire : fait/testé vs restant à faire
├── LICENSE                      # placeholder MIT, à ajuster
├── .gitignore
├── install.sh                  # installation directe (sans .deb/.rpm), lit ./src/
├── pyproject.toml               # dépendances (uv, session 63) + config ruff/pytest/coverage (session 60)
├── src/                        # SOURCE UNIQUE — code + docs partagées
│   ├── switch-capture               # point d'entrée UNIQUE (CLI + GTK4), voir plus bas
│   ├── switch_capture_core.py       # logique métier, sans dépendance GTK
│   ├── switch_capture_cli.py        # CLI (capture / uninstall / mirror / import-bin)
│   ├── switch_capture_gtk.py        # app GTK4, 5 pages, multi-captures (CaptureSession)
│   ├── org.transcende.switch_capture.desktop  # entrée menu applications (voir "Icône")
│   ├── icons/hicolor/scalable/apps/
│   │   └── org.transcende.switch_capture.svg  # icône app, arborescence hicolor standard
│   └── docs/
│       ├── INSTALL.md          # doc générique = celle d'install.sh
│       ├── USAGE.md            # référence CLI + GUI, identique quelle que soit la méthode
│       ├── CAPTURE-METHODS.md  # comparaison packet-capture/rpcap/mirroring+GRE/flow mirroring QoS, procédures manuelles multi-constructeurs
│       ├── README-feature-bin.md
│       └── config.yaml.example
├── models/                      # (créé à l'usage, non versionné) modèles de capture YAML, voir plus bas
├── tests/                       # suite pytest (indépendante de GTK4 et d'un switch réel)
│   ├── conftest.py              # ajoute src/ à sys.path (pas de packaging setup.py)
│   ├── test_capture_templates.py
│   └── test_tap_injector_thread.py  # découplage téléchargement/injection TAP, voir plus bas
├── uv.lock                      # verrouillage des dépendances (uv, session 63)
├── feature-bin/                 # (optionnel, non versionné) dépôt local de .bin, voir plus bas
├── packaging/                  # paquet .deb
│   ├── build_deb.sh            # lit ../src/, génère l'arbre FHS au build, dpkg-deb
│   ├── INSTALL-deb.md          # doc d'install spécifique apt/EPEL... (Debian/Ubuntu)
│   └── debian/DEBIAN/          # SEULEMENT les métadonnées : control, postinst, postrm
└── packaging-rpm/               # paquet .rpm
    ├── build_rpm.sh            # lit ../src/, tarball + rpmbuild
    ├── INSTALL-rpm.md          # doc d'install spécifique dnf/EPEL (Rocky/RHEL/CentOS)
    └── switch-capture.spec
```

**Icône/`.desktop`** : mêmes principes que le reste — source unique sous
`src/` (`icons/hicolor/...` + `org.transcende.switch_capture.desktop`),
copiée par les trois méthodes d'installation vers l'emplacement standard
(`/usr/share/icons/hicolor/...`, `/usr/share/applications/`). Voir la
section « Icône de l'application » plus bas pour le détail (pourquoi cette
arborescence précise, résolution en mode non installé, etc).

**Principe d'uniformisation** : `src/` est la seule copie du code applicatif et
des docs partagées (USAGE.md, config.yaml.example, README-feature-bin.md).
`install.sh`, `packaging/build_deb.sh` et `packaging-rpm/build_rpm.sh` la
lisent tous les trois de la même façon et construisent l'arborescence finale
(`/usr/lib/switch-capture`, `/usr/share/doc/switch-capture`, etc.) **au
moment du build**, plutôt que de la committer en dur trois fois. Seule la
doc d'installation diffère par nature entre les trois méthodes (paquets
système et étapes différents) : chacune a la sienne (`src/docs/INSTALL.md`
pour install.sh, `packaging/INSTALL-deb.md`, `packaging-rpm/INSTALL-rpm.md`),
mais `packaging/debian/` et `packaging-rpm/` ne contiennent plus, eux, que
des métadonnées de paquet — aucune copie de code ou de doc partagée.

## Un seul exécutable, un seul fichier source : `src/switch-capture`

`src/switch-capture` (sans extension `.py`) EST `/usr/bin/switch-capture` —
`install.sh`/`build_deb.sh`/`build_rpm.sh` le copient tel quel, en
réécrivant juste la ligne shebang pour pointer vers l'interpréteur retenu
(`sed -i "1s|^#!.*|#!${PYTHON_BIN}|"`, important sur el8 où ce n'est pas
`/usr/bin/python3`). Pas de fichier `switch_capture_launcher.py` séparé
en `/usr/lib/`, pas de wrapper heredoc régénéré différemment par chacune
des trois méthodes : un seul fichier, une seule logique, copié partout à
l'identique. Il importe `switch_capture_cli`/`switch_capture_gtk` (dans
`/usr/lib/switch-capture/`, ajouté à `sys.path` explicitement en tête de
fichier) et arbitre entre les deux, toutes deux construites au-dessus de
`switch_capture_core.py` (aucune dépendance couplée à l'une ou l'autre) :

- **sans argument** : lance la GUI GTK4 si PyGObject/GTK4 sont
  disponibles, sinon affiche l'aide CLI ;
- **arguments (et/ou `--config` YAML, et/ou `SWITCH_SSH_PASSWORD`)
  suffisants** pour construire une invocation complète (`capture`,
  `uninstall` ou `import-bin`) : bascule automatiquement en CLI, **sans
  jamais ouvrir de fenêtre**, même si GTK4 est installé — important pour
  cron/systemd sur une machine qui a aussi un environnement graphique ;
- **`-c`/`--cli`** force la CLI quels que soient les autres arguments ;
- **`-g`/`--gtk`** force la GUI, avec message d'erreur explicite si
  GTK4/PyGObject sont absents (jamais un plantage muet).
- **arguments partiels/invalides** (ex: `switch-capture capture
  --switch-ip ...` sans `--ssh-user`) : la CLI est invoquée telle quelle
  pour que son message d'erreur habituel (champ manquant, etc.)
  s'affiche — le lanceur ne bascule vers la GUI que si *rien* n'a été
  fourni, jamais pour masquer une tentative de CLI incomplète.
- **`import-bin`** est un cas particulier : elle n'a pas besoin de
  `Config` (pas de switch à joindre), donc pas de champs obligatoires à
  valider — sa simple présence syntaxiquement valide dans les arguments
  suffit à déclencher la bascule CLI directe (voir `_try_build_cli_config`
  dans `switch-capture` : traitement spécifique de cette sous-commande).

GTK4/PyGObject sont une dépendance **optionnelle** dans les trois méthodes
d'installation (`Recommends`, jamais `Depends`/`Requires`) : leur absence
n'empêche jamais l'installation ni l'usage en CLI. Piège connu et corrigé :
`switch_capture_gtk.main()` ne doit **jamais** passer `sys.argv` complet à
`Gtk.Application.run()` (le lanceur a déjà consommé `-c`/`-g` avant
d'arriver là ; les repasser fait planter GTK sur un flag qu'il ne connaît
pas) — `run(sys.argv[:1])` uniquement.

## GUI GTK4 : 5 pages multi-captures, pas un formulaire à rallonge

`switch_capture_gtk.py` organise l'interface en 5 pages (`Gtk.Stack` +
`Gtk.StackSwitcher` dans la barre de titre), reflétant le cycle de vie
réel d'une campagne de capture **potentiellement multi-switches/multi-
interfaces simultanée** (comparaison client/routeur/serveur — voir
`CAPTURE-METHODS.md`) plutôt qu'une seule capture à la fois :

1. **Configuration** — liste des captures planifiées (`self._sessions:
   list[CaptureSession]`) + formulaire d'ajout. Chaque « + Ajouter cette
   capture à la liste » construit un `Config` via `_build_config()`, crée
   un `CaptureSession`, l'ajoute à la liste. Toujours pas d'édition
   in-place au sens strict (`_on_remove_session`), mais depuis le
   25/08/2026 un bouton « Modifier » (`_on_edit_session`) retire la
   session puis repeuple entièrement le formulaire avec ses valeurs
   (`_config_to_raw_dict` + `_apply_form_values`, mot de passe SSH
   compris) — voir features.md, section « GUI : édition d'une capture
   déjà ajoutée à la liste » — donc plus de ressaisie manuelle complète.
   Désactivé si la capture est déjà en cours. Champs conditionnels
   selon `transfer_mode`/`output_mode` (voir plus bas). Bouton « Importer
   un dépôt .bin... » toujours présent, indépendant des sessions.
2. **Installation** — bouton « Lancer l'installation de toutes les
   captures » : pour chaque session `pending`/`failed`, spawn un
   `threading.Thread(target=session.setup.prepare)` (méthode `prepare()`
   de `SetupAndCaptureThread`, PAS `.start()` sur l'objet Thread lui-même —
   voir plus bas). Statuts affichés en direct (`pending`/`running`/`ok`/
   `failed`).
3. **Démarrage** — le bouton « Démarrer toutes les captures » n'est
   sensible (`set_sensitive`) que si **toutes** les sessions ont
   `install_status == "ok"` — c'est la garde explicitement demandée :
   l'installation de toutes les captures est un préalable au démarrage de
   n'importe laquelle. Au clic : pour chaque session prête, crée
   `CaptureRotationThread` si `output_mode != "rpcap"`, lance
   `session.setup.start_capture_blocking` dans un thread dédié, bascule
   vers Journal.
4. **Journal** — statut + progression par session (rafraîchi chaque
   seconde via `GLib.timeout_add` dans `_refresh_journal`), bouton
   « Arrêter toutes les captures » (`stop_event.set()` sur chaque session
   en cours), console de logs globale (toutes les sessions partagent le
   même sink loguru -> `LOG_QUEUE`, les messages s'interleaves
   naturellement).
5. **Résultats** — liste des `.pcap` de `spool_dir`/`archive_dir` de
   **toutes** les sessions (scan à la demande, bouton Rafraîchir), chaque
   ligne étiquetée `[label/Spool]` ou `[label/Archive]` pour distinguer
   l'origine.

### Pourquoi `prepare()`/`start_capture_blocking()` séparés dans `core.py`

`SetupAndCaptureThread` reste un `threading.Thread` (compat CLI : `run()`
enchaîne les deux phases comme avant, `.start()`/`.join()` inchangés pour
`switch_capture_cli.run_capture`). Mais un objet `Thread` ne peut être
démarré qu'une fois (`.start()` une seule fois dans sa vie) — impossible
donc d'utiliser le même objet pour la phase Installation PUIS la phase
Démarrage via `.start()` deux fois. La GUI multi-captures appelle donc
`prepare()` et `start_capture_blocking()` **directement comme méthodes
normales**, chacune depuis son propre `threading.Thread(target=...)`
créé à la volée — l'objet `SetupAndCaptureThread` sert alors de simple
conteneur de méthodes/état, jamais démarré comme Thread lui-même dans ce
chemin. `start_capture_blocking()` lève `RuntimeError` si appelé avant
`prepare()` (`self._prepared` non renseigné).

### Champs conditionnels (`_apply_transfer_mode_visibility`/`_apply_output_mode_visibility`)

Chaque ligne de formulaire (`_row`/_row_spin`/`_row_path`/`_row_dropdown`/
`_row_check`) s'enregistre dans **deux** dicts : `self._entries[key]` (le
widget de saisie, pour lire la valeur) et `self._rows[key]` (la ligne
complète — Box label+widget —, pour la masquer/l'afficher). Connectés au
signal `notify::selected` des dropdowns `transfer_mode`/`output_mode` :
- `transfer_mode=sshfs` -> affiche `mount_point` (masqué en `scp`, le défaut).
- `output_mode=fifo` -> `fifo_path` visible ; `tap`/`rpcap` masqués.
- `output_mode=tap` -> `tap_interface`/`tap_cleanup_on_stop` visibles.
- `output_mode=rpcap` -> `rpcap_port` visible ; **tout** ce qui touche au
  ring-buffer/rapatriement (`capture_basename`, `rotation_seconds`,
  `max_ring_files`, `spool_dir`, `archive_dir`, `poll_interval`) masqué —
  aucun fichier local en mode rpcap.

Toutes les zones à contenu variable (formulaire, listes, logs) appellent
`scrolled_window.set_overlay_scrolling(False)` + `set_policy(NEVER,
AUTOMATIC)` : scrollbar GTK4 classique verticale uniquement (espace
toujours réservé, visible dès qu'il y a plus à voir), jamais de scroll
horizontal. La fenêtre s'ouvre en 960×780 par défaut.

### Piège de test rencontré : `import -window root` sous Xvfb sans WM

Capturer une fenêtre GTK4 avec `import -window root` (ImageMagick) sur un
Xvfb sans gestionnaire de fenêtres/compositeur peut renvoyer une image
**périmée** après une mise à jour dynamique de l'UI (ex: liste de sessions
qui vient de changer), alors que l'état interne des widgets est déjà à
jour (vérifié via `listbox.get_first_child()`/`get_next_sibling()`) — pas
un bug applicatif. `import -window <ID exact via xdotool search>` (plutôt
que `root`) contourne le problème.

## Modèles de capture réutilisables (`models/`)

Ajouté le 23/08/2026 (features.md, point 1 de la liste « pas fait »).
Deux boutons dans le formulaire d'ajout de la page Configuration, à côté
de « + Ajouter cette capture à la liste » :

- **« Enregistrer comme modèle »** (`CaptureWindow._on_save_template`) :
  demande un nom via `Gtk.MessageDialog` + `Gtk.Entry`, lit le formulaire
  avec `_collect_raw_form_values()` (comme `_build_config()`, mais sans
  validation des champs obligatoires et **sans jamais lire le widget
  `ssh_password`**), puis appelle `save_capture_template` (core).
- **« Importer un modèle... »** (`CaptureWindow._on_load_template`) :
  liste `models/*.yaml` via `list_capture_templates`, propose un choix
  dans un `Gtk.DropDown` inséré dans la boîte de dialogue, charge le
  fichier avec `load_capture_template` et applique les valeurs sur le
  formulaire via `_apply_form_values()` — y compris les dropdowns
  `transfer_mode`/`output_mode`/`model` (résolution par valeur réelle,
  pas par libellé affiché) et la ré-application de
  `_apply_transfer_mode_visibility()`/`_apply_output_mode_visibility()`
  pour que les champs conditionnels se masquent/affichent correctement.
  Le mot de passe SSH n'est jamais restauré (jamais présent dans le
  fichier), un message le rappelle explicitement.

Logique de (dé)sérialisation dans `switch_capture_core.py` (aucune
dépendance GTK, testable en isolation, voir `tests/test_capture_templates.py`) :

- `TEMPLATE_EXCLUDED_FIELDS = {"ssh_password"}` et `_TEMPLATE_FIELDS`
  (calculé une fois via `dataclasses.fields(Config)`, champs `init=True`
  moins les champs exclus) — source de vérité unique pour ce qu'un
  modèle peut contenir.
- `config_to_template_dict(cfg)` / `template_dict_to_config_kwargs(data)` :
  conversions Config ↔ dict, toutes deux filtrent sur `_TEMPLATE_FIELDS`
  — `ssh_password` est donc écarté même si un appelant le passe par
  erreur dans `data` (pas seulement absent côté lecture du formulaire).
- `sanitize_template_name(name)` : liste noire plutôt que liste blanche
  de caractères — seuls `/`, `\` et l'octet nul sont interdits (empêche
  une traversée de dossier type `../../etc/passwd`), tout le reste est
  accepté (accents, espaces, ponctuation) pour un nom de modèle libre.
- `save_capture_template(models_dir, name, data)` : crée `models_dir` si
  besoin, écrit `<nom>.yaml` (`yaml.safe_dump`, clés triées). N'accepte
  pas de `Config` mais un simple `dict` — décision volontaire : côté GTK,
  `_collect_raw_form_values()` ne peut pas construire un `Config` valide
  puisque `ssh_password` (obligatoire pour `Config.__post_init__`) n'est
  jamais lu ; passer un `dict` évite de contourner cette validation avec
  un mot de passe factice.
- `load_capture_template(models_dir, name)` : lève `FileNotFoundError` si
  absent, renvoie un dict filtré prêt à fusionner avec un `ssh_password`
  saisi séparément (`Config(ssh_password=..., **kwargs)`).
- `list_capture_templates(models_dir)` : liste triée des `.stem` des
  `.yaml` du dossier, `[]` si le dossier n'existe pas encore (pas
  d'exception — le dossier n'existe qu'après le premier enregistrement).

**Piège évité** : `Config.__post_init__` exige `ssh_password` non vide et
valide les champs obligatoires (`switch_ip`, `ssh_user`,
`capture_interface`) — inutilisable tel quel pour un enregistrement de
modèle potentiellement partiel/sans mot de passe. D'où le choix d'un
`dict` brut comme format d'échange plutôt qu'un `Config`, aussi bien pour
`save_capture_template` que pour le retour de `load_capture_template`
(fusionné avec un mot de passe au moment de la construction du `Config`
final, jamais avant).

## Dépôt de `.bin` local et `import-bin`

Un dossier `feature-bin/` (sans « s », voir `README-feature-bin.md` pour
la structure `<modèle>/<version>/*.bin`) placé à la racine du dépôt, à
côté de `src/`, est :

- **importé automatiquement par `install.sh`** à chaque exécution
  (fusion, rien n'est supprimé côté cible) — voir la section dédiée dans
  `install.sh` juste après la création de l'arborescence. Si le dossier
  s'appelle `features-bin` (avec un « s », erreur de frappe courante),
  un avertissement explicite le signale au lieu d'échouer silencieusement.
- **jamais embarqué dans le `.deb`/`.rpm`** — volontairement : ce sont des
  fichiers propriétaires HPE (vendor, liés à un modèle/une version précis,
  pas redistribuables), les intégrer au paquet buildé n'aurait pas de
  sens. À la place, la sous-commande CLI `switch-capture import-bin
  <dossier>` fait exactement le même travail (résolution automatique de
  la cible : `/etc/switch-capture/feature-bin` si présent, sinon
  `./feature-bin`), utilisable identiquement après une install par
  `install.sh`, `.deb` ou `.rpm`. Voir USAGE.md pour les exemples, et le
  bouton « Importer un dépôt .bin... » de la page Configuration côté GUI.

## Pourquoi 2 threads plutôt qu'un plugin Wireshark

Un "vrai" plugin Wireshark (dissector Lua/C) ne peut pas piloter SSH, un
transfert SCP ou l'installation d'une feature switch. La bonne
architecture reste donc : un **orchestrateur** (`switch_capture_core`) qui
gère le cycle de vie côté switch/filesystem, et **Wireshark lui-même** en
mode "capture live" sur une **interface pipe** (`wireshark -k -i <fifo>`)
ou une **interface TAP**. En mode `rpcap`, ce schéma à deux threads
disparaît : Wireshark se connecte directement au switch en réseau, il n'y
a rien à rapatrier ni réinjecter (voir plus bas).

## Transfert de fichiers : SCP par défaut, sshfs en repli legacy

`Config.transfer_mode` : `"scp"` (défaut) ou `"sshfs"` (legacy). En mode
`scp`, aucun montage FUSE : `CaptureRotationThread` maintient sa propre
connexion netmiko (pour `dir flash:/<prefix>*.pcap` et `delete flash:/...`)
et une connexion paramiko dédiée au transfert SCP (`scp_get`/`scp_put`, via
le module `scp` — canal SCP séparé du canal interactif utilisé par les
commandes CLI, paramiko `SSHClient` indépendant plutôt qu'une réutilisation
des internals netmiko). `_prepare_switch` active `scp server enable` (pas
`sftp server enable` — commande Comware distincte). Le mode `sshfs` reste
disponible (`--transfer-mode sshfs`, `_mount_sshfs`/`_is_mounted`) pour qui
en dépend déjà, mais n'est plus recommandé : SCP est plus fiable sur un
lien distant/instable et ne nécessite pas FUSE côté client.

**Piège rencontré et corrigé (23/08/2026)** — deux bugs distincts remontés
en usage réel, tous deux au niveau du protocole SCP lui-même (pas de la CLI
Comware, qui elle n'était pas concernée) :

1. **`flash:` ne se met pas dans un chemin SCP.** `flash:` est une syntaxe
   propre aux commandes CLI Comware (`dir flash:/...`, `delete flash:/...`,
   `install activate feature flash:/...`) — le serveur SCP du switch a pour
   racine la flash elle-même, donc un chemin `flash:/<fichier>` échoue côté
   SCP alors qu'il fonctionne en CLI. Exemple correct :
   `10.0.0.1:/capture2_00001.pcap`, pas `10.0.0.1:flash:/capture2_00001.pcap`.
   `scp_get`/`scp_put` reçoivent désormais des chemins préfixés `/` (racine),
   jamais `flash:/`. Les appels CLI (`dir`, `delete`, `install activate
   feature`, `write`) gardent, eux, `flash:/<fichier>` — ce sont deux
   syntaxes distinctes pour la même flash, à ne pas mélanger.
2. **`Bad file descriptor` après le premier fichier rapatrié.** L'ancienne
   version ouvrait une connexion SCP (`open_scp_ssh_client`) une seule fois
   en tout début de capture (`run()`) et la réutilisait pour chaque fichier
   rapatrié tout au long du polling (`self._scp_ssh_client`). Le switch
   ferme apparemment la session SSH dédiée au SCP après un transfert (piste
   la plus probable : timeout ou fermeture volontaire côté Comware après
   complétion d'un `scp get`), et réutiliser ce transport devenu invalide
   sur le fichier suivant levait `Bad file descriptor`. Correctif :
   `_process_closed_file_scp` ouvre désormais une connexion SCP dédiée
   **par fichier rapatrié**, refermée juste après dans un `finally` — même
   schéma que `_push_feature_file`, qui n'était pas concerné (déjà
   ouvert/fermé par appel). Coût : une reconnexion SSH par fichier plutôt
   qu'une connexion persistante ; contrepartie jugée nécessaire pour
   fiabiliser le rapatriement. `_poll_conn` (netmiko, `dir`/`delete`)
   reste, lui, ouvert pour toute la durée de la capture — seul le canal SCP
   était concerné par le problème remonté.

Validé réellement (pas juste relu) : `sshd` local installé dans
l'environnement de dev, rapatriement séquentiel de 2 fichiers avec
reconnexion SCP à chaque fichier + contenu vérifié octet pour octet côté
client après transfert, `scp_put` testé isolément avec le chemin sans
`flash:` — les deux au niveau protocole SCP réel (pas mocké). `py_compile`
sur les 3 fichiers source Python après modification.

## NTP : nécessaire pour comparer des traces entre elles

`SetupAndCaptureThread._ensure_ntp()` vérifie `display ntp-service status`
(regex sur `clock status:\s*(\w+)` — **piège** : un simple `in` sur la
chaîne casse ici, `"unsynchronized"` contenant la sous-chaîne
`"synchronized"`) et configure `ntp-service enable` +
`ntp-service unicast-server <ip>` si `--ntp-server` est fourni et
l'horloge n'est pas synchronisée. Le statut (`ntp_synced`, `ntp_detail`)
est stocké dans `SharedState` et écrit dans le sidecar de métadonnées
(`write_capture_metadata`, un `capture-meta.json` dans `archive_dir`/
`spool_dir` avec `capture_label`, `switch_ip`, `capture_interface`,
`model`, timestamps, statut NTP). Sans horloges synchronisées entre
plusieurs switches capturant chacun un point du même trafic
(client/routeur/serveur), les timestamps ne sont pas comparables d'une
trace à l'autre — c'est tout l'intérêt de cette vérification, la
corrélation elle-même se fait dans un outil tiers, hors périmètre de
switch-capture.

## Interfaces TAP (`output_mode = "tap"`) et RPCAP (`output_mode = "rpcap"`)

Un FIFO ne peut avoir qu'un seul lecteur pcap cohérent : une seule capture
"live" à la fois. Pour observer plusieurs captures simultanément (même
trafic vu à plusieurs points), deux options :

- **TAP** (`ensure_tap_interface`, `TapFrameWriter`, `iter_pcap_frames`
  dans `switch_capture_core.py`) : crée une interface réseau virtuelle
  (`ip tuntap add dev <name> mode tap`), y injecte les trames extraites des
  `.pcap` rapatriés (`TUNSETIFF` + `os.write` sur `/dev/net/tun` — **pas**
  de décodage/reconstruction, juste les octets bruts de chaque trame,
  extraits via un parsing minimal des enregistrements pcap). Nécessite
  root/CAP_NET_ADMIN et le paquet `iproute2`/`iproute`. Testé de bout en
  bout dans ce dépôt (pcap → trame → TAP → `tcpdump` a bien reçu la
  trame). `tap_cleanup_on_stop` (def `False`) contrôle si l'interface est
  supprimée à l'arrêt ou laissée en place. `tap_pace_playback` (def
  `False`) contrôle si les trames d'un fichier rapatrié sont réinjectées
  en respectant approximativement leur écart de temps d'origine plutôt
  qu'aussi vite que possible — voir section dédiée « Lissage de la
  réinjection TAP » plus bas. `tap_launch_wireshark` (def `False`)
  lance automatiquement Wireshark sur l'interface une fois celle-ci
  prête, plutôt que de laisser l'utilisateur le faire — désactivé par
  défaut car peu adapté aux captures multiples simultanées (une fenêtre
  par capture au lieu d'une seule observant toutes les interfaces) ; voir
  section dédiée « Lancement automatique de Wireshark en mode TAP » plus
  bas.
- **RPCAP** (`_run_rpcap_blocking`) : utilise `packet-capture remote
  interface <if> port <port>`, une commande Comware native qui fait du
  switch un serveur RPCAP — Wireshark s'y connecte directement
  (`rpcap://<ip>:<port>/<if>`), sans fichier, FIFO ni TAP local. Plus
  simple que TAP quand disponible, mais **la disponibilité n'est pas
  garantie** : c'est le même moteur `packet-capture` que le mode local
  (même `MODEL_PROFILES`), donc soumis aux mêmes limites selon
  modèle/version — vérifier `display packet-capture status` avant de s'y
  fier. Depuis le 07/09/2026, `switch-capture inspect` (mode dry run) fait
  cette vérification à la place de l'utilisateur : `inspect_switch()`
  envoie aussi cette commande et restitue sa sortie brute telle quelle
  dans le rapport (`rpcap_status_raw`), sans tenter de la parser en
  booléen faute d'un exemple réel vérifié contre un switch physique — voir
  features.md, section « Autres limites connues », pour le détail et les
  tests. Dans ce mode, `CaptureRotationThread` n'est **pas** démarré du
  tout (`run_capture` dans `switch_capture_cli.py` : `t2 = None` si
  `output_mode == "rpcap"`) — rien à rapatrier.

## Lissage de la réinjection TAP (`tap_pace_playback`, 24/08/2026)

Traite la partie testable-en-isolation de la piste laissée ouverte dans
features.md (« pacage des trames injectées selon leurs timestamps
d'origine ») : `iter_pcap_frames` ignorait jusqu'ici les timestamps de
chaque enregistrement pcap (`_ts_sec`, `_ts_usec` préfixés `_`, jamais
utilisés) — `_feed_into_tap` écrivait les trames d'un fichier rapatrié
aussi vite que possible, sans rapport avec leur écart de temps d'origine.

- `iter_pcap_frames(pcap_file, with_timestamps=False)` : paramètre
  optionnel ajouté sans changer la signature par défaut ni le
  comportement historique (le seul appelant existant, `_feed_into_tap` en
  chemin sans pacing, ne le passe pas). `with_timestamps=True` yield
  `(timestamp_epoch, frame)` au lieu de `frame` seul.
- `compute_pacing_delays(timestamps, max_gap_seconds)` : fonction pure
  dans `switch_capture_core.py`, sans dépendance à `time.sleep` ni à
  `Config`/`CaptureRotationThread` — calcule le délai à attendre avant
  chaque trame, plafonné à `max_gap_seconds` (un vrai silence de
  plusieurs minutes dans la capture d'origine ne doit pas bloquer la
  réinjection d'autant), jamais négatif (horloge switch imprécise ou
  trames réordonnées → clampé à 0).
- `Config.tap_pace_playback: bool = False` / `Config.tap_pace_max_gap_seconds:
  float = 2.0` (validé `> 0` dans `__post_init__`) : nouveaux champs,
  wiring CLI automatique via `_CONFIG_FIELDS`
  (`switch_capture_cli.py`, `_add_common_config_args`) — `--tap-pace-playback`/
  `--tap-pace-max-gap`, même convention que `--tap-interface`/
  `--tap-cleanup-on-stop`.
- `CaptureRotationThread._feed_into_tap` : si `tap_pace_playback` est
  actif, matérialise la liste des `(timestamp, frame)` du fichier rapatrié
  (`iter_pcap_frames(..., with_timestamps=True)`), calcule les délais une
  fois (`compute_pacing_delays`), puis `time.sleep(delay)` avant chaque
  `write_frame` si `delay` est non nul. Sinon (défaut), chemin identique à
  avant ce changement — aucun `time.sleep` ajouté, aucune régression de
  perf pour qui n'active pas l'option.

**Limite assumée** : `_feed_into_tap` tourne dans `CaptureRotationThread`
lui-même — un `time.sleep` de pacing y bloque donc aussi le polling
suivant (rapatriement du fichier .pcap suivant) pendant ce temps.
Découpler téléchargement et lecture/injection via une file d'attente et
un thread dédié (pour que le pacing n'affecte jamais le polling) est
explicitement laissé pour une session future — voir features.md, point 1
de la section « Pas fait ».

**Non fait dans cette session, et pourquoi** : intégration GUI (case à
cocher GTK4 équivalente à `tap_cleanup_on_stop`) et mesure empirique
contre un switch réel (est-ce que le lissage améliore réellement la
fluidité perçue côté Wireshark, quelles valeurs par défaut de
`rotation_seconds`/`tap_pace_max_gap_seconds` sont pertinentes en
pratique) — respectivement pas d'environnement GTK4/PyGObject/Xvfb, et
pas de switch réel disponible dans cette session pour les valider comme
le reste de ce dépôt l'exige (voir méthodologie de test ci-dessus et dans
features.md). Le mécanisme lui-même (core + CLI) est testé réellement,
voir `tests/test_tap_pacing.py`.

## Port mirroring (`switch-capture mirror`) : capture à débit ligne

`MirrorConfig`/`MirrorThread`/`configure_local_mirror`/
`configure_gre_mirror`/`teardown_mirror` dans `switch_capture_core.py` :
pousse une configuration de mirroring (SPAN local ou ERSPAN/GRE distant),
syntaxe Comware vérifiée contre la doc H3C officielle (`mirroring-group`,
`interface tunnel ... mode gre`, `service-loopback type tunnel` si requis
par la plateforme). Contrairement à `SetupAndCaptureThread`, `MirrorThread`
ne bloque pas : il pousse la config puis se termine, le mirroring continue
de fonctionner côté switch sans supervision. Capture au niveau du plan de
données (ASIC), avant tout traitement CPU — contourne les limites de débit
de `packet-capture` (local ou remote). Le collecteur (Wireshark/tcpdump)
est externe, hors périmètre de cet outil ; Wireshark décode l'ERSPAN
nativement, aucune interface de réception à créer côté collecteur.

## Journalisation : audit complet des commandes envoyées au switch

Chaque `conn.send_command`/`send_command_timing` de `switch_capture_core.py`
est précédé d'un `logger.debug`/`logger.info` avec la commande littérale
(ou, pour une confirmation `y` sur prompt `[Y/N]`, un message dédié
"confirmation envoyée (y)") — **aucune commande poussée sur le switch
n'échappe aux logs**, même au niveau `debug`. Convention de niveau (pour ne
pas noyer le niveau `info` par défaut sous des requêtes `display` répétées) :

- `debug` : requêtes en lecture seule (`display ...`), confirmations `y`,
  et détail commande par commande des séquences de configuration
  (`configure_local_mirror`/`configure_gre_mirror`/`teardown_mirror` —
  refactorées en liste de commandes + boucle pour ça, même ordre/mêmes
  commandes qu'avant, un seul site de log à maintenir par fonction).
- `info` : conservé pour les actions ponctuelles qui l'étaient déjà
  (activation SCP/NTP, activation de la feature, suppression d'un fichier
  distant côté flash, résumé mirroring) — c'est le niveau de log "normal"
  d'une capture, la trace commande par commande n'apparaît qu'en `debug`.

**Piège de test rencontré** : pas de switch réel disponible pour valider
ça "pour de vrai" comme le reste du projet (SSH/SCP contre un `sshd`
local, TAP contre `tcpdump`, etc.) — utilisé à la place un faux `conn`
(`FakeConn`, méthodes `send_command`/`send_command_timing`/`config_mode`/
`exit_config_mode` qui enregistrent tout sans rien envoyer réellement),
`connect_switch` monkeypatché pour l'injecter, et le sink loguru redirigé
vers une liste en mémoire (niveau `TRACE`) pour vérifier par assertion
que chaque commande effectivement "envoyée" au faux `conn` apparaît
littéralement dans un message capturé. Fonctionne bien pour ce genre de
changement (structure/couverture des logs), pas un substitut aux tests
contre un vrai switch pour tout ce qui touche au comportement Comware
lui-même.

## Profils matériels (`MODEL_PROFILES`)

| Modèle  | Comware | packet-capture                          |
|---------|---------|------------------------------------------|
| 5130    | 7       | feature installable (`.bin` séparé)       |
| 5140    | 7       | feature installable (`.bin` séparé)       |
| 5510    | 7       | feature installable (`.bin` séparé)       |
| 5520    | 7       | feature installable (`.bin` séparé)       |
| 3600 V2 | 5       | **non supporté** — pas de ring-buffer     |

Correction importante (une hypothèse antérieure de ce fichier était
fausse) : **5510/5520 ne sont pas natifs**, ils nécessitent l'installation
de la feature `packet-capture` exactement comme 5130/5140 —
`MODEL_PROFILES["5510"]["packet_capture"]` et `["5520"]` valent tous les
deux `"installable"`, pas `"builtin"`. Le mécanisme `"builtin"` reste dans
le code (au cas où un modèle non listé en aurait besoin un jour), mais
aucun modèle actuellement listé ne l'utilise.

Le modèle est auto-détecté via `display version` (`detect_model`), avec
possibilité de le forcer manuellement dans le formulaire (utile si la
sortie ne matche aucun alias connu, ou pour un modèle apparenté non encore
dans la liste). `packet-capture remote` (rpcap) partage ce même tableau de
disponibilité (même moteur, voir plus haut) — sa disponibilité réelle
varie en plus selon la version logicielle, plus finement que ce que
`MODEL_PROFILES` peut exprimer par modèle seul.

Limite connue sur les alias eux-mêmes (session 08, verrouillée par des
tests en [session 50](sessions/session-50.md)) : `5130`/`5140` utilisent
le format réel HPE à tiret (`"5130-28-EI"`), vérifié et corrigé après une
régression. `5510`/`5520` (ainsi que `MSR4000`/`3600v2`) n'ont, eux,
jamais été audités faute de sortie `display version` réelle disponible
pour ces modèles — leurs alias sont restés sous forme collée
(`"5510HI"`), qui ne matcherait vraisemblablement pas une sortie switch
réelle si elle suit le même schéma que 5130/5140. Voir
`tests/test_model_detection.py` pour le comportement actuel verrouillé
des deux côtés (glued/dash).

Pour le 3600 V2 (Comware 5) : il n'existe pas de commande `packet-capture`
à ring-buffer ni de mécanisme `install activate feature`, et `packet-capture
remote` n'existe pas non plus. L'alternative est le **port mirroring**
(`switch-capture mirror`, voir plus haut) — capture au débit ligne,
indépendante de `packet-capture`, disponible même là où celui-ci ne l'est
pas.

## Filtres de capture : ACL ou inline, sans ACL

Contrairement à ce qu'on pourrait croire en lisant certains posts
communautaires HPE (qui utilisent une ACL + une politique QoS
`mirror-to cpu` pour faire remonter le trafic vers le CPU sur certains
5130), **la commande `packet-capture` accepte un filtre inline**, sans ACL
ni politique QoS à préconfigurer :

```
packet-capture interface <interface>
    [ capture-filter <expression> ]
    [ display-filter <expression> ]
    limit-captured-frames <n>
    capture-ring-buffer duration <n>
    capture-ring-buffer files <n>
    write flash:/<fichier>.pcap
```

`capture-filter` prend une expression façon **tcpdump/BPF** (chaîne de 1 à
256 caractères) : qualifiers (`host`, `port`, `proto`, `net`...), variables,
opérateurs logiques (`and`/`or`/`not`) et relationnels. C'est ce que le
formulaire GTK expose dans le champ "Filtre de capture", avec un menu de
préréglages (`CAPTURE_FILTER_PRESETS` dans `switch_capture_core.py`).

L'ACL reste une option (et la seule solution si vous avez besoin de
matcher sur des critères qu'une expression `capture-filter` ne sait pas
exprimer, ou si vous voulez réutiliser une ACL déjà en place ailleurs),
mais elle n'est **plus nécessaire** pour l'usage courant.

### 5 exemples, du plus simple au plus complexe

1. **Un hôte** — tout le trafic vers/depuis une IP :
   ```
   host 10.0.0.5
   ```

2. **Hôte + port** — une session de gestion SSH précise :
   ```
   host 10.0.0.5 and tcp port 22
   ```

3. **Un protocole** — trafic GRE d'un tunnel (cas des switches
   5510/5520 en cours de diagnostic keepalive GRE) :
   ```
   proto gre
   ```
   Limite : le filtre ne voit que l'en-tête GRE extérieur. Pour inspecter
   le contenu encapsulé (ex: un keepalive ICMP dans le tunnel), filtrez au
   niveau du protocole externe ici, puis affinez côté Wireshark avec un
   display filter (`gre`) une fois le flux ouvert.

4. **Sous-réseau, hygiène du bruit** — ne garder que l'IP d'un VLAN de
   management, en excluant implicitement ARP/STP/LLDP (non-IP, donc jamais
   matchés) :
   ```
   net 192.168.99.0/24
   ```

5. **Exclusion de protocoles de contrôle bruyants** — tout capturer sauf
   OSPF hello et VRRP (utile pour ne pas noyer une capture de diagnostic
   applicatif sous du bruit de routage) :
   ```
   not proto ospf and not proto vrrp
   ```

## Désinstallation de la feature (CLI `uninstall` ou bouton GTK)

Séquence Comware standard, implémentée dans `UninstallThread` et exposée à
la fois par `switch-capture -c uninstall ...` (CLI) et par un bouton dans
le formulaire GTK4 :

```
install deactivate feature flash:/<fichier>.bin slot <N>
install commit
delete /unreserved flash:/<fichier>.bin        # optionnel (case à cocher)
```

- `install deactivate` seul ne suffit pas : sans `install commit`, la
  feature redevient active au prochain redémarrage.
- La suppression du `.bin` de la flash est optionnelle (`--remove-bin` en
  CLI, case à cocher dans le formulaire) — le laisser en place permet une
  réactivation rapide sans retransfert.
- Sans effet uniquement si le modèle avait le profil `"builtin"` (aucun
  modèle actuellement listé — 5510/5520 nécessitent bien l'installation,
  voir correction plus haut) : dans ce cas hypothétique, rien n'aurait été
  installé côté flash, le bouton le signale simplement dans la console de
  logs / la boîte de dialogue.
- Sur 3600 V2, non applicable (jamais rien installé, packet-capture non
  supporté sur cette plateforme).
- **Confirmation renforcée (23/08/2026)** : la connexion SSH n'est jamais
  tentée sans confirmation explicite de l'IP, sur les deux interfaces.
  - GTK : le dialogue ajoute un `Gtk.Entry` sous la case à cocher ; le
    bouton « Désinstaller » (`Gtk.ResponseType.OK`) démarre insensible et
    ne s'active que lorsque le texte saisi correspond exactement à
    `cfg.switch_ip` (espaces de début/fin ignorés) — revérifié
    défensivement dans le handler `response` avant tout appel à
    `UninstallThread`.
  - CLI : flag `--confirm-ip`, **opt-in** (défaut = comportement inchangé,
    aucun prompt) pour ne pas casser un appel cron/systemd sans entrée
    standard (voir plus haut, section lanceur). Fourni, `run_uninstall`
    demande de retaper l'IP via `input()` avant de construire quelque
    connexion que ce soit ; `EOFError` est traitée comme un abandon (code
    de sortie 1), pas comme un crash.
  - Les deux passent par la même fonction pure `confirm_ip_matches(entered,
    expected)` dans `switch_capture_core.py` (juste avant `UninstallThread`)
    pour ne jamais diverger sur la règle de correspondance.

## Approcher le temps réel

Le pipeline est intrinsèquement basé sur des fichiers tournants, pas sur
un flux continu natif — la latence minimale est donc `rotation_seconds`
(le switch doit *clôturer* un fichier avant qu'on puisse le lire), plus
jusqu'à `poll_interval` (pire cas : le fichier vient de se clôturer juste
après un scan), plus le temps de copie sshfs (non négligeable sur un lien
à ~15 000 km).

Réglage recommandé pour un "quasi temps réel" raisonnable :
**`rotation_seconds = 20`**, **`poll_interval = 5`** (valeurs par défaut du
formulaire) → latence typique de l'ordre de 25-30 s avant qu'un paquet
capturé n'apparaisse dans Wireshark.

Arbitrages :
- **Descendre à 10 s / 2-3 s** réduit la latence mais augmente la
  fréquence d'ouverture/fermeture de fichier côté switch (I/O flash plus
  fréquentes, plus de petits transferts sshfs) — à tester en labo avant
  une utilisation prolongée en prod.
- **Monter à 60 s et plus** réduit l'overhead mais rend l'expérience "live"
  peu utile (on retombe presque sur une analyse a posteriori par blocs).
- La latence ne descendra jamais sous `rotation_seconds`, quel que soit le
  réglage de `poll_interval` : c'est la contrainte structurelle du
  ring-buffer côté switch, pas un problème d'implémentation du script.

**Si un vrai temps réel est nécessaire** (latence sub-seconde), ce
pipeline fichiers-tournants n'est pas le bon outil : `--output-mode rpcap`
(streaming réseau direct, si le modèle le supporte) ou `switch-capture
mirror` (SPAN/ERSPAN+GRE vers un collecteur dédié `tcpdump`/Wireshark)
éliminent tous deux complètement la logique de rotation/réinjection — voir
`src/docs/CAPTURE-METHODS.md` pour le détail des deux options.

## Sécurité / bonnes pratiques

- Le mot de passe SSH n'est **jamais écrit sur disque** par l'app GTK : il
  vit uniquement en mémoire (widget `Gtk.PasswordEntry`) le temps de la
  session. Alternative : variable d'environnement `SWITCH_SSH_PASSWORD`
  au lancement, laisser le champ vide dans le formulaire. Même principe
  côté CLI : `SWITCH_SSH_PASSWORD` plutôt que `--ssh-password` en clair
  sur la ligne de commande (visible dans l'historique shell / `ps`) ou
  dans un `config.yaml` committé.
- Aucun utilisateur local n'est créé sur le switch : le compte RADIUS
  existant doit déjà être autorisé pour les services `ssh` et `scp` côté
  serveur RADIUS (`sftp` uniquement si `--transfer-mode sshfs`).
- Mode `sshfs` (legacy) uniquement : monté sans `allow_other`, seul
  l'utilisateur qui lance l'app y a accès.
- Mode `tap` : nécessite root/CAP_NET_ADMIN pour créer l'interface réseau —
  n'accordez cette capability qu'au compte de service dédié, pas à
  l'utilisateur final.
- Testez d'abord sur un switch de labo, en particulier le flux de
  désinstallation, avant utilisation sur un switch de production distant
  sans présence sur site.

## Tests automatisés (`tests/`, pytest)

Ajouté le 23/08/2026, en complément (pas en remplacement) des scripts de
validation ad hoc décrits section par section dans ce fichier (FakeConn,
sshd local, Xvfb...) qui restent la référence pour tout ce qui touche au
comportement Comware/SSH/GTK réel :

```bash
uv sync
uv run pytest tests/ -v
```

- `tests/conftest.py` ajoute `src/` à `sys.path` : `src/` reste copié tel
  quel par `install.sh`/`build_deb.sh`/`build_rpm.sh`, jamais installé comme
  un paquet pip (`pyproject.toml` gère les dépendances via `uv` depuis la
  session 63, mais ne définit toujours aucun `[build-system]` — voir
  l'en-tête de ce fichier et `docs/sessions/session-63.md`). Pas besoin
  de préfixer chaque test avec un `sys.path.insert`.
- `tests/test_capture_templates.py` : 22 tests couvrant les modèles de
  capture réutilisables (section dédiée ci-dessus) — le premier module
  testé automatiquement dans ce dépôt, choisi précisément parce qu'il ne
  dépend ni de GTK4/PyGObject ni d'un switch réel (contrairement à la
  quasi-totalité du reste du projet, qui nécessite soit un vrai switch
  Comware soit au minimum un environnement graphique Xvfb pour être
  validé). Utilise `tmp_path` (fixture pytest) pour ne jamais écrire dans
  un vrai dossier `models/` pendant les tests.
- `tests/test_uninstall_confirm.py` (23/08/2026) : 10 tests couvrant la
  confirmation renforcée avant désinstallation (section dédiée ci-dessus)
  — `confirm_ip_matches` en isolation, et `run_uninstall(...,
  confirm_ip=...)` avec `UninstallThread` remplacée par un faux thread
  (même principe que FakeConn : aucune connexion SSH réellement ouverte).
  Le volet GTK de cette même fonctionnalité (gating du bouton
  « Désinstaller ») a été validé par introspection de widgets sous Xvfb
  au moment du changement, mais délibérément pas ajouté ici — voir point
  suivant.
- `tests/test_inspect.py` (23/08/2026) : 20 tests couvrant le mode dry
  run (section dédiée ci-dessus) — `is_ntp_synchronized` et
  `format_inspect_report` en isolation, validation `InspectConfig`, et
  `inspect_switch` avec un `FakeConn` volontairement dépourvu de toute
  méthode d'écriture (`config_mode` absente exprès — une régression qui
  ferait envoyer une commande de configuration casserait le test avec une
  `AttributeError`, pas juste un test qui échoue silencieusement). Le
  bouton GTK « Inspecter » a été validé de la même façon que
  « Désinstaller » ci-dessus, pas ajouté à pytest pour la même raison.
- `tests/test_tap_pacing.py` (24/08/2026) : 16 tests couvrant le lissage
  de réinjection TAP (section dédiée ci-dessous, « Lissage de la
  réinjection TAP ») — `iter_pcap_frames` avec/sans timestamps sur un
  `.pcap` synthétique construit à la main, `compute_pacing_delays` en
  isolation, validation de `Config.tap_pace_max_gap_seconds`, et
  `_feed_into_tap` avec un `FakeTapWriter` (pas de vraie interface TAP,
  pas de root/CAP_NET_ADMIN requis) et `time.sleep` monkeypatché.
- Total actuel : **68 passed** (`pytest tests/ -v`).
- Périmètre volontairement limité pour l'instant à ce qui ne dépend ni de
  GTK4/PyGObject ni d'un switch réel : convertir les scripts ad hoc
  existants (FakeConn pour l'audit de commandes, sshd local pour SCP,
  extraction/injection TAP contre `tcpdump`, introspection de widgets
  GTK) en tests `pytest` réutilisables est une piste pour une session
  future, pas fait ici.

## Pistes d'amélioration envisagées, non implémentées

- **Filtrage ACL pour `switch-capture mirror`** : `packet-capture` a déjà
  un filtre inline (voir « Filtres de capture » ci-dessus), mais
  `switch-capture mirror` ne mirrore aujourd'hui que des ports entiers.
  Le flow mirroring Comware (`mirror-to interface ... destination-ip
  ...`, piloté par ACL + QoS policy plutôt que par `mirroring-group` —
  voir `CAPTURE-METHODS.md` section 4, ajoutée le 01/09/2026) permettrait
  de filtrer aussi le mirroring ASIC/GRE, sans les limites CPU de
  `packet-capture`. Non implémenté, documenté pour l'instant uniquement
  comme procédure manuelle de référence.
- **Débit en direct côté switch (CLI brut)** : la version "moyen, à partir
  de `bytes_merged`" de cette idée est traitée (voir section « Débit de
  transfert moyen en direct » ci-dessous et features.md) ; reste en
  suspens la version d'origine — un débit *instantané* extrait en
  parsant la sortie CLI brute de `packet-capture` pendant la capture
  (`conn.read_channel()`, actuellement seulement loguée en `trace`) —
  qui nécessite de vérifier le format réel de cette sortie contre un
  switch, non disponible dans les sessions récentes.
- **Migration `Gtk.FileChooserNative`/`Gtk.MessageDialog` vers
  `Gtk.FileDialog`/`Gtk.AlertDialog`** (identifié le 12/09/2026, audit
  Context7 — voir [session 56](sessions/session-56.md)) : les deux
  classes utilisées aujourd'hui dans `switch_capture_gtk.py`
  (sélecteurs de dossier, lignes ~845/862 ; confirmations, lignes
  ~1664/1902/1942/2355) sont dépréciées depuis GTK 4.10 au profit de
  `Gtk.FileDialog`/`Gtk.AlertDialog` (API asynchrone `*_async`/
  `*_finish` plutôt que le signal `response` actuel — confirmé contre
  la documentation PyGObject à jour). Ni cassé ni supprimé aujourd'hui :
  dette technique, pas un bug actif. Non implémenté : nécessite (1) de
  vérifier la version GTK4 réellement disponible sur les cibles de
  packaging actuelles (Debian, Rocky/RHEL 9 — paquet système `gtk4`,
  voir `packaging-rpm/switch-capture.spec`) avant de s'engager sur la
  nouvelle API, même principe que la vérification d'alias 5510/5520
  (ne jamais deviner sans preuve — voir features.md), et (2) une
  réécriture des 6 sites d'appel ainsi que des scripts ad hoc Xvfb qui
  les valident (la GUI reste hors périmètre pytest, voir section
  « Tests automatisés » ci-dessus).
- **Callback de progression SCP en direct** (identifié le 12/09/2026,
  audit Context7) : le paquet `scp` (`scp>=0.14`, classe `SCPClient`)
  accepte un paramètre `progress` — `function(filename, size, sent)`,
  appelé pendant le transfert (confirmé contre le code source/README du
  paquet, non indexé sur Context7, vérifié par recherche web directe) —
  jamais utilisé par `scp_get`/`scp_put` aujourd'hui, qui ne calculent
  un débit qu'une fois le fichier entièrement rapatrié (voir « Débit de
  transfert moyen en direct » ci-dessous). Permettrait un pourcentage de
  progression par fichier, remonté jusqu'à la page « Journal » de la
  GUI et au CLI verbeux — utile en particulier pour les fichiers de
  capture volumineux pendant le polling de rotation. Non implémenté.
- **Support d'un keyfile PyKeePass en plus du mot de passe maître**
  (identifié le 12/09/2026, audit Context7) : `PyKeePass(path,
  password=..., keyfile=...)` accepte un fichier clé en plus du mot de
  passe maître (confirmé contre la documentation pykeepass,
  `CredentialsError` couvrant aussi un keyfile incorrect/manquant) —
  pratique de durcissement KeePass courante (mot de passe + keyfile),
  non supportée aujourd'hui par `_open_keepass_db` (mot de passe maître
  seul). Ajout rétrocompatible envisagé : `--keepass-keyfile`/clé YAML
  `keepass_keyfile` optionnelle, `None` par défaut. Non implémenté.
- **`pyproject.toml` centralisant la configuration `ruff`/`pytest`/
  `coverage`** (identifié le 12/09/2026, audit Context7) : `ruff`
  découvre nativement un `[tool.ruff]` dans `pyproject.toml` (ou un
  `ruff.toml` séparé, confirmé contre la documentation Astral/Ruff à
  jour) — éviterait de répéter `--line-length 120` sur chacune des deux
  commandes `ruff` de `CLAUDE.md` ; de même `[tool.pytest.ini_options]`
  (`testpaths = ["tests"]`) et `[tool.coverage.run]`
  (`source = ["src"]`) éviteraient de répéter `tests/`/`--source=src`.
  **Point d'attention** : `tests/conftest.py` documente explicitement
  l'absence actuelle de `pyproject.toml`/`setup.py` comme un choix
  délibéré (`src/` copié tel quel par les 3 méthodes d'installation,
  pas de packaging) — un `pyproject.toml` limité aux seules sections
  `[tool.*]` ci-dessus (sans `[build-system]`/`[project]`) ne remettrait
  pas en cause ce choix, mais le premier commit d'un tel fichier devra
  le documenter explicitement (y compris dans `tests/conftest.py`
  lui-même) pour éviter toute confusion future sur ce point. Non
  implémenté.

(Trois pistes retirées de cette liste le 23/08/2026 : « Sauvegarde/
rechargement de profils de configuration » — en fait déjà livrée cette
même date sous le nom « Modèles de capture réutilisables sans mot de
passe », cette entrée n'avait simplement pas été retirée de la liste ;
« Confirmation renforcée avant désinstallation » et « Mode "dry run" » —
toutes deux traitées dans cette session, voir sections Désinstallation
ci-dessus et « Mode dry run » ci-dessous, ainsi que features.md. Une
quatrième piste, « Compteur de paquets/débit en direct », a été
partiellement traitée le 24/08/2026, puis son volet GUI a été complété le
24/08/2026 (même journée, suite de session) — voir points ci-dessus et
section dédiée plus bas ; retirée de cette liste à ce titre. Une
cinquième piste, « Case à cocher GTK4 "lissage TAP" (`tap_pace_playback`) »,
a été traitée le 24/08/2026 dans la foulée du même environnement
GTK4/PyGObject/Xvfb — voir « Intégration GUI du lissage de réinjection
TAP » dans features.md ; retirée de cette liste à ce titre. Une sixième
piste, « Trousseau système (libsecret/GNOME Keyring) pour mémoriser le mot
de passe SSH », a été traitée le 25/08/2026 — voir section dédiée
ci-dessous et features.md ; retirée de cette liste à ce titre. Une
septième piste, « Keepalive netmiko sur la connexion de polling longue
durée » (identifiée le 12/09/2026, audit Context7), a été traitée le
12/09/2026 (session 57) — voir « Connexion SSH de contrôle (netmiko) »
dans features.md ; retirée de cette liste à ce titre.)

