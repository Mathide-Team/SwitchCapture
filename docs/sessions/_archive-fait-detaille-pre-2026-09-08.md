# Archive détaillée — « Fait, et testé réellement » (avant restructuration)

> Contenu daté de l'ancien `features.md`, conservé tel quel lors de la restructuration du 08/09/2026 : entrées session par session côté vérification/tests, plus la liste numérotée originale des demandes (points 1 à 20) avec leur résolution, plus l'ancien pavé « Suivi des sessions » (comptages et environnements par jour).
>
> Ce texte fait doublon avec `docs/sessions/` (qui documente les mêmes sessions côté raisonnement/conception, généralement en plus détaillé) — voir `docs/sessions/index.md` pour naviguer session par session. Conservé ici par sécurité, pour ne rien perdre du détail « côté tests » écrit au fil de l'eau.

---

### Modèles de capture réutilisables sans mot de passe (23/08/2026)

Deux boutons dans le formulaire d'ajout de la page Configuration, à côté
de « + Ajouter cette capture à la liste » :

- **« Enregistrer comme modèle »** : demande un nom (boîte de dialogue),
  écrit la configuration courante du formulaire — **hors `ssh_password`**
  — en YAML dans `models/<nom>.yaml` (dossier créé si absent).
- **« Importer un modèle... »** : liste les `.yaml` de `models/` dans un
  menu déroulant, charge le fichier choisi et remplit le formulaire
  (champs texte/nombre/case à cocher/listes déroulantes `transfer_mode`/
  `output_mode`/`model`) — le mot de passe SSH n'est jamais restauré,
  message explicite invitant à le ressaisir.

Logique de sérialisation côté `switch_capture_core.py` (sans dépendance
GTK, testable en isolation) : `config_to_template_dict`/
`template_dict_to_config_kwargs` (filtrage aux seuls champs valides de
`Config`, `ssh_password` exclu dans les deux sens même si présent par
erreur dans les données d'entrée), `sanitize_template_name` (rejette les
séparateurs de chemin `/`/`\` pour empêcher une traversée de dossier type
`../../etc/passwd`, accepte accents/ponctuation courante), `save_capture_template`/
`load_capture_template`/`list_capture_templates`.

Testé réellement (22 tests `pytest`, voir section Tests automatisés
ci-dessous) : round-trip Config → dict → YAML → dict → nouveau `Config`
valide (mot de passe ressaisi séparément), non-persistance du mot de
passe même si présent explicitement dans les données passées à
`save_capture_template`, rejet des noms invalides, dossier `models/`
créé à la demande, listing trié, erreur explicite sur modèle manquant.
Import direct de `switch_capture_gtk` + `py_compile` sur les 2 fichiers
source Python modifiés pour confirmer l'absence de régression de syntaxe/
signature ; `ruff check --line-length 120` ne signale aucune nouvelle
erreur par rapport à l'état du dépôt avant ce changement (32 erreurs
préexistantes inchangées, toutes hors des lignes ajoutées).

### Confirmation renforcée avant désinstallation — retaper l'IP (23/08/2026)

Remplace, côté GUI, la simple boîte Oui/Non par une confirmation qui
oblige à retaper l'IP du switch avant de pouvoir cliquer sur
« Désinstaller » — piste listée dans CLAUDE.md, désormais traitée :

- **GTK** : le dialogue de désinstallation (`_on_uninstall_session`)
  ajoute un `Gtk.Entry` sous la case « supprimer aussi le .bin ». Le
  bouton « Désinstaller » démarre insensible (`set_sensitive(False)`) et
  ne redevient cliquable que lorsque le texte saisi correspond exactement
  (espaces de début/fin ignorés) à `cfg.switch_ip`. Revérification
  défensive dans `on_response` (au cas où une réponse OK serait émise
  autrement que par un clic sur ce bouton précis) : la désinstallation
  n'est jamais lancée si l'IP retapée ne correspond pas.
- **CLI** : nouveau flag `--confirm-ip` sur `switch-capture uninstall`,
  **opt-in** (comportement par défaut inchangé) pour ne pas casser un
  lancement automatisé (cron/systemd, voir CLAUDE.md) qui n'a aucune
  entrée standard à laquelle répondre. Fourni, il déclenche un prompt
  interactif demandant de retaper l'IP avant toute tentative de connexion
  SSH ; une `EOFError` (stdin fermée) est traitée comme un abandon propre
  plutôt qu'un traceback.
- **Logique partagée** : `confirm_ip_matches(entered, expected)`, ajoutée
  à `switch_capture_core.py` juste avant `UninstallThread` (sans
  dépendance CLI/GTK, testable en isolation), utilisée à l'identique par
  les deux interfaces pour que la règle de correspondance ne diverge
  jamais entre elles.

Testé réellement (pas juste relu) :
- CLI : 10 tests `pytest` (voir section Tests automatisés ci-dessous) —
  `UninstallThread` remplacée par un faux thread qui n'ouvre aucune
  connexion SSH, pour prouver qu'aucune tentative de connexion n'a lieu
  quand l'IP saisie ne correspond pas. Couvre aussi le cas `EOFError` et
  la non-régression du comportement par défaut (`confirm_ip=False` ->
  zéro appel à `input()`, donc aucun risque pour un usage cron/systemd
  existant).
- GTK : introspection directe des widgets sous Xvfb (même méthode que le
  reste du projet) — `Gtk.Application` réelle, dialogue effectivement
  ouvert, `Gtk.Entry` manipulée via `set_text()` : bouton insensible au
  départ, reste insensible sur IP incorrecte, devient sensible sur IP
  correcte (espaces tolérés), redevient insensible si le champ est vidé.
  Script de validation ad hoc, non committé — même choix que les autres
  validations GTK de ce dépôt (voir CLAUDE.md ; `tests/` reste
  volontairement indépendant de GTK4/PyGObject, voir juste en dessous).
- `py_compile` + import réel des 3 fichiers source modifiés : aucune
  régression de signature.
- `ruff check --line-length 120 src/` : 33 erreurs, strictement identique
  à l'état du dépôt avant ce changement (mesuré dans l'environnement de
  cette session, avec ruff 0.16.4 et sans config ruff figée dans le
  dépôt — l'écart avec le « 32 » noté lors de la session précédente
  vient probablement d'une version d'outil différente, sans lien avec ce
  changement). Le nouveau fichier `tests/test_uninstall_confirm.py` est
  ruff-clean à l'exception du même avertissement `C408` (`dict()` au lieu
  d'un littéral) déjà présent et accepté dans `test_capture_templates.py`.

### Mode dry run — « Inspecter » un switch sans rien modifier (23/08/2026)

Détecte modèle/version/features actives sur un switch sans jamais rien
configurer — piste listée dans CLAUDE.md, désormais traitée. Utile avant
une première intervention sur un switch distant sans accès physique : on
sait ce qui s'y trouve avant de risquer d'y toucher.

- **`InspectConfig`** (`switch_capture_core.py`), volontairement plus
  légère que `Config` — même principe que `MirrorConfig` : pas de
  `capture_interface` obligatoire, puisque le dry run ne capture rien.
  Champs : `switch_ip`, `ssh_user`, `ssh_password` (ou
  `SWITCH_SSH_PASSWORD`), `model`, `feature_bin_path`/`feature_bin_dir`,
  `transfer_mode`. `connect_switch()` accepte maintenant `Config |
  InspectConfig` (duck typing déjà utilisé de fait pour `MirrorConfig`
  ailleurs dans le fichier, type hint désormais honnête).
- **`inspect_switch(cfg)`** : uniquement des commandes `display` — jamais
  de `config_mode()` ni de commande de configuration, contrairement à
  `SetupAndCaptureThread._prepare_switch` qui peut activer scp/sftp
  server ou configurer NTP au passage si besoin. Détecte modèle + version
  (`display version`), si la feature est déjà active (`display install
  active`, modèle "installable"), si le service de transfert est déjà
  activé (`display current-configuration | include scp|sftp`), et l'état
  NTP (`display ntp-service status`, lecture seule ici — pas de
  configuration automatique comme dans le flux d'installation normal).
- **`is_ntp_synchronized(status_output)`** : extraite de la fonction
  imbriquée qui existait dans `_ensure_ntp`, désormais partagée entre
  l'installation (qui peut agir sur ce qu'elle observe) et le dry run
  (qui ne fait qu'observer) — pour qu'elles ne divergent jamais sur cette
  lecture. Petit refactor sans changement de comportement pour
  `_ensure_ntp`.
- **`format_inspect_report(...)`** : formatage du rapport partagé entre
  CLI (`print()` direct) et GTK (boîte de dialogue) — pour que les deux
  interfaces ne divergent jamais dans ce qu'elles rapportent.
- **CLI** : `switch-capture inspect --switch-ip ... --ssh-user ...`
  (`--model`, `--feature-bin-path`/`-dir`, `--transfer-mode`, `--config`
  — un YAML déjà utilisé pour `capture` fonctionne tel quel, les champs
  en trop sont simplement ignorés). Dispatché *avant* `build_config()`
  dans `main()` — `inspect_parser` n'ayant pas les champs propres à la
  capture (ex. `capture_interface`), appeler `build_config()` dessus
  aurait fait échouer la validation avec un message trompeur.
- **GTK** : bouton « Inspecter (dry run) » sur chaque ligne de capture
  (page Configuration, à côté de « Désinstaller la feature » et
  « Supprimer »), exécuté en tâche de fond (thread + `GLib.idle_add`,
  même pattern que l'installation) — résultat affiché dans une boîte de
  dialogue.

Testé réellement (pas juste relu) :
- 20 tests `pytest` (voir section Tests automatisés ci-dessous) —
  `is_ntp_synchronized` en isolation, validation `InspectConfig`,
  `inspect_switch` avec un `FakeConn` qui n'a **aucune méthode
  d'écriture** (`config_mode`/`exit_config_mode` absentes exprès : toute
  tentative de configuration ferait planter le test avec une
  `AttributeError`, preuve indirecte que le dry run ne configure jamais
  rien) — couvre modèle installable (actif/pas actif), modèle non
  supporté, modèle inconnu, modèle forcé via `--model`, formatage du
  rapport, et le dispatch CLI `run_inspect` de bout en bout (succès,
  configuration invalide, échec de connexion).
- GTK : introspection directe des widgets sous Xvfb — `Gtk.Application`
  réelle, bouton « Inspecter » effectivement cliqué, thread de fond
  attendu via la boucle GLib (`GLib.timeout_add`, pas de sleep bloquant),
  boîte de dialogue de résultat retrouvée et son contenu vérifié (IP,
  modèle, version, mention dry run présents ; aucune commande hors
  `display` envoyée). Un vrai bug a été détecté et corrigé pendant cette
  validation : le premier essai de script patchait
  `switch_capture_gtk.connect_switch`, qui n'existe pas (le module GTK
  n'importe pas ce nom) — `inspect_switch` résout `connect_switch(...)`
  dans les globals de `switch_capture_core`, où il fallait patcher.
  Script ad hoc, non committé (même choix que les autres validations GTK
  de ce dépôt — voir CLAUDE.md).
- `py_compile` + import réel des 3 fichiers source modifiés : aucune
  régression de signature.
- `ruff check --line-length 120 src/` : 35 erreurs (33 avant ce
  changement, +2 attendus : `except Exception` dans `run_inspect` et
  `_on_inspect_session`, strictement le même motif `BLE001` déjà présent
  et accepté à plus de 10 endroits ailleurs dans ces mêmes fichiers).

### Bugs GVFS/GOA du sélecteur de fichiers — diagnostic et correctif (28/08/2026, suite)

**Tâche features.md traitée : bugs 8/9/11/12** (« Bouton « … » … : `Erreur
creating proxy … org.gtk.vfs.GoaVolumeMonitor` … puis « Erreur de
segmentation (core dumped) » », et l'avertissement `Gtk-CRITICAL **:
thaw_updates: assertion 'GTK_IS_FILE_SYSTEM_MODEL (model)' failed`
associé) — signalés par l'utilisateur comme partageant probablement une
cause commune côté sélecteur de fichiers GTK, jamais investigués faute
d'environnement GTK4/PyGObject/Xvfb disponible dans les sessions
précédentes. GTK4/PyGObject/Xvfb, `xdotool`, `gcc`, `setcap`, `pytest`,
`ruff` et un accès réseau apt/pip complet étaient tous disponibles dans
cette session.

**Diagnostic, confirmé par reproduction réelle (pas seulement déduit)** :
`Gtk.FileChooserNative` (utilisé par les 4 boutons « … » du formulaire —
feature `.bin`, dossier d'archivage, import de dépôt `.bin` — et,
indirectement, tout sélecteur de fichier de l'application) sollicite,
pour peupler sa barre latérale, les moniteurs de volumes distants fournis
par le paquet système `gvfs` (démons D-Bus `org.gtk.vfs.GoaVolumeMonitor`,
`org.gtk.vfs.UDisks2VolumeMonitor`, entre autres). Sur un poste où ces
démons sont absents ou mal enregistrés — cas d'une session RDP/xrdp,
signalé par l'utilisateur — leur activation D-Bus échoue : au mieux un
avertissement, au pire l'instabilité/le crash observés (l'assertion
`thaw_updates` porte sur le modèle interne du sélecteur, dont l'état peut
être corrompu par un moniteur de volume qui répond de façon inattendue en
cours d'énumération).

**Reproduit dans cette session** : sous Xvfb, avec une vraie session
D-Bus (`dbus-daemon --session`) mais sans `udisks2`/GOA installés,
l'ouverture d'un `Gtk.FileChooserNative` produit littéralement
`GVFS-RemoteVolumeMonitor-WARNING **: remote volume monitor with dbus
name org.gtk.vfs.UDisks2VolumeMonitor is not supported` — même famille
d'erreur que celle rapportée par l'utilisateur pour le moniteur GOA (autre
implémentation du même mécanisme `GVolumeMonitor` distant).

**Correctif retenu** : switch-capture n'a jamais besoin de choisir un
emplacement distant (`sftp://`, `google-drive://`…) dans ses sélecteurs
de fichiers/dossiers — uniquement des chemins locaux (dossier de la
feature `.bin`, dossier d'archivage, fichier KeePass). Positionner
`GIO_USE_VFS=local` et `GIO_USE_VOLUME_MONITOR=unix` — deux mécanismes
GIO officiellement documentés
(https://docs.gtk.org/gio/overview.html), qui forcent respectivement
l'implémentation VFS et l'implémentation de moniteur de volumes locales
plutôt que celles fournies par le module `gvfs` — supprime cette
dépendance à `gvfs` pour tout le processus, sans changer le comportement
pour la seule chose que cet outil demande à ces sélecteurs : un chemin
local. `GIO_USE_VFS=local` seul ne suffit pas (vérifié empiriquement,
l'avertissement persistait) : le moniteur de volumes est un point
d'extension GIO séparé, d'où le second réglage.

- `os.environ.setdefault("GIO_USE_VFS", "local")` +
  `os.environ.setdefault("GIO_USE_VOLUME_MONITOR", "unix")`, positionnés
  **avant tout `import gi`**, dans **les deux** fichiers qui font ce
  premier import : `switch_capture_gtk.py` (tout en haut, avant même
  `import queue`) et `src/switch-capture` (le point d'entrée unique
  CLI/GTK — son propre premier `import gi` a lieu dans `_gtk_available()`,
  appelée avant même que `switch_capture_gtk` ne soit importé). Dupliqué
  plutôt que factorisé : `src/switch-capture` doit rester autonome
  (copié tel quel par les 3 méthodes d'installation, voir sa docstring).
  `setdefault` : ne jamais écraser un réglage explicite déjà présent dans
  l'environnement de qui lance l'outil.

**Testé réellement (pas juste relu)**, **7 tests `pytest` nouveaux**
(`tests/test_gvfs_env_workaround.py`) :
- 3 tests ne nécessitant aucun affichage graphique (juste `subprocess` +
  environnement contrôlé) : `switch_capture_gtk.py` positionne bien les
  deux variables à l'import quand elles sont absentes, ne les écrase
  jamais si déjà présentes, et un override partiel (une seule des deux
  déjà positionnée) ne touche que l'autre.
- 3 tests équivalents pour `src/switch-capture`, dont un qui exécute
  (`exec`) le corps du module sous un `__name__` différent de
  `"__main__"` — pour vérifier l'ordre réel des opérations sans lancer
  l'application — et confirme que les variables sont bien positionnées
  avant même que `_gtk_available()` ne devienne appelable.
- **1 test d'intégration bout en bout**, le plus significatif : relance
  sa propre paire Xvfb + `dbus-daemon --session` (même méthode que le
  reste de ce dépôt), ouvre un vrai `Gtk.FileChooserNative` deux fois —
  sans puis avec les deux variables — et vérifie littéralement la
  présence de `GVFS-RemoteVolumeMonitor` dans le premier cas et son
  absence dans le second. Se saute proprement (`pytest.skip`) si Xvfb/
  `dbus-daemon`/GTK4 manquent, même politique que les autres tests GUI de
  ce dépôt.

`py_compile` sur `switch_capture_gtk.py`/`src/switch-capture` : OK.
`ruff check --line-length 120 src/` : mêmes erreurs `BLE001`
pré-existantes qu'avant ce changement, à l'unité près (comparaison directe
avec une copie du dépôt d'avant modification — seuls les numéros de ligne
décalent, à cause du bloc de commentaire ajouté). Suite `pytest` complète
rejouée, en plusieurs lots pour tenir dans les contraintes de temps de
cette session (mêmes fichiers, aucun test omis) : **230 tests réels
passés, 0 échec** au total sur l'ensemble du dépôt (223 précédents + 7
nouveaux ; l'ancien unique échec, `test_taphelper_end_to_end_as_real_nonroot_user`,
passe cette fois — privilèges/outils kernel disponibles dans cet
environnement précis, sans lien avec ce changement).

**Non fait dans cette session** : la seconde moitié du bug 10 (« `Ctrl+C`
remonte un `Traceback`/`KeyboardInterrupt` brut au lieu d'une sortie
propre ») **n'est pas couverte par ce correctif** — c'est un problème de
gestion de signal (SIGINT), sans rapport avec GVfs/GOA, qui reste entier ;
reformulé comme point séparé dans la todo-list ci-dessous plutôt que
laissé sous un intitulé qui suggérait à tort qu'il partageait la même
cause que 8/9/11/12. Aucune vérification empirique du crash exact
rapporté par l'utilisateur (segmentation fault) : l'environnement de
reproduction de cette session produit un avertissement de la même famille
mais pas un crash à proprement parler (GVfs plus complet/stable dans ce
sandbox que sur le poste RDP/xrdp d'origine) — la disparition de
l'avertissement dans l'environnement reproductible ici est un signal fort
mais pas une preuve directe que le segfault précis rapporté disparaît
aussi ; à confirmer si l'utilisateur peut retester sur le poste
d'origine.

### Lissage de la réinjection TAP selon les timestamps d'origine (24/08/2026)

Traite la partie testable-en-isolation du point 1 de la liste « Pas fait »
ci-dessous (pacage des trames injectées selon leurs timestamps d'origine) :

- `iter_pcap_frames(pcap_file, with_timestamps=False)` : nouveau paramètre
  optionnel. `False` (défaut) = comportement historique strictement
  inchangé (yield des octets de trame seuls). `True` = yield
  `(timestamp_epoch, frame)`, timestamp reconstruit depuis `ts_sec`/
  `ts_usec` de l'enregistrement pcap (jusqu'ici lus puis jetés).
- `compute_pacing_delays(timestamps, max_gap_seconds)` : fonction pure
  (aucun `time.sleep`, aucun effet de bord) qui calcule, pour une liste de
  timestamps, le délai à attendre avant chaque trame pour rejouer les
  écarts de temps d'origine — plafonné à `max_gap_seconds` pour qu'un
  silence réel de plusieurs minutes dans la capture ne bloque pas la
  réinjection d'autant. Premier délai toujours 0.0, jamais de délai
  négatif (horloge switch imprécise / trames réordonnées → clampé à 0).
- `Config.tap_pace_playback` (bool, défaut `False`) et
  `Config.tap_pace_max_gap_seconds` (float, défaut `2.0`, doit être
  strictement positif — validé dans `__post_init__`) : nouveaux champs,
  sans effet sur le comportement par défaut (pacing désactivé par
  défaut). Exposés côté CLI : `--tap-pace-playback` / `--tap-pace-max-gap`
  sur `switch-capture capture` (mêmes conventions que `--tap-interface`/
  `--tap-cleanup-on-stop`, wiring automatique via `_CONFIG_FIELDS`).
- `CaptureRotationThread._feed_into_tap` : si `tap_pace_playback` est
  activé, utilise `iter_pcap_frames(..., with_timestamps=True)` +
  `compute_pacing_delays` et attend (`time.sleep`) le délai calculé avant
  chaque trame ; sinon (défaut), chemin inchangé — écriture aussi vite que
  possible, aucun `time.sleep` ajouté. Mise à jour de `SharedState`
  (`files_merged`/`bytes_merged`/`last_activity`/`last_file_name`)
  inchangée dans les deux cas.

**N'est pas fait ici** (voir point 1 ci-dessous, inchangé sur ce volet) :
l'intégration GUI (case à cocher GTK4 équivalente à « Nettoyer l'interface
TAP à l'arrêt ») n'a pas été ajoutée — pas d'environnement GTK4/PyGObject/
Xvfb disponible dans cette session pour la valider comme le reste du
projet l'exige (voir méthodologie de test dans CLAUDE.md) ; ajouter un
champ non testé aurait été contraire à la rigueur du reste de ce dépôt.
Seuls CLI et core sont couverts, tous deux testés réellement.

Testé réellement (pas juste relu), 16 tests `pytest` nouveaux (voir
`tests/test_tap_pacing.py`, section Tests automatisés ci-dessous) :
`iter_pcap_frames` avec/sans timestamps sur un `.pcap` synthétique
construit à la main (comportement historique confirmé inchangé),
`compute_pacing_delays` en isolation (écarts reflétés, plafond appliqué,
délai négatif clampé à 0, liste vide, longueur préservée), validation
`Config` (rejet d'un `tap_pace_max_gap_seconds` <= 0), et
`_feed_into_tap` avec un `FakeTapWriter` (pas de vraie interface TAP) et
`time.sleep` monkeypatché : sans pacing, aucun appel à `sleep` ; avec
pacing, appels à `sleep` dans l'ordre et avec les délais exacts attendus
(y compris le plafonnement d'un silence de 10 s à `max_gap_seconds=1.0`),
et progression (`SharedState`) toujours mise à jour. `py_compile` sur
`switch_capture_core.py`/`switch_capture_cli.py`. `ruff check
--line-length 120 src/switch_capture_core.py src/switch_capture_cli.py` :
25 erreurs, strictement identique à l'état d'avant ce changement (aucune
des 25 n'est sur une ligne ajoutée/modifiée ici) ; total dépôt inchangé à
35 (compte déjà noté lors de la session précédente).

### Débit de transfert moyen en direct (24/08/2026)

Traite l'une des deux pistes listées dans CLAUDE.md (« Compteur de
paquets/débit en direct dans l'UI »), avec une portée volontairement
réduite par rapport à l'idée d'origine — voir justification ci-dessous :

- `compute_average_throughput(bytes_merged, started_at, now)`
  (`switch_capture_core.py`) : fonction pure, débit moyen en octets/s
  depuis le début de la capture, calculé à partir de
  `SharedState.bytes_merged`/`started_at` (déjà alimentés par
  `CaptureRotationThread` à partir de tailles de fichier réellement
  rapatriées). `None` si la capture n'a pas démarré ou si l'écart de
  temps est nul/négatif (horloge imprécise) plutôt qu'une division par
  zéro ou un débit négatif trompeur ; `0.0` est un résultat valide
  distinct de `None` (capture démarrée, rien de rapatrié pour l'instant).
- `format_transfer_rate(bytes_per_second)` : formatage lisible (`o/s`/
  `Ko/s`/`Mo/s`/`Go/s`), `"—"` si l'entrée est `None`, valeur négative
  ramenée à 0 par sécurité côté affichage.

**Portée volontairement réduite** : l'idée d'origine dans CLAUDE.md
envisageait de parser la sortie CLI brute de `packet-capture` pendant la
capture (`conn.read_channel()`, actuellement seulement loguée en
`trace` dans `_run_capture_blocking_local`) pour en extraire un débit
instantané côté switch. Le format exact de cette sortie n'a jamais été
vérifié contre un switch réel dans ce dépôt — l'écrire à l'aveugle
contredirait la méthodologie du reste du projet (rien n'est marqué fait
sans validation réelle, voir CLAUDE.md). Un débit *moyen* calculé à
partir de `bytes_merged`/`started_at`, déjà fiables et déjà utilisés
ailleurs (page Journal de la GUI, sidecar `capture-meta.json`), est la
version de cette fonctionnalité qui peut être implémentée et testée
honnêtement dans cette session.

Testé réellement (pas juste relu), 16 tests `pytest` nouveaux (voir
`tests/test_transfer_rate.py`, section Tests automatisés ci-dessous) :
`compute_average_throughput` (capture pas démarrée, écart nul, écart
négatif, cas normal, débit nul valide distinct de `None`, écart
fractionnaire) et `format_transfer_rate` (`None`, zéro, négatif ramené à
zéro, chaque unité, bornes exactes de changement d'unité — `1023` reste
en `o/s`, `1024` bascule en `Ko/s`, etc.). `py_compile` sur
`switch_capture_core.py`. `ruff check --line-length 120 src/` : 35
erreurs, strictement identique à l'état du dépôt avant ce changement
(aucune sur les lignes ajoutées).

### Intégration GUI du débit moyen en direct (24/08/2026, suite)

Ancienne limite « pas fait ici » de la fonctionnalité ci-dessus, désormais
traitée : un environnement GTK4/PyGObject/Xvfb a pu être mis en place
dans cette session (`gir1.2-gtk-4.0`, `python3-gi`, `xdotool`, `Xvfb`
installés), ce qui permet de valider le rendu comme le reste du dépôt
l'exige.

- `switch_capture_gtk.py` importe désormais `compute_average_throughput`/
  `format_transfer_rate` depuis `switch_capture_core`. `_refresh_journal`
  (page Journal) calcule `compute_average_throughput(session.state.bytes_merged,
  session.state.started_at, time.time())` pour chaque session dont
  `output_mode != "rpcap"` et ajoute `format_transfer_rate(rate)` à la fin
  de la ligne existante (`"{files_merged} fichier(s), {format_size(...)} —
  {débit}"`). Mode `rpcap` inchangé (`"streaming réseau direct (rpcap)"`,
  aucun débit affiché — il n'y a rien à rapatrier dans ce mode).
- `time` était déjà importé en tête de fichier (utilisé ailleurs) — aucun
  nouvel import de module standard nécessaire.

Testé réellement (pas juste relu) : introspection directe des widgets
sous Xvfb (même méthode que le reste du projet) — `Gtk.Application`
réelle, deux sessions factices injectées dans `win._sessions`
(`SharedState` avec `bytes_merged`/`started_at` fixés pour produire un
débit connu, et une session `rpcap`), `_refresh_journal()` appelée
directement, labels de `_progress_list` parcourus par introspection
(`get_first_child`/`get_next_sibling`) : le débit attendu apparaît
littéralement dans la ligne de la session non-rpcap (`"... — 1024.0
Ko/s"` pour 10 Mo en 10 s), et la ligne rpcap ne contient aucune mention
de débit. Script de validation ad hoc, non committé (même choix que les
autres validations GTK de ce dépôt, voir CLAUDE.md). `py_compile` sur
`switch_capture_gtk.py`. `pytest tests/ -v` : 84 passed (inchangé — ce
volet GUI n'est pas couvert par la suite pytest, pour la même raison que
les autres volets GTK de ce dépôt, voir CLAUDE.md). `ruff check
--line-length 120 src/` : 34 erreurs (écart de compte avec le « 35 »
précédent dû à la version de ruff installée dans cette session, comme
déjà noté pour un écart similaire le 23/08 — aucune des erreurs n'est sur
les lignes modifiées ici).

### Intégration GUI du lissage de réinjection TAP (24/08/2026, suite)

Ancienne limite « intégration GUI : non faite » de la section « Lissage de
la réinjection TAP » ci-dessus, désormais traitée — même environnement
GTK4/PyGObject/Xvfb que pour l'intégration GUI du débit moyen (voir
section suivante) :

- **Case à cocher** « lisser la réinjection TAP selon les timestamps
  d'origine » (`tap_pace_playback`) et **spin flottant** « Écart max entre
  trames (s) » (`tap_pace_max_gap_seconds`, pas de 0.5, 1 décimale, borné
  à `[0.1, 3600.0]` — la borne basse à 0.1 empêche depuis la GUI toute
  valeur `<= 0` que `Config.__post_init__` rejetterait de toute façon
  côté core), ajoutées dans le formulaire d'ajout juste après « supprimer
  l'interface TAP à l'arrêt », sur le modèle exact de
  `tap_cleanup_on_stop`/`tap_interface`.
- Nouveau helper `_row_spin_float` (`switch_capture_gtk.py`) : variante de
  `_row_spin` existant pour un champ flottant (`Gtk.Adjustment` +
  `Gtk.SpinButton(digits=...)`) — les spins existants du formulaire sont
  tous entiers (`slot`, `rotation_seconds`, etc.), aucun helper flottant
  n'existait encore.
- **Visibilité conditionnelle** : les deux nouveaux champs suivent
  `_apply_output_mode_visibility` exactement comme `tap_interface`/
  `tap_cleanup_on_stop` — visibles seulement si `output_mode == "tap"`.
- **Câblage complet** dans les trois chemins qui touchent déjà
  `tap_cleanup_on_stop` : `_build_config` (construction du `Config` réel
  au clic sur « + Ajouter cette capture »),`_collect_raw_form_values`/
  `_apply_form_values` (sérialisation/restauration des modèles de capture
  réutilisables — round-trip Enregistrer/Importer désormais complet pour
  ces deux champs, alors que côté core `_TEMPLATE_FIELDS` les incluait
  déjà automatiquement depuis leur ajout au niveau `Config`, seul le
  câblage GUI manuel manquait).

Testé réellement (pas juste relu) : introspection directe des widgets
sous Xvfb (même méthode que le reste du projet) — `Gtk.Application`
réelle, formulaire rempli, 16 vérifications automatiques : présence des
widgets/lignes, valeurs par défaut cohérentes avec `Config`
(`tap_pace_playback=False`, `tap_pace_max_gap_seconds=2.0`), masquage en
mode `fifo` et `rpcap`, affichage en mode `tap`, répercussion réelle dans
l'objet `Config` construit par `_build_config` (`True`/`5.5` avec valeurs
non-défaut), présence dans le dict de `_collect_raw_form_values`,
restauration effective par `_apply_form_values` après remise à zéro des
widgets (round-trip modèle complet), et confirmation que le `SpinButton`
ne permet aucune valeur `<= 0`. Script de validation ad hoc, non committé
(même choix que les autres validations GTK de ce dépôt, voir CLAUDE.md).
`py_compile` sur `switch_capture_gtk.py`. `pytest tests/ -v` : 84 passed
(inchangé — ce volet GUI n'est pas couvert par la suite pytest, pour la
même raison que les autres volets GTK de ce dépôt). `ruff check
--line-length 120 src/` : 34 erreurs, strictement identique à l'état du
dépôt avant ce changement (aucune sur les lignes ajoutées/modifiées ici).

### GUI : édition d'une capture déjà ajoutée à la liste (25/08/2026)

Ancienne limite « pas d'édition en place d'une capture déjà ajoutée à la
liste (supprimer puis recréer) » (voir « Autres limites connues »
ci-dessous, désormais reformulée) — traitée dans la mesure où elle est
testable sans switch réel, avec le même environnement GTK4/PyGObject/Xvfb
que les autres volets GUI de ce dépôt.

- Nouveau bouton **« Modifier »** sur chaque ligne de la liste des
  captures planifiées (page Configuration), à côté de « Inspecter »,
  « Désinstaller la feature » et « Supprimer ». Désactivé si la capture
  est déjà en cours (`session.capture_running`), pour ne pas permettre de
  modifier sous le tapis la config d'un thread actif.
- Au clic : la session est retirée de `self._sessions` (même effet que
  « Supprimer ») **et** le formulaire d'ajout est intégralement repeuplé
  avec ses valeurs via `_apply_form_values` (mécanisme déjà existant pour
  l'import de modèles réutilisables), y compris `ssh_password` — que
  `_apply_form_values` ignore volontairement pour les modèles chargés
  depuis le disque, mais que ce chemin-ci reporte quand même sur le
  widget, puisque ce mot de passe n'a jamais quitté la mémoire du
  processus entre l'ajout initial et l'édition (pas d'exposition
  supplémentaire par rapport à l'état actuel). Nouveau helper
  `_config_to_raw_dict(cfg)` : convertit un `Config` déjà construit vers
  le même format de dict que `_collect_raw_form_values`, pour réutiliser
  `_apply_form_values` sans dupliquer sa logique de repeuplement (dont la
  ré-application de la visibilité conditionnelle
  `_apply_transfer_mode_visibility`/`_apply_output_mode_visibility`).
  Bascule automatique sur la page Configuration (`_stack.set_visible_child_name`)
  si l'utilisateur se trouvait sur une autre page.
- **Ce n'est pas de l'édition in-place au sens strict** : la session est
  bien retirée puis reconstruite au clic sur « + Ajouter cette capture »,
  comme avant. Ce qui change, c'est que l'utilisateur n'a plus besoin de
  ressaisir manuellement tous les champs — le formulaire est déjà prérempli
  à l'identique, il ne reste qu'à ajuster ce qui doit changer.

Testé réellement (pas juste relu), sous Xvfb (même méthode que le reste
du projet) : `Gtk.Application` réelle, session factice construite avec
une valeur non-défaut sur chacun des 21 champs (`switch_ip`, `ssh_user`,
`ssh_password`, `slot`, `model`, `capture_label`, `capture_interface`,
`rotation_seconds`, `max_ring_files`, `capture_filter`, `output_mode`,
`tap_interface`, `tap_cleanup_on_stop`, `tap_pace_playback`,
`tap_pace_max_gap_seconds`, `rpcap_port`, `spool_dir`, `fifo_path`,
`poll_interval`, `ensure_ntp`, `transfer_mode`), 34 vérifications par
introspection directe des widgets : bouton « Modifier » retrouvé et actif,
retrait effectif de la session après clic, bascule de page, chacun des 21
champs correctement repeuplé dans le formulaire (dont la visibilité
conditionnelle réappliquée pour le mode `tap`), ré-ajout via le bouton
« + Ajouter cette capture » reconstruisant bien une session équivalente
(mêmes valeurs vérifiées sur 3 champs représentatifs, dont un flottant),
et bouton « Modifier » présent mais désactivé pour une session dont
`capture_running=True`. Script de validation ad hoc, non committé (même
choix que les autres validations GTK de ce dépôt, voir CLAUDE.md).
`py_compile` sur `switch_capture_gtk.py`. `pytest tests/ -v` : 84 passed
(inchangé — ce volet GUI n'est pas couvert par la suite pytest, pour la
même raison que les autres volets GTK de ce dépôt). `ruff check
--line-length 120 src/` : 34 erreurs, strictement identique à l'état du
dépôt avant ce changement (aucune sur les lignes ajoutées).

### Trousseau système pour le mot de passe SSH (25/08/2026)

Mémorise le mot de passe SSH entre deux lancements sans jamais le stocker
en clair sur disque, via le trousseau système (GNOME Keyring/libsecret
sous Linux, service D-Bus standard « Secret Service ») — piste listée dans
CLAUDE.md (« Pistes d'amélioration envisagées »), désormais traitée. Un
modèle de capture réutilisable (`models/*.yaml`, voir section dédiée
ci-dessus) exclut déjà délibérément `ssh_password` pour la même raison de
principe ; cette fonctionnalité comble le manque pour qui veut malgré tout
ne plus le ressaisir, sans renoncer à ne rien écrire en clair.

- **CLI uniquement dans cette session** (voir « Non fait ici » plus bas) :
  `--remember-password` et `--forget-password` — mutuellement exclusifs —
  sur `switch-capture capture`, `switch-capture uninstall` et
  `switch-capture inspect`.
- **Résolution automatique sans flag dédié** : si aucun mot de passe n'est
  fourni par `--ssh-password`/YAML ni par `SWITCH_SSH_PASSWORD`, et que
  `--switch-ip`/`--ssh-user` sont connus, le mot de passe précédemment
  mémorisé (le cas échéant) est chargé automatiquement — même principe que
  `SWITCH_SSH_PASSWORD`, mais persistant d'un lancement à l'autre.
- `switch_capture_core.py` : `save_ssh_password_to_keyring`/
  `load_ssh_password_from_keyring`/`delete_ssh_password_from_keyring`
  (dépendance `keyring` strictement optionnelle, même statut que PyGObject
  — absence détectée à l'import, jamais un `ImportError` qui casserait le
  reste de l'outil).

Testé réellement (pas juste relu) :
- **22 tests `pytest` nouveaux** (voir `tests/test_keyring_password.py`,
  section Tests automatisés ci-dessous) avec un faux backend `keyring` en
  mémoire (round-trip, non-fuite entre comptes, idempotence de la
  suppression, échec d'écriture, absence du module) et le câblage CLI
  (résolution automatique respectant l'ordre de priorité CLI/YAML > env >
  trousseau, `build_config` de bout en bout, `--remember-password`/
  `--forget-password`).
- **Round-trip contre un vrai service Secret Service** (pas seulement le
  faux backend ci-dessus) : `gnome-keyring` installé dans l'environnement
  de cette session, vraie session D-Bus dédiée
  (`dbus-run-session`/`gnome-keyring-daemon --unlock`). Scénario CLI
  complet exécuté réellement sous cette session : `inspect
  --remember-password` avec mot de passe fourni → mémorisé ; relance
  d'`inspect` sans aucun mot de passe fourni → retrouvé automatiquement et
  identique ; suppression réelle confirmée ; nouvelle tentative sans aucun
  mot de passe disponible → erreur de validation explicite comme attendu,
  aucune régression du garde-fou existant.
- `py_compile` + import réel des 2 fichiers source modifiés.
- `pytest tests/ -v` : **106 passed** (84 précédents + 22 nouveaux).
- `ruff check --line-length 120 src/` : 34 erreurs, strictement identique à
  l'état du dépôt avant ce changement (25 sur `switch_capture_core.py`/
  `switch_capture_cli.py` seuls, également identique — aucune sur les
  lignes ajoutées). `tests/test_keyring_password.py` ruff-clean.

**Non fait dans cette section (25/08/2026, session CLI/core)** : intégration
GUI — traitée juste en dessous, dans une session ultérieure disposant à
nouveau de l'environnement GTK4/PyGObject/Xvfb.

### Intégration GUI du trousseau système (25/08/2026)

Câble côté `switch_capture_gtk.py` le mécanisme core/CLI décrit juste
au-dessus (qui restait, lui, complet et testé mais non relié à la GUI) :

- Nouvelle ligne de formulaire juste sous le champ mot de passe SSH :
  case à cocher « mémoriser dans le trousseau système » + bouton
  « Oublier le mot de passe mémorisé » (`_row_remember_password`). Ni l'un
  ni l'autre n'est un champ de `Config` — jamais lus par `_build_config`/
  `_collect_raw_form_values`, jamais repeuplés par `_apply_form_values`,
  même principe que `ssh_password` lui-même (un modèle importé ne
  restaure jamais rien touchant au mot de passe).
- **Si `keyring` n'est pas installé** (`KEYRING_AVAILABLE` faux, même
  garde-fou que côté core) : case et bouton désactivés avec une infobulle
  explicite plutôt qu'une action qui échouerait silencieusement.
- **Mémorisation** : `_on_add_session` appelle en tâche de fond
  `save_ssh_password_to_keyring` si la case est cochée au moment de l'ajout
  d'une capture à la liste (`_maybe_remember_password`) — dialogue
  d'erreur explicite (`GLib.idle_add`) en cas d'échec d'écriture (trousseau
  verrouillé, service Secret Service absent), jamais avalé silencieusement
  puisque l'utilisateur a coché la case volontairement.
- **Oubli** : `_on_forget_password` lit `switch_ip`/`ssh_user` du
  formulaire (pas besoin d'un `Config` complet — pas de mot de passe ni
  d'interface de capture requis pour identifier l'entrée à supprimer),
  appelle `delete_ssh_password_from_keyring` en tâche de fond, confirme
  par une boîte de dialogue si une entrée a réellement été supprimée ou
  non.
- **Auto-remplissage silencieux** (`_maybe_autofill_password`) : quand le
  focus quitte les champs `switch_ip`/`ssh_user`
  (`Gtk.EventControllerFocus`, signal `leave`), si le champ mot de passe
  est vide et qu'une entrée est mémorisée pour ce couple, elle est
  chargée automatiquement et la case « mémoriser » recochée pour refléter
  l'état réel du trousseau — même principe que la « résolution automatique
  sans flag dédié » côté CLI, transposé à la GUI. Ne touche **jamais** un
  champ mot de passe déjà rempli (revérifié une seconde fois juste avant
  d'appliquer le résultat, au cas où l'utilisateur aurait tapé quelque
  chose pendant la requête D-Bus) et reste silencieux si rien n'est
  mémorisé (une lecture qui échoue ne doit jamais interrompre la saisie).

Testé réellement (pas juste relu), sous Xvfb — avec, cette fois, un
**vrai service Secret Service** en plus (les validations GTK précédentes
de ce dépôt n'avaient jamais eu besoin de trousseau) :
- Environnement combiné mis en place et vérifié stable : `Xvfb :99`,
  `dbus-daemon --session` et `gnome-keyring-daemon --unlock --daemonize`
  lancés en processus détachés (`setsid ... &`, weakly-owned par le shell
  d'origine) plutôt que via `dbus-run-session` — le premier essai avec
  `dbus-run-session` provoquait un échec systématique et reproductible de
  `Gtk.init_check()` au tout premier appel (le flag `initialized` de
  l'override PyGObject se figeant à `False` avant que la connexion X11 ne
  soit pleinement établie, avec un `Xlib XOpenDisplay` qui échouait
  également en direct) ; contourner ce flag en le forçant à `True`
  provoquait un `Segmentation fault` (état interne GDK déjà corrompu par
  l'échec initial) — piège identifié et écarté en changeant d'approche de
  lancement plutôt qu'en masquant le symptôme.
- Script de validation ad hoc (`validate_gtk_keyring.py`, non committé,
  même choix que les autres validations GTK de ce dépôt) : `Gtk.Application`
  + `CaptureWindow` réels, 12 vérifications par introspection directe des
  widgets et par appel direct des méthodes de la fenêtre — présence et
  type du widget `remember_password`, décoché par défaut, sensible
  (trousseau disponible), bouton « Oublier » retrouvé et sensible ;
  ajout d'une capture avec la case cochée → mot de passe effectivement
  écrit dans le trousseau (vérifié par une lecture indépendante) ; perte
  de focus après ressaisie de `switch_ip`/`ssh_user` seuls (mot de passe
  vidé) → mot de passe retrouvé et champ rempli, case recochée
  automatiquement ; une saisie utilisateur existante n'est jamais écrasée
  par un second passage d'auto-remplissage ; clic sur « Oublier » →
  suppression réellement confirmée par une lecture indépendante ; ajout
  d'une capture avec la case décochée → rien n'est écrit dans le
  trousseau pour ce couple. **12/12 vérifications passées.**
- `py_compile` + import réel des 4 fichiers source du dépôt (aucune
  régression de signature).
- `pytest tests/ -v` : **106 passed** (inchangé — ce volet GUI n'est pas
  couvert par la suite pytest, pour la même raison que les autres volets
  GTK de ce dépôt).
- `ruff check --line-length 120 src/` : 34 erreurs, strictement identique
  à l'état du dépôt avant ce changement ; sur `switch_capture_gtk.py`
  seul, 9 erreurs (import non trié + `noqa` désormais inutiles sur
  le bloc d'import déjà présent, étendu avec les nouveaux imports
  `keyring`, et 4 `except Exception` déjà acceptés ailleurs dans ce même
  fichier) — aucune nouvelle erreur sur les lignes ajoutées par ce
  changement.

### Correctif : `sudo` + interface graphique + RDP (26/08/2026)

Bug rapporté : `sudo ./switch-capture` échouait systématiquement sur une
session RDP (xrdp) — `Authorization required, but no authorization
protocol specified` puis `RuntimeError: Gtk couldn't be initialized` —
alors que la même commande fonctionnait sans `sudo`. Cause : `sudo`
réinitialise `HOME` (donc `XAUTHORITY`) par défaut, root ne trouve donc
plus le cookie d'autorisation X11 de la session graphique ; une session
xrdp, contrairement à certaines sessions console locales, n'accorde pas
automatiquement cet accès à root (pas de `xhost` implicite). Détail du
diagnostic et des choix d'implémentation dans CLAUDE.md.

- `CaptureApp.do_activate` (`switch_capture_gtk.py`) capture précisément
  ce cas (`try/except RuntimeError`, message exact vérifié pour ne jamais
  masquer un autre bug) et affiche un diagnostic actionnable avec 3
  solutions de contournement, au lieu d'un traceback Python.
- Corrige au passage `Gtk.Application.run()` qui renvoyait `0` malgré le
  crash (exception avalée par le dispatch de signal PyGObject) : exit
  code `1` désormais correct.
- Documenté côté utilisateur : USAGE.md, nouvelle section « Dépannage ».

Testé réellement (pas juste relu) :
- Bug reproduit à l'identique dans un environnement Xvfb + vrai cookie
  X11, cassé de la même façon que `sudo` le fait (`HOME=/root`,
  `XAUTHORITY` invalide) : message et traceback strictement identiques à
  ceux rapportés.
- Après correctif, même scénario : diagnostic clair, exit code 1, plus de
  traceback.
- Non-régression confirmée sous Xvfb avec un environnement X11 valide :
  l'app démarre normalement (capture d'écran prise).

### Icône de l'application (26/08/2026)

- Icône SVG dessinée pour l'app (`src/icons/hicolor/scalable/apps/
  org.transcende.switch_capture.svg`, arborescence de thème hicolor
  standard) + fichier `org.transcende.switch_capture.desktop` (entrée
  menu applications, `Exec=switch-capture -g`).
- Câblée dans `switch_capture_gtk.py` : résolution même en lancement non
  installé (`_register_app_icon`, ajout du dossier `icons/` du dépôt
  comme chemin de recherche du thème courant), et
  `Gtk.Window.set_default_icon_name` pour l'icône de fenêtre/barre des
  tâches sous X11.
- Câblée dans les 3 méthodes d'installation (`install.sh`,
  `packaging/build_deb.sh` + `postinst`/`postrm`,
  `packaging-rpm/switch-capture.spec` + `build_rpm.sh`) : copie vers
  `/usr/share/icons/hicolor/scalable/apps/` et `/usr/share/applications/`,
  rafraîchissement best-effort des caches (`gtk-update-icon-cache`,
  `update-desktop-database`).

Testé réellement :
- API GTK4 vérifiée par introspection directe plutôt que supposée,
  notamment la structure de dossier exacte attendue par
  `Gtk.IconTheme.add_search_path` (contre-intuitive, corrigée après un
  premier essai silencieusement erroné — détail dans CLAUDE.md).
- Bout en bout sous Xvfb, dans le vrai contexte `do_activate` : `xprop`
  sur la fenêtre réellement ouverte confirme `_NET_WM_ICON` et
  `_GTK_APPLICATION_ID` correctement positionnés ; capture d'écran prise.
- `.deb` réellement construit (`dpkg-deb`) et contenu vérifié
  (`dpkg-deb -c`) : icône et `.desktop` présents aux bons emplacements.
- `.rpm` réellement construit (`rpmbuild`, qui détecte et déclare tout
  seul `Provides: application(org.transcende.switch_capture.desktop)`)
  et contenu vérifié (`rpm -qlp`).
- `install.sh` testé avec `--prefix` pointant vers un répertoire
  réellement vide (pas un chroot déjà pourvu d'un `usr/bin`) — a révélé
  un bug latent préexistant sans rapport avec l'icône (`$BIN_DIR` jamais
  créé par `install -d`, invisible en usage réel où `/usr/bin` existe
  toujours déjà) ; corrigé (une ligne), retesté avec succès.

### Découplage téléchargement/injection TAP (26/08/2026)

Traite le point resté en suspens dans la section « Pas fait » ci-dessous
(hors mesure contre un switch réel) : `_feed_into_tap`, et son éventuel
délai de lissage (`tap_pace_playback`), tournait de façon synchrone dans
le thread de rotation lui-même — un fichier au lissage lent retardait
d'autant le rapatriement du fichier suivant.

- `CaptureRotationThread` : nouvelle file d'attente (`self._tap_queue`) +
  thread dédié (`_injector_loop`), démarrés par `_setup_tap` (mode `tap`
  uniquement — le mode `fifo`, sans lissage, reste synchrone et inchangé).
  `_dispatch_for_injection` remplace l'appel direct à `_feed_into_tap` :
  dépose sur la file (jamais bloquant) en mode `tap`, appelle
  `_feed_into_fifo` directement en mode `fifo`.
- Arrêt propre dans `_cleanup` : sentinelle + `join(timeout=5.0)` du
  thread injecteur **avant** de fermer `self._tap_writer`, pour éviter
  une écriture après fermeture. Détail du raisonnement (pourquoi ce
  timing importe, pourquoi ce catch large) dans CLAUDE.md.

Testé réellement, `tests/test_tap_injector_thread.py` (9 nouveaux tests) :
- Aiguillage `_dispatch_for_injection` correct par `output_mode`.
- `_injector_loop` : ordre de réinjection respecté, arrêt propre sur
  sentinelle et sur `stop_event` seul, survit à un fichier corrompu et à
  une exception inattendue sans bloquer les fichiers suivants.
- **Test central** : un 2ᵉ fichier déposé pendant qu'un lissage bloque le
  1ᵉʳ (sleep simulé, contrôlé par le test) est accepté immédiatement
  (< 0,5 s), sur son propre thread — les deux finissent injectés dans le
  bon ordre une fois débloqués.
- `_cleanup` : thread injecteur bien joint (fichier en attente traité)
  avant fermeture du writer TAP ; robuste si `_setup_tap` n'a jamais
  tourné.

`pytest tests/ -v` : **115 passed** (106 précédents + 9 nouveaux, aucune
régression). `ruff check --line-length 120 src/` : 35 erreurs (34
préexistantes + 1 nouvelle, volontaire — `except Exception` large dans
`_injector_loop`, cohérent avec l'idiome déjà utilisé partout ailleurs
dans ce fichier pour la même raison ; détail dans CLAUDE.md).
`tests/test_tap_injector_thread.py` : 0 erreur ruff.

### Correctif régression : détection auto des modèles 5130EI/5130HI/5140EI/5140HI (26/08/2026, suite)

Corrige la régression signalée dans la section « Patch utilisateur
intégré » ci-dessus : le renommage `5130`/`5140` → `5130EI`/`5130HI`/
`5140EI`/`5140HI` avait réduit les alias de détection automatique
(`MODEL_PROFILES[...]["aliases"]`) à la seule forme collée
(`"5130EI"`/`"5130ei"`), perdant au passage les formes `"5130-28"`/
`"5130-52"` de l'ancien modèle `5130` fusionné — or la sortie réelle de
`display version` place le suffixe de gamme après le numéro de port
(ex. `HPE 5130-28-EI Switch`), donc plus aucune détection automatique
ne matchait pour ces quatre modèles.

- `MODEL_PROFILES` : alias élargis pour `5130EI`/`5130HI`/`5140EI`/
  `5140HI`, sur le même principe que l'ancien modèle fusionné mais
  répartis EI/HI (ex. `5130EI` : `"5130-28-EI"`, `"5130-52-EI"`,
  `"5130EI"`, `"5130ei"`). `MSR4000`/`5510`/`5520`/`3600v2` non
  touchés (aucune régression constatée, pas de couverture de test sur
  leur format réel).
- Choix retenu entre les deux options laissées ouvertes par la note de
  régression (mettre à jour les tests vs. alias de rétrocompatibilité) :
  **les deux** — alias corrigés pour que la détection automatique
  refonctionne sur un switch réel, *et* `tests/test_inspect.py` mis à
  jour pour attester du nouveau nom de modèle détecté (`"5130EI"` au
  lieu de l'ancien `"5130"`, y compris le test CLI `--model` et le test
  de modèle forcé passé de `"5140"` à `"5140EI"` — `"5140"` seul n'étant
  plus une clé valide de `MODEL_PROFILES`).

`pytest tests/ -v` : **115 passed** (110 + les 5 précédemment en échec,
aucune régression ailleurs). `ruff check src/switch_capture_core.py
tests/test_inspect.py` : 21 erreurs, toutes préexistantes (20
`BLE001`/`try-except-pass` déjà tolérées + 1 `C408` dans un test non
touché) — aucune nouvelle catégorie introduite par ce correctif.

**Limite connue** : les alias `5510`/`5520`/`MSR4000`/`3600v2` n'ont
pas été audités pour ce même risque (forme réelle de `display version`
non vérifiée faute de switch/logs disponibles pour ces modèles) — à
garder en tête si une régression similaire est un jour rapportée
dessus.

### Filtre de capture : masquage optionnel du trafic SSH/SCP outil↔switch — core + CLI (26/08/2026, suite)

Traite la partie testable-en-isolation du point 5 de la todo-list « Reste
à corriger et à faire » ci-dessous (« Filtre de capture ») : jusqu'ici,
l'exclusion du trafic SSH/SCP entre la machine qui exécute l'outil et le
switch (ajoutée par le patch utilisateur intégré, voir plus bas) était
codée en dur et toujours active — la demande initiale voulait en faire
une option (case « masquer le trafic de capture » dans une future page
Préférences), combinable proprement avec le filtre du formulaire quand il
est renseigné.

- `build_capture_filter(switch_ip, capture_filter, hide_capture_traffic=True)`
  (`switch_capture_core.py`) : fonction pure extraite de la logique
  jusqu'ici inline dans `_run_capture_blocking_local`, qui construit la
  clause `capture-filter "..."` complète (espace final inclus, comme
  attendu par la commande packet-capture). Combine proprement les deux
  sources : exclusion SSH/SCP (`not (host {switch_ip} and port 22)`) *et*
  filtre utilisateur si les deux sont actifs (`... and ...`), l'un des
  deux seul si l'autre est désactivé/vide, et **aucune clause
  `capture-filter` du tout** dans la commande envoyée au switch si ni
  l'un ni l'autre ne s'applique (`hide_capture_traffic=False` et
  `capture_filter` vide) — plutôt qu'une clause avec un contenu vide qui
  aurait été syntaxiquement bancale.
- `Config.hide_capture_traffic: bool = True` : nouveau champ, défaut
  `True` pour préserver exactement le comportement du patch utilisateur
  intégré (aucune régression pour qui ne touche pas à ce réglage). Repris
  automatiquement par `_TEMPLATE_FIELDS` (modèles de capture réutilisables,
  voir section dédiée plus haut) sans changement de code supplémentaire —
  même mécanisme générique que pour `tap_pace_playback` en son temps.
- **CLI** : `--no-hide-capture-traffic` sur `switch-capture capture`, même
  convention que `--no-ensure-ntp` (flag opt-out, `store_const` +
  `default=None` pour ne changer le comportement que si explicitement
  demandé).
- `_run_capture_blocking_local` appelle désormais `build_capture_filter`
  au lieu de construire la chaîne inline — comportement par défaut
  strictement identique (vérifié par les tests ci-dessous), mode `rpcap`
  non concerné (pas de `packet-capture` local dans ce mode).

**Non fait dans cette session** (voir « Reste à corriger et à faire » —
point 5 reste listé, reformulé) : la partie GUI (case à cocher dans une
page Préférences qui n'existe pas encore — voir points 1-4 de la même
liste, eux aussi non traités) n'a pas pu être ajoutée ni validée, faute
d'environnement GTK4/PyGObject/Xvfb disponible dans cette session — même
limite déjà rencontrée et documentée pour d'autres volets GUI de ce dépôt
(voir par ex. la première moitié de la section « Lissage de la
réinjection TAP » plus haut, traitée en deux temps pour la même raison).
Le core et le CLI sont, eux, complets et testés : rien à refaire côté GUI
au-delà du câblage d'un widget, sur le modèle exact de
`tap_pace_playback`/`tap_cleanup_on_stop`.

Testé réellement (pas juste relu), **8 tests `pytest` nouveaux** (voir
`tests/test_capture_filter.py`, section Tests automatisés ci-dessous) :
comportement par défaut (exclusion seule, exclusion + filtre utilisateur,
équivalence explicite/implicite de `hide_capture_traffic=True`),
`hide_capture_traffic=False` avec et sans filtre utilisateur (dont le cas
« aucune clause du tout »), bonne interpolation de `switch_ip`, espace
final présent quand la clause n'est pas vide et absent quand elle l'est.
`py_compile` sur `switch_capture_core.py`/`switch_capture_cli.py`.
`pytest tests/ -v` : **123 passed** (115 précédents + 8 nouveaux, aucune
régression). `ruff check --line-length 120 src/` : 20 erreurs — voir la
section dédiée juste en dessous (« Ménage ruff »), qui couvre aussi ce
changement (aucune nouvelle erreur introduite par `build_capture_filter`
ou son câblage CLI).

### Ménage ruff (26/08/2026, suite)

Correction des erreurs `ruff check --line-length 120 src/` facilement
corrigeables sans changement de design, à la demande explicite de
l'utilisateur — de 31 à **20** erreurs restantes :

- **5 corrigées automatiquement** (`ruff check --fix`) : imports non
  triés (`I001`) et 4 directives `# noqa` devenues inutiles (`RUF100`,
  résidus de sessions précédentes dont le code annoté a changé depuis).
- **`EXE001`** (shebang présent mais fichier non exécutable) :
  `src/switch_capture_cli.py` rendu exécutable (`chmod +x`) — aucun
  changement de code.
- **4× `S110`** (`try/except/pass`, suggestion ruff : logger plutôt
  qu'avaler silencieusement) dans `switch_capture_core.py` :
  `_process_closed_file_scp` (fermeture connexion SCP dédiée),
  `CaptureRotationThread._cleanup` (déconnexion poll, fermeture FIFO,
  suppression FIFO) — chaque `pass` remplacé par un `logger.debug(...)`
  explicite décrivant l'échec ignoré, sans changer le comportement
  (toujours best-effort, toujours silencieux côté utilisateur final) mais
  désormais traçable en cas de diagnostic.
- **`SIM115`** (ouverture de fichier hors context manager) sur le FIFO de
  `_launch_wireshark` : `# noqa: SIM115` + commentaire expliquant pourquoi
  un `with` ne convient pas ici — le descripteur (`self._fifo_fd`) est
  utilisé par d'autres méthodes et fermé explicitement dans `_cleanup`,
  sa durée de vie dépasse la fonction qui l'ouvre.
- **Les 20 `BLE001` restants (`except Exception` large) volontairement
  non touchés** : motif déjà utilisé et documenté comme accepté à plus de
  10 endroits dans ce même dépôt (voir par ex. la justification détaillée
  dans CLAUDE.md pour `_injector_loop`) — les corriger en masse aurait été
  un changement de design (restreindre chaque `except` à une exception
  précise, avec le risque de casser la robustesse « thread de fond qui ne
  doit jamais mourir silencieusement » sur certains chemins), pas une
  correction facile au sens de la demande.

`pytest tests/ -v` : **123 passed** (aucune régression introduite par ce
ménage, purement stylistique/logging). `ruff check --line-length 120
src/`: 20 erreurs, toutes `BLE001`.

### Archivage en pcapng (26/08/2026, suite)

**Tâche features.md traitée : point 19, « Privilégier pcapng à pcap »**.
Portée choisie, en l'absence de précision de l'utilisateur au-delà de la
demande brute (`notes/demandes-2026-08-26.md`) : le format `.pcap`
classique que `packet-capture` écrit sur la flash du switch est imposé
par le firmware Comware lui-même, hors de portée de cet outil ; de même,
la réinjection live (FIFO/TAP) continue de lire ces `.pcap` classiques
rapatriés sans changement, `iter_pcap_frames` restant le seul parseur
utilisé à ce stade. Le point d'application retenu est donc l'**archivage**
(`Config.archive_dir`) : c'est la seule étape qui produit des fichiers
`.pcap` destinés à être conservés durablement par l'utilisateur (sinon
suppression immédiate après fusion), et donc le seul endroit où le format
de stockage a un intérêt à long terme (pcapng : métadonnées d'interface,
horodatage plus précis, format recommandé par Wireshark).

- **`convert_pcap_to_pcapng(pcap_path, pcapng_path)`** (nouvelle fonction
  pure, `switch_capture_core.py`) : réécrit un `.pcap` classique en
  `.pcapng` valide (Section Header Block + une Interface Description
  Block reprenant le `LinkType` du fichier source + une Enhanced Packet
  Block par trame), en réutilisant `iter_pcap_frames(with_timestamps=True)`
  pour le parsing. **Aucune dépendance externe ajoutée** (pas de
  scapy/tshark) : uniquement `struct`, sur le même principe que le reste
  du parsing pcap déjà présent dans ce module.
- **`archive_capture_file(pcap_file, archive_dir, as_pcapng=True)`**
  (nouvelle fonction) : factorise le code d'archivage jusqu'ici dupliqué
  entre `_feed_into_tap` et `_feed_into_fifo` (un simple `shutil.move`), et
  y ajoute la conversion pcapng optionnelle. **Repli explicite** sur un
  archivage `.pcap` classique si la conversion échoue (`ValueError`/
  `OSError` — fichier déjà corrompu, par exemple) : un échec de conversion
  ne doit jamais faire perdre le fichier source, seulement dégrader
  silencieusement (avec `logger.warning`) vers le comportement historique.
- **Nouveau champ `Config.archive_as_pcapng: bool = True`** — défaut
  volontairement actif (« privilégier » pcapng au sens de la demande),
  sans effet si `archive_dir` n'est pas défini (rien n'est archivé dans ce
  cas, comportement inchangé).
- **CLI** : `--no-archive-as-pcapng` sur `switch-capture capture`, même
  convention opt-out que `--no-ensure-ntp`/`--no-hide-capture-traffic`
  (`store_const` + `default=None`).
- `_feed_into_tap`/`_feed_into_fifo` appellent désormais
  `archive_capture_file` au lieu de leur `shutil.move` inline respectif —
  comportement de réinjection live (avant l'archivage) strictement
  inchangé dans les deux modes, seule l'étape d'archivage après coup est
  concernée.
- Documentation mise à jour : `src/docs/USAGE.md` (nouvelle ligne
  `--no-archive-as-pcapng` dans le tableau des options de `capture`),
  `src/docs/config.yaml.example` (`archive_as_pcapng` commenté à côté
  d'`archive_dir`).

**Non fait dans cette session** : câblage GUI (case à cocher dans la
future page Préférences, voir points 1-4 de « Reste à corriger et à
faire » ci-dessus — la page elle-même n'existe pas encore), faute
d'environnement GTK4/PyGObject/Xvfb disponible dans cette session — même
limite déjà rencontrée pour `hide_capture_traffic` et documentée
ailleurs dans ce fichier. Câblage attendu, une fois l'environnement
disponible, sur le modèle exact de `tap_pace_playback`/
`hide_capture_traffic`.

Testé réellement (pas juste relu), **12 tests `pytest` nouveaux** (voir
`tests/test_pcap_to_pcapng.py`) : structure du fichier `.pcapng` produit
(ordre des blocs SHB/IDB/EPB, un EPB par trame), préservation exacte des
octets de trame et du `LinkType`, préservation des timestamps (résolution
microseconde), erreur propagée sur un pcap source invalide, cas d'un pcap
sans aucune trame, `archive_capture_file` avec/sans conversion activée,
repli sur `.pcap` classique en cas de fichier corrompu (le fichier
archivé existe bien et son contenu est intact), câblage réel dans
`_feed_into_tap`/`_feed_into_fifo` (fichier archivé effectivement en
`.pcapng` par défaut, en `.pcap` si `archive_as_pcapng=False`), et défaut
du nouveau champ `Config.archive_as_pcapng`. `py_compile` sur
`switch_capture_core.py`/`switch_capture_cli.py` : OK.
`pytest tests/ -v` : **135 passed** (123 précédents + 12 nouveaux, aucune
régression). `ruff check --line-length 120 src/` : toujours **20**
erreurs, toutes `BLE001` préexistantes — aucune nouvelle catégorie
introduite par ce changement.

### Sens de capture : inbound / outbound / bidirection (26/08/2026, suite)

**Tâche features.md traitée : point 6, « À rechercher (recherche
internet) »**. Recherche effectuée contre la documentation officielle
H3C (« Packet capture commands », plusieurs révisions du Command
Reference V7) : l'hypothèse d'origine est **confirmée**, ce n'était pas
un artefact de ce dépôt. `packet-capture local interface ... [
bidirection | outbound ] ...` et `packet-capture remote interface ... [
bidirection | outbound ] ...` ne capturent que le trafic **entrant**
si ni `bidirection` ni `outbound` n'est précisé — Comware n'a pas de
mot-clé `inbound` explicite, l'absence des deux autres mots-clés EST le
sens entrant.

- **`build_capture_direction_clause(capture_direction)`** (nouvelle
  fonction pure, `switch_capture_core.py`, même principe que
  `build_capture_filter`) : retourne `"bidirection "`/`"outbound "` pour
  ces deux valeurs, ou une chaîne vide pour `"inbound"` (pas de clause
  `inbound` inventée, puisqu'elle n'existe pas côté Comware).
- **Nouveau champ `Config.capture_direction: str = "bidirection"`** —
  défaut choisi **différent** du défaut Comware (qui serait "inbound" en
  l'absence de tout mot-clé) : switch-capture capture désormais les deux
  sens par défaut, conformément à l'objectif explicitement formulé
  (« capturer les deux sens »). Validé dans `Config.__post_init__`
  (`inbound`/`outbound`/`bidirection` uniquement).
- **CLI** : `--capture-direction {inbound,outbound,bidirection}` sur
  `switch-capture capture`, choix explicite (pas un flag opt-out comme
  `--no-hide-capture-traffic`, puisqu'il y a trois valeurs possibles et
  non un simple booléen) ; récupéré automatiquement par `_CONFIG_FIELDS`
  sans câblage supplémentaire, même mécanisme générique que
  `--output-mode`/`--transfer-mode`.
- **Câblage dans les deux commandes qui parlent réellement à
  `packet-capture`** : `_run_capture_blocking_local` (`output_mode`
  "fifo"/"tap") insère la clause juste après `interface <iface>` et
  avant la clause `capture-filter`, dans le même ordre que documenté par
  H3C ; `_run_rpcap_blocking` (`output_mode` "rpcap") l'insère juste
  avant `port <port>`. Sans effet en `output_mode` "rpcap" si le switch
  ne supporte pas ce mot-clé pour `packet-capture remote` sur une
  version donnée — non vérifiable sans switch réel, mais la syntaxe est
  identique à `packet-capture local` dans toute la documentation
  consultée.

**Non fait dans cette session** : câblage GUI (sélecteur dans la future
page Préférences ou directement dans le formulaire principal — voir
points 1-4 et le point urgent 18 de « Reste à corriger et à faire »
ci-dessus), faute d'environnement GTK4/PyGObject/Xvfb disponible dans
cette session — même limite déjà rencontrée pour `hide_capture_traffic`/
`archive_as_pcapng`. Câblage attendu, une fois l'environnement
disponible, sur le même modèle (menu déroulant à 3 valeurs plutôt qu'une
case à cocher, cette fois). **Non vérifié empiriquement contre un switch
réel** : la syntaxe vient de la documentation H3C officielle, pas d'un
test contre un `packet-capture` réel (aucun switch disponible dans cette
session) — à confirmer à la prochaine occasion d'accès à un switch, en
particulier la disponibilité du mot-clé `bidirection` sur `packet-capture
remote` pour les modèles/versions réellement utilisés (5130/5140/5510/
5520).

Testé réellement (pas juste relu), **13 tests `pytest` nouveaux** (voir
`tests/test_capture_direction.py`) : les 3 valeurs de
`build_capture_direction_clause` (dont l'absence de clause pour
"inbound"), l'espace final présent/absent selon le cas, le rejet d'une
valeur invalide, le défaut `"bidirection"` de `Config.capture_direction`,
l'acceptation explicite des 3 valeurs et le rejet d'une valeur invalide
côté `Config`, et le câblage CLI bout en bout (`--capture-direction`
répercuté dans le `Config` construit, défaut conservé si l'option est
omise, rejet argparse d'un choix hors liste). `py_compile` sur
`switch_capture_core.py`/`switch_capture_cli.py` : OK.
`pytest tests/ -v` : **148 passed** (135 précédents + 13 nouveaux, aucune
régression). `ruff check --line-length 120 src/` : toujours **20**
erreurs, toutes `BLE001` préexistantes — aucune nouvelle catégorie
introduite par ce changement.



Liste brute des demandes/anomalies remontées par l'utilisateur le
26/08/2026, conservée telle quelle in extenso dans
`notes/demandes-2026-08-26.md` (fichier « patch » de ses propres notes,
pour traçabilité) et reprise ici sous forme de todo-list structurée.
**Aucun de ces points n'a été développé dans cette session** — inventaire
et priorisation uniquement.

### Patch utilisateur intégré (26/08/2026, `switch_capture_core.patch`)

L'utilisateur a fourni séparément un patch unifié (`notes/
switch_capture_core.patch`, conservé tel quel pour traçabilité) modifiant
directement `src/switch_capture_core.py`. Intégré tel quel dans cette
session (54 hunks sur 55 appliqués automatiquement avec `patch -p1`,
1 hunk purement cosmétique — retour à la ligne d'un `struct.unpack` —
réappliqué à la main après échec de contexte). Contenu du patch, tel que
fourni par l'utilisateur : renommage des modèles `5130`/`5140` en
`5130EI`/`5130HI`/`5140EI`/`5140HI` (+ ajout `MSR4000` en `builtin`),
nouveau champ `Config.packet_capture_cmd`, nouvelle fonction
`delete_remote_all_file_capture` (nettoyage des captures résiduelles en
flash avant démarrage et lors de la désinstallation), exclusion
systématique du trafic SSH/SCP vers le switch dans le `capture-filter`
envoyé au switch (`not (host {switch_ip} and port 22)`, combiné le cas
échéant avec le filtre du formulaire), `fifo_path` suffixé par
`switch_ip` (plusieurs captures simultanées), retrait du préfixe `/` sur
les chemins SCP distants (`feature_filename`/`filename` poussés/récupérés
sans `/` initial), et de nombreux ajouts de `logger.debug`.
**Non vérifié/testé au-delà de la compilation** (`py_compile` : OK,
`ruff check` : 20 erreurs, toutes `BLE001`/`try-except-pass` déjà
tolérées ailleurs dans ce fichier, aucune nouvelle catégorie) : le
renommage des modèles cassait **5 tests existants**
(`tests/test_inspect.py`, 4 échecs + 1 CLI) qui référençaient encore
l'ancien nom de modèle `"5130"` — à l'analyse, ce n'était pas qu'un
problème de tests obsolètes : les alias de détection automatique
avaient eux aussi perdu en route les formes `"5130-28"`/`"5130-52"` de
l'ancien modèle fusionné, cassant la détection sur un switch réel.
**Corrigé dans cette session**, voir « Correctif régression : détection
auto des modèles 5130EI/5130HI/5140EI/5140HI » ci-dessous. `pytest
tests/ -v` à l'état initial du patch : 110 passed, 5 failed (115
précédents).

### Lancement automatique de Wireshark en mode TAP — core + CLI (26/08/2026, suite)

**Tâche features.md traitée : point 14, « Lancement automatique de
Wireshark en mode TAP »**.

- **Nouveau champ `Config.tap_launch_wireshark: bool = False`** —
  désactivé par défaut, docstring dédiée expliquant le compromis :
  chaque `CaptureRotationThread` ignore les autres, donc l'activer sur
  plusieurs captures simultanées ouvre une fenêtre Wireshark par capture
  plutôt que la fenêtre unique observant toutes les interfaces que ce
  mode permet quand Wireshark est lancé manuellement (voir la docstring
  de `CaptureRotationThread`, section « Réinjection live » ci-dessus) —
  ce dernier reste le mieux adapté pour des captures multiples. Sans
  effet en `output_mode` "fifo" (qui lance déjà Wireshark inconditionnellement,
  voir `_launch_wireshark`) ou "rpcap" (Wireshark s'y connecte
  directement en réseau).
- **`_launch_wireshark_tap()`** (nouvelle méthode de `CaptureRotationThread`) :
  appelle `subprocess.Popen(["wireshark", "-k", "-i", tap_interface])`,
  appelée depuis `_setup_tap()` juste après `ensure_tap_interface()`
  (donc uniquement une fois l'interface confirmée créée et active) si
  `tap_launch_wireshark` est activé. Contrairement à `_launch_wireshark`
  (mode "fifo", qui bloque sur `open(fifo_path, "wb")` en attendant que
  Wireshark ouvre l'autre bout), cet appel ne bloque jamais : l'interface
  TAP existe déjà comme périphérique réseau noyau, Wireshark s'y attache
  via pcap comme sur n'importe quelle interface.
- **CLI** : `--tap-launch-wireshark` (`store_true`, défaut `None`) sur
  `switch-capture capture`, même style que `--tap-cleanup-on-stop`/
  `--tap-pace-playback` (flag d'activation, pas d'opt-out, puisque
  `Config` vaut déjà `False` par défaut).
- **Documentation** : entrée ajoutée à la table d'options et à l'exemple
  « Captures multiples simultanées via TAP » de `USAGE.md` (avec le même
  avertissement sur le compromis multi-fenêtres), et à
  `config.yaml.example`.

**Non fait dans cette session** : câblage GUI. Contrairement à
`hide_capture_traffic`/`archive_as_pcapng`/`capture_direction` (qui
attendent tous la future page Préférences, points 1-4 ci-dessous),
`tap_cleanup_on_stop` et `tap_pace_playback` — les deux options `tap_*`
les plus proches de celle-ci — sont déjà câblées comme cases à cocher
directement dans le formulaire principal (`switch_capture_gtk.py`,
`_row_check`, visibles seulement si `output_mode == "tap"`) : la case
`tap_launch_wireshark` a donc vocation à les rejoindre au même endroit,
pas nécessairement à attendre la page Préférences. Toujours faute
d'environnement GTK4/PyGObject/Xvfb disponible dans cette session — même
limite déjà rencontrée pour les points 5, 6, 19. **Non vérifié
empiriquement** : ni contre un switch réel, ni même avec un binaire
`wireshark` réel (absent de cette session également) — seul l'appel
`subprocess.Popen` et ses arguments ont été vérifiés, pas le
comportement de Wireshark lui-même une fois lancé.

**Testé réellement (pas juste relu), mais sans aucune dépendance du
projet ni `pytest` installés dans cette session** (pas d'accès réseau
pour les installer, contrairement aux sessions précédentes qui
listaient un `pytest tests/ -v` complet — voir `requirements.txt`/
`requirements-dev.txt`) : un stub minimal de `loguru` (hors dépôt,
jamais copié dans ce zip) a permis d'importer et d'exécuter réellement
`switch_capture_core`/`switch_capture_cli` malgré cette absence. Un
mini-runner maison reproduisant `tmp_path`/`monkeypatch`/`pytest.raises`/
`pytest.approx`/`capsys` (sans `@pytest.mark.parametrize`, 2 tests de
`test_capture_templates.py` ignorés pour cette raison, sans lien avec ce
changement) a fait passer **117 tests réels de la suite existante, 0
échec**, sur `test_tap_injector_thread.py`, `test_tap_pacing.py`,
`test_capture_direction.py`, `test_capture_filter.py`,
`test_transfer_rate.py`, `test_uninstall_confirm.py`,
`test_pcap_to_pcapng.py`, `test_inspect.py` et `test_capture_templates.py`
— tout sauf `test_keyring_password.py` (fixtures dédiées `fake_keyring`/
`keyring_unavailable` non reproduites, module `keyring` de toute façon
non installé ici et sans lien avec ce changement). S'y ajoutent **12
vérifications ciblées nouvelles** sur `tap_launch_wireshark` (Popen
appelé/non appelé selon le flag, ordre d'appel après
`ensure_tap_interface`, `_wireshark_proc` correctement affecté, câblage
CLI avec/sans le flag, non-écrasement d'une valeur YAML par le défaut
argparse) et un aller-retour explicite par
`config_to_template_dict`/`save_capture_template`/`load_capture_template`/
`template_dict_to_config_kwargs` confirmant que le nouveau champ survit
à la sérialisation d'un modèle réutilisable. `py_compile` sur les deux
fichiers modifiés : OK. `ruff` non disponible non plus dans cette
session (pas de vérification de style possible, à refaire à la
prochaine session outillée).

### Étude de faisabilité : switch-capture comme plugin extcap Wireshark (27/08/2026)

**Tâche features.md traitée : point 16, « Étudier la possibilité de
devenir un plugin `extcap` pour Wireshark »**. Tâche purement de
recherche (aucun code produit), documentation officielle Wireshark
consultée par recherche web pour cette session — sources citées en fin
de section.

**Ce qu'est extcap.** Interface de plugin permettant à un exécutable
externe (binaire, script Python…) d'apparaître comme une source de
capture à part entière dans Wireshark, pour les cas où la source n'est
pas une interface locale/pipe/fichier classique (matériel exotique,
capture distante…). Les extcaps vivent dans un dossier dédié que
Wireshark scanne et invoque automatiquement (chemin visible dans
Wireshark via Aide → À propos → Dossiers → « Extcap path » ; sous Linux
en paquet système, typiquement
`/usr/lib/<triplet>/wireshark/extcap/`, ou un dossier utilisateur
équivalent selon la distribution).

**Le protocole, en 4 étapes**, chacune un appel de l'extcap avec des
arguments différents : `--extcap-interfaces` (liste les interfaces que
cet extcap propose) ; `--extcap-interface IFACE --extcap-dlts` (types de
lien supportés) ; `--extcap-interface IFACE --extcap-config` (décrit les
options de configuration spécifiques à cette interface, utilisées par
Wireshark pour construire une boîte de dialogue) ; puis, au lancement de
la capture, `--extcap-interface IFACE [options choisies] --capture
[--extcap-capture-filter FILTRE] --fifo CHEMIN` — Wireshark crée le FIFO
et l'ouvre en lecture, à charge pour l'extcap d'y écrire un flux pcap
classique continu (un en-tête global, puis des trames).

**Proximité structurelle forte avec l'existant.** C'est précisément ce
que fait déjà `_feed_into_fifo()` (mode "fifo" actuel) : un en-tête pcap
global écrit une seule fois (`self._wrote_global_header`), puis les
trames de chaque fichier `.pcap` rapatrié concaténées à la suite dans le
même flux. Le mécanisme bas niveau est donc déjà celui qu'exigerait un
extcap — seule l'orchestration diffère : aujourd'hui l'outil crée le
FIFO (`mkfifo`) et lance lui-même `wireshark -k -i <fifo>` (voir
`_launch_wireshark`) ; en mode extcap, c'est l'inverse, Wireshark crée
le FIFO et lance l'outil avec `--fifo <chemin>`.

**Les types de champs de configuration** que Wireshark sait afficher
pour un extcap couvrent large : entier, flottant, sélecteur, case à
cocher, boutons radio, sélection de fichier, sélection multiple,
**champ mot de passe (texte masqué)**, date/heure. De quoi représenter
proprement la plupart des champs de `Config` actuels (`switch_ip` en
texte, `ssh_password` en champ mot de passe masqué, `output_mode` en
radio/sélecteur, `rotation_seconds` en entier, etc.) sans improviser.

**Pipes de contrôle optionnels** (`--extcap-control-in`/
`--extcap-control-out`) : permettent à l'extcap d'envoyer des messages
affichés dans la barre de statut de Wireshark, ou de piloter une petite
barre d'outils (boutons, listes) pendant que la capture tourne. Utile
ici en particulier : les phases longues de switch-capture avant que le
moindre paquet n'arrive (upload de la feature `packet-capture`, attente
de fin de capture côté switch, transfert SCP/TFTP) pourraient remonter
un message de statut dans Wireshark, là où aujourd'hui c'est la page
« Journal » de la GUI GTK qui joue ce rôle.

**Précédent direct pertinent : `sshdump`**, extcap officiel livré avec
Wireshark lui-même, qui capture déjà du trafic sur un hôte distant via
SSH. La différence avec switch-capture reste substantielle : `sshdump`
suppose un outil de capture générique déjà présent côté distant
(`tcpdump`/`dumpcap`) et ne connaît rien à Comware, alors que
switch-capture orchestre spécifiquement le cycle de vie de la feature
`packet-capture` (upload du binaire, syntaxe CLI différente par modèle
5130EI/5130HI/5140EI/5140HI, attente active de fin de capture,
rotation en ring buffer, vérification NTP entre switches…) — un
`sshdump` nu ne remplace donc pas switch-capture, mais confirme qu'un
extcap SSH-vers-switch est un modèle déjà éprouvé par le projet
Wireshark lui-même.

**Tension architecturale (évaluation de cette session, pas un fait
documenté)** : le dialogue de configuration extcap reste un formulaire
plat à un seul écran. Il représente mal ce que fait la GUI GTK actuelle
au-delà du simple lancement d'une capture : assistant de détection de
modèle, modèles de capture réutisables (`config_to_template_dict` &
associés), page dédiée à la réinjection multi-captures TAP simultanées,
mirroring de port (`switch-capture mirror`, une commande à part), suivi
d'avancement détaillé. Retranscrire tout cela dans une boîte de dialogue
extcap semble mal adapté à l'outil tel qu'il a été conçu.

**Recommandation (également une évaluation, pas un fait) : ne pas
remplacer l'application GTK par un extcap.** Un wrapper extcap
**séparé et volontairement plus simple** — n'exposant que l'équivalent
du mode "fifo" pour une capture unique, sans assistant ni gestion de
modèles — serait plus réaliste comme point d'entrée complémentaire pour
qui veut une capture rapide sans ouvrir l'application complète. Resterait
alors la question du stockage des identifiants (le champ mot de passe
extcap n'a pas de lien avec le trousseau système déjà utilisé ici) et de
la découverte de modèle, qui devraient soit rester manuels, soit
réutiliser `switch_capture_core` en amont (avant que Wireshark
n'invoque l'extcap) — non creusé plus avant, hors du périmètre d'une
« étude ».

**Retombée croisée, pour la prochaine session qui traiterait le point
17 (urgent, toujours non traité)** : le man page officiel extcap
mentionne en passant le modèle de privilèges de `dumpcap`
lui-même — bits setuid/setgid conservés seulement pour les utilisateurs
du groupe système « wireshark » — comme approche déjà éprouvée par le
projet Wireshark pour capturer sans être root. Piste à évaluer pour la
création d'interface TAP de switch-capture (probablement via
`setcap`/un groupe dédié plutôt que ce mécanisme setuid précis, TAP et
capture passive n'ayant pas exactement les mêmes besoins), mais aucune
mise en œuvre ni vérification faite ici — simple note pour ne pas
repartir de zéro.

**Sources consultées** (recherche web, résumées et reformulées
ci-dessus, aucune reproduction de texte protégé) :
- Wireshark Developer's Guide, chapitre Extcap —
  `wireshark.org/docs/wsdg_html_chunked/ChCaptureExtcap.html`
- page de manuel `extcap(4)` — `wireshark.org/docs/man-pages/extcap.html`
  et `man7.org/linux/man-pages/man4/extcap.4.html`
- Wireshark Wiki, page Development/Extcap —
  `wiki.wireshark.org/Development/Extcap`
- exemple officiel `doc/extcap_example.py` dans le dépôt Wireshark
  (GitHub, miroir en lecture seule)
- extcap `sshdump` (livré avec Wireshark) et exemples tiers
  (`n2disk`, `wlan-extcap`, `pyspinel`) pour les emplacements
  d'installation et les patterns d'usage courants

### Repli KeePass pour le mot de passe SSH (27/08/2026, suite)

Traite la partie « repli sur un fichier KeePass si aucun trousseau système
n'est installé » du point 4 ci-dessous (section « Menu et préférences »),
listée depuis le 25/08/2026 comme « reste à faire » à côté du trousseau
système. Voir CLAUDE.md, section « Repli KeePass pour le mot de passe SSH »,
pour le détail complet.

- `switch_capture_core.py` : trois fonctions symétriques à celles du
  trousseau système (`save_ssh_password_to_keepass`,
  `load_ssh_password_from_keepass`, `delete_ssh_password_from_keepass`),
  import optionnel de `pykeepass` (`KEEPASS_AVAILABLE`). Ouvre un fichier
  `.kdbx` **existant** (jamais créé par cet outil) avec un mot de passe
  maître ; une entrée par couple switch/utilisateur, même identifiant que
  le trousseau système.
- `switch_capture_cli.py` : nouveau `--keepass-path` (`capture`,
  `uninstall`, `inspect`) + variable d'environnement
  `SWITCH_CAPTURE_KEEPASS_PASSWORD` (mot de passe maître, jamais en
  argument CLI en clair). `--remember-password`/`--forget-password` et le
  chargement automatique basculent sur ce repli **uniquement** si le
  trousseau système (`keyring`) est indisponible — jamais en plus de lui.
  Ordre de résolution complet : CLI/YAML > `SWITCH_SSH_PASSWORD` >
  trousseau système > repli KeePass.
- `src/docs/USAGE.md` : nouvelle sous-section « Mémoriser le mot de passe
  SSH entre deux lancements », couvrant trousseau système et repli
  KeePass (le trousseau système lui-même n'était jusqu'ici pas documenté
  dans ce fichier malgré son ajout le 25/08/2026).
- `requirements.txt`/`requirements-dev.txt` : `pykeepass` documenté comme
  dépendance optionnelle, même statut que `keyring`.

**Testé, avec une réserve propre à cette session** : environnement sans
accès réseau/pip cette fois-ci (contrairement aux sessions précédentes) —
ni `pykeepass`, ni `pytest` eux-mêmes ne sont installables ici. Le cycle
complet (save/load/delete, non-fuite entre comptes, mot de passe maître
incorrect, fichier absent, priorités CLI/env/trousseau/KeePass,
`--remember-password`/`--forget-password` avec et sans repli disponible,
`build_config` bout en bout, présence de `--keepass-path` dans
l'analyseur d'arguments) a été vérifié réellement avec un faux backend
`pykeepass` en mémoire, `keyring` restant réellement absent dans ce
sandbox (reproduisant fidèlement le scénario ciblé par ce repli, sans
avoir besoin de le simuler). Une suite `pytest` dédiée a été committée
(`tests/test_keepass_password.py`, 27 tests) et exécutée réellement via un
mini-shim compatible avec l'API `pytest` utilisée (fixtures/monkeypatch/
tmp_path/raises, non committé) faute de `pytest` installable ici :
**27 passed, 0 failed** — à confirmer avec un vrai `pytest` dès qu'un
environnement avec accès réseau est disponible. `ruff` non disponible non
plus dans ce sandbox : pas de `ruff check` sur les fichiers modifiés cette
session (à refaire dès que possible). Détail complet dans CLAUDE.md.

**Reste à faire** : câblage GUI (`switch_capture_gtk.py`, champ « chemin
du fichier KeePass » sous la case à cocher du trousseau système), sur le
modèle de « Intégration GUI du trousseau système » ci-dessus — nécessite
aussi la future page Préférences pour stocker `--keepass-path` de façon
persistante (voir point 1-4 ci-dessous, la page elle-même n'existe pas
encore) ; GTK4/PyGObject et Xvfb ne sont de toute façon pas disponibles
dans ce sandbox pour le valider visuellement.

### Câblage GUI du repli KeePass (28/08/2026, suite)

Traite le « Reste à faire » de la section précédente : câble côté
`switch_capture_gtk.py` le repli KeePass décrit juste au-dessus (qui
restait, lui, complet et testé mais non relié à la GUI), sur le modèle
exact de « Intégration GUI du trousseau système » (25/08/2026).

- Nouveau champ « Fichier KeePass (.kdbx, repli) » (`keepass_path`,
  `_row_path` avec sélecteur de fichier), ajouté sous la case
  « mémoriser le mot de passe SSH » **uniquement quand le trousseau
  système est indisponible** (`not KEYRING_AVAILABLE`) — même priorité
  que côté CLI (`switch_capture_cli.py::_apply_password_keyring_actions`) :
  le repli KeePass n'est jamais consulté en plus du trousseau système,
  seulement à sa place.
- Comme `ssh_password` et comme côté CLI, le mot de passe maître de la
  base KeePass n'est **jamais un champ de ce formulaire** : uniquement lu
  depuis `SWITCH_CAPTURE_KEEPASS_PASSWORD` au moment de l'action
  (`_resolve_keepass_master_password`, symétrique de son équivalent CLI).
- `keepass_path` est un champ transversal, pas un champ de `Config` :
  absent de `_build_config`/`_collect_raw_form_values`/
  `_apply_form_values` (pas encore de page Préférences pour le persister,
  voir point 1-4 ci-dessous — il se ressaisit à chaque lancement, comme
  le mot de passe SSH lui-même).
- `_maybe_remember_password`, `_on_forget_password` et
  `_maybe_autofill_password` retombent sur
  `save_ssh_password_to_keepass`/`load_ssh_password_from_keepass`/
  `delete_ssh_password_from_keepass` quand `keyring` est indisponible,
  avec les mêmes garde-fous que le volet trousseau système (dialogue
  d'erreur explicite si l'écriture échoue plutôt qu'avalée
  silencieusement ; auto-remplissage qui ne touche jamais un mot de passe
  déjà saisi ; suppression idempotente).
- Si ni `keyring` ni `pykeepass` ne sont installés, la case et le bouton
  « Oublier » restent désactivés avec une infobulle explicite (aucune
  régression du garde-fou existant) ; si seul `pykeepass` manque, le
  champ `keepass_path` lui-même est désactivé avec sa propre infobulle.

Testé réellement (pas juste relu), sous Xvfb avec GTK4/PyGObject réels :
- **12 tests `pytest` nouveaux** (`tests/test_gui_keepass_wiring.py`) :
  présence/sensibilité du champ selon `KEYRING_AVAILABLE`/
  `KEEPASS_AVAILABLE` (5 cas), exclusion de `keepass_path` de `Config` et
  des modèles de capture réutilisables (2 cas), appel effectif de
  `save_ssh_password_to_keepass`/`delete_ssh_password_from_keepass` avec
  les bons arguments quand le trousseau est indisponible (2 cas),
  dialogue d'erreur explicite quand aucun repli n'est prêt (chemin ou mot
  de passe maître manquant, 1 cas), lecture de
  `SWITCH_CAPTURE_KEEPASS_PASSWORD` (2 cas) — via `monkeypatch` sur les
  constantes `KEYRING_AVAILABLE`/`KEEPASS_AVAILABLE` et les fonctions
  `save_ssh_password_to_keepass`/`delete_ssh_password_from_keepass`
  importées dans `switch_capture_gtk.py`, même principe que les fausses
  fonctions déjà utilisées côté core (`test_keepass_password.py`).
- `py_compile` + import réel de `switch_capture_gtk.py` (sous Xvfb).
- `pytest tests/ -v` : **222 passed, 1 failed** (210 précédents + 12
  nouveaux ; l'unique échec est `test_taphelper_end_to_end_as_real_nonroot_user`,
  pré-existant, sans rapport — voir plus haut).
- `ruff check --line-length 120 src/` : 21 erreurs, strictement identique
  à l'état du dépôt avant ce changement (vérifié par comparaison directe
  avec une copie non modifiée) — aucune nouvelle erreur sur les lignes
  ajoutées.
- `flake8 --max-line-length 120 src/switch_capture_gtk.py` : 15 erreurs,
  également strictement identique à l'état du dépôt avant ce changement
  (mêmes numéros de ligne, tous en dehors des zones modifiées) ;
  `tests/test_gui_keepass_wiring.py` : 0 erreur.

**Reste à faire** : persistance de `keepass_path` (attend toujours la
page Préférences, comme anticipé) ; validation visuelle manuelle non
effectuée (uniquement via l'introspection directe des widgets par les
tests `pytest` ci-dessus, pas de script de capture d'écran cette
session). **Traité le 29/08/2026** (voir « Menu hamburger et page
Préférences » ci-dessous) : `keepass_path` déménagé en page Préférences
et persisté dans `config.yaml`.

### Câblage GUI de 4 réglages core/CLI déjà traités (28/08/2026)

Contrairement aux sessions précédentes (25/08 à 27/08), **GTK4/PyGObject
et Xvfb sont disponibles dans cette session**, ainsi qu'`iproute2`
(`ip`) — les trois manquaient jusqu'ici et bloquaient explicitement tout
le câblage GUI en attente (voir notes datées ci-dessus et CLAUDE.md).
Traite les 4 réglages déjà implémentés côté `switch_capture_core.py`/
`switch_capture_cli.py` mais listés comme « reste à faire : câblage
GUI » à plusieurs endroits de ce fichier — sur le modèle déjà en place
pour `tap_cleanup_on_stop`/`tap_pace_playback` (24-25/08/2026), sans
attendre la future page Préférences puisque ce modèle place déjà les
réglages directement dans le formulaire principal :

- **`hide_capture_traffic`** (case à cocher, section « Capture », visible
  en permanence) — masque le trafic SSH/SCP outil↔switch dans la
  capture, cochée par défaut (comportement historique préservé).
- **`capture_direction`** (menu déroulant, section « Capture », visible
  en permanence) — `bidirection`/`inbound`/`outbound`, défaut
  `bidirection`.
- **`archive_as_pcapng`** (case à cocher, section « Sortie live », juste
  après « Dossier d'archivage ») — convertit les fichiers archivés en
  pcapng, cochée par défaut ; visible seulement en mode fichier
  (`fifo`/`tap`), masquée en `rpcap` (aucun archivage possible dans ce
  mode), même règle de visibilité que les autres champs de rapatriement.
- **`tap_launch_wireshark`** (case à cocher, section « Sortie live »,
  juste après « Écart max entre trames ») — rejoint
  `tap_cleanup_on_stop`/`tap_pace_playback` au même endroit du
  formulaire, comme anticipé dans la note du 26/08/2026 ; visible
  seulement en mode `tap`.

Câblage complet dans les 4 points d'entrée du formulaire :
`_build_config` (construction du `Config` final), `_collect_raw_form_values`/
`_apply_form_values` (aller-retour modèle de capture réutilisable
YAML), et `_config_to_raw_dict` (repeuplement du formulaire via
« Modifier » sur une capture déjà ajoutée). `_apply_output_mode_visibility`
mis à jour pour les deux champs dépendants du mode ; `hide_capture_traffic`/
`capture_direction` restent visibles quel que soit le mode (le filtre et
le sens de capture s'appliquent indépendamment du mode de sortie choisi).

**Testé réellement** (pas juste relu), pour la première fois avec un
vrai GTK4/PyGObject/Xvfb sur ce projet plutôt qu'un stub ou une
vérification différée : suite `pytest` complète existante rejouée sans
aucune modification requise — **175 tests toujours au vert** — plus une
nouvelle suite dédiée `tests/test_gui_new_fields.py` (9 tests,
construction réelle de `CaptureWindow` via `Gtk.Application`/Xvfb) :
présence des 4 champs dans `_entries`/`_rows`, valeurs par défaut du
`Config` construit identiques à celles du dataclass, bascule des widgets
répercutée dans `_build_config`, visibilité correcte pour les 3 valeurs
de `output_mode`, aller-retour `_config_to_raw_dict`/`_apply_form_values`.
**184 tests réels passés, 0 échec au total.** Ce nouveau fichier de test
se saute proprement (`pytest.skip`) si aucun affichage graphique n'est
accessible, vérifié explicitement (`unset DISPLAY` → 9 `skipped`, pas
d'échec de collecte) pour ne pas casser une future session sans Xvfb.
Capture d'écran réelle sous Xvfb (fenêtre ciblée par `xdotool`/ID, pas
`import -window root`, même piège que documenté le 26/08/2026) confirmant
visuellement l'affichage des 4 champs aux emplacements attendus, en mode
`tap`. `py_compile` sur `switch_capture_gtk.py` : OK. `ruff` toujours
absent de ce sandbox malgré l'accès réseau retrouvé (paquet non demandé
cette session) : pas de `ruff check` non plus cette fois — à refaire dès
que possible, comme noté les sessions précédentes.

**Non fait** : les deux priorités urgentes (17, 18) restent non
traitées — voir « Suivi des sessions » ci-dessous, ce n'était pas
l'objet de cette tâche. Le reste des champs `reste à faire` sans lien
avec ces 4 réglages (menu hamburger/page Préférences elle-même, garde-fou
installation pendant capture, bugs GVFS/GOA, i18n) non plus.

### Garde-fou installation pendant une capture en cours (28/08/2026, suite)

Traite le point 7 de la section « Comportement de capture » ci-dessous :
« Empêcher le lancement d'une installation si une trace est déjà en
cours : bouton grisé et/ou pop-up d'alerte. » Tâche choisie pour cette
session car explicitement identifiée comme petite/peu risquée à livrer
en une seule réponse (« peut se greffer à un point proche », voir
« Suivi des sessions » précédent) et parce que l'environnement GTK4/Xvfb
retrouvé la session précédente (voir « Câblage GUI de 4 réglages
core/CLI déjà traités » ci-dessus) permet de la tester réellement plutôt
que de la livrer en aveugle.

**Ce qui a été fait**, dans `switch_capture_gtk.py` :

- `_on_install_all` (bouton « Lancer l'installation de toutes les
  captures », page Installation) refuse désormais de démarrer toute
  préparation si au moins une session a `capture_running == True` : une
  pop-up d'alerte (`_show_dialog`) liste la ou les capture(s) concernée(s)
  par leur libellé et invite à les arrêter depuis la page Journal avant
  de relancer une installation. Aucun `_start_prepare` n'est appelé dans
  ce cas — comportement testé (voir plus bas), pas seulement documenté.
- `_refresh_install_list` grise le bouton (`set_sensitive(False)`) et
  pose une info-bulle explicative dès qu'une capture est en cours,
  indépendamment du clic (donc avant même que l'utilisateur ne tente
  l'action) ; il redevient actif dès qu'aucune capture n'est plus en
  cours.
- Ce rafraîchissement est désormais appelé à trois moments : à la
  construction de la fenêtre (déjà existant), juste après le démarrage
  d'une capture (`_on_start_all`, pour griser immédiatement sans
  attendre le prochain tick), et à chaque tick du minuteur périodique
  déjà utilisé par la page Journal (`_refresh_journal`, ~1×/s) — ce
  dernier point couvre aussi bien la fin naturelle d'une capture que son
  arrêt manuel, sans code de rafraîchissement supplémentaire à
  maintenir.

**Non fait délibérément** : pas de garde équivalent côté CLI
(`switch_capture_cli.py`) — le point 7 de `features.md`, tel que rédigé
par l'utilisateur (« bouton grisé et/ou pop-up d'alerte »), décrit un
comportement d'interface graphique ; le CLI ne propose pas de bouton et
lance ses captures de façon strictement séquentielle (pas de notion de
« capture déjà en cours pendant qu'on relance une installation » côté
CLI, qui n'a qu'un seul flux d'exécution à la fois). À revoir si
l'utilisateur signale un besoin CLI équivalent.

**Testé réellement** : nouvelle suite `tests/test_install_guard_while_running.py`
(5 tests, construction réelle de `CaptureWindow` via `Gtk.Application`/
Xvfb, même pattern que `tests/test_gui_new_fields.py`) — bouton actif
sans capture en cours, grisé dès qu'une capture est marquée en cours,
réactivé après l'arrêt de cette capture, `_on_install_all` n'appelle
`_start_prepare` pour aucune session et affiche une pop-up quand une
capture tourne (`_start_prepare`/`_show_dialog` remplacés par des
espions via `monkeypatch`, aucune connexion SSH réelle nécessaire — même
principe que `tests/test_uninstall_confirm.py`), et `_on_install_all`
fonctionne normalement (appelle bien `_start_prepare`) quand rien n'est
en cours. Suite pytest complète rejouée sans aucune régression :
**189 tests réels passés, 0 échec** (184 précédents + ces 5 nouveaux).
`ruff check --line-length 120 src/` : toujours **4 erreurs** dans
`switch_capture_gtk.py` (`BLE001`, pré-existantes, aucune nouvelle) ;
`ruff check --line-length 120 tests/test_install_guard_while_running.py` :
seul le même bruit `RUF100`/`noqa: E402` déjà présent dans
`tests/test_gui_new_fields.py` (conservé volontairement pour flake8, qui
applique `E402` contrairement à `ruff`, comme documenté dans ce fichier
de test existant). Cette session, contrairement à la précédente,
disposait bien de `ruff` (installé via pip, réseau PyPI accessible).

### Mode non-root pour le mode TAP — switch-capture-taphelper (28/08/2026, suite)

Traite le point 17 de la section « Urgences » ci-dessous : « Ne pas avoir
besoin d'être root pour écouter une interface (mode utilisateur). »
Contrairement au point 18 (câblage GUI, non traité cette session — voir
« Non fait » plus bas), celui-ci touche à des privilèges système et a
donc été entièrement **vérifié empiriquement** dans ce sandbox (`ip`,
`gcc`, `setcap` disponibles cette session), pas seulement écrit puis
supposé correct.

**Solution retenue** : une aide privilégiée minimale et séparée,
`switch-capture-taphelper` (nouveau fichier `src/helpers/switch-capture-taphelper.c`,
~180 lignes, aucune dépendance externe — ni `ip`, ni netlink, ni
libcap-dev — seulement `<linux/if_tun.h>`/`<sys/ioctl.h>`/`<sys/socket.h>`
de la libc). C'est le **seul** morceau de switch-capture qui porte des
privilèges : `cap_net_admin+ep` positionné via `setcap` (**jamais** de bit
setuid, jamais root) — le process garde l'UID réel de l'utilisateur qui
l'invoque, il gagne seulement `CAP_NET_ADMIN` en effectif. Trois
sous-commandes, chacune sur un seul nom d'interface passé en argument et
strictement validé (longueur/caractères, jamais de shell/exec, voir
`valid_ifname()` dans le `.c`) :

- `add <ifname>` : ouvre `/dev/net/tun`, `TUNSETIFF` (crée si besoin),
  **`TUNSETOWNER` vers l'UID réel de l'appelant**, puis `TUNSETPERSIST`.
  C'est ce `TUNSETOWNER` qui est la clé du mécanisme : le noyau autorise
  ensuite un processus **non privilégié** dont l'UID correspond au
  propriétaire déclaré à s'attacher lui-même à ce même tap persistant —
  c'est exactement ce que fait déjà `TapFrameWriter` (aucune modification
  nécessaire de son côté).
- `up <ifname>` : active l'interface (`SIOCGIFFLAGS`/`SIOCSIFFLAGS` sur une
  socket `AF_INET`, équivalent de `ip link set ... up`).
- `del <ifname>` : `TUNSETPERSIST(0)`, non bloquant si déjà absente (même
  politique que `delete_tap_interface` côté Python).

**Câblage Python** (`switch_capture_core.py`) : `ensure_tap_interface`/
`delete_tap_interface` appellent désormais `_taphelper_path()` (résout
`SWITCH_CAPTURE_TAPHELPER` env, puis `/usr/lib/switch-capture/switch-capture-taphelper`,
puis à côté du fichier source — pour un usage non installé) ; si trouvée
et que le process n'est **pas** root, l'aide est utilisée (`add`+`up`,
ou `del`) ; sinon repli sur `ip` directement, **comportement historique
inchangé** (root/cron continue de fonctionner sans l'aide).

**Câblage installation, sur les 3 méthodes équivalentes** (voir section
dédiée « Installation — 3 méthodes équivalentes » plus haut), chacune
best-effort — l'absence de `gcc`/`setcap` n'empêche jamais l'installation
du reste, elle dégrade juste le mode TAP vers « nécessite root » comme
avant cette fonctionnalité :

- `install.sh` : installe `gcc`/`libcap2-bin` (APT) ou `gcc`/`libcap`
  (DNF) en best-effort, compile puis `setcap` juste après la pose du
  lanceur, résumé clair en fin d'exécution (« Mode TAP … : OK » ou
  raison de l'absence).
- `build_deb.sh`/`packaging/debian/DEBIAN/` : compilation **au moment du
  build** (`gcc` devient une dépendance de *build*, `dpkg-deb`/`dpkg`
  aussi utilisés pour résoudre l'architecture, voir plus bas) ; `setcap`
  déplacé dans `postinst` (les capabilities ne survivent pas de façon
  fiable à `dpkg-deb --build`/l'installation du `.deb` lui-même) ;
  `libcap2-bin` ajouté en `Recommends`.
- `build_rpm.sh`/`switch-capture.spec` : `BuildRequires: gcc`, compilation
  dans `%build`, `setcap` dans `%post` (même raison que le `.deb`) ;
  `Requires: libcap` (dépendance stricte cette fois, contrairement au
  `.deb` — cohérent avec le reste du spec qui préfère des `Requires`
  fermes).

**Correctif de packaging découvert et corrigé en cours de route** : un
binaire compilé rend le paquet spécifique à l'architecture de build — les
deux paquets étaient jusqu'ici `Architecture: all` (`.deb`) / `BuildArch:
noarch` (`.rpm`), ce qui serait devenu **incorrect** (un `.deb`
« all » s'installe sans vérification sur n'importe quelle architecture,
y compris une où le binaire ne tourne pas). Corrigé : `control` utilise
un placeholder `__BUILD_ARCH__` substitué par `dpkg --print-architecture`
dans `build_deb.sh` (nom de fichier de sortie et champ `Architecture`
alignés, ex. `switch-capture_1.0.0_amd64.deb` au lieu de `..._all.deb`) ;
`BuildArch: noarch` simplement retiré du `.spec` (rpmbuild retient alors
l'architecture de la machine de build, `RPMS/<arch>/` au lieu de
`RPMS/noarch/`). Repéré en écrivant les scripts, pas après coup lors des
tests — mais illustre pourquoi les trois méthodes ont été testées
réellement plutôt que livrées en aveugle cette fois.

**Testé réellement, de bout en bout, les trois méthodes d'installation** :
compilation, `setcap`, puis en tant qu'**utilisateur non-root réel** créé
pour l'occasion (`useradd`/`su -`, pas de mock) — `add`/`up` de
l'interface TAP, vérification via `ip -d link show` (`persist on user
<utilisateur>`), attachement réussi de `TapFrameWriter` (Python, sans
aucun privilège) avec écriture effective d'une trame, puis `del` et
disparition confirmée de l'interface :
- `install.sh -y` exécuté réellement (pas relu seulement) : rapporte
  « Mode TAP … : OK », vérifié non-root ensuite.
- `packaging/build_deb.sh` puis `apt-get install ./*.deb` réel : capability
  bien préservée par `dpkg-deb --build` + `setcap` en `postinst`, vérifié
  non-root ensuite.
- `packaging-rpm/build_rpm.sh` puis installation réelle du `.rpm` généré :
  capability bien positionnée par `%post`, vérifié non-root ensuite
  (`rpmbuild` a dû être appelé avec `--nodeps` dans ce sandbox précis
  pour contourner une limite locale — `gcc` est installé via APT sur cet
  hôte Ubuntu de test, invisible à la base RPM qui vérifie
  `BuildRequires: gcc` — sans rapport avec le contenu du `.spec`
  lui-même, qui reste correct pour une vraie machine de build
  RHEL/Rocky).
- `/dev/net/tun` : mode `0600` par défaut dans ce sandbox précis (`crw-------`,
  root uniquement), corrigé en `0666` manuellement pour chaque test —
  sur un système cible réel, ce device est normalement déjà `0666` via une
  règle udev standard (comme documenté par le pilote tun/tap du noyau) ;
  **si un déploiement réel se heurte à un `/dev/net/tun` restrictif**, ce
  sera un réglage udev à corriger côté système, pas un bug de
  `switch-capture-taphelper`.

Nouvelle suite `tests/test_tap_helper_nonroot.py` (9 tests) : résolution
de `_taphelper_path` (override env, non-exécutable ignoré, `None` si
rien trouvé), aiguillage `ensure_tap_interface`/`delete_tap_interface`
(non-root+aide trouvée → aide utilisée ; root → toujours `ip` même si
l'aide existe, compatibilité cron inchangée ; non-root+aide absente →
repli `ip`, message d'erreur explicite) — le tout mocké (`subprocess.run`
substitué), plus **un test d'intégration réel non mocké** qui compile
l'aide, positionne la capability, crée un utilisateur non-root jetable et
rejoue exactement la vérification manuelle décrite ci-dessus,
automatiquement (`@pytest.mark.skipif` propre si l'environnement ne
s'y prête pas — root/gcc/setcap/`/dev/net/tun` absents — jamais un échec
silencieux). Suite pytest complète rejouée : **184 tests réels passés, 0
échec** (175 précédents + ces 9 nouveaux ; l'écart avec le total de 189
de la session précédente vient de `test_install_guard_while_running.py`
et `test_gui_new_fields.py`, ignorés cette session faute de GTK4/Xvfb
dans **cet** environnement précis — l'un des deux sandbox est
systématiquement incomplet d'une session à l'autre, voir « Suivi des
sessions »). `ruff check --line-length 120` sur `switch_capture_core.py`
et `tests/test_tap_helper_nonroot.py` : aucune erreur nouvelle
introduite par cette session (mêmes lignes pré-existantes qu'avant,
fichier de test propre).

**Non fait délibérément** : pas de tentative d'implémenter aussi le point
18 (sélection packet-capture/mirroring/rpcap dans le formulaire GTK)
cette session — periomètre déjà large pour une réponse (aide privilégiée
+ core + 3×packaging + tests, chacun vérifié réellement) ; le point 18
reste entier, GTK4/Xvfb absents de **cet** environnement précis cette
fois (contrairement à la session du 28/08 précédente) donc de toute
façon non testable en GUI ici.



1. ~~Menu hamburger en haut à gauche de la fenêtre.~~ **Traité le
   29/08/2026** (voir section dédiée ci-dessus, « Menu hamburger et page
   Préférences ») : `Gtk.MenuButton`/`Gio.Menu`, deux entrées.
2. ~~Contenu du menu : « Préférences » et « Quitter ».~~ **Traité le
   29/08/2026**, voir ci-dessus.
3. ~~« Préférences » ouvre une page dédiée reprenant les réglages
   actuellement dans le formulaire de configuration principal :~~
   - ~~Utilisateur par défaut~~
   - ~~Feature packet-capture (dépôt local des `.bin` par modèle/version,
     import de dépôt `.bin`)~~
   - ~~NTP (section complète)~~
   - ~~Sortie live (section complète)~~
   ~~Sauvegarde dans `config.yaml` via un bouton de validation explicite.
   En conséquence, retirer du formulaire de configuration principal les
   champs : Slot IRF/Chassis, Modèle, forcer un `.bin`.~~ **Traité le
   29/08/2026, sur un périmètre réduit** (voir section dédiée
   ci-dessus) : page Préférences avec Slot/Modèle/`.bin` forcé (retirés
   du formulaire principal, comme demandé) + `keepass_path` (point 4
   ci-dessous), sauvegarde dans `config.yaml` en fusion via bouton
   « Enregistrer ». Utilisateur par défaut/dépôt `.bin`/NTP/Sortie live
   **non repris en Préférences** : déjà directement dans le formulaire
   principal depuis les sessions du 28/08/2026 (voir « Non fait » de la
   section dédiée pour le détail de cet arbitrage).
4. Mots de passe dans le trousseau système si disponible (déjà fait le
   25/08/2026, voir section dédiée ci-dessus). ~~Repli sur un fichier
   KeePass si aucun trousseau système n'est installé~~ **Core + CLI +
   documentation utilisateur traités le 27/08/2026** (voir section dédiée
   ci-dessus, « Repli KeePass pour le mot de passe SSH ») — câblage GUI
   traité le 28/08/2026 (voir section dédiée ci-dessus). ~~reste à faire :
   réglage correspondant (`--keepass-path`) dans la nouvelle page
   Préférences~~ **`keepass_path` persisté en page Préférences le
   29/08/2026** (voir section dédiée ci-dessus) : point 4 entièrement
   traité.

### Sélection packet-capture / port mirroring dans le formulaire GUI (28/08/2026, suite)

**Point 18 (« Urgences », seul point encore marqué urgent depuis
plusieurs sessions) traité et testé réellement.** Le formulaire GTK4 ne
permettait jusqu'ici de configurer que le côté packet-capture
(fifo/tap/rpcap, géré en sessions multi-captures via `CaptureSession`) ;
le port mirroring (`MirrorConfig`/`MirrorThread`, déjà entièrement
implémenté et testé côté core, exposé uniquement par le CLI
`switch-capture mirror`) était totalement absent de la GUI.

- Nouveau dropdown **« Type de capture »** en haut du formulaire de la
  page Configuration (`capture_type`, valeurs `packet-capture`/
  `mirroring`, `packet-capture` par défaut — comportement inchangé tant
  que l'utilisateur ne change pas ce réglage).
- Les sections déjà existantes (Slot/Modèle, Feature packet-capture,
  Transfert de fichiers, NTP, Capture, Sortie live, ainsi que les
  boutons Tester/Ajouter/Enregistrer modèle/Importer modèle) sont
  désormais regroupées dans un conteneur unique (`_packet_capture_box`)
  masqué quand `capture_type == "mirroring"`.
- Nouveau bloc **« Port mirroring »** (`_mirroring_box`), visible
  seulement en mode mirroring : `mirror_mode` (local/gre),
  `mirror_group_id`, `mirror_source_interfaces` (liste séparée par des
  virgules), `mirror_direction`, puis selon `mirror_mode` —
  `mirror_monitor_interface` (mode local) ou
  `mirror_tunnel_id`/`mirror_tunnel_local_ip`/`mirror_tunnel_ip`/
  `mirror_tunnel_mask`/`mirror_remote_ip`/`mirror_loopback_interface`
  (mode gre) — visibilité conditionnelle testée programmatiquement pour
  les deux modes (`_apply_mirror_mode_visibility`).
- **Choix de conception délibéré** : le mirroring pousse une
  configuration switch en une seule action (pas de fichier local, pas
  de rotation/spool, pas de polling — voir le commentaire déjà présent
  au-dessus de `MirrorConfig` dans `switch_capture_core.py`), il ne
  rejoint donc **pas** le modèle `CaptureSession`/liste de captures
  planifiées ni les pages Installation/Démarrage/Résultats (pensées
  pour le cycle de vie packet-capture). Deux boutons dédiés dans le
  bloc mirroring lui-même — « Pousser la configuration de mirroring »
  et « Retirer le mirroring » — lancent `MirrorThread` en tâche de
  fond (`teardown=False`/`True`), exactement le même schéma que
  `UninstallThread`/`_on_uninstall_session` déjà en place (callback
  `on_done(success, message)`, dialogue de résultat +
  `_set_journal_status`, thread conservé dans `self._mirror_threads`
  pour éviter une collecte prématurée). `_build_mirror_config()`
  réutilise directement la validation de
  `MirrorConfig.__post_init__` plutôt que de la dupliquer (champs
  obligatoires selon `mode`, erreurs affichées dans un dialogue plutôt
  que de lever une exception non gérée — testé).
- Modèles de capture (Enregistrer/Importer, `_config_to_raw_dict`/
  `_apply_form_values`) **non étendus** au mirroring dans cette
  session — restent spécifiques à `Config`/packet-capture, point non
  demandé et hors du périmètre initial de ce chantier.

Testé réellement : nouvelle suite `tests/test_gui_mirroring.py` (13
tests, GTK4/PyGObject réels sous Xvfb, même schéma de `skip` propre que
`test_gui_new_fields.py` si l'affichage graphique manque) — présence
des champs, bascule `_apply_capture_type_visibility`
(packet-capture ↔ mirroring, dans les deux sens), bascule
`_apply_mirror_mode_visibility` (local ↔ gre), construction d'un
`MirrorConfig` valide dans les deux modes depuis le formulaire (y
compris parsing/nettoyage de la liste d'interfaces sources séparées par
des virgules), levée d'erreur propre sur champs obligatoires manquants
(monitor_interface en mode local ; tunnel_local_ip/tunnel_ip/remote_ip
en mode gre ; source_interfaces dans tous les cas), et absence de crash
sur formulaire mirroring vide au clic sur « Pousser ». Suite complète
rejouée : **211 tests, 210 passés, 1 échec pré-existant sans rapport**
(voir décompte en tête de ce fichier et CLAUDE.md). Capture d'écran
réelle sous Xvfb (fenêtre ciblée par ID, `import -window root`) confirmant
visuellement le bloc packet-capture masqué et le bloc mirroring affiché
une fois `capture_type` basculé sur « mirroring ». `ruff check
--line-length 120` propre sur le fichier modifié et le nouveau fichier
de test (les 4 erreurs `BLE001` restantes dans
`switch_capture_gtk.py` sont pré-existantes, sur des lignes non
touchées par cette session — vérifié par comparaison avec le fichier
avant modification).

**Non fait dans cette session, volontairement hors périmètre** :
vérification empirique contre un switch réel (aucun switch réel
disponible dans ce sandbox, comme pour le reste du projet) ; extension
des modèles de capture réutilisables au mirroring ; toute forme
d'affichage de statut mirroring persistant dans les pages Journal/
Résultats (le mirroring ne produit pas de session au sens de l'outil,
voir choix de conception ci-dessus).

### Menu hamburger et page Préférences (29/08/2026)

Point 1 (« Menu et préférences ») traité intégralement, sur le périmètre
précisé par la note du 28/08/2026 ci-dessous (points 1939-1965) plutôt
que sur la liste complète de la demande d'origine du 26/08/2026 — voir
« Non fait » en fin de section pour le pourquoi.

- **Menu hamburger** (`Gtk.MenuButton` + `Gio.Menu`, icône
  `open-menu-symbolic`) en haut à gauche de la barre de titre, sur toutes
  les pages (posé sur le `Gtk.HeaderBar` commun) : deux entrées,
  « Préférences » (action `win.preferences`) et « Quitter » (action
  `win.quit-app`, réutilise `_on_close_request` — même nettoyage des
  threads de capture en cours et de la fenêtre Préférences si ouverte
  que le bouton de fermeture natif de la fenêtre).
- **Page Préférences** (`Gtk.Window` modale, transient-for la fenêtre
  principale) : Slot IRF/châssis, Modèle, Forcer un `.bin` précis, et
  Fichier KeePass (`.kdbx`, repli) — ces 4 champs uniquement, retirés du
  formulaire de capture principal. Bouton « Enregistrer » qui valide,
  persiste, et met à jour l'état en mémoire (pas de fermeture
  automatique, pour pouvoir enchaîner plusieurs enregistrements sans
  rouvrir la page).
- **Persistance** (`switch_capture_core.load_gui_preferences`/
  `save_gui_preferences`, nouvelles fonctions, testées indépendamment de
  GTK4) : lues au démarrage dans `./config.yaml` (dossier de lancement,
  même convention que `spool_dir`/`DEFAULT_MODELS_DIR`), écrites après
  clic sur « Enregistrer ». **Toujours en fusion, jamais en écrasement**
  du fichier : seules les 4 clés gérées (`slot`/`model`/
  `feature_bin_path`/`keepass_path`) sont lues/modifiées, tout le reste
  d'un `config.yaml` déjà utilisé pour `switch-capture capture --config`
  (switch_ip, ssh_user, capture_interface...) est préservé tel quel —
  fichier unique partageable entre GUI et CLI sans conflit, voir
  `config.yaml.example` mis à jour. Une valeur remise à vide/« Auto »
  retire la clé du fichier plutôt que d'y écrire un vide explicite. Un
  `config.yaml` absent ou invalide (YAML mal formé, droits...) au
  démarrage ne bloque jamais le lancement : valeurs par défaut
  conservées, avertissement journalisé (`_load_preferences`, `except
  Exception` volontairement large — voir note ruff plus bas).
- **`keepass_path`** : jusqu'ici un champ à part du formulaire principal
  (jamais un champ de `Config`), affiché seulement quand le trousseau
  système était indisponible et **jamais persisté** (ressaisi à chaque
  lancement). Déménagé en Préférences, toujours affiché mais grisé
  (`set_sensitive(False)`) quand le trousseau système est disponible ou
  que `pykeepass` est absent — plutôt que masqué, pour rester réglable en
  prévision d'une bascule future. Comme avant, le mot de passe maître de
  la base ne transite jamais par un champ GUI (uniquement
  `SWITCH_CAPTURE_KEEPASS_PASSWORD`).
- **Cohérence des 4 points d'entrée du formulaire** (`_build_config`,
  `_collect_raw_form_values`, `_config_to_raw_dict`, `_apply_form_values`)
  mis à jour pour lire `slot`/`model`/`feature_bin_path` depuis
  `self._prefs` plutôt que des widgets retirés ; `_row_model` (mort,
  plus aucun appelant) supprimé.
- **Modèles de capture réutilisables** (`save_capture_template`/
  `load_capture_template`) : `slot`/`model`/`feature_bin_path` retirés de
  `TEMPLATE_EXCLUDED_FIELDS`/`_TEMPLATE_FIELDS` côté core — ce ne sont
  plus des réglages « par capture », un modèle n'a plus à les embarquer
  (même principe déjà en place pour `ssh_password`).
- **Éditer une capture existante** (`_on_edit_session`, bouton
  « Modifier ») : resynchronise désormais explicitement `self._prefs`
  sur les `slot`/`model`/`feature_bin_path` de **cette** session avant de
  repeupler le formulaire — sans quoi soumettre à nouveau après édition
  aurait silencieusement basculé ces 3 réglages vers les Préférences
  *actuellement* en mémoire (qui peuvent avoir changé depuis l'ajout de
  cette capture), sans que rien ne le signale à l'écran. Comportement
  couvert par un test dédié (voir plus bas). N'écrit jamais
  `config.yaml` de sa propre initiative — seul un « Enregistrer » explicite
  en page Préférences le fait.

**Tests** (tous réellement exécutés, sous Xvfb pour les tests GTK4) :
`tests/test_gui_preferences_config.py` (13, nouveau — persistance core
pure : absence de fichier, fusion, retrait de clé sur vide/`None`,
préservation de clés étrangères) ; `tests/test_gui_preferences_window.py`
(20, nouveau — retrait des champs du formulaire principal, chargement au
démarrage avec/sans fichier/fichier invalide, `_build_config` reflète les
Préférences, `_save_preferences`, actions `win.preferences`/`win.quit-app`,
cycle de vie de la fenêtre Préférences, resynchronisation à l'édition
d'une session) ; `tests/test_gui_keepass_wiring.py` (13, réécrit — les
tests qui vérifiaient la présence/absence conditionnelle du champ
`keepass_path` dans `self._entries` du formulaire principal vérifient
maintenant sa sensibilité dans `self._prefs_entries`, nouveau dict
d'exposition des widgets de la page Préférences pour rester testable sans
parcourir l'arbre — même rôle que `self._entries` pour le formulaire
principal ; le reste, inchangé dans son intention, adapté pour lire
`self._prefs["keepass_path"]` au lieu d'un widget) ;
`tests/test_capture_templates.py` (retrait de `slot`/`model` de
l'assertion « champs couverts », ajout d'une assertion d'exclusion
dédiée). **Suite complète du dépôt : 265 tests au total** (230
précédents + 35 nouveaux/modifiés net) — **0 échec sur les 3 premières
exécutions consécutives**, puis `test_taphelper_end_to_end_as_real_
nonroot_user` (pré-existant, sans rapport avec ce changement — voir
détail dans « Environnement de cette session » ci-dessous) est devenu
**stablement en échec** (3 tentatives isolées supplémentaires, toutes en
échec) sans qu'aucun code n'ait changé entre-temps : donc **264 passés,
1 échec** en l'état final de cette session, pour la même raison
déjà documentée par les sessions précédentes (capacités kernel/
`iproute2` dans ce sandbox précis), mais avec une donnée nouvelle — cette
fois la dérive s'est produite **au sein d'une même session**, pas
seulement d'une session à l'autre comme observé jusqu'ici.

**Environnement de cette session** : à l'ouverture, ni `iproute2` (`ip`)
ni `gvfs`/`gvfs-daemons`/`gvfs-backends`/`dbus-x11` ni
`pytest`/`ruff`/`keyring`/`pykeepass`/`netmiko`/`paramiko`/`scp`/`loguru`
n'étaient préinstallés (GTK4/PyGObject l'était, lui) — tous installés en
début de session (apt/pip, accès réseau disponible). Confirme, comme la
session du 28/08, qu'un environnement constaté ne persiste pas d'une
session à l'autre : après installation d'`iproute2`, le test
d'intégration non-root TAP (`test_taphelper_end_to_end_as_real_nonroot_user`,
qui en dépend) **passe 3 fois d'affilée**, plus tôt dans cette même
session (confirme à nouveau que son échec dans d'autres sessions tenait à
l'environnement, pas au code) — puis, sans qu'aucun code n'ait changé
entre-temps, **échoue de façon stable** en toute fin de session (3
tentatives isolées supplémentaires, toutes en échec, aucun résidu
`sc_helper_test_user`/`vcaphelpertest` trouvé, aucune trace AppArmor,
Firecracker/microVM confirmé par `dmesg`) : la capacité kernel dont
dépend ce test peut donc dériver **au sein même d'une session**, pas
seulement d'une session à l'autre comme documenté jusqu'ici — cause
exacte non identifiée, non creusée davantage, hors périmètre de cette
session ; de même pour
`test_gvfs_env_workaround.py` après installation de `gvfs`/
`gvfs-daemons`/`gvfs-backends` (l'avertissement `GVFS-RemoteVolumeMonitor`
que ce test reproduit délibérément ne peut apparaître sans `gvfs`
installé) — celui-ci resté stable (passé à chaque exécution après
installation).
`ruff check --line-length 120 src/` comparé ligne à ligne à une copie
pristine du zip d'entrée (`--no-cache` des deux côtés pour écarter tout
artefact de cache) : les 21 erreurs pré-existantes (15 `BLE001` dans
`switch_capture_core.py`, 4 dans `switch_capture_gtk.py`, 1 `BLE001` dans
`switch_capture_cli.py`, 1 `UP037` dans `switch_capture_core.py`) toutes
intactes, aucune touchée ; **+2 `BLE001`** ajoutés par cette session
(`_load_preferences` et le bouton « Enregistrer » de la page Préférences,
tous deux des `except Exception` volontairement larges pour ne jamais
faire planter l'application sur un `config.yaml` corrompu ou une erreur
d'écriture — même principe que les ~20 autres déjà dans ce fichier,
laissés tels quels). `ruff format --check` non traité comme porte de
qualité (jamais appliqué à ce dépôt à ce jour, réécrirait des milliers de
lignes préexistantes sans rapport avec ce changement — voir style dense
multi-arguments déjà partout dans `switch_capture_gtk.py`, que ce
changement suit).

**Non fait cette session, noté explicitement** : la demande d'origine du
26/08/2026 plaçait aussi « Utilisateur par défaut », le dépôt `.bin`
(import compris) et les sections NTP/« Sortie live » complètes en page
Préférences. Non repris ici : ces réglages ont depuis rejoint directement
le formulaire principal lors des sessions du 28/08/2026 (câblage de
`hide_capture_traffic`/`capture_direction`/`archive_as_pcapng`/
`tap_launch_wireshark`), choix documenté explicitement dans CLAUDE.md à
cette date, et la note la plus récente sur le sujet (« Suivi des
sessions », avant cette session) limitait déjà le périmètre restant du
point 1 aux 4 champs traités ici. Les rouvrir aurait défait un travail
récent, testé, et débordé le cadre d'une session. Signalé pour arbitrage
si un besoin réel s'en fait sentir. Également non fait : vérification
empirique contre un switch réel (aucun disponible dans ce sandbox, comme
pour le reste du projet).

### Gestion propre de Ctrl+C (SIGINT) dans l'app GTK4 (29/08/2026, suite)

Point 10 (reformulé le 28/08/2026), volet `Ctrl+C`/SIGINT — voir détail
dans CLAUDE.md, section dédiée, pour le diagnostic complet et le fix
retenu (résumé : `CaptureApp.do_activate` installe désormais un
gestionnaire SIGINT via `GLib.unix_signal_add()`, qui ferme la fenêtre
principale par le même chemin que le bouton de fermeture natif / «
Quitter » du menu — `_on_close_request` — au lieu de laisser Python lever
un `KeyboardInterrupt` brut à l'intérieur d'un callback GLib quelconque).

**Tests ajoutés** : `tests/test_gtk_sigint.py` (nouveau fichier, même
convention `pytest.importorskip("gi")` que les 5 fichiers `test_gui_*.py`
existants), 5 tests — enregistrement de la source GLib après activation +
idempotence, et `_on_sigint` arrête bien une capture en cours
(`state.stop_event`), ferme la fenêtre Préférences si ouverte, et ne lève
jamais si appelé avant qu'une fenêtre n'existe.

**Non testé réellement cette session** — écart assumé par rapport à la
pratique habituelle de ce dépôt (reproduire le bug, corriger, re-tester
sous Xvfb) : aucune des deux étapes n'était possible ici, faute
d'environnement. Seule vérification effectuée : `python3 -m py_compile`
sur `switch_capture_gtk.py` et `tests/test_gtk_sigint.py` (syntaxe
uniquement), plus un contrôle manuel de longueur de ligne (`awk 'length
> 120'`, palliatif à `ruff check --line-length 120`, lui aussi
indisponible) : aucune ligne ajoutée ne dépasse 120 caractères (la seule
trouvée dans tout le fichier, ligne 1397, est préexistante, comparée à
une copie pristine du zip d'entrée, et hors périmètre de ce changement).

**Environnement de cette session** — le plus contraint rencontré à ce
jour sur ce projet (voir « Suivi des sessions » en fin de document pour
l'historique complet des environnements précédents, tous différents) :
**réseau totalement désactivé** (`x-deny-reason: host_not_allowed` sur
toute requête sortante, y compris `pypi.org`/`archive.ubuntu.com` —
vérifié explicitement, pas supposé), contrairement à toutes les sessions
précédentes documentées ici, qui avaient toujours eu au moins un accès
partiel. Résultat : aucun paquet manquant n'a pu être installé, ni via
`apt` ni via `pip`. Restés absents (contrairement à la session du
29/08/2026 précédente, où les mêmes paquets avaient pu être installés en
tout début de session) : `pytest`, `ruff`, `loguru`, `netmiko`,
`paramiko`, `scp`, `keyring`, `pykeepass`. `python3-gi`/PyGObject 3.48.2
lui-même **était** présent (à la différence des sessions « GTK4/PyGObject
absents » précédemment documentées), mais pas le typelib
`gir1.2-gtk-4.0` (`gi.require_version("Gtk", "4.0")` lève `ValueError:
Namespace Gtk not available`) — combinaison inédite dans l'historique de
ce projet (jusque-là, PyGObject et son typelib GTK4 étaient toujours
soit présents ensemble, soit absents ensemble). `Xvfb` était présent mais
inutile dans ces conditions. Conséquence directe : aucun des trois
fichiers source principaux n'est importable dans ce sandbox
(`switch_capture_core.py`/`switch_capture_cli.py` échouent dès `from
loguru import logger` ; `switch_capture_gtk.py`, en plus, dès `gi.
require_version("Gtk", "4.0")`), et la suite `pytest` existante (19
fichiers `test_*.py` avant cette session) n'a pas pu être exécutée, ne
serait-ce qu'une fois, à titre de non-régression.

**Remarque annexe, hors périmètre de cette session, signalée pour
arbitrage** : `pytest.importorskip("gi")`, utilisé par les 5 fichiers
`test_gui_*.py` existants et repris à l'identique dans
`test_gtk_sigint.py`, protège contre l'absence du module `gi` lui-même,
mais pas contre la combinaison précise de ce sandbox (`gi` présent, «
Gtk 4.0 » absent) : `gi.require_version("Gtk", "4.0")` lèverait alors une
`ValueError` non interceptée à la collecte plutôt qu'un skip propre.
Observation faite hors pytest (absent cette session), via un `python3 -c`
direct ; non corrigée ici (toucherait 5 fichiers existants sans rapport
avec le point 10, et resterait de toute façon invérifiable cette
session).

### Filtre de capture

5. ~~Revoir le filtre de capture~~ **Core + CLI traités le 26/08/2026**
   (voir section dédiée ci-dessus, `build_capture_filter` +
   `Config.hide_capture_traffic` + `--no-hide-capture-traffic`) —
   **câblage GUI traité le 28/08/2026** (voir section dédiée ci-dessus,
   « Câblage GUI de 4 réglages core/CLI déjà traités ») : case à cocher
   dans le formulaire principal, section « Capture ». Entièrement traité.

### Comportement de capture

6. ~~À rechercher (recherche internet) : `packet-capture` semble ne pas
   capter les trames émises par le switch lui-même (capture inbound
   uniquement apparente) — objectif : capturer les deux sens (both).~~
   **Traité le 26/08/2026** (voir section dédiée ci-dessus, « Sens de
   capture : inbound / outbound / bidirection ») : hypothèse confirmée
   par la doc H3C officielle, `build_capture_direction_clause` +
   `Config.capture_direction` (défaut `bidirection`) + `--capture-direction`.
   **Câblage GUI traité le 28/08/2026** (menu déroulant dans le formulaire
   principal, section « Capture ») — reste à faire : vérification
   empirique contre un switch réel (aucun switch réel disponible dans ce
   sandbox).
7. ~~Empêcher le lancement d'une installation si une trace est déjà en
   cours : bouton grisé et/ou pop-up d'alerte.~~ **Traité le 28/08/2026**
   (voir section dédiée ci-dessus, « Garde-fou installation pendant une
   capture en cours ») : bouton grisé en continu tant qu'une capture est
   en cours (`_refresh_install_list`) + pop-up d'alerte si l'action est
   malgré tout déclenchée (`_on_install_all`). Entièrement traité côté
   GUI ; pas de garde équivalent côté CLI (voir section dédiée pour la
   justification).
19. ~~Privilégier `pcapng` à `pcap`~~ **Traité le 26/08/2026** (voir
    section dédiée ci-dessus, `convert_pcap_to_pcapng` +
    `archive_capture_file` + `Config.archive_as_pcapng` +
    `--no-archive-as-pcapng`). **Câblage GUI traité le 28/08/2026** (case
    à cocher dans le formulaire principal, section « Sortie live », juste
    après « Dossier d'archivage »). Entièrement traité.

### Bugs rapportés (logs joints par l'utilisateur)

8. ~~Bouton « … » en bout de ligne « feature bin » : plantage à l'usage
   (`Erreur creating proxy … org.gtk.vfs.GoaVolumeMonitor`, avertissement
   GTK sur l'espace disponible, puis « Erreur de segmentation (core
   dumped) »).~~ **Diagnostiqué et corrigé le 28/08/2026** (voir section
   dédiée ci-dessus, « Bugs GVFS/GOA du sélecteur de fichiers ») :
   `GIO_USE_VFS=local` + `GIO_USE_VOLUME_MONITOR=unix`. Avertissement de
   la même famille reproduit puis confirmé disparu ; segfault exact non
   reproduit dans cette session (voir réserve dans la section dédiée).
9. ~~Bouton « … » après le champ « dossier d'archivage » : mêmes erreurs
   GVFS/GOA au démarrage, puis `Gtk-CRITICAL **: thaw_updates: assertion
   'GTK_IS_FILE_SYSTEM_MODEL (model)' failed`.~~ **Même correctif que le
   point 8** — tous deux passent par le même code (`_on_browse`).
10. ~~**Reformulé** : la partie GVFS/GOA de ce point (l'assertion
    `thaw_updates` réapparaissant à l'arrêt) relève du même correctif que
    8/9/11/12 ci-dessus. Le volet `Ctrl+C`/SIGINT, sans rapport avec
    GVfs/GOA.~~ **Traité et vérifié empiriquement le 29/08/2026** (voir
    section dédiée dans CLAUDE.md, « Gestion propre de Ctrl+C (SIGINT)
    dans l'app GTK4 » puis « Vérification empirique du fix Ctrl+C/SIGINT
    — point 10 clos ») : `CaptureApp` installe un gestionnaire SIGINT via
    `GLib.unix_signal_add()` — pas `signal.signal`, qui ne s'exécute pas
    de façon fiable pendant que la boucle événementielle GLib tourne, ce
    qui provoquait le `Traceback`/`KeyboardInterrupt` brut rapporté — qui
    ferme la fenêtre principale par le même chemin que le bouton de
    fermeture natif / « Quitter » du menu (`_on_close_request`), sans
    logique dupliquée. **Vérifié empiriquement dans une session
    ultérieure** (environnement GTK4/Xvfb/pytest retrouvé) : les 5 tests
    `tests/test_gtk_sigint.py` passent (219 → 270 tests au total avec le
    reste de la suite, 0 échec), et un test d'intégration bout en bout
    (vrai `SIGINT` envoyé à `src/switch-capture -g` réellement lancé)
    confirme un exit code 0 sans traceback. Entièrement traité.
11. ~~Bouton « Importer dépôt bin » : même profil de plantage/`Ctrl+C` avec
    traceback brut que les points 9-10.~~ **Volet plantage/GVFS corrigé
    le 28/08/2026, même correctif que 8/9/12** (`_on_import_bin` utilise
    aussi `Gtk.FileChooserNative`) ; le volet `Ctrl+C`/traceback reste
    ouvert, voir point 10 reformulé ci-dessus.
12. ~~Bouton « … » des features : mêmes erreurs GVFS/GOA puis « Erreur de
    segmentation (core dumped) ».~~ **Même correctif que le point 8.**

### Internationalisation

13. ~~Franciser les libellés de l'interface encore en anglais (ex. :
    « features ») et mettre en place l'internationalisation complète :
    fichier `.pot` + fichier `.po` (`en-US`).~~ **CLI traitée le
    30/08/2026** (voir CLAUDE.md, section dédiée) : infrastructure
    `gettext` posée et **CLI entièrement câblée** (36 `help=` +
    1 `description=` d'argparse, 46 chaînes uniques après dédoublonnage),
    `switch-capture.pot` extrait via `xgettext`, `locale/en_US/LC_MESSAGES/
    switch-capture.po` traduit à la main (46/46) et compilé en `.mo`.
    **GUI GTK4 traitée le 31/08/2026** (voir CLAUDE.md, section dédiée) :
    `switch_capture_gtk.py` **entièrement câblé** — tous les libellés
    statiques (`label=`, `title=`, `placeholder_text=`, `secondary_text=`,
    `text=`/`add_button()` de `Gtk.MessageDialog`, titres statiques passés
    à `_show_dialog`/`GLib.idle_add(self._show_dialog, ...)`, y compris 9
    appels initialement manqués au premier passage puis retrouvés via
    `ruff check` — voir CLAUDE.md) enveloppés dans `_()`, partageant le
    même domaine/`.pot`/`.po` que la CLI (`locale/switch-capture.pot`,
    127 chaînes uniques au total CLI+GUI, 127/127 traduites, 0 fuzzy — porté
    à **130** le 31/08/2026 avec les 3 nouvelles chaînes de la sous-commande
    `analyze-pacing` (voir « Pas fait » ci-dessus), 130/130 traduites.
    **Choix de périmètre assumé, comme pour la CLI :** les messages
    dynamiques du Journal (f-strings avec IP/nom de capture) et corps de
    dialogues interpolés (`str(exc)`, etc.) restent en français — non
    traités, à faire dans une session ultérieure si besoin. Vérifié
    réellement : `py_compile` OK ; `ruff check`/`ruff format` comparés au
    baseline du fichier original avant modification — mêmes 6 erreurs
    `BLE001` préexistantes, aucune nouvelle, même besoin de reformatage
    cosmétique préexistant ; suite pytest non-GTK à 200 passés (aucune
    régression) ; **GTK4 réellement indisponible dans ce sandbox** (essai
    d'installation de `gir1.2-gtk-4.0` échoué, paquet introuvable sur le
    miroir) donc pas de test visuel réel de la fenêtre — la fonction `_()`
    du module a néanmoins été exercée réellement (pas seulement relue) en
    import mocké de `gi`/`Gtk` (stubs Python purs, sans rendu), confirmant
    que chaque chaîne testée bascule correctement en anglais avec
    `LANGUAGE=en_US` et repasse en français par défaut (`fallback=True`).
    **Vérification pérennisée le 31/08/2026** (voir CLAUDE.md, section
    dédiée) : cette vérification manuelle au cas par cas est désormais un
    test automatisé permanent de la suite pytest
    (`tests/test_gtk_i18n_translations.py`, 14 tests) — complétude
    (chaque chaîne `_(...)` du code source, extraite via `ast` donc à
    l'abri d'un oubli de mise à jour manuelle, a une entrée non vide dans
    le `.mo` compilé), non-régression (aucune traduction identique au
    français hors les 2 exceptions délibérées), exactitude sur un
    échantillon, et repli français par défaut. Premier test de la suite à
    réellement importer et exercer `switch_capture_gtk.py` dans ce
    sandbox (les `test_gui_*.py` existants nécessitent un vrai GTK4/Xvfb
    et restent exclus/skippés).
    Le `.po` `en_US` n'a été relu que par moi, pas par une personne
    anglophone native — à faire relire avant diffusion publique.

### Fonctionnalités

14. ~~Lancement automatique de Wireshark en mode TAP (attaché à
    l'interface TAP créée par l'outil).~~ **Core + CLI traités le
    26/08/2026** (voir section dédiée ci-dessus, `Config.tap_launch_wireshark`
    + `_launch_wireshark_tap` + `--tap-launch-wireshark`). **Câblage GUI
    traité le 28/08/2026** (voir section dédiée ci-dessus, « Câblage GUI
    de 4 réglages core/CLI déjà traités ») : case à cocher dans le
    formulaire principal, aux côtés de `tap_cleanup_on_stop`/
    `tap_pace_playback`, comme anticipé. **Non vérifié empiriquement** :
    ni contre un switch réel, ni avec un binaire `wireshark` réel (absent
    de ce sandbox) — seul l'appel `subprocess.Popen` et ses arguments ont
    été vérifiés par substitution (voir tests existants, non modifiés
    cette session).

### Projet futur (hors switch-capture lui-même)

15. ~~Squelette vide (nouveau projet) reprenant toutes les demandes et
    recommandations de dev accumulées ici, pour un futur projet très
    similaire en Python + GTK4 : `loguru`, `ruff`, pre-commit, tests
    automatisés.~~ **Traité le 29/08/2026** (voir CLAUDE.md, section
    dédiée) : livré à côté de ce dépôt (`gtk4-project-skeleton/`, hors
    switch-capture lui-même comme demandé), pas dedans — séparation
    core/CLI/GUI, `loguru`, tests indépendants de GTK4 (`conftest.py`
    ajoutant `src/` à `sys.path`), `.pre-commit-config.yaml` (mêmes hooks
    que ce dépôt, y compris le doublon volontaire ruff/flake8 pour E402),
    `pyproject.toml` (`[tool.ruff]` ligne 120). Volontairement absent :
    packaging `.deb`/`.rpm`/`install.sh`, `.desktop`/icône, toute logique
    métier réelle — à recréer si le futur projet en a effectivement
    besoin. Vérifié réellement : `py_compile` sur les 4 fichiers Python,
    `pytest` (1/1 passé), TOML et YAML tous deux parsés sans erreur
    (`tomllib`/`pyyaml`).
16. ~~Étudier la possibilité de devenir un plugin `extcap` pour
    Wireshark.~~ **Étude traitée le 27/08/2026** (voir section dédiée
    ci-dessus) — conclusion : techniquement proche de ce qui existe déjà
    (mode "fifo"), mais recommandation de ne **pas** remplacer
    l'application GTK actuelle ; wrapper extcap séparé et minimal
    envisageable si la demande se confirme. Aucun code écrit, tâche
    purement d'étude.

### Urgences

17. ~~**Priorité 000 — urgent.** Ne pas avoir besoin d'être root pour
    écouter une interface (mode utilisateur).~~ **Traité et vérifié
    empiriquement le 28/08/2026** (voir section dédiée ci-dessus,
    `switch-capture-taphelper`) : aide privilégiée `cap_net_admin+ep`
    (jamais setuid/root), câblée dans `switch_capture_core.py` et dans
    les 3 méthodes d'installation, testée de bout en bout en tant
    qu'utilisateur non-root réel sur chacune.
18. ~~**Priorité 0000 — urgent.** Le formulaire actuel ne permet pas de
    sélectionner entre `packet-capture`/SCP, mirroring-tunnel et
    `rpcap`.~~ **Traité et testé réellement le 28/08/2026** (voir
    section dédiée ci-dessus, « Sélection packet-capture / port
    mirroring dans le formulaire GUI ») : `rpcap` restait déjà
    sélectionnable comme `output_mode` du bloc packet-capture (voir
    « Sortie live », traité précédemment) ; c'est la sélection
    packet-capture ↔ mirroring-tunnel qui manquait entièrement à la
    GUI — désormais un dropdown « Type de capture » dédié, bloc
    mirroring complet (SPAN local / GRE distant), câblé sur
    `MirrorConfig`/`MirrorThread` déjà existants côté core. Plus aucun
    point marqué urgent dans cette liste.

### Collecte pytest bloquée par `gi.require_version()` sans filet (31/08/2026, 4e session du jour)

Tous les points numérotés de features.md étaient déjà clos en début de
session (seul restait ouvert le volet durée-SCP du point « Pas fait »
n°1, bloqué sans switch réel). Plutôt que fabriquer une tâche
artificielle, cette session traite la « remarque annexe, hors périmètre,
signalée pour arbitrage » notée en session du 29/08/2026 (voir
CLAUDE.md, section Ctrl+C/SIGINT) : `pytest.importorskip("gi")`, utilisé
par 6 fichiers (`test_gtk_sigint.py`, `test_gui_keepass_wiring.py`,
`test_install_guard_while_running.py`, `test_gui_preferences_window.py`,
`test_gui_new_fields.py`, `test_gui_mirroring.py`), protège contre
l'absence du module `gi` lui-même mais pas contre la combinaison précise
où `gi` est installé alors que le typelib `gir1.2-gtk-4.0` ne l'est
pas : chacun de ces fichiers enchaînait avec
`gi.require_version("Gtk", "4.0")` sans filet, ce qui lève un
`ValueError` non intercepté **à la collecte**, faisant échouer la suite
pytest dans son ensemble (`Interrupted: 6 errors during collection`,
**0 test exécutable**, y compris pour les 15 autres fichiers sans aucun
rapport avec GTK4).

C'est précisément cette combinaison qui s'est présentée dans le sandbox
de cette session (`gi`/PyGObject présent, typelib GTK4 absent) —
reproduite pour de vrai avant correctif, pas supposée. C'est aussi,
rétrospectivement, la raison exacte pour laquelle les 3 dernières
sessions (30/08 puis 31/08 ×2, voir CLAUDE.md) devaient invoquer pytest
avec une exclusion manuelle de ces mêmes fichiers (plus
`test_taphelper_end_to_end_as_real_nonroot_user`) pour obtenir une suite
exécutable — un contournement répété plutôt qu'un correctif.

**Correctif** : nouvelle fonction `require_gtk4()` centralisée dans
`tests/conftest.py` (import `gi`, `try`/`except ValueError` autour des
deux `gi.require_version()`, `pytest.skip(..., allow_module_level=True)`
en cas d'échec — le paramètre `allow_module_level` s'est révélé
nécessaire en cours de session : un premier essai sans lui lève une
`RuntimeError` explicite, puisque ces 6 fichiers appellent la fonction au
niveau module, avant toute fonction de test, exactement comme ils
appelaient `gi.require_version()` avant ce correctif). Les 6 fichiers
concernés remplacent leurs 3 lignes dupliquées
(`gi = pytest.importorskip("gi")` + 2×`gi.require_version(...)`) par
`from conftest import require_gtk4` + `gi = require_gtk4()` — centralisé
une seule fois plutôt que dupliqué, pour que tout futur fichier de test
GUI en bénéficie automatiquement.

**Vérifié réellement cette session** :

- Bug reproduit avant correctif (`pytest tests/` depuis `src/` :
  `Interrupted: 6 errors during collection`, 0 test exécuté), puis
  disparu après correctif.
- `python3 -m py_compile` OK sur les 7 fichiers modifiés
  (`tests/conftest.py` + les 6 fichiers de test).
- `ruff check --line-length 120`, comparé fichier par fichier à une copie
  pristine du zip d'entrée (`--no-cache` des deux côtés) : un premier jet
  introduisait 6 nouvelles erreurs `I001` (tri des imports, à cause d'une
  ligne vide superflue entre `import pytest` et
  `from conftest import require_gtk4`) — repéré par cette comparaison
  avant livraison, corrigé, re-vérifié : **exactement les 13 mêmes
  erreurs préexistantes sur ces 7 fichiers, aucune nouvelle**. Aucune
  ligne ajoutée ne dépasse 120 caractères (`awk 'length > 120'`).
- Suite complète rejouée **sans aucune exclusion manuelle** (`pytest
  tests/`, pour la première fois documentée dans ce dépôt sans
  `--ignore`/désélection des fichiers GTK4/`ip`) : **226 passés, 4
  échecs, 7 skips** (231 tests énumérés par `--collect-only` + 65
  fonctions de test réparties dans les 6 fichiers désormais sautés
  proprement au niveau module plutôt que de faire échouer la collecte —
  non énumérées individuellement par `--collect-only` puisque la collecte
  s'arrête au skip, mais bien comptées comme 6 skips de module par
  l'exécution réelle, plus le skip préexistant, déjà présent avant cette
  session, de `test_gvfs_env_workaround.py`). Les 4 échecs sont
  préexistants et sans rapport avec ce correctif : 3 dans
  `test_gvfs_env_workaround.py` (relance `switch_capture_gtk.py` dans un
  sous-processus réel, qui nécessite donc lui aussi un vrai typelib GTK4
  — absent ici) et 1 dans `test_tap_helper_nonroot.py`
  (`test_taphelper_end_to_end_as_real_nonroot_user`, `Permission denied`
  sur l'attachement TAP en tant qu'utilisateur non-root — la même
  limitation de capacité noyau propre à ce sandbox, déjà documentée à
  plusieurs reprises dans ce fichier, `iproute2` ayant dû être réinstallé
  en tout début de session comme plusieurs fois déjà par le passé).

**Reste ouvert** : rien de nouveau — toujours uniquement le volet
durée-SCP réelle du point « Pas fait » n°1 (switch physique requis) et la
relecture du `.po` `en_US` par une personne anglophone native. Point
d'attention pour une session future, noté ici pour mémoire plutôt que
comme tâche : un 7e fichier de test GTK4 qui appellerait directement
`gi.require_version(...)` sans passer par `require_gtk4()` réintroduirait
le même risque — rien ne l'empêche mécaniquement (pas de garde-fou du
type test dédié/lint custom), seule la convention documentée ici le
prévient.

### Filtrage ACL pour `switch-capture mirror` — core + CLI (01/09/2026, 2e session du jour)

Piste d'amélioration listée dans `CLAUDE.md` (« Pistes d'amélioration
envisagées, non implémentées »), traitée cette session côté core + CLI
(câblage GUI non fait, voir « Reste ouvert » ci-dessous) :
`switch-capture mirror --filter-mode acl` filtre désormais le mirroring
par une ACL avancée + politique QoS (`traffic classifier` + `traffic
behavior` + `qos policy`), au lieu de dupliquer tout un port comme le
mirroring-group existant (`--filter-mode port`, toujours le défaut,
comportement inchangé).

- `MirrorConfig` (`switch_capture_core.py`) : nouveaux champs
  `filter_mode` ("port"/"acl", défaut "port"), `acl_number` (3000 par
  défaut, validé 3000-3999 hors 3998/3999 — plage vérifiée contre la doc
  H3C « ACL commands »), `acl_rules` (règles ACL avancée complètes,
  envoyées telles quelles), `classifier_name`/`behavior_name`/
  `qos_policy_name` (optionnels, déduits de `group_id` si omis, ex.
  `SWCAP_CLS_1`). Validation `__post_init__` étendue en conséquence ; en
  mode "gre" + `filter_mode` "acl", `tunnel_ip` n'est plus exigé (pas
  d'interface Tunnel créée, l'encapsulation ERSPAN est inline dans le
  `mirror-to` — contrairement au mode "gre" historique).
- Deux nouvelles fonctions, sur le modèle de `configure_local_mirror`/
  `configure_gre_mirror`/`teardown_mirror` déjà existantes :
  `configure_acl_mirror()` (ACL avancée → traffic classifier → traffic
  behavior avec `mirror-to interface <if>` en local ou `mirror-to
  interface destination-ip <ip> source-ip <ip>` en ERSPAN → qos policy →
  application sur chaque interface source dans le(s) sens de
  `direction`) et `teardown_acl_mirror()` (ordre inverse requis par
  Comware : retire d'abord `qos apply policy` de chaque interface, puis
  la policy, le behavior, le classifier, l'ACL).
- Piège repris de la doc H3C (`CAPTURE-METHODS.md` section 4, vérifiée en
  session précédente du même jour) : `qos apply policy` ne prend jamais
  de mot-clé `both`, contrairement à `mirroring-group ... mirroring-port
  ... both` — une commande par sens, géré correctement par les deux
  nouvelles fonctions.
- `MirrorThread.run()` : dispatch vers `configure_acl_mirror`/
  `teardown_acl_mirror` quand `filter_mode == "acl"`, sinon comportement
  "port" inchangé.
- CLI : 6 nouvelles options (`--filter-mode {port,acl}`, `--acl-number`,
  `--acl-rule` répétable, `--classifier-name`, `--behavior-name`,
  `--qos-policy-name`), câblées automatiquement via
  `_MIRROR_CONFIG_FIELDS` (dérivé des champs du dataclass, aucun ajout
  manuel nécessaire côté `run_mirror`). Aide `--help` traduite en anglais
  comme le reste de la CLI (voir point 13) : 6 nouvelles chaînes + 2
  modifiées (aide de `mirror`/`--teardown`) ; `.pot`/`.po` `en_US`
  régénérés (136 chaînes traduites au total, 0 fuzzy, 0 non traduit),
  recompilés en `.mo`.
- Documentation : `CAPTURE-METHODS.md` section 4 n'est plus « non piloté
  par switch-capture » — nouvelle sous-section « Ce que fait
  switch-capture automatiquement » ajoutée sur le modèle des sections
  1-3, table de vue d'ensemble et section « Laquelle choisir ? » mises à
  jour en conséquence ; `USAGE.md` (tableau de référence des options
  `mirror` + nouvel exemple).

Vérifié réellement cette session :
- 32 nouveaux tests dédiés (`tests/test_mirror_acl_filter.py`), sur le
  modèle `FakeConn` de `test_inspect.py` (aucun test dédié n'existait
  jusqu'ici pour `configure_local_mirror`/`configure_gre_mirror`/
  `teardown_mirror` eux-mêmes — seul `test_gui_mirroring.py`, qui
  nécessite GTK4, couvrait indirectement le mirroring côté GUI) :
  validation complète de `MirrorConfig` (plage `acl_number`, noms par
  défaut/explicites, non-régression du mode "port"), séquence exacte de
  commandes de `configure_acl_mirror`/`teardown_acl_mirror` (local et
  GRE, direction both/inbound/outbound, plusieurs interfaces/règles ACL),
  et dispatch `MirrorThread` (`ConnectHandler` monkeypatché, jamais de
  connexion SSH réelle).
- Suite complète : **258 passés** (226 + les 32 nouveaux), toujours les 4
  mêmes échecs préexistants sans rapport (absence GTK4/typelib,
  restriction kernel non-root TAP) et 7 skips — 0 régression.
- `ruff check --line-length 120`, comparé fichier par fichier à une copie
  pristine du zip d'entrée (`--no-cache` des deux côtés, même méthode que
  les sessions précédentes) : exactement les mêmes 17 erreurs
  préexistantes sur `switch_capture_core.py`/`switch_capture_cli.py`,
  aucune nouvelle. Aucune ligne ajoutée ne dépasse 120 caractères
  (`awk 'length > 120'`).
- `py_compile` OK sur les 3 fichiers modifiés (`switch_capture_core.py`,
  `switch_capture_cli.py`, `tests/test_mirror_acl_filter.py`).
- `switch-capture -c mirror --help` comparé français (défaut) vs
  `LANGUAGE=en_US` : les 6 nouvelles options + les 2 aides modifiées
  s'affichent traduites et complètes dans les deux langues, `msgfmt
  --check` OK sur le `.po` final.

Non vérifié empiriquement (comme le reste du mirroring existant, section
3) : aucun switch réel disponible dans ce sandbox pour confirmer les
commandes contre un vrai Comware — seule la syntaxe, déjà vérifiée
contre la doc H3C officielle en session précédente du même jour
(`CAPTURE-METHODS.md` section 4), a été reprise ici.

**Reste ouvert** : câblage GUI de `--filter-mode acl` et des options
associées (`--acl-number`/`--acl-rule`/`--classifier-name`/
`--behavior-name`/`--qos-policy-name`) — non fait cette session, CLI
uniquement ; voir le formulaire GUI existant pour `--mode local/gre`
(section « Sélection packet-capture / port mirroring dans le formulaire
GUI », 28/08/2026) comme point de départ. Sans changement par ailleurs :
le volet durée-SCP réelle (« Pas fait » n°1, switch physique requis) et
la relecture du `.po` `en_US` par une personne anglophone native (8
entrées de plus depuis ce changement, jamais relues par un locuteur
natif comme le reste du fichier).

### Câblage GUI du filtrage ACL pour `switch-capture mirror` (02/09/2026)

Point laissé ouvert par la session précédente (ci-dessus, « Reste
ouvert ») : le bloc « Port mirroring » du formulaire GUI GTK4 permet
maintenant de choisir `filter_mode` (`port`/`acl`) et de renseigner les
champs associés, sur le modèle déjà suivi pour `--mode local/gre`
(section « Sélection packet-capture / port mirroring dans le formulaire
GUI », 28/08/2026).

- `switch_capture_gtk.py` : nouveau helper `_row_multiline()` (ligne de
  formulaire « une valeur par ligne », pas d'équivalent GTK4 simple pour
  une liste répétable façon `--acl-rule action="append"` côté CLI) et 6
  nouveaux champs dans le bloc mirroring — menu déroulant `mirror_filter_mode`
  (`port`/`acl`), spin `mirror_acl_number` (3000 par défaut), champ
  multi-lignes `mirror_acl_rules` (une règle ACL par ligne, avec un
  exemple affiché en hint sous le champ faute de `placeholder_text`
  natif sur `Gtk.TextView`), et 3 champs texte optionnels
  `mirror_classifier_name`/`mirror_behavior_name`/`mirror_qos_policy_name`.
- `_apply_mirror_mode_visibility()` étendue pour croiser `mode` et
  `filter_mode` plutôt que ne dépendre que de `mode` seul : en
  `filter_mode == "acl"`, `configure_acl_mirror()` (core) n'utilise que
  `tunnel_local_ip`/`remote_ip` et ne crée aucune interface Tunnel — les
  champs `mirror_tunnel_id`/`mirror_tunnel_ip`/`mirror_tunnel_mask`/
  `mirror_loopback_interface`, propres au mode `"gre"` **historique**
  (`filter_mode == "port"` seul), restent donc masqués même en mode
  `"gre"` dès que `filter_mode == "acl"`, pour ne pas laisser croire à
  l'utilisateur qu'ils sont pris en compte alors qu'ils seraient
  silencieusement ignorés côté switch. Vérifié à la fois par test et par
  capture d'écran réelle (voir plus bas).
- `_build_mirror_config()` : construit les 6 nouveaux champs, dont
  `acl_rules` à partir du buffer du `Gtk.TextView` (une ligne non vide =
  une règle, mêmes règles de nettoyage — `strip()`, lignes vides
  ignorées — que le découpage par virgules déjà utilisé pour
  `mirror_source_interfaces`).
- Choix délibéré : les nouveaux libellés/placeholders ne sont **pas**
  enveloppés dans `_()` (i18n, point 13), pour rester cohérents avec les
  ~15 champs déjà existants du même bloc « Port mirroring » (aucun n'est
  traduit, y compris le hint `hint_mirror` ajouté le 28/08/2026,
  antérieur à la session i18n du 31/08 mais jamais rattrapé) — traduire
  seulement les 6 nouveaux aurait introduit une incohérence visuelle à
  l'intérieur du même bloc plutôt que d'en réduire une. Un futur audit
  i18n dédié au bloc mirroring dans son ensemble reste possible mais
  hors du périmètre d'une tâche unique.

Vérifié réellement cette session :
- **9 nouveaux tests** dans `tests/test_gui_mirroring.py` (22 au total,
  tous passés) : présence des 6 nouvelles clés dans `MIRROR_KEYS`,
  visibilité croisée `mode`/`filter_mode` (dont le cas `mode="gre"` +
  `filter_mode="acl"` : `tunnel_local_ip`/`remote_ip` visibles,
  `tunnel_id`/`tunnel_ip`/`tunnel_mask`/`loopback_interface` masqués),
  construction de `MirrorConfig` en mode acl (local et gre), parsing
  `acl_rules` une règle par ligne avec lignes vides ignorées, noms
  classifier/behavior/qos_policy dérivés de `group_id` quand laissés
  vides puis correctement écrasés quand fournis, `ValueError` sur
  `acl_rules` manquant et sur `acl_number` invalide (3999, exclu).
- Suite complète : **335 passés, 2 échecs préexistants sans rapport, 0
  skip** (voir intro du fichier) — 0 régression.
- `ruff check --line-length 120`, fichier par fichier contre une copie
  pristine du zip d'entrée (`--no-cache` des deux côtés) : exactement
  les 6 mêmes erreurs préexistantes sur `switch_capture_gtk.py`, aucune
  nouvelle, seuls les numéros de ligne décalent. Aucune ligne ajoutée ne
  dépasse 120 caractères (`awk 'length > 120'`) ; `ruff format --check`
  signale le même unique bloc préexistant qu'avant modification (sans
  rapport avec cette session).
- `py_compile` OK sur `switch_capture_gtk.py`.
- Vérification visuelle par capture d'écran réelle (Xvfb `900x2200`,
  `xdotool`/`import` — voir « Environnement » ci-dessous) : formulaire en
  `mode="gre"` + `filter_mode="acl"`, tous les champs ACL affichés avec
  leurs valeurs de test, IP source/collecteur du tunnel toujours
  visibles, Tunnel ID/IP/masque/loopback correctement absents.

Non vérifié empiriquement (comme le reste du mirroring existant) :
aucun switch réel disponible dans ce sandbox — la config poussée dépend
entièrement de `configure_acl_mirror()` côté core, déjà couvert par ses
propres tests dédiés (session précédente).

**Reste ouvert** : sans changement — le volet durée-SCP réelle (« Pas
fait » n°1, switch physique requis) et la relecture du `.po` `en_US` par
une personne anglophone native.

### Relecture linguistique du `.po` `en_US` (02-03/09/2026)

Reprend le second volet laissé ouvert par les sessions précédentes
(ci-dessus, « Reste ouvert ») : relecture complète, entrée par entrée,
des 137 chaînes traduites de `src/locale/en_US/LC_MESSAGES/switch-capture.po`
(CLI `switch_capture_cli.py` + GUI `switch_capture_gtk.py`).

**Important, à ne pas perdre de vue pour une future session** : ceci
est une relecture par Claude (IA), pas par une personne anglophone
native humaine — le point « Reste ouvert » n'est donc **pas** clos,
seulement avancé. Cette relecture corrige des incohérences internes et
des tournures repérables sans ambiguïté, mais ne remplace pas un vrai
regard natif sur des nuances plus fines (registre, idiomatismes
propres à un anglais technique nord-américain vs britannique, etc.).

Deux catégories de corrections trouvées et appliquées, chacune vérifiée
en comparant systématiquement au `msgid` français source (pas seulement
au `msgstr` isolé) pour distinguer une vraie incohérence de traduction
d'un simple reflet fidèle d'une variation déjà présente dans le
français source :

- **États vides au singulier au lieu du pluriel** (5 occurrences) :
  `"No capture added yet."`, `"No capture to install."`,
  `"No capture."`, `"No capture running."`, `"No capture finished
  yet."` — la convention anglaise pour un état de liste vide est quasi
  systématiquement au pluriel (« No results », « No items », « No
  captures » plutôt que « No capture »), même quand le français source
  utilise le singulier après « aucune » (grammaire française normale,
  qui ne dicte pas la même règle côté anglais). Corrigées en
  `"No captures added yet."`, `"No captures to install."`,
  `"No captures."`, `"No captures running."`, `"No captures finished
  yet."`. Un 6e message très proche, `"No capture can start until this
  step is complete for all of them."`, **volontairement laissé
  inchangé** : il décrit une règle/contrainte générale (« pas une seule
  capture ne peut démarrer »), construction où le singulier reste
  naturel en anglais (parallèle à « No dog is allowed »), contrairement
  aux 5 précédents qui sont de simples états de liste vide.
- **Incohérence « e.g.: » vs « e.g. »** (3 occurrences sur 9 au total
  utilisant « e.g. ») : le français source utilise tantôt « ex: »
  (deux-points) tantôt « ex. » (point) pour introduire un exemple ; côté
  anglais, les 3 entrées issues d'un « ex: » à deux-points avaient été
  traduites tantôt en gardant le deux-points (« e.g.: »), tantôt en le
  perdant (« e.g. »), sans cohérence — un même « ex: » source donnant
  deux rendus différents. Un deux-points après « e.g. » est par ailleurs
  peu naturel en anglais (l'usage standard serait plutôt une virgule, «
  e.g., X », ou rien du tout). Standardisées sur la forme déjà
  majoritaire dans le fichier (« e.g. X », sans ponctuation
  intermédiaire), la plus proche de l'usage technique courant, plutôt
  que d'imposer la virgule partout (qui aurait demandé de toucher les 6
  entrées déjà correctes pour un gain marginal).
- Reste du fichier (dialogues, libellés de boutons, aide CLI
  `argparse`) relu intégralement sans trouver d'autre erreur ou
  incohérence claire — vocabulaire technique cohérent d'une entrée à
  l'autre (« mirroring », « capture », « template », « keyring »,
  « fallback »…), formulations naturelles, ponctuation de fin de phrase
  cohérente avec le français source.
- `PO-Revision-Date` mis à jour (30/08/2026 → 03/09/2026) pour
  refléter cette relecture, `Last-Translator` volontairement laissé à
  « Automatically generated » — reste vrai pour la génération initiale
  des chaînes, et changer cette ligne pourrait à tort laisser croire à
  une relecture humaine native.

Vérifié réellement cette session :
- `msgfmt --check` propre sur le `.po` modifié, `.mo` recompilé.
- Chargement réel des 8 traductions touchées via `gettext.translation()`
  (pas seulement une relecture visuelle du `.po`) : les 8 nouvelles
  valeurs anglaises confirmées correctes à l'exécution.
- **3 nouveaux cas** ajoutés à `test_known_strings_translate_to_english`
  (déjà existant, `tests/test_gtk_i18n_translations.py`) pour
  pérenniser ces corrections en test de non-régression, plutôt que de
  les laisser reposer uniquement sur une relecture ponctuelle — suit le
  même principe que la pérennisation de la vérification i18n en test
  automatisé le 31/08/2026 (voir CLAUDE.md, section dédiée).
- Suite complète : **338 passés (335 + 3 nouveaux), 2 échecs
  préexistants sans rapport, 0 skip** — 0 régression.
- `ruff check --line-length 120` et `py_compile` OK sur
  `tests/test_gtk_i18n_translations.py`.
- Les 10 cas déjà existants de `test_known_strings_translate_to_english`
  n'étaient touchés par aucune des 8 corrections (vérifié avant
  modification) — aucun risque de collision avec les assertions
  existantes.

**Reste ouvert** : le volet durée-SCP réelle (« Pas fait » n°1, switch
physique requis) — sans changement. La relecture par une personne
anglophone native humaine, elle, **avance** sans être **close** :
cette session a corrigé les incohérences détectables mécaniquement/
systématiquement, mais un regard humain natif sur les nuances fines de
formulation reste une chose que Claude ne peut pas garantir remplacer
entièrement.

### Mise à jour du README pour la 4e méthode de capture (03/09/2026)

`README.md` était resté à « Trois façons de récupérer du trafic depuis
un switch », sans aucune mention du flow mirroring filtré par ACL
(core+CLI le 01/09/2026, GUI le 02/09/2026) — repéré en cherchant une
tâche faisable après avoir confirmé que les 19 points numérotés sont
tous traités et que le seul autre volet ouvert (mesure SCP réelle)
nécessite un switch physique. `src/docs/CAPTURE-METHODS.md`, lui, était
déjà à jour (« quatre façons distinctes » depuis la session du
01/09/2026) — seul le `README.md`, point d'entrée du dépôt, n'avait
jamais été aligné.

- Titre de section : « Trois façons » → « Quatre façons de récupérer du
  trafic depuis un switch », intro complétée (« filtrage fin par ACL »
  ajouté à la liste des contextes qui justifient l'une ou l'autre
  méthode).
- Nouvelle sous-section « 4. Flow mirroring filtré par ACL —
  `switch-capture mirror --filter-mode acl` », même gabarit que les 3
  sections existantes (description courte + exemple de commande),
  reprenant la terminologie déjà établie dans `CAPTURE-METHODS.md`
  section 4 (`traffic classifier`/`traffic behavior`/`qos policy`).
- Section 2 (`packet-capture remote`) : « le plus simple des trois
  modes » → « des quatre méthodes » (comparaison numérique désormais
  fausse depuis l'ajout de la 4e méthode, corrigée par la même occasion).
- Tableau « Structure du dépôt » : description de `CAPTURE-METHODS.md`
  simplifiée de « comparaison des 3 méthodes de capture + flow
  mirroring QoS » (formulation bancale, ajout après coup) à
  « comparaison des 4 méthodes de capture ».
- Les 2 autres occurrences de « trois »/« Trois » dans le fichier
  (méthodes d'**installation** : script direct/`.deb`/`.rpm`) sont sans
  rapport avec les méthodes de capture — volontairement laissées
  inchangées, toujours exactement 3.

Vérifié réellement cette session :
- La commande d'exemple ajoutée (`switch-capture mirror --filter-mode
  acl --acl-number 3000 --acl-rule "rule 0 permit ip source 10.0.0.5 0"
  --source-interface GigabitEthernet1/0/1 --monitor-interface
  GigabitEthernet1/0/24`) parsée avec succès contre le vrai
  `build_arg_parser()` de `switch_capture_cli.py` (pas seulement relue
  visuellement) — un exemple non testé aurait été contraire à la
  rigueur du reste de ce dépôt.
- Suite complète (aucun fichier `.py` touché cette session, uniquement
  `README.md`) : **338 passés, 2 échecs préexistants sans rapport, 0
  skip** — identique à la session précédente, confirme l'absence
  d'impact.

**Reste ouvert** : sans changement — le volet durée-SCP réelle (« Pas
fait » n°1, switch physique requis) et la relecture du `.po` `en_US`
par une personne anglophone native humaine (avancée le 02-03/09/2026,
toujours pas close). Repéré au passage, mais volontairement non traité
cette session (tâche distincte, hors périmètre d'une tâche unique) :
23 alertes `ruff check` préexistantes sur `src/` (22 `BLE001` — capture
large `except Exception`, déjà repérées lors de sessions précédentes et
jamais corrigées, très probablement délibérées dans du code réseau/
threads d'arrière-plan/nettoyage où un `except Exception` généralisé
est le choix défensif normal plutôt qu'un oubli — et 1 `UP037`, un
type-hint entre guillemets `"PyKeePass"` devenu inutile depuis `from
__future__ import annotations`, celle-ci probablement sûre à corriger
en une ligne mais non faite pour rester concentré sur une seule tâche
cette session).

### Correctif `ruff` `UP037` sur `_open_keepass_db` (03/09/2026)

Reprend le point mineur repéré mais volontairement non traité par la
session précédente (ci-dessus, « Reste ouvert ») : sur les 23 alertes
`ruff check` préexistantes sur `src/`, une seule (`UP037`) était jugée
sûre à corriger sans risque — les 22 autres (`BLE001`, capture large
`except Exception`) restent volontairement intactes, très probablement
délibérées dans ce code réseau/threads d'arrière-plan/nettoyage.

`switch_capture_core.py:1483`, signature de `_open_keepass_db()` :
`-> "PyKeePass"` (type-hint entre guillemets) → `-> PyKeePass` (sans
guillemets). Guillemets devenus inutiles depuis l'ajout de `from
__future__ import annotations` en tête de fichier (ligne 11, présent
depuis bien avant cette session) : avec cet import, **toutes** les
annotations du module sont automatiquement stockées comme chaînes non
évaluées (PEP 563), donc les guillemets explicites sur `"PyKeePass"`
ne changeaient plus rien au comportement — juste du bruit visuel que
`ruff --fix` aurait de toute façon supprimé un jour.

Vérifié réellement cette session, avec un soin particulier car la
fonction touchée gère un cas où `PyKeePass` peut être `None` (import
optionnel, `pykeepass` non installé) :
- Import du module réussi dans les deux cas — avec et sans `pykeepass`
  installé (module réel absent simulé via un `builtins.__import__`
  intercepté, pas juste supposé) — `KEEPASS_AVAILABLE` correctement
  `True`/`False`, et `_open_keepass_db.__annotations__` strictement
  identique dans les deux cas (`{'return': 'PyKeePass', ...}`, chaîne
  non évaluée) : confirme que le retrait des guillemets ne change
  absolument rien à l'exécution, dans aucun des deux scénarios.
- `ruff check --line-length 120 --no-cache` comparé précisément (par
  code d'erreur, puis diff textuel filtré de la seule ligne concernée)
  à une copie pristine du zip d'entrée : 23 → 22 erreurs, exactement
  la disparition de l'unique `UP037`, les 22 `BLE001` restants
  byte-identiques (même fichiers, mêmes lignes, même message).
- `py_compile` OK.
- Suite complète : **338 passés, 2 échecs préexistants sans rapport, 0
  skip** — identique aux sessions précédentes.
- Les 40 tests spécifiquement liés à KeePass
  (`tests/test_keepass_password.py` + `tests/test_gui_keepass_wiring.py`,
  la fonction touchée étant directement utilisée par ces deux fichiers)
  relancés isolément par prudence supplémentaire : 40/40 passés.

**Reste ouvert** : sans changement — le volet durée-SCP réelle (« Pas
fait » n°1, switch physique requis) et la relecture du `.po` `en_US`
par une personne anglophone native humaine. Les 22 `BLE001` restants ne
sont **pas** un point ouvert au sens d'un travail à faire : ce sont des
`except Exception` très probablement volontaires (threads
d'arrière-plan, nettoyage, connexions réseau) qu'il serait risqué de
resserrer sans switch réel pour vérifier exhaustivement quels types
d'exceptions netmiko/paramiko/scp/pykeepass peuvent réellement survenir
à chaque site — les documenter ici pour mémoire plutôt que les
retraiter à l'aveugle dans une future session.

### Piste de capture distante : mirroring vers VLAN + VXLAN L2 sur switch 5520 HI (04-05/09/2026)

20. Signalé par l'utilisateur le 04/09/2026 : sur un switch 5520 (HI),
    il est possible de faire un `mirroring-group` vers un VLAN dédié
    (ex. VLAN 666), puis d'amener ce VLAN jusqu'au Linux de capture via
    du VXLAN L2. **Confirmé explicitement par l'utilisateur le
    05/09/2026** (« ce n'est pas officiel mais je t'impose la
    méthode ») : la combinaison n'existe pas comme exemple H3C officiel
    unique (voir recherche ci-dessous), mais l'utilisateur atteste de
    son fonctionnement réel de par sa pratique du matériel, et demande
    explicitement qu'elle soit retenue comme méthode valide malgré
    l'absence de documentation officielle combinée — traitée dès lors
    comme une source de vérité pour ce projet, au même titre qu'une
    doc H3C officielle l'aurait été. **Toujours pas implémentée en
    code** : la syntaxe exacte (numéros de VLAN/groupe/VSI/VNI/tunnel
    tels qu'utilisés concrètement) reste à obtenir de l'utilisateur
    avant d'écrire quoi que ce soit dans `MirrorConfig`/CLI/GUI — cette
    partie-là n'est pas remplacée par la confirmation de principe.

**Ce qui est confirmé indépendamment** (recherche menée le 04/09/2026,
deux mécanismes Comware bien documentés séparément — la combinaison des
deux, elle, n'a pas été retrouvée telle quelle dans un exemple officiel
unique, mais est désormais admise comme fonctionnelle sur la base de
l'attestation de l'utilisateur ci-dessus plutôt que d'une source
officielle) :

- Le mécanisme *remote-probe VLAN* (`mirroring-group remote-source` +
  `mirroring-group remote-probe vlan <id>` + port réflecteur) est
  documenté de longue date côté H3C (Comware historique, S3100 jusqu'aux
  séries actuelles) : le switch source recopie le trafic mirroré vers un
  port réflecteur, qui le réinjecte dans le VLAN sonde ; ce VLAN doit
  ensuite être « autorisé à traverser » les équipements intermédiaires
  jusqu'au switch de destination, qui compare le VLAN reçu au VLAN sonde
  configuré et ressort le trafic sur son port moniteur. Dans la
  documentation officielle H3C consultée, cette traversée « intermédiaire »
  est décrite comme un VLAN réellement trunké de proche en proche sur un
  réseau commuté L2 classique — pas nativement via un tunnel VXLAN.
- Le *VXLAN L2 gateway matériel* est une fonctionnalité documentée
  spécifiquement pour la gamme **5520 HI** (« VXLAN L2/L3 gateway support
  for up to 1024 unicast tunnels with 511 VXLAN/per tunnel », QuickSpecs
  HPE + guide dédié « HPE FlexNetwork 5520 HI Switch Series VXLAN
  Configuration Guide », référence 5200-8313) — **non retrouvée
  confirmée pour un 5520 non-HI** dans les sources consultées, à
  vérifier précisément sur le modèle exact utilisé avant de se fier à
  cette piste. Le modèle Comware général pour le VXLAN L2 (confirmé par
  ailleurs sur d'autres familles H3C/Comware) : une VSI (ou
  bridge-domain) associée à un VNI, une interface `Tunnel` en `mode
  vxlan` (source/destination en boucle locale) ou une interface `Nve`
  (mode multipoint avec `peer-list`), le VLAN local étant raccordé à la
  VSI via un `service-instance`/`encapsulation` sur le port ou
  directement par association VLAN↔VSI selon la plateforme.
- L'idée de l'utilisateur combine ces deux mécanismes : au lieu de
  trunker le VLAN sonde de proche en proche sur un réseau L2 classique
  (contrainte forte : adjacence L2 bout en bout), le lier localement à
  une VSI/VNI VXLAN pour l'acheminer par-dessus un réseau routé
  jusqu'au site de capture — architecturalement cohérent avec le
  fonctionnement de chaque brique prise séparément, mais à confirmer en
  pratique (comportement du switch quand un VLAN est à la fois « sonde
  de mirroring » et « raccordé à une VSI VXLAN », performance, MTU avec
  l'encapsulation VXLAN qui ajoute ~50 octets, etc.).
- Côté Linux (site de capture), rien de spécifique à switch-capture à
  développer pour la réception : le noyau Linux sait nativement créer
  une interface VXLAN (`ip link add vxlan666 type vxlan id <vni> dev
  <if> dstport 4789 ...`), sans que le switch distant ait besoin d'être
  du matériel spécial — Wireshark/tcpdump capture directement dessus
  comme une interface Ethernet ordinaire (le VLAN décapsulé, pas de
  dissection GRE/ERSPAN nécessaire côté capture, contrairement au mode
  `--mode gre` déjà implémenté).

**Intérêt potentiel par rapport à l'existant** (`--mode gre`,
encapsulation GRE/ERSPAN déjà implémentée) : le VXLAN utilise l'UDP
(port 4789 par défaut), souvent plus simple à laisser passer par des
pare-feux/NAT que le GRE brut (protocole IP 47, sans port) ; permettrait
en théorie d'agréger plusieurs groupes de mirroring vers le même VLAN
sonde et donc un seul tunnel VXLAN pour plusieurs sources ; et évite de
dépendre de la dissection ERSPAN-dans-GRE côté Wireshark. Inconvénient
principal : dépendance à une fonctionnalité matérielle a priori réservée
aux modèles « HI », donc moins portable que GRE (disponible plus
largement sur Comware) — à confirmer précisément sur le modèle exact de
l'utilisateur.

**Reste ouvert** : sans changement à la date du 05/09/2026 tel que noté
ci-dessus ; voir la section suivante pour l'implémentation core+CLI
réalisée juste après, une fois la syntaxe exacte fournie par
l'utilisateur.

### Implémentation core + CLI du mode `--mode vxlan` (05/09/2026)

Suite directe du point 20 ci-dessus : l'utilisateur a fourni la syntaxe
exacte manquante (VLAN 666 / groupe 10, vsi=`mirror` / vni=666, tunnel 0
mode vxlan, raccordement par `service-instance`), permettant de passer à
l'implémentation. Portée volontairement limitée à **core + CLI** cette
session — la GUI suivra dans une session ultérieure, exactement comme
pour le filtrage ACL (core+CLI le 01/09, GUI le 02/09).

**Ce qui a été fait** :

- `MirrorConfig` : nouveau `mode="vxlan"` (en plus de `"local"`/`"gre"`),
  5 nouveaux champs — `remote_probe_vlan`, `vsi_name`, `vxlan_vni`,
  `service_instance_id` (optionnel, déduit de `group_id` si omis, comme
  `classifier_name` et consorts en filter_mode acl), `reflector_interface`
  (obligatoire). Réutilise directement `group_id`/`tunnel_id`/
  `tunnel_local_ip`/`remote_ip`/`source_interfaces` déjà existants
  (mêmes concepts que pour `--mode gre`). Validation dédiée dans
  `__post_init__` : champs requis, `remote_probe_vlan` dans 1-4094,
  `vxlan_vni` dans 0-16777215 — piège repéré et corrigé en cours de
  session : un VLAN ou VNI valant `0` est une valeur légitime à valider
  (pas juste « absente »), la vérification « champ manquant » utilise
  donc `v is None or v == ""` plutôt que la simple troncature Python
  `not v` (qui aurait traité `0` comme manquant).
- `mode="vxlan"` **non combinable avec `filter_mode="acl"` pour
  l'instant** : refusé explicitement (`ValueError`) plutôt que
  silencieusement mal géré — les interactions entre les deux
  mécanismes n'ont pas été étudiées.
- `configure_vxlan_mirror()`/`teardown_vxlan_mirror()`, nouvelles
  fonctions dans `switch_capture_core.py`, même style que
  `configure_gre_mirror`/`configure_acl_mirror` (liste de commandes,
  `conn.send_command`, logs `debug`/`info`). Séquence : VLAN sonde → VSI
  + VNI → interface Tunnel en mode vxlan (source/destination) →
  raccordement tunnel↔VSI → `service-instance` sur le port réflecteur
  (VLAN↔VSI) → `mirroring-group` (remote-probe vlan + mirroring-port +
  reflector-port). Teardown dans l'ordre inverse, avec gestion de la
  confirmation « Continue? [Y/N] » sur `undo interface tunnel` (comme
  `teardown_mirror` en mode gre).
- `MirrorThread.run()` : nouvelle branche de dispatch pour
  `mode == "vxlan"`, configure et teardown.
- CLI : `--mode` accepte désormais `vxlan` ; 5 nouvelles options
  (`--remote-probe-vlan`, `--vsi-name`, `--vxlan-vni`,
  `--service-instance-id`, `--reflector-interface`). Câblage automatique
  via `_MIRROR_CONFIG_FIELDS` (dérivé de `dataclasses.fields`), aucune
  modification de `run_mirror` nécessaire — même mécanisme que pour
  l'ajout de l'ACL le 01/09.
- i18n CLI : les nouvelles/modifiées `help=` enveloppées dans `_(...)`
  comme le reste de la CLI (point 13). `xgettext --language=Python
  --from-code=UTF-8 -o locale/switch-capture.pot switch_capture_cli.py
  switch_capture_gtk.py` ré-exécuté depuis `src/` (même commande que les
  sessions précédentes) → 142 `msgid` contre 137 avant (5 entièrement
  nouvelles + 3 dont le texte source a changé). En-tête du `.pot`
  restauré à la main après extraction (comme d'habitude).
  `msgmerge --update --backup=none` sur le `.po` `en_US` existant : 6
  nouvelles entrées vides + 3 marquées `fuzzy` — les 9 traduites à la
  main en anglais (`polib`), flags `fuzzy` levés, `.mo` recompilé.
- `CAPTURE-METHODS.md` : nouvelle section 5, **explicitement marquée
  expérimentale** (bandeau d'avertissement en tête de section, ligne
  dédiée dans le tableau de vue d'ensemble avec ⚠️, entrée dans
  « Laquelle choisir ? ») — inclut la séquence de commandes équivalente
  à la main, la configuration côté collecteur Linux (`ip link add ...
  type vxlan`, hors périmètre de switch-capture, même philosophie que
  GRE/ACL) et la réponse à la question de l'utilisateur sur
  l'authentification : **VXLAN standard n'a aucune authentification ni
  chiffrement natifs** (RFC 7348, le VNI n'est qu'un identifiant de
  segment, pas un secret) — même posture que GRE/ERSPAN déjà en place,
  mitigation pratique par pare-feu/ACL réseau plutôt que par un
  mécanisme intégré à switch-capture.

**Vérifié réellement cette session** :

- Génération de la séquence de commandes exacte testée avec les
  paramètres **exacts** fournis par l'utilisateur (VLAN 666, groupe 10,
  vsi=mirror, vni=666, tunnel 0, service-instance) via un faux `conn`
  qui journalise chaque commande — séquence conforme à la conception.
- **26 nouveaux tests** dans `tests/test_mirror_vxlan.py` (validation
  complète de `MirrorConfig` en mode vxlan, séquence exacte de commandes
  pour configure/teardown, gestion de la confirmation Y/N, non-régression
  des modes local/gre existants) — tous passés.
- Suite complète : **364 passés (338 + 26 nouveaux), 2 échecs
  préexistants sans rapport, 0 skip** — 0 régression.
- `ruff check --line-length 120` sur `src/` : toujours 22 erreurs
  (les mêmes `BLE001` préexistants), aucune nouvelle. Aucune ligne
  ajoutée ne dépasse 120 caractères (vérifié précisément avec `awk`
  + `FNR`, pas `NR`, pour éviter un décompte faussé par la
  concaténation de plusieurs fichiers). `py_compile` OK sur les 2
  fichiers modifiés.
- `test_gtk_i18n_translations.py` (17 tests, complétude i18n **GUI**)
  toujours intégralement passé après régénération du `.pot`/`.po`/`.mo`
  — 3 nouveaux cas de non-régression ajoutés par la session précédente
  (« No captures. », « No captures running. », « e.g. lab-5130-client »)
  inchangés.
- `switch-capture mirror --help` (français et `LANGUAGE=en_US`) relu
  visuellement — rendu propre dans les deux langues, nouvelles options
  correctement documentées.

**Résultat** : `switch-capture mirror --mode vxlan` pilotable en CLI,
entièrement testé (hors switch réel), documenté dans
`CAPTURE-METHODS.md` avec ses réserves. `features.md` : point 20 mis à
jour, décompte de sessions incrémenté.

**Reste ouvert** :
- ~~**Câblage GUI**~~ — fait le 06/09/2026, voir section dédiée
  ci-dessous.
- **Jamais testé contre un switch réel** : toute la séquence de
  commandes reste une reconstruction best-effort (voir
  `CAPTURE-METHODS.md` section 5 et le docstring de
  `MirrorConfig.reflector_interface`) — à valider par l'utilisateur
  contre son 5520 HI avant tout déploiement en production. En
  particulier : le rôle exact du reflector port combiné au raccordement
  VSI n'a pas été confirmé indépendamment de la parole de l'utilisateur.
- Sans changement par ailleurs : le volet durée-SCP réelle (« Pas fait »
  n°1, switch physique requis) et la relecture du `.po` `en_US` par une
  personne anglophone native humaine.

### Câblage GUI du mode `--mode vxlan` (06/09/2026)

Suite directe de la section précédente : le menu déroulant `mirror_mode`
du formulaire GTK4 se limitait à `local`/`gre`, et les 5 champs du mode
vxlan n'avaient pas de widgets — même schéma que pour l'ACL (core+CLI le
01/09, GUI le 02/09).

**Ce qui a été fait** (`switch_capture_gtk.py`) :

- `self._mirror_mode_options` étendu à `("local", "gre", "vxlan")`, avec
  un libellé explicite dans le menu déroulant (« vxlan (VLAN sonde +
  VXLAN L2, expérimental — 5520 HI) »).
- 5 nouveaux champs de formulaire dans le bloc « Port mirroring » :
  `mirror_remote_probe_vlan` (`_row_spin`), `mirror_vsi_name` (`_row`),
  `mirror_vxlan_vni` (`_row_spin`, plage 0-16777215),
  `mirror_service_instance_id` (`_row`, optionnel), et
  `mirror_reflector_interface` (`_row`) — plus un label d'avertissement
  dédié (même style que le hint ACL/mirroring existant, non traduit
  comme le reste des hints du formulaire).
- `tunnel_local_ip`/`remote_ip` (déjà existants pour le mode gre) sont
  réutilisés tels quels pour vxlan — cohérent avec `MirrorConfig` côté
  core, qui exige ces deux champs pour `gre` **et** `vxlan`.
- `_apply_mirror_mode_visibility()` étendu avec un 3e cas : les 5
  nouveaux champs (+ le hint) ne s'affichent qu'en `mode == "vxlan" and
  filter_mode == "port"` — masqués en `filter_mode == "acl"` car cette
  combinaison est refusée côté core (`MirrorConfig.__post_init__` lève
  `ValueError`), même logique de masquage préventif que pour les champs
  spécifiques au mode `gre`.
- Construction de `MirrorConfig` dans le handler de soumission : les 5
  nouveaux champs lus et transmis (`service_instance_id` casté en `int`
  si renseigné, sinon `None` pour laisser le core déduire depuis
  `group_id` comme en filter_mode acl).
- Aucune modification côté core/CLI/i18n nécessaire — le câblage GUI
  réutilise intégralement ce qui existait déjà depuis la session du
  05/09/2026.

**Vérifié réellement cette session** :

- **7 nouveaux tests** dans `tests/test_gui_mirroring.py` (même style
  que les tests GUI ACL du 02/09) : affichage des champs vxlan +
  champs partagés avec gre en mode vxlan, masquage en mode
  local/gre, masquage quand `filter_mode == "acl"` est sélectionné en
  même temps que `mode == "vxlan"`, construction d'un `MirrorConfig`
  valide à partir du formulaire rempli, substitution de
  `service_instance_id` quand fourni, levée d'erreur sur champs
  requis manquants, levée d'erreur sur la combinaison vxlan+acl — tous
  passés.
- Suite complète (`pytest tests/`, Xvfb réel + GTK4 typelib) :
  **371 passés (364 + 7 nouveaux), 2 échecs préexistants sans rapport,
  0 skip** — 0 régression. Les 2 échecs identiques et sans rapport que
  d'habitude : `test_gvfs_env_workaround.py` et
  `test_taphelper_end_to_end_as_real_nonroot_user` (`ip`/iproute2
  absent de ce sandbox).
- `ruff check --line-length 120` sur `src/` : toujours 22 erreurs (les
  mêmes `BLE001` préexistants), aucune nouvelle.
- `tests/test_gtk_i18n_translations.py` (17 tests) toujours
  intégralement passé — les libellés de champs/hints du formulaire ne
  sont pas enveloppés dans `_(...)` dans ce fichier (convention déjà en
  place avant cette session, cf. `hint_mirror`/`hint_template` et tous
  les `_row*` existants), donc aucune nouvelle chaîne à traduire
  introduite par ce câblage GUI — pas de régénération `.pot`/`.po`/`.mo`
  nécessaire.
- `py_compile` OK sur `switch_capture_gtk.py`.

**Résultat** : `switch-capture mirror --mode vxlan` entièrement
pilotable depuis la GUI GTK4 (formulaire + visibilité conditionnelle),
en plus de la CLI. Les 4 méthodes de capture/mirroring (dont vxlan) sont
désormais toutes câblées CLI+GUI. `features.md` : point 20 mis à jour,
compteur de sessions incrémenté (43 → 44).

**Reste ouvert** : uniquement ce qui l'était déjà avant cette session —
**jamais testé contre un switch réel** (voir réserves détaillées dans la
section précédente et `CAPTURE-METHODS.md` section 5), le volet
durée-SCP réelle (« Pas fait » n°1, switch physique requis), et la
relecture du `.po` `en_US` par une personne anglophone native humaine.

### Correctif i18n GUI : 3 messages de dialogue oubliés (06/09/2026, 2e session du jour)

En reprenant la todo-list, aucune tâche nouvelle n'était faisable sans
switch réel ni relecture humaine native — seul un oubli a été repéré :
lors de la passe d'internationalisation de la GUI (point 13, 31/08/2026),
3 chaînes de messages de dialogue de `switch_capture_gtk.py` n'avaient
pas été enveloppées dans `_()`, contrairement à ce que documentait déjà
`features.md` (« choix de périmètre assumé » ne couvrait explicitement
que les f-strings du Journal et les corps `str(exc)` — pas ces 3-là,
statiques hormis un paramètre) :

- `"(défaut)"` dans le dialogue « Import terminé » (`_run_import_bin_async`).
- « Aucun modèle trouvé dans {dir}/. Utilisez d'abord « Enregistrer comme
  modèle ». » dans `_on_load_template`.
- « Une capture est déjà en cours ({count}). Arrêtez-la (page « Journal »)
  avant de lancer une nouvelle installation. » dans `_on_install_all`.

Les 3 chaînes ont été reformulées avec un paramètre nommé
(`.format(dir=...)`/`.format(count=...)`), sur le modèle déjà en place
pour `_("Inspection de {ip}")`. Piège repéré en cours de route : `_()`
imbriqué dans une f-string (`f"... {target_dir or _('(défaut)')}"`)
s'affiche correctement à l'exécution mais **n'est pas extrait par
`xgettext`** (contrairement à l'extraction par `ast` du test de
complétude, qui elle le voit) — corrigé en sortant l'appel `_()` de la
f-string (variable intermédiaire `target_label`).

Vérifié réellement cette session :
- `xgettext --language=Python --from-code=UTF-8 -o locale/switch-capture.pot
  switch_capture_cli.py switch_capture_gtk.py` (même commande que toutes
  les sessions i18n précédentes) → 144 `msgid` contre 142 avant, les 3
  nouvelles chaînes bien présentes (confirmé par comparaison `polib` des
  deux `.pot`, pas seulement un diff textuel).
- `msgmerge --update --backup=off` du `.po` `en_US` contre le nouveau
  `.pot` : 0 chaîne perdue, les 3 nouvelles ajoutées avec `msgstr`
  vide, traduites à la main en anglais, `msgfmt --check` OK.
- `msgfmt --statistics` : 144 traduites (142 + 3 nouvelles − 1 doublon
  de comptage) contre 141 sur le `.po` d'avant cette session — cohérent,
  aucune chaîne devenue vide.
- `python3 -m pytest tests/test_gtk_i18n_translations.py -v` : **17/17
  passés**, en particulier `test_every_gtk_source_string_is_translated`
  (qui aurait échoué sur les 3 chaînes manquantes si le `.mo` n'avait pas
  été régénéré).
- Suite complète (`pytest tests/ -q`, environnement de cette session sans
  GTK4/PyGObject réel — `import gi` échoue, donc `test_gui_*.py`
  auto-skippés comme prévu par leur garde existante) : **287 passés, 4
  échecs, 7 skips** — les 4 échecs, tous préexistants et sans rapport
  avec ce changement (`ip`/iproute2 absent de ce sandbox précis pour
  `test_gvfs_env_workaround.py`/`test_taphelper_end_to_end_as_real_
  nonroot_user` — `gvfs`/`iproute2` n'ont pas pu être installés cette
  session, dépôts miroir renvoyant des 404 sur plusieurs paquets requis).
  0 régression sur les 287 tests qui tournent dans cet environnement.
- `ruff check --line-length 120 src/` : exactement 22 erreurs des deux
  côtés (comparé fichier par fichier à une copie pristine du zip
  d'entrée), aucune nouvelle — et une ligne >120 caractères préexistante
  (l'une des 3 corrigées) a même disparu en reformattant sur plusieurs
  lignes.
- `py_compile switch_capture_gtk.py` : OK.

**Non vérifié empiriquement** : rendu visuel réel des 3 dialogues
corrigés (GTK4/PyGObject indisponible dans cet environnement, comme
pour une partie des sessions précédentes) — seule la fonction `_()` et
la génération des chaînes ont été exercées, pas l'affichage à l'écran.

**Reste ouvert** : inchangé par rapport à la session précédente — jamais
testé contre un switch réel, le volet durée-SCP réelle (« Pas fait »
n°1), la relecture du `.po` `en_US` par une personne anglophone native
humaine (désormais 3 entrées de plus jamais relues par un locuteur
natif, comme le reste du fichier), et les messages dynamiques du Journal
(f-strings avec IP/nom de capture) et corps de dialogues `str(exc)`,
qui restent un choix de périmètre assumé (voir point 13) plutôt qu'un
oubli — distinction désormais plus nette qu'avant cette session.

### Documentation : options `--mode vxlan` manquantes dans USAGE.md (06/09/2026, 3e session du jour)

En reprenant la todo-list une 3e fois dans la même journée, toujours
aucune tâche numérotée nouvelle faisable sans switch réel ni relecture
humaine native — recherche d'un oubli de documentation, sur le modèle
de la session du 03/09/2026 (README resté à « trois méthodes » après
l'ajout de la 4e). Trouvé : `src/docs/USAGE.md`, section « Sous-commandes
CLI », affirmait encore « quatre méthodes de capture » (sans citer le
mirroring VXLAN) et sa table « Référence des options — `mirror` » ne
documentait `--mode` que pour `local`/`gre` — aucune trace des 5
options propres à `--mode vxlan` (`--remote-probe-vlan`, `--vsi-name`,
`--vxlan-vni`, `--service-instance-id`, `--reflector-interface`), ni
d'exemple de commande, alors que ce mode est implémenté core+CLI depuis
le 05/09 et câblé en GUI depuis le 06/09. `README.md` et
`CAPTURE-METHODS.md`, eux, étaient déjà à jour (5 méthodes, section 5
dédiée) — seul `USAGE.md` n'avait pas suivi.

- « quatre méthodes » → « cinq méthodes » dans l'intro de la section
  sous-commandes, liste complétée avec le mirroring VXLAN.
- Table `mirror` : ligne `--mode` complétée avec `vxlan` ; nouvelles
  lignes pour les 5 options dédiées ; `--tunnel-local-ip`/`--remote-ip`
  reformulées « mode `gre` ou `vxlan` » (elles étaient déjà partagées
  par les deux modes côté CLI, juste non documentées comme telles).
- Nouvelle sous-section d'exemple « Mirroring vers VLAN sonde + VXLAN L2
  (⚠️ expérimental) », même gabarit que les 3 exemples `mirror`
  existants, renvoyant vers `CAPTURE-METHODS.md` section 5 pour le
  détail de la config poussée et la commande `ip link add ... type
  vxlan` côté collecteur.

Vérifié réellement cette session :
- La commande d'exemple ajoutée (`switch-capture mirror --mode vxlan
  --group-id 10 --source-interface GigabitEthernet1/0/1
  --remote-probe-vlan 666 --vsi-name mirror --vxlan-vni 666
  --reflector-interface GigabitEthernet1/0/2 --tunnel-local-ip
  10.0.0.1 --remote-ip 203.0.113.10`) parsée avec succès contre le vrai
  `build_arg_parser()` de `switch_capture_cli.py`, tous les attributs
  vérifiés (`mode`, `vsi_name`, `vxlan_vni`, `reflector_interface`) —
  pas seulement relue.
- Suite complète (aucun fichier `.py` touché cette session, uniquement
  `src/docs/USAGE.md`) : **287 passés, 4 échecs préexistants sans
  rapport, 7 skips** — identique à la session précédente, confirme
  l'absence d'impact.

**Reste ouvert** : sans changement — le volet durée-SCP réelle (« Pas
fait » n°1, switch physique requis), la relecture du `.po` `en_US` par
une personne anglophone native humaine, et les messages dynamiques du
Journal/`str(exc)` restant un choix de périmètre assumé (point 13).

### Documentation : sous-commande `analyze-pacing` absente de USAGE.md (06/09/2026, 4e session du jour)

En reprenant la todo-list une 4e fois dans la même journée, toujours
aucune tâche numérotée nouvelle faisable sans switch réel ni relecture
humaine native — recherche élargie à l'ensemble du dépôt (pas seulement
au nombre de méthodes de capture, déjà vérifié cohérent partout ce
tour-ci : README/CAPTURE-METHODS/USAGE tous à « cinq méthodes »).
Trouvé : la sous-commande `analyze-pacing` (`switch_capture_cli.py`,
ajoutée le 31/08/2026 — voir « Pas fait » n°1 et CLAUDE.md, section
dédiée) n'apparaissait nulle part dans `USAGE.md` ni `README.md` : ni
dans la liste des sous-commandes, ni dans les commandes `--help`
citées, ni en table d'options, ni en exemple — alors qu'elle est
entièrement implémentée, testée (12 tests dédiés) et déjà internationalisée
(CLI+GUI). Un utilisateur lisant uniquement `USAGE.md` n'aurait aucun
moyen de savoir que cette sous-commande existe.

- Intro « Sous-commandes CLI » complétée avec `analyze-pacing` et sa
  description courte ; `switch-capture -c analyze-pacing --help` ajouté
  à la liste des commandes d'aide intégrée.
- Nouvelle section « Référence des options — `analyze-pacing` » (même
  gabarit que les 3 tables d'options existantes), précisant que cette
  sous-commande ne se connecte à aucun switch (arguments uniquement).
- Nouvel exemple « Analyser le lissage TAP sur un `.pcap` déjà
  rapatrié », juste après l'exemple `inspect` existant.

Vérifié réellement cette session :
- La commande d'exemple ajoutée (`switch-capture analyze-pacing
  capture_2026-09-01.pcap --candidate-max-gap 1 --candidate-max-gap 2
  --candidate-max-gap 5`) parsée avec succès contre le vrai
  `build_arg_parser()` de `switch_capture_cli.py`, `pcap_file` et
  `candidate_max_gaps` vérifiés — pas seulement relue.
- Suite complète (aucun fichier `.py` touché cette session, uniquement
  `src/docs/USAGE.md`) : **287 passés, 4 échecs préexistants sans
  rapport, 7 skips** — identique aux 2e et 3e sessions du jour, confirme
  l'absence d'impact.

**Reste ouvert** : sans changement — le volet durée-SCP réelle (« Pas
fait » n°1, switch physique requis), la relecture du `.po` `en_US` par
une personne anglophone native humaine, et les messages dynamiques du
Journal/`str(exc)` restant un choix de périmètre assumé (point 13).

### Complétude de `config.yaml.example` : 3 réglages Config non documentés (06/09/2026, 5e session du jour)

En reprenant la todo-list une 5e fois dans la même journée, toujours
aucune tâche numérotée nouvelle faisable sans switch réel ni relecture
humaine native — recherche élargie à la cohérence documentaire de
l'ensemble du dépôt, sur le modèle des 3 sessions précédentes du jour.
Trouvé : `src/docs/config.yaml.example` ne documentait pas 3 champs
`Config` bien réels — `hide_capture_traffic`, `tap_pace_playback`,
`tap_pace_max_gap_seconds` — pourtant câblés en CLI et en GUI depuis
fin août 2026 (voir sections dédiées ci-dessus) et documentés dans le
docstring de `Config`. Un 4e champ, `packet_capture_cmd`, est bien
absent lui aussi mais **délibérément** : sans flag CLI ni docstring
utilisateur ni case GUI, c'est un champ interne muté par
`inspect_switch()`, pas un réglage à présenter à côté des autres.

- 3 nouvelles entrées commentées ajoutées à `config.yaml.example`, même
  style que l'existant (`hide_capture_traffic` près de
  `capture_filter` ; `tap_pace_playback`/`tap_pace_max_gap_seconds`
  dans le bloc `tap_*` déjà présent).
- Nouveau `tests/test_config_example_completeness.py` (3 tests) :
  compare automatiquement les `dest=` du sous-parseur CLI `capture`
  (introspection réelle de `build_arg_parser()`) aux champs de `Config`
  et au contenu de l'exemple, pour détecter ce type d'oubli
  automatiquement à l'avenir — même logique que
  `tests/test_gtk_i18n_translations.py` (31/08/2026). `packet_capture_cmd`
  explicitement exclu de la vérification, avec un test dédié qui
  échouerait si ce champ gagnait un jour un vrai flag CLI (voir
  CLAUDE.md, section dédiée, pour le détail du raisonnement).

Vérifié réellement cette session : le nouveau test échoue bien sur la
version d'origine de `config.yaml.example` (3 clés listées comme
manquantes), passe après le correctif ; `ruff check`/`ruff format
--line-length 120` sur le nouveau fichier de test (0 erreur après un
reformatage) ; `ruff check --line-length 120 src/` toujours à 22
erreurs (aucun `.py` de `src/` touché) ; contenu YAML actif de
l'exemple revérifié analysable par `yaml.safe_load` une fois les
commentaires retirés. Suite complète : **290 passés** (287 + 3
nouveaux), **4 échecs préexistants sans rapport, 7 skips** — identique
aux 2e/3e/4e sessions du jour. Voir CLAUDE.md, section dédiée, pour le
détail complet.

**Reste ouvert** : sans changement — le volet durée-SCP réelle (« Pas
fait » n°1, switch physique requis), la relecture du `.po` `en_US` par
une personne anglophone native humaine, et les messages dynamiques du
Journal/`str(exc)` restant un choix de périmètre assumé (point 13).

### Documentation : 3 flags `capture` absents de la table de référence USAGE.md (06/09/2026, 6e session du jour)

En reprenant la todo-list une 6e fois dans la même journée, toujours
aucune tâche numérotée nouvelle faisable sans switch réel ni relecture
humaine native. Recherche élargie une nouvelle fois à la cohérence
documentaire, cette fois sur `USAGE.md` lui-même plutôt que
`config.yaml.example` (traité la session précédente).

Trouvé, en comparant systématiquement les `dest=`/flags réels de
`_add_common_config_args` (`switch_capture_cli.py`) à la table
« Référence des options — `capture` / `uninstall` » de `USAGE.md` :
`--no-hide-capture-traffic`, `--tap-pace-playback` et
`--tap-pace-max-gap` sont des flags CLI bien réels (câblés en GUI
depuis fin août 2026, et déjà documentés dans `config.yaml.example`
depuis la session précédente), mais n'apparaissaient dans **aucune**
section de `USAGE.md` — ni dans la table de référence, ni ailleurs
(seul `--tap-pace-max-gap` était mentionné en passant dans le contexte
de `analyze-pacing`, sans jamais expliquer ce que fait le flag
lui-même côté `capture`). Un utilisateur parcourant la table de
référence n'avait aucun moyen de savoir que ces 3 options existent.

Différence de nature relevée avant correctif, comme pour
`packet_capture_cmd` la session précédente : le trio
`--remember-password`/`--forget-password`/`--keepass-path` est lui
aussi absent de cette table, mais **délibérément** — il est déjà
documenté en détail dans une section dédiée (« Mémoriser le mot de
passe SSH entre deux lancements »), donc pas un oubli à corriger.

#### Ce qui a été fait

- 3 nouvelles lignes dans la table de référence `capture`/`uninstall`
  de `USAGE.md` : `--no-hide-capture-traffic` (juste après
  `--capture-filter`, même emplacement logique que
  `hide_capture_traffic` dans `config.yaml.example`) et
  `--tap-pace-playback`/`--tap-pace-max-gap` (dans le bloc `--tap-*`
  existant, juste après `--tap-launch-wireshark`), reprenant les
  défauts et la portée déjà décrits dans le `help=` CLI.
- Nouveau fichier `tests/test_usage_md_completeness.py` (2 tests) :
  compare automatiquement les flags longs du sous-parseur CLI
  `capture` (introspection réelle de `build_arg_parser()`, pas une
  liste recopiée à la main) au contenu de la table de référence de
  `USAGE.md`, même logique que
  `tests/test_config_example_completeness.py` (session précédente)
  pour que ce type d'oubli soit détecté par la suite pytest plutôt que
  par une relecture manuelle ponctuelle. Le trio
  `remember-password`/`forget-password`/`keepass-path` est exclu
  explicitement (documenté ailleurs), avec un test dédié qui
  vérifierait que ces flags existent toujours côté CLI si l'exclusion
  devenait un jour fausse.

#### Vérifié réellement cette session

- Le nouveau test de complétude vérifié dans les deux sens : version
  d'origine de `USAGE.md` (celle du zip d'entrée, table sans les 3
  lignes) restaurée temporairement → échec confirmé, listant
  exactement les 3 flags manquants (`--no-hide-capture-traffic`,
  `--tap-pace-max-gap`, `--tap-pace-playback`) ; version corrigée
  réappliquée → passe.
- `ruff format --line-length 120` : 1 ligne reformatée dans le nouveau
  fichier de test (condensation d'une compréhension multi-ligne) ;
  `ruff check --line-length 120 --no-cache` : 0 erreur sur le nouveau
  fichier ; `ruff check --line-length 120 --no-cache src/` : toujours
  exactement 22 erreurs préexistantes (`USAGE.md` n'est pas du Python,
  aucun fichier `.py` de `src/` touché cette session).
- Suite complète : **292 passés** (290 + 2 nouveaux), **4 échecs
  préexistants sans rapport, 7 skips** — identique aux 2e/3e/4e/5e
  sessions du jour pour la cause des 4 échecs et des 7 skips.
  Environnement inchangé : GTK4/PyGObject absent (`test_gui_*.py`
  auto-skippés), `ip`/iproute2 et `gvfs` toujours non installables
  (dépôts miroir en 404).

#### Résultat

`src/docs/USAGE.md` documente désormais, dans sa table de référence
rapide, tous les flags CLI de `capture`/`uninstall` sauf le trio
mot-de-passe/KeePass (déjà documenté ailleurs en détail, exclusion
assumée et vérifiée par test). `features.md` : nouvelle sous-section
datée, compteur de sessions incrémenté (48 → 49).

#### Reste ouvert

Inchangé par rapport aux sessions précédentes du jour : jamais testé
contre un switch réel, le volet durée-SCP réelle (« Pas fait » n°1,
switch physique requis), la relecture du `.po` `en_US` par une
personne anglophone native humaine, et les messages dynamiques du
Journal/corps `str(exc)` qui restent un choix de périmètre assumé
(point 13) plutôt qu'un oubli.

### Documentation/bug : exemple `-v` mal placé dans `USAGE.md` (07/09/2026)

En reprenant la todo-list le lendemain de la 6e et dernière session du
06/09/2026, toujours aucune tâche numérotée nouvelle faisable sans
switch réel ni relecture humaine native (6 sessions la veille, même
constat à chaque fois — aucune évolution entre-temps). Recherche
élargie une nouvelle fois à la cohérence documentaire, cette fois en
comparant *empiriquement* — pas seulement en relisant — chaque flag CLI
réel de **toutes** les sous-commandes (`capture`, `uninstall`,
`mirror`, `inspect`, `analyze-pacing`, `import-bin`, par introspection
de `build_arg_parser()`) au contenu de `USAGE.md`.

Trouvé : l'exemple « Config de base + surcharge ponctuelle du filtre »
de `USAGE.md` plaçait `-v` *après* `capture` :
`switch-capture capture --config ... --capture-filter "..." -v`. Or
`-v`/`--verbose` est déclaré sur le parseur racine
(`switch_capture_cli.build_arg_parser`), *avant* `add_subparsers()` —
donc utilisable uniquement avant le nom de la sous-commande. Copié/collé
tel quel, cet exemple échoue réellement avec
`switch-capture: error: unrecognized arguments: -v`, vérifié
empiriquement (`parser.parse_args(...)`, pas une supposition) — et pas
seulement pour `capture` : la même contrainte de placement vérifiée pour
les 6 sous-commandes (`-v` avant : succès systématique ; `-v` après :
échec systématique, même message d'erreur). Différent des bugs
documentaires des sessions précédentes (des flags absents d'une
table) : ici, l'exemple existant était activement incorrect, pas
seulement incomplet.

- Exemple corrigé dans `USAGE.md` (`-v` déplacé avant `capture`).
- Note ajoutée juste après « Aide intégrée » expliquant que `-v` est une
  option globale à placer avant la sous-commande, valable pour les 6
  sous-commandes, avec le message d'erreur exact si mal placée ; rappel
  ajouté dans la table de référence `capture`/`uninstall` (seule table
  où `-v` apparaît, pour ne pas dupliquer la même ligne dans les 3
  autres tables).
- Nouveau `tests/test_cli_verbose_flag_position.py` (15 tests) :
  verrouille `-v` avant/après pour les 6 sous-commandes (paramétré), et
  rejoue l'exemple corrigé directement depuis le contenu actuel de
  `USAGE.md` (extraction du bloc `` ```bash `` par recherche de texte,
  pas une copie codée en dur qui pourrait diverger du fichier réel) —
  même logique que `tests/test_usage_md_completeness.py`/
  `tests/test_config_example_completeness.py` des sessions précédentes.

Vérifié réellement cette session : les 2 nouveaux tests visant
spécifiquement l'exemple cassé et la note explicative échouent bien
contre la version d'origine de `USAGE.md` (restaurée temporairement :
`-v` après `capture` → `SystemExit: 2`/`unrecognized arguments: -v`
confirmé ; note retirée → assertion sur sa présence confirmée en échec),
passent de nouveau après réapplication du correctif. `ruff format
--line-length 120` sur le nouveau fichier de test : 1 reformatage
(listes d'arguments condensées éclatées une ligne par élément),
revérifié propre ensuite ; `ruff check --line-length 120 --no-cache` : 0
erreur. `ruff check --line-length 120 --no-cache src/` : toujours
exactement 22 erreurs préexistantes (aucun fichier `.py` de `src/`
touché cette session). Suite complète : **307 passés** (292 + 15
nouveaux), **4 échecs préexistants sans rapport, 7 skips** — identique
aux 6 sessions de la veille (06/09/2026) pour la cause des 4 échecs et des 7
skips. Repéré au passage, sans rapport avec cette session et non
corrigé (hors périmètre) : `ruff check --line-length 120 --no-cache
tests/` (l'ensemble du dossier, pas seulement le nouveau fichier)
remonte 27 erreurs préexistantes réparties sur d'autres fichiers plus
anciens — 13 `RUF100`, 7 `C408`, 5 `PLW1510`, 1 `I001`, 1 `F401` —
mentionné ici pour mémoire plutôt que découvert en silence par une
session future.

**Reste ouvert** : sans changement par rapport aux 6 sessions de la
veille (06/09/2026) — le volet durée-SCP réelle (« Pas fait » n°1, switch physique
requis), la relecture du `.po` `en_US` par une personne anglophone
native humaine, et les messages dynamiques du Journal/`str(exc)`
restant un choix de périmètre assumé (point 13). Nouveau celui-ci : les
tables de référence `mirror`/`inspect`/`analyze-pacing` n'ont,
contrairement à `capture`/`uninstall`, aucun test de complétude
automatisé comparable à `tests/test_usage_md_completeness.py` (qui ne
couvre que `capture`/`uninstall`) — vérifiées manuellement complètes
cette session (comparaison systématique par introspection, voir
ci-dessus), mais sans garde-fou automatisé contre un futur oubli. Les 27
erreurs `ruff check` préexistantes de `tests/` dans son ensemble (voir
ci-dessus) ne sont pas non plus corrigées.

### Documentation : 3 flags `inspect` absents de la table de référence USAGE.md (07/09/2026, 2e session du jour)

En reprenant la todo-list dans la foulée de la session précédente du
même jour (correctif `-v`), qui avait explicitement laissé ouvert le
constat suivant en « Reste ouvert » : les tables de référence
`mirror`/`inspect`/`analyze-pacing` de `USAGE.md`, contrairement à
`capture`/`uninstall`, n'ont aucun test de complétude automatisé
comparable à `tests/test_usage_md_completeness.py` — seulement
« vérifiées manuellement complètes » par introspection ponctuelle.
Reprise de cette introspection empirique (`build_arg_parser()`, pas une
relecture) pour les 3 tables restantes.

Résultat : la table `mirror` (26 flags) et la table `analyze-pacing` (2
options, dont l'argument positionnel) sont bien complètes. La table
`inspect`, en revanche, ne l'était **pas** : `--remember-password`,
`--forget-password` et `--keepass-path` sont des flags CLI réels de
`inspect_parser` (mécanismes identiques à `capture`, vérifiés
fonctionnels — `build_inspect_config` résout `keepass_path`/appelle
`_maybe_fill_password_from_keyring`, `run_inspect` appelle
`_apply_password_keyring_actions`), mais étaient absents de la table
« Référence des options — `inspect` » — un utilisateur voulant
mémoriser ou oublier un mot de passe SSH pour `inspect` (dry run,
souvent le tout premier contact avec un switch) n'avait aucun moyen de
le découvrir sans lire le `--help` ou le code.

- 3 lignes ajoutées à la table `inspect` de `USAGE.md` (mêmes
  libellés que dans le `--help` réel de la sous-commande).
- `tests/test_usage_md_completeness.py` étendu (pas un nouveau
  fichier) : `_inspect_flags()`/`_inspect_subparser()` par
  introspection de `build_arg_parser()`, et
  `test_reference_table_documents_every_inspect_flag` sur le même
  principe que le test `capture` déjà existant (délimitation de la
  table par recherche de texte entre les deux titres `##` encadrants,
  pas une copie codée en dur qui pourrait diverger du fichier réel).

Vérifié réellement cette session : le nouveau test échoue bien contre
la version d'origine de `USAGE.md` (3 lignes retirées temporairement →
`AssertionError: Flag(s) CLI de \`inspect\` absents de la table de
référence USAGE.md : ['--forget-password', '--keepass-path',
'--remember-password']` confirmé), passe de nouveau après
réapplication du correctif. `ruff format --line-length 120` sur
`tests/test_usage_md_completeness.py` et `src/docs/USAGE.md` : aucun
reformatage nécessaire ; `ruff check --line-length 120 --no-cache
tests/test_usage_md_completeness.py` : 0 erreur. Suite complète :
**308 passés** (307 + 1 nouveau), **4 échecs préexistants sans
rapport, 7 skips** — identique aux sessions précédentes pour la cause
des 4 échecs et des 7 skips. Aucun fichier `.py` de `src/` touché
cette session. `features.md` : nouvelle sous-section datée, compteur
de sessions incrémenté (49 → 50).

**Reste ouvert** : sans changement par rapport à la session
précédente — le volet durée-SCP réelle (« Pas fait » n°1, switch
physique requis), la relecture du `.po` `en_US` par une personne
anglophone native humaine, les messages dynamiques du Journal/`str(exc)`
restant un choix de périmètre assumé (point 13), et les 27 erreurs
`ruff check` préexistantes de `tests/` dans son ensemble (non
corrigées, hors périmètre de cette session). Le point flagué comme
« reste ouvert » par la session précédente (absence de garde-fou
automatisé pour `mirror`/`inspect`/`analyze-pacing`) est désormais
traité pour les 3 tables : `capture`/`uninstall` et `inspect` ont
chacune leur test dédié dans `test_usage_md_completeness.py` ;
`mirror` et `analyze-pacing` ont été vérifiées complètes par la même
introspection mais n'ont pas (encore) de test dédié équivalent — elles
n'ont simplement révélé aucun trou cette fois-ci, contrairement à
`inspect`.

### Tests de complétude automatisés pour les tables `mirror` et `analyze-pacing` de USAGE.md (07/09/2026, 4e session du jour)

Point explicitement laissé en « Reste ouvert » par la session
précédente du même jour (vérification `display packet-capture status`
au mode dry run) : `mirror` et `analyze-pacing` avaient été vérifiées
complètes par introspection ponctuelle (`build_arg_parser()`), sans le
garde-fou automatisé équivalent à celui de `capture`/`inspect` dans
`tests/test_usage_md_completeness.py` — un futur oubli sur l'une de ces
deux tables ne serait donc pas détecté automatiquement.

- `tests/test_usage_md_completeness.py` étendu (pas un nouveau fichier) :
  `_mirror_subparser()`/`_mirror_flags()` et
  `test_reference_table_documents_every_mirror_flag` sur le même
  principe que `capture`/`inspect` (tous les flags de `mirror` sont des
  `--xxx`, aucune exclusion nécessaire) ; `_analyze_pacing_subparser()`/
  `_analyze_pacing_flags()` et
  `test_reference_table_documents_every_analyze_pacing_flag`, avec une
  nuance : l'argument positionnel `pcap_file` (sans `--`) est documenté
  par son nom nu dans la table, géré séparément des options `--xxx`
  longues plutôt qu'exclu comme `--config`/`--verbose` le sont pour
  `capture`.
- Les deux tests **passent dès maintenant** : aucun nouveau trou trouvé
  dans `USAGE.md` (confirme la vérification manuelle de la session
  précédente), l'apport est le verrouillage automatique pour l'avenir,
  pas une correction de documentation.

Vérifié réellement cette session (pas seulement relu) : les deux
nouveaux tests, retestés dans les deux sens — une ligne retirée
temporairement de chaque table (`--teardown` pour `mirror`,
`--candidate-max-gap` pour `analyze-pacing`) fait échouer le test
correspondant avec le message d'erreur attendu (liste du flag manquant),
réapplication du contenu d'origine → passe de nouveau. `ruff format
--line-length 120` et `ruff check --line-length 120 --no-cache` sur
`tests/test_usage_md_completeness.py` : aucun reformatage nécessaire, 0
erreur (les 27 erreurs `ruff check` préexistantes de `tests/` dans son
ensemble, elles, restent inchangées — vérifié par comparaison avant/après
sur l'ensemble du dossier). `py_compile` sur le fichier modifié. Suite
complète comparée avant/après dans ce même sandbox : **313 passés → 315
passés** (+2, les deux nouveaux tests), **5 échecs et 7 skips
identiques avant et après** — échecs préexistants et sans rapport avec
ce changement (`ip`/iproute2 absent, backend `keyring` indisponible ici ;
GTK4/PyGObject entièrement absent dans ce sandbox précis, contrairement
à d'autres sessions où seul le typelib manquait). Aucun fichier `.py` de
`src/` touché cette session, uniquement `tests/test_usage_md_completeness.py`.

**Résultat** : `capture`/`uninstall`, `inspect`, `mirror` et
`analyze-pacing` disposent désormais chacune d'un test de complétude
automatisé dédié dans `tests/test_usage_md_completeness.py` — les 4
tables de référence de `USAGE.md` sont couvertes, plus aucune ne dépend
d'une relecture manuelle pour rester synchronisée avec la CLI réelle.
`features.md` : nouvelle sous-section datée, compteur de sessions
incrémenté (51 → 52).

**Reste ouvert** : inchangé sur le fond par rapport aux sessions
précédentes — le volet durée-SCP réelle (« Pas fait » n°1, switch
physique requis) reste la seule chose bloquée par l'absence de switch
réel ; la relecture du `.po` `en_US` par une personne anglophone native
humaine ; les messages dynamiques du Journal/`str(exc)` (choix de
périmètre assumé, point 13) ; les 27 erreurs `ruff check` préexistantes
de `tests/` dans son ensemble (non corrigées, hors périmètre) ; la
disponibilité réelle de `packet-capture remote` (rpcap) selon
modèle/version, dont seul le moyen de vérification a changé (voir
« Autres limites connues » ci-dessous), pas la limite elle-même.

### Correctif : 3 tests `test_gvfs_env_workaround.py` échouaient au lieu de sauter proprement sans typelib GTK4 (08/09/2026)

Point mineur laissé explicitement ouvert par la session précédente
(voir CLAUDE.md, dernière ligne de la section « Tests de complétude
automatisés... ») : `test_gvfs_env_workaround.py::TestSwitchCaptureGtkModule`
(3 tests) importe directement `switch_capture_gtk.py`, module qui fait
un `gi.require_version("Gtk", "4.0")` **inconditionnel** dès son import
(contrairement à `src/switch-capture`, dont `_gtk_available()` avale
l'exception) — sans typelib GTK4, le sous-processus lancé par `_probe()`
se terminait donc avec un code de retour non nul, faisant échouer
franchement ces 3 tests (`assert result.returncode == 0`) plutôt que de
les sauter proprement, contrairement aux 6 fichiers `test_gui_*.py`/
`test_gtk_sigint.py`/`test_install_guard_while_running.py` déjà protégés
par `conftest.require_gtk4()` (31/08/2026, voir section « Collecte
pytest bloquée par `gi.require_version()` sans filet » ci-dessus).

**Pourquoi `require_gtk4()` n'a pas pu être réutilisé tel quel** : cette
fonction est conçue pour un `pytest.skip(..., allow_module_level=True)`
au niveau du **module entier**, appelée en tête de fichier — adaptée aux
6 fichiers ci-dessus qui ne contiennent que des tests nécessitant GTK4.
Ce n'est pas le cas de `test_gvfs_env_workaround.py` : `TestEntrypointScript`
(3 tests) et `TestGvfsRemoteVolumeMonitorWarningGone` (1 test, déjà
protégé par son propre skip ad hoc) n'ont besoin ni l'un ni l'autre de
GTK4 — les sauter aussi aurait réduit la couverture réelle du fichier
sans raison.

**Correctif** : nouvelle fonction `_gtk4_typelib_available()` (locale à
ce fichier, même principe que `require_gtk4()` mais sans le
`allow_module_level` — un simple `bool`) + décorateur
`@pytest.mark.skipif(...)` posé sur la classe `TestSwitchCaptureGtkModule`
uniquement, pour ne sauter que ces 3 tests précis et laisser les 4
autres tests du fichier s'exécuter normalement.

**Vérifié réellement cette session** :
- Bug reproduit avant correctif : `python3 -m pytest
  tests/test_gvfs_env_workaround.py -v` → **3 failed, 3 passed, 1
  skipped**, les 3 échecs exactement ceux de `TestSwitchCaptureGtkModule`,
  avec le traceback `ValueError: Namespace Gtk not available` remonté
  depuis le sous-processus (typelib `gir1.2-gtk-4.0` absent de ce
  sandbox, confirmé indépendamment par `python3 -c "import gi;
  gi.require_version('Gtk', '4.0')"`).
- Après correctif, même commande : **3 passed, 4 skipped** — les 3 tests
  ciblés sautent proprement (`SKIPPED`), les 4 autres (dont le skip ad
  hoc préexistant de `TestGvfsRemoteVolumeMonitorWarningGone`) inchangés.
- `ruff check --line-length 120 --no-cache` sur le fichier modifié,
  comparé précisément à une copie pristine du zip d'entrée : exactement
  les 5 mêmes erreurs préexistantes (`PLW1510`, absence de `check=`
  explicite sur des `subprocess.run` non touchés par ce changement),
  aucune nouvelle ; `ruff format --line-length 120 --check` : déjà
  formaté, aucun changement nécessaire. `ruff check --line-length 120
  --no-cache src/ tests/` : toujours **49** erreurs au total (22 `src/`
  + 27 `tests/`, inchangé — ce correctif ne change aucun compte, il
  transforme des échecs francs en skips propres, pas des erreurs de
  style).
- `py_compile` OK sur le fichier modifié.
- Suite complète rejouée (`pytest tests/ -q`, dépendances installées en
  début de session — `loguru`/`netmiko`/`paramiko`/`scp`/`keyring`/
  `pykeepass` absents au départ, réseau pip disponible) : **316 passés,
  1 échec préexistant sans rapport, 10 skips** (contre 315 passés/5
  échecs/7 skips la session précédente dans un sandbox différent —
  l'écart de décompte entre sessions reste dû à l'environnement, pas au
  code, comme documenté de longue date dans ce fichier). L'unique échec
  restant, `test_taphelper_end_to_end_as_real_nonroot_user`
  (`tests/test_tap_helper_nonroot.py`), est préexistant et sans rapport :
  `ip`/iproute2 absent de ce sandbox précis (`FileNotFoundError: [Errno
  2] No such file or directory: 'ip'`), même limitation déjà documentée
  à plusieurs reprises dans ce fichier.

**Résultat** : les 3 faux échecs disparaissent (deviennent des skips
propres) sans réduire la couverture réelle du fichier — `TestEntrypointScript`
et `TestGvfsRemoteVolumeMonitorWarningGone` continuent de s'exécuter
normalement, avec ou sans GTK4 disponible. `features.md` : nouvelle
sous-section datée, compteur de sessions incrémenté (52 → 53).

**Reste ouvert** : sans changement — le volet durée-SCP réelle (« Pas
fait » n°1, switch physique requis) reste la seule chose bloquée par
l'absence de switch réel ; la relecture du `.po` `en_US` par une
personne anglophone native humaine ; les messages dynamiques du
Journal/`str(exc)` (choix de périmètre assumé, point 13) ; les 27
erreurs `ruff check` préexistantes de `tests/` dans son ensemble (non
corrigées, hors périmètre — ce correctif n'en a supprimé aucune,
`PLW1510` n'était pas dans la liste des erreurs corrigées ici) ; la
disponibilité réelle de `packet-capture remote` (rpcap) selon
modèle/version.

### Couverture de tests ajoutée pour le transfert SCP (08/09/2026, 2e session du jour)

Constat de départ : plus aucun item numéroté de la todo-list n'est
faisable dans ce sandbox (voir « Suivi des sessions » ci-dessous — seule
la mesure de durée SCP contre un switch réel reste ouverte). À la demande
explicite de l'utilisateur, tâche hors-liste choisie parmi plusieurs
proposées : renforcer la couverture de tests sur une zone non testée,
plutôt qu'inventer un faux item de todo-list.

Recherche exhaustive (noms de fonctions + `sshd`/`paramiko`/`SSHClient`
dans tout `tests/`) : six fonctions de `switch_capture_core.py`
n'apparaissaient dans **aucun** fichier de test persistant —
`open_scp_ssh_client`, `scp_get`, `scp_put`, `list_remote_pcap_files`,
`delete_remote_file`, `delete_remote_all_file_capture` — malgré les
mentions de vérifications « réelles contre un `sshd` local » lors de la
correction du 23/08/2026 (voir section dédiée plus haut, « Transfert de
fichiers »). Ces vérifications historiques n'ont manifestement jamais
laissé de test persistant dans ce dépôt.

**Nouveau fichier `tests/test_scp_transfer.py`, 15 tests** :

- `open_scp_ssh_client` (2 tests) : lève `RuntimeError` si
  paramiko/scp absents (`paramiko`/`SCPClient` à `None`) ; paramètres de
  connexion exacts sinon (`timeout=15`, `look_for_keys=False`,
  `allow_agent=False`, `AutoAddPolicy`) — via un remplacement in-memory
  des globals `paramiko`/`SCPClient` du module (`FakeSSHClient`), pas de
  vraie connexion TCP.
- `scp_get`/`scp_put` (4 tests) : `SCPClient` construit à partir de
  `ssh_client.get_transport()`, utilisé comme context manager (fermeture
  garantie), chemin local converti en `str` ; non-régression explicite
  des deux bugs corrigés le 23/08/2026 (absence de préfixe `flash:` côté
  SCP, une connexion `SCPClient` dédiée par appel plutôt que réutilisée).
- `list_remote_pcap_files` (3 tests) : commande `dir flash:/<prefix>*.pcap`
  envoyée telle quelle, parsing correct (dernier token des lignes finissant
  par `.pcap`, `startup.cfg` ignoré, tri alphabétique/chronologique),
  liste vide si aucune correspondance.
- `delete_remote_file` (3 tests) : commande `delete flash:/<fichier>`,
  confirmation automatique (`y`) uniquement si le switch la demande
  (`Continue?`/`[Y/N]`), aucun `y` parasite sinon.
- `delete_remote_all_file_capture` (3 tests) : suppression de chaque
  fichier listé, no-op si liste vide, absorption silencieuse d'un échec
  de listing (`try/except Exception` déjà présent dans le code) sans
  remonter l'exception à l'appelant.

Comme pour `test_inspect.py`, la couche netmiko est simulée par un
`FakeConn` maison (`send_command`/`send_command_timing` journalisés) ; la
couche paramiko/scp par un remplacement in-memory des deux globals du
module, jamais par un vrai réseau. **Ne remplace pas** une vérification
contre un vrai `sshd`/switch — seul un filet de non-régression qui
n'existait pas avant cette session : un renommage de paramètre, une
inversion get/put, un oubli de retrait du préfixe `flash:` ou une
régression sur le ré-armement de connexion feraient désormais échouer un
test au lieu de passer inaperçus.

`openssh-server` non installable dans ce sandbox précis cette fois
(dépôt `security.ubuntu.com` renvoyant des 404 sur les paquets requis au
moment de cette session — encore une variation d'environnement d'une
session à l'autre, comme documenté de longue date dans ce fichier),
confirmant que l'approche mockée était la seule possible ici.

Vérifié réellement cette session :
- `pytest tests/test_scp_transfer.py -v` : **15 passés**.
- Suite complète : **331 passés (316 + 15), 1 échec préexistant sans
  rapport (`ip`/iproute2 absent, même cause que la session précédente),
  10 skips inchangés** — 0 régression.
- `ruff check --line-length 120 tests/test_scp_transfer.py` : 0 erreur
  (4 corrigées en cours d'écriture : tri d'imports, import inutilisé,
  annotation de type entre guillemets superflue, valeur par défaut
  mutable en attribut de classe).
- `ruff format --line-length 120 --check` : conforme.
- `py_compile` OK.

**Reste ouvert** : sans changement — le volet durée-SCP réelle (« Pas
fait » n°1, switch physique requis) reste la seule chose bloquée par
l'absence de switch réel ; la relecture du `.po` `en_US` par une personne
anglophone native humaine ; les messages dynamiques du Journal/`str(exc)`
(choix de périmètre assumé, point 13) ; la disponibilité réelle de
`packet-capture remote` (rpcap) selon modèle/version. `detect_model`,
`detect_software_version`, `resolve_feature_bin`, `write_capture_metadata`,
`SetupAndCaptureThread` et `format_pacing_analysis_report` restent, eux
aussi, sans test persistant dans ce dépôt — repérés lors de la même
recherche exhaustive que ci-dessus, mais volontairement laissés hors
périmètre de cette session (portée délibérément limitée à la couche de
transfert SCP) : candidats pour une prochaine session de renforcement de
couverture.

### Suivi des sessions

Sessions de développement datées déjà réalisées sur ce projet (voir
horodatage des sous-sections de « Fait, et testé réellement » ci-dessus) :
**51** — 3 le 23/08, 4 le 24/08, 3 le 25/08, 8 le 26/08/2026, 2 le
27/08/2026 (l'étude de faisabilité extcap, puis le repli KeePass), 6 le
28/08/2026 (câblage GUI de `hide_capture_traffic`/`capture_direction`/
`archive_as_pcapng`/`tap_launch_wireshark`, puis garde-fou installation
pendant une capture en cours — point 7, puis mode non-root — point 17,
puis sélection packet-capture/mirroring en GUI — point 18, puis câblage
GUI du repli KeePass, puis diagnostic/correctif des bugs GVFS/GOA — points
8/9/11/12), 4 le 29/08/2026 (menu hamburger + page Préférences — point 1,
entièrement traité ; puis Ctrl+C/SIGINT câblé et écrit — point 10, non
vérifié empiriquement à ce stade ; puis vérification empirique de ce même
correctif dans une 3e session du jour — point 10 entièrement clos, voir
section dédiée ci-dessus ; puis squelette de projet futur — point 15,
entièrement traité, 4e session du jour, voir CLAUDE.md), 1 le 30/08/2026
(i18n CLI — point 13, câblage `gettext` + `.pot`/`.po` en_US, GUI restant
ouvert), 4 le 31/08/2026 (i18n GUI GTK4 — point 13 désormais entièrement
clos, CLI+GUI ; puis analyse des écarts de lissage TAP —
`analyze_pacing_gaps`/`switch-capture analyze-pacing`, volet analyse du
point « Pas fait » n°1 désormais couvert ; puis pérennisation en test
automatisé de la vérification i18n GUI —
`tests/test_gtk_i18n_translations.py`, 3e session du jour ; puis
correctif de la collecte pytest bloquée par `gi.require_version()` sans
filet — `tests/conftest.py::require_gtk4()`, voir section dédiée
ci-dessus, 4e session du jour), 2 le 01/09/2026 (documentation flow
mirroring QoS vérifiée contre la doc H3C et ajoutée à
`CAPTURE-METHODS.md` section 4, session sans développement ; puis
filtrage ACL pour `switch-capture mirror` — core + CLI, voir section
dédiée ci-dessus, 2e session du jour), 2 le 02/09/2026 (câblage GUI du
filtrage ACL pour `switch-capture mirror`, voir section dédiée
ci-dessus — point « Reste ouvert » de la session précédente désormais
clos ; puis relecture linguistique du `.po` `en_US` — voir section
dédiée ci-dessus, avancée mais volontairement pas déclarée close, 2e
session du jour), 2 le 03/09/2026 (mise à jour du `README.md` pour la
4e méthode de capture, voir section dédiée ci-dessus ; puis correctif
`ruff` `UP037` sur `_open_keepass_db`, voir section dédiée ci-dessus,
2e session du jour), 1 le 04/09/2026 (piste de capture distante par
mirroring vers VLAN + VXLAN L2 sur switch 5520 HI, signalée par
l'utilisateur, recherche H3C/HPE menée et documentée — voir section
dédiée ci-dessus, pas de code écrit, matériel réel nécessaire avant
implémentation), 1 le 05/09/2026 (implémentation core + CLI de
`switch-capture mirror --mode vxlan`, syntaxe exacte fournie par
l'utilisateur suite à sa confirmation du 04/09 — voir section dédiée
ci-dessus, GUI restant à câbler dans une session ultérieure), 1 le
06/09/2026 (câblage GUI du mode `--mode vxlan` — voir section dédiée
ci-dessus, point « Reste ouvert » de la session précédente désormais
clos), 1 le 06/09/2026, 2e session du jour (correctif i18n GUI — 3
messages de dialogue oubliés lors du câblage initial, voir section
dédiée ci-dessus ; GTK4/PyGObject **absent** cette fois, `iproute2`/
`gvfs` non installables — dépôts miroir renvoyant des 404 sur plusieurs
paquets requis — donc `test_gui_*.py` auto-skippés et 4 échecs
préexistants sans rapport laissés en l'état), 1 le 06/09/2026, 3e
session du jour (documentation `USAGE.md` complétée pour `--mode
vxlan` — table d'options et exemple manquants depuis leur câblage GUI
plus tôt le même jour, voir section dédiée ci-dessus ; même environnement
que la session précédente, aucune réinstallation), 1 le 06/09/2026, 4e
session du jour (documentation `USAGE.md` complétée pour la
sous-commande `analyze-pacing`, absente depuis son ajout le 31/08/2026
— voir section dédiée ci-dessus ; même environnement que les sessions
précédentes du jour, aucune réinstallation), 1 le 06/09/2026, 5e
session du jour (complétude de `config.yaml.example` —
`hide_capture_traffic`/`tap_pace_playback`/`tap_pace_max_gap_seconds`
ajoutés, `packet_capture_cmd` délibérément exclu, plus test de
non-régression associé, voir section dédiée ci-dessus ; même
environnement que les sessions précédentes du jour, aucune
réinstallation), 1 le 06/09/2026, 6e session du jour (documentation
`USAGE.md` complétée pour la table de référence `capture`/`uninstall` —
3 flags manquants, `--no-hide-capture-traffic`/`--tap-pace-playback`/
`--tap-pace-max-gap`, plus nouveau
`tests/test_usage_md_completeness.py`, voir section dédiée ci-dessus ;
même environnement que les sessions précédentes du jour, aucune
réinstallation), 1 le 07/09/2026 (le lendemain — exemple `-v`
mal placé — après `capture` au lieu d'avant — corrigé dans `USAGE.md`,
note ajoutée sur ce comportement global du parseur, plus nouveau
`tests/test_cli_verbose_flag_position.py`, voir section dédiée
ci-dessus ; même environnement que la veille, aucune réinstallation),
1 le 08/09/2026 (correctif des 3 tests `test_gvfs_env_workaround.py`
qui échouaient franchement, au lieu de sauter proprement, sans typelib
GTK4 — voir section dédiée ci-dessus), 1 le 08/09/2026, 2e session du
jour (plus aucun item numéroté faisable dans ce sandbox restant, tâche
hors-liste choisie par l'utilisateur : nouveau fichier
`tests/test_scp_transfer.py`, +15 tests couvrant `open_scp_ssh_client`/
`scp_get`/`scp_put`/`list_remote_pcap_files`/`delete_remote_file`/
`delete_remote_all_file_capture`, jusque-là sans aucun test persistant
malgré des vérifications réelles historiques non conservées en test —
voir section dédiée ci-dessus ; même environnement que la session
précédente du jour),
plus le socle initial non daté (3
méthodes de capture, CLI, GUI 5 pages, packaging × 3, journalisation,
tests).
Environnement retrouvé le 28/08/2026 (GTK4/PyGObject, Xvfb, `ip`/iproute2,
accès pip/apt) pour les deux premières sessions du jour ; **absent**
(GTK4/PyGObject) pour la troisième (mode non-root), qui disposait en
revanche de `gcc`/`setcap`, absents des sessions précédentes ; **de
nouveau présent** (GTK4/PyGObject, Xvfb, apt) pour la quatrième et la
cinquième ; et **de nouveau présent, cette fois avec en plus `gcc`/
`setcap`/`iproute2`/accès réseau complet simultanément** pour la
sixième (bugs GVFS/GOA). Première session du 29/08/2026 (Préférences) :
GTK4/PyGObject présent mais `iproute2`/`gvfs`/
`pytest`/`ruff`/`keyring`/`pykeepass`/`netmiko`/`paramiko`/`scp`/`loguru`
tous **absents au tout début**, installés en cours de session — **confirme
une nouvelle fois** qu'il ne faut pas supposer qu'un environnement
constaté persiste d'une session à l'autre, y compris au sein d'une même
journée, dans les deux sens, et qu'un échec de test isolé peut tenir
entièrement à l'environnement du sandbox plutôt qu'au code. Fait nouveau
cette fois : le test TAP non-root a **dérivé au sein même de cette
session** — 3 passages réussis puis échec stable ensuite, sans aucun
changement de code entre les deux — la variabilité d'environnement de ce
sandbox ne se limite donc pas à l'écart entre deux sessions distinctes.
**Deuxième session du 29/08/2026** (Ctrl+C/SIGINT, voir section dédiée
ci-dessus pour le détail) : environnement le plus contraint rencontré à
ce jour — **réseau totalement désactivé** (une première ; toutes les
sessions précédentes avaient eu au moins un accès partiel), donc aucun
paquet manquant installable ; `pytest`/`ruff`/`loguru`/`netmiko`/
`paramiko`/`scp`/`keyring`/`pykeepass` tous absents et restés absents ;
PyGObject présent mais **sans son typelib GTK4** (`gir1.2-gtk-4.0`),
combinaison inédite (jusque-là toujours présents ou absents ensemble) —
aucun des trois fichiers source principaux n'était donc importable,
suite `pytest` non exécutable. Confirme, une fois de plus, qu'un
environnement constaté ne présage en rien de celui de la session
suivante, y compris au sein de la même journée.
**Troisième session du 29/08/2026** (vérification empirique Ctrl+C/SIGINT,
voir CLAUDE.md, « Vérification empirique du fix Ctrl+C/SIGINT ») :
typelib GTK4 de nouveau absent au démarrage (même symptôme que la
session précédente), mais réseau apt/pip cette fois disponible — tout
réinstallé en début de session avec succès. Piège d'infrastructure
notable, propre à ce sandbox et sans lien avec le code du projet : des
démons lancés en arrière-plan simple (`&` sans `setsid`) ne survivent pas
d'un appel d'outil au suivant ici, ce qui a d'abord fait échouer
silencieusement toute tentative d'affichage GTK (`Gtk.init_check()`
retournait pourtant `True`) — corrigé en relançant Xvfb/dbus/gnome-keyring
avec `setsid ... < /dev/null &`, vérifié stable avant de poursuivre. Une
fois résolu : suite complète exécutée avec succès, **270/270**, y compris
`test_gtk_sigint.py` pour la toute première fois.
**Deuxième session du 01/09/2026** (filtrage ACL pour `switch-capture
mirror`, voir section dédiée ci-dessus) : `xgettext`/`msgfmt`/`msgmerge`
(paquet `gettext`), `ruff`, `pytest` et `polib` tous **absents au tout
début**, installés en cours de session (`apt-get install gettext` +
`pip install`, réseau apt/pip disponible) — GTK4/PyGObject **sans son
typelib** au départ, sans impact ici (tâche core + CLI uniquement,
aucune des trois vérifications de cette session ne nécessitait
GTK4). Confirme une fois de plus qu'un environnement constaté ne
présage en rien de celui de la session suivante.
**Session du 02/09/2026** (câblage GUI du filtrage ACL, voir section
dédiée ci-dessus) : GTK4/PyGObject sans typelib, `pytest`/`ruff`/
`gettext`/`Xvfb`/`gnome-keyring`/`dbus-x11`/`xdotool`/`imagemagick`/
`loguru`/`netmiko`/`paramiko`/`scp`/`keyring`/`pykeepass` tous absents
au départ, réseau apt/pip disponible, tout installé en cours de
session sans incident. `ip`/iproute2 absent (comme la 2e session du
01/09). Piège d'infrastructure inédit rencontré et documenté ici pour
la première fois : avec `keyring` installé **et** une vraie session
D-Bus active (`dbus-launch`) mais sans démon secret service réellement
lancé dessus (`gnome-keyring-daemon` installé mais pas démarré), le
backend `SecretService` de `keyring` (via `jeepney`) bloque
indéfiniment sur son premier appel plutôt que d'échouer proprement —
`tests/test_inspect.py::test_run_inspect_invalid_config_returns_2`
(entre autres) restait bloqué sans jamais lever ni retourner. Sans
rapport avec le code applicatif : les tests eux-mêmes ne nécessitent
aucun trousseau système réel (voir `requirements-dev.txt`). Contourné
en ne positionnant **pas** `DBUS_SESSION_BUS_ADDRESS` pour les
lancements `pytest`/le script de capture d'écran — seuls `DISPLAY`/
`GDK_BACKEND=x11` suffisent pour GTK4 (juste un avertissement bus
d'accessibilité inoffensif) ; **si une future session doit vraiment
tester le repli KeePass/trousseau contre un vrai bus D-Bus, prévoir de
lancer `gnome-keyring-daemon --start --components=secrets` dessus au
préalable plutôt que de se contenter de `dbus-launch` seul.** Autre
piège déjà documenté le 29/08 mais reconfirmé : la résolution Xvfb par
défaut (1280x1024) est trop basse pour capturer tout le formulaire
« Nouvelle capture » sans scroller (formulaire ~1500px de haut) — une
résolution plus haute (`900x2200` cette session) est nécessaire pour
une capture d'écran complète en un seul cliché.
**Session du 03/09/2026** (relecture linguistique du `.po` `en_US`,
voir section dédiée ci-dessus — 2e session du 02/09/2026 au sens du
travail effectué, mais horodatée 03/09/2026 côté outillage réel de ce
sandbox) : `gettext`/`msgfmt` absents au tout début, réinstallés sans
incident (réseau apt disponible). GTK4/PyGObject **avec** typelib
présent d'entrée cette fois, mais Xvfb **non persistant** entre deux
échanges de cette session (le process lancé en fin d'échange précédent
n'était plus vivant au début de celui-ci, contrairement à ce qu'observé
lors de sessions antérieures avec `setsid ... < /dev/null &`) — relancé
simplement (`Xvfb :99 ... &` + `sleep 2`), sans quoi la suite retombait
silencieusement à des dizaines de tests **skip** (au lieu d'échouer
franchement) faute d'affichage réel, un mode de défaillance à surveiller
en début de toute future session avant de faire confiance à un
« 0 skip » resté d'une session précédente. Confirme une fois de plus
qu'un environnement constaté à un instant T (y compris au sein d'une
même session) ne garantit rien pour l'instant suivant.
**2e session du 03/09/2026** (mise à jour du `README.md`, voir section
dédiée ci-dessus) : même piège Xvfb qu'un peu plus tôt dans la journée,
reconfirmé — non persistant d'un échange à l'autre, revérifié
(`Gtk.init_check()`) avant de faire tourner la suite. GTK4/PyGObject
avec typelib présent d'entrée. Session sans code touché (uniquement
`README.md`), donc peu d'occasion de rencontrer un piège
d'infrastructure nouveau — mentionné ici surtout pour confirmer, une
session de plus, que le symptôme Xvfb décrit juste au-dessus n'est pas
un incident isolé.
**3e session du 03/09/2026** (correctif `ruff` `UP037`, voir section
dédiée ci-dessus) : environnement stable et déjà en place depuis les 2
sessions précédentes du jour (GTK4/PyGObject avec typelib, Xvfb,
`ruff`, `pytest`), aucune réinstallation nécessaire — juste Xvfb
revérifié (`Gtk.init_check()`) par prudence avant la suite complète,
comme désormais systématique. Rien de nouveau à signaler côté
infrastructure.
**Session du 04/09/2026** (piste VXLAN L2 + mirroring VLAN, voir
section dédiée ci-dessus) : session purement documentaire, uniquement
`web_search` (documentation officielle H3C/HPE en ligne) — aucun outil
du sandbox lui-même sollicité (pas de Python, pas de GTK4, pas de
pytest), donc rien à signaler côté environnement.
**Session du 05/09/2026** (implémentation core + CLI de `--mode vxlan`,
voir section dédiée ci-dessus) : GTK4/PyGObject avec typelib, Xvfb,
`ruff`, `pytest`, `gettext` tous déjà en place depuis les sessions
précédentes de la veille, aucune réinstallation nécessaire — juste Xvfb
revérifié (`Gtk.init_check()`) par prudence, comme désormais
systématique. Seule nouveauté d'environnement : `polib` déjà installé
depuis la session de relecture `.po` du 02-03/09, réutilisé directement
pour appliquer les 9 traductions sans repasser par une édition manuelle
du fichier `.po`.
**Session du 08/09/2026** (correctif des 3 tests `test_gvfs_env_workaround.py`,
voir section dédiée ci-dessus) : `pytest` déjà présent, mais
`loguru`/`netmiko`/`paramiko`/`scp`/`keyring`/`pykeepass`/`ruff` tous
absents au tout début, réseau pip disponible et tout installé sans
incident (`pip install -r requirements-dev.txt` + `pip install ruff`).
GTK4/PyGObject sans son typelib — confirmé explicitement avant le
correctif (`python3 -c "import gi; gi.require_version('Gtk', '4.0')"` →
`ValueError: Namespace Gtk not available`), c'est précisément cette
combinaison que le correctif de cette session traite. Aucun piège
d'infrastructure nouveau rencontré au-delà de celui déjà documenté et
corrigé cette même session.

Estimation, à ajuster à chaque session réelle, du nombre de sessions
restantes pour traiter les points encore ouverts (les points 5, 6, 14,
18 et 19 étant désormais **entièrement traités** côté core/CLI/GUI,
seule la vérification empirique contre un switch réel restant hors de
portée pour 6 et 14 ; le point 16 entièrement traité, étude terminée
sans code à écrire ; le point 4 désormais **entièrement traité** côté
core/CLI/documentation/GUI — trousseau système et repli KeePass tous
deux câblés en GUI, `keepass_path` désormais persisté en page
Préférences ; le point 7, garde-fou installation pendant capture,
désormais **entièrement traité** côté GUI ; le point 17, mode non-root,
désormais **entièrement traité et vérifié empiriquement** — voir section
dédiée ci-dessus ; les bugs 8, 9, 11, 12 désormais **traités et vérifiés
par reproduction réelle** — voir section dédiée ci-dessus ; le point 1,
menu hamburger + page Préférences, désormais **entièrement traité et
testé** — voir section dédiée ci-dessus ; le point 10, Ctrl+C/SIGINT,
désormais **entièrement traité et vérifié empiriquement** (suite pytest
+ test d'intégration bout en bout avec un vrai signal OS) — voir section
dédiée ci-dessus) ; le point 15, squelette projet futur, désormais
**entièrement traité** — voir CLAUDE.md, section dédiée ; le point 13,
i18n, désormais **entièrement traité, CLI et GUI GTK4 toutes deux
câblées** — voir CLAUDE.md, section dédiée ; le volet analyse du seul
point restant en « Pas fait » (n°1, lissage TAP) désormais couvert par
`analyze_pacing_gaps`/`switch-capture analyze-pacing` — voir section
dédiée ci-dessous et CLAUDE.md) : **0** point numéroté restant dans
« Fait » avec un volet sandbox-faisable encore ouvert. Il reste
exactement **1** chose non faisable dans ce sandbox : la mesure réelle de
la durée SCP contre un switch physique (voir « Pas fait » ci-dessous).
Plus aucun test écrit-mais-jamais-couru dans ce dépôt, et **plus aucun
point marqué urgent.**

