# Session 20 — 28/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Session du 28/08/2026 (suite, 6e session du jour) — bugs GVFS/GOA (features.md 8/9/11/12)

Environnement le plus complet rencontré jusqu'ici sur ce projet :
GTK4/PyGObject, Xvfb, `xdotool`, `gcc`, `setcap`, `iproute2`, `pytest`,
`ruff`, et un accès réseau apt/pip sans restriction, tous disponibles
simultanément. A permis de traiter le dernier chantier resté en jachère
faute d'environnement : les 4 rapports de bug GVFS/GOA de l'utilisateur
(`Erreur creating proxy … org.gtk.vfs.GoaVolumeMonitor`, assertion
`Gtk-CRITICAL **: thaw_updates: assertion 'GTK_IS_FILE_SYSTEM_MODEL
(model)' failed`, « Erreur de segmentation (core dumped) »), que
l'utilisateur avait lui-même noté comme partageant probablement une
cause commune.

**Méthode de diagnostic** : plutôt que de deviner un correctif, tenter
d'abord de reproduire. Premier essai sous Xvfb seul (sans session D-Bus)
: `Gtk.init()` réussit mais un avertissement `Unable to acquire session
bus: Failed to execute child process "dbus-launch"` apparaît dès la
création du premier `Gtk.FileChooserNative` — signal que le sélecteur de
fichiers a bien une dépendance D-Bus, mais pas encore la bonne piste
(l'échec `dbus-launch` en lui-même n'est pas ce que l'utilisateur a
rapporté). Deuxième essai avec une vraie session D-Bus
(`dbus-daemon --session --print-address=1 --print-pid=1 --fork`, gvfs
installé mais udisks2/GOA non installés) : l'ouverture du même
`Gtk.FileChooserNative` produit cette fois
`GVFS-RemoteVolumeMonitor-WARNING **: remote volume monitor with dbus
name org.gtk.vfs.UDisks2VolumeMonitor is not supported` — signature
directement de la même famille que celle rapportée par l'utilisateur pour
le moniteur GOA (implémentation sœur du même mécanisme `GVolumeMonitor`
distant fourni par le module `gvfs`). Confirme que le mécanisme en cause
est bien l'activation D-Bus des moniteurs de volumes distants de `gvfs`,
pas un problème plus profond du sélecteur de fichiers lui-même.

**Recherche de correctif** : recherche web sur la documentation GIO
officielle (`docs.gtk.org/gio/overview.html`) plutôt que sur des forums —
confirme que `GIO_USE_VFS`/`GIO_USE_VOLUME_MONITOR` sont deux variables
d'environnement documentées et officiellement supportées pour choisir
l'implémentation VFS/moniteur de volumes GIO, la valeur `local`/`unix`
désignant explicitement l'implémentation intégrée à GIO (sans `gvfs`) ;
la documentation GIO recommande même explicitement `GIO_USE_VFS=local`
« for security-sensitive programs », ce que switch-capture est (accès
SSH à des switches réseau). Testé empiriquement avant d'écrire le
correctif définitif : `GIO_USE_VFS=local` seul **ne suffit pas** — le
`GVFS-RemoteVolumeMonitor-WARNING` persiste, parce que le moniteur de
volumes est un point d'extension GIO séparé de l'implémentation VFS des
fichiers ; il a fallu ajouter `GIO_USE_VOLUME_MONITOR=unix` pour que
l'avertissement disparaisse complètement — vérifié avant/après dans le
même environnement de reproduction.

**Implémentation** : `os.environ.setdefault(...)` pour les deux
variables, dans `switch_capture_gtk.py` (tout en haut du fichier, avant
`import queue`, donc bien avant `import gi` quelques lignes plus bas) et
dans `src/switch-capture` (le point d'entrée unique CLI/GTK). Ce dernier
est nécessaire en plus du premier : `src/switch-capture::_gtk_available()`
fait son propre `import gi` (pour la simple détection de disponibilité,
avant même de savoir s'il faut lancer la GUI), et ce module est importé
et exécuté *avant* `switch_capture_gtk` dans le flux normal de
l'application (`main()` → `run_gtk()` → `_gtk_available()` d'abord, *puis*
`from switch_capture_gtk import main as gtk_main`). Sans le doublon dans
`src/switch-capture`, l'avertissement GVfs pourrait déjà survenir lors de
ce premier `import gi` de détection, avant même que `switch_capture_gtk`
n'ait la moindre chance de positionner quoi que ce soit. Dupliqué plutôt
que factorisé dans un module commun : la docstring de `src/switch-capture`
est explicite sur le fait que ce fichier doit rester autonome (copié tel
quel par les 3 méthodes d'installation, avec juste le shebang réécrit).
`setdefault` dans les deux cas : ne jamais écraser un réglage explicite
déjà présent dans l'environnement de qui lance l'outil — un utilisateur
qui aurait positionné ces variables lui-même pour une autre raison (accès
volontaire à un montage `gvfs` distant, débogage GIO) garde la main.

**Nouvelle suite `tests/test_gvfs_env_workaround.py` (7 tests)** :
3 tests sur `switch_capture_gtk.py` et 3 sur `src/switch-capture`
n'utilisent que `subprocess` avec un environnement contrôlé — aucun
besoin d'Xvfb, puisque ces variables sont lues par GIO à la résolution de
ses extension points, pas par le rendu GTK. Le test sur `src/switch-capture`
le plus poussé fait un `exec()` du corps du fichier sous un `__name__`
différent de `"__main__"` (pour que le bloc `if __name__ == "__main__":
sys.exit(main())` final ne se déclenche pas) et vérifie que
`_gtk_available()` reste appelable avec les variables déjà positionnées —
preuve structurelle de l'ordre réel des opérations, pas seulement un test
de la valeur finale des variables. **Piège rencontré** : le premier essai
de ce test échouait avec `NameError: name '__file__' is not defined`,
`switch-capture` faisant lui-même référence à `__file__` dans son code de
résolution de `sys.path` — corrigé en injectant `'__file__':
'switch-capture'` dans le dict de namespace passé à `exec()`.

Le 7e test est un test d'intégration bout en bout, réutilisant exactement
la méthode de reproduction manuelle décrite plus haut (Xvfb +
`dbus-daemon --session` relancés dans le test lui-même, sur un port
différent — `:97` — des autres tests de ce dépôt pour éviter toute
collision si plusieurs suites tournaient en parallèle) : ouvre un vrai
`Gtk.FileChooserNative` deux fois, une fois sans les variables et une
fois avec, et vérifie littéralement la présence/absence de
`GVFS-RemoteVolumeMonitor` dans le `stderr` capturé de chaque sous-processus.
Se saute proprement (`pytest.skip`) si Xvfb/`dbus-daemon`/GTK4 manquent —
même politique que les autres tests GUI de ce dépôt.

**Piège d'exécution rencontré cette session (nouveau, à ajouter à celui
déjà noté sur Xvfb/dbus ne survivant pas entre appels d'outil)** :
`pytest tests/ -v` sur la suite complète (sans filtre) dépassait la
limite de temps d'un appel d'outil de ce sandbox, y compris avec
`--timeout` pytest posé — probablement un test bloquant sur une attente
réseau/D-Bus sans rapport avec ce changement (non identifié précisément,
pas creusé plus avant faute de temps). Contourné en découpant l'exécution
en plusieurs lots dans des appels d'outils séparés (non-GUI d'abord avec
`--timeout=15` et `-k` excluant explicitement le test d'intégration
taphelper le plus long, puis les 4 fichiers de tests GUI séparément) —
aucun test omis au global, juste répartis différemment dans le temps.
Après installation de `iproute2` (absent au tout début de cette session,
contrairement aux sessions précédentes qui l'avaient), le test
d'intégration `test_taphelper_end_to_end_as_real_nonroot_user`
(pré-existant, sans lien avec ce changement) passe pour la première fois
dans une session où il était auparavant collecté — confirme que son échec
dans les sessions précédentes tenait bien à l'environnement (privilèges
kernel + `iproute2`), pas à un bug du code.

`py_compile` sur `switch_capture_gtk.py`/`src/switch-capture` : OK.
`ruff check --line-length 120 src/` : comparaison ligne à ligne avec une
copie du dépôt d'avant modification — mêmes 4 erreurs `BLE001`
pré-existantes dans `switch_capture_gtk.py`, seuls les numéros de ligne
décalent (bloc de commentaire ajouté en tête de fichier) ; même unique
erreur pré-existante (`except Exception` dans `_gtk_available`) sur
`src/switch-capture`, à la ligne inchangée puisque le bloc ajouté est
avant cette fonction mais celle-ci n'a pas bougé de position relative
dans le fichier de façon à changer son propre numéro de ligne visible
dans le rapport (vérifié directement, pas supposé). Suite `pytest`
complète du dépôt rejouée en plusieurs lots (voir piège ci-dessus) :
**230 tests réels passés, 0 échec** au total (223 précédents + 7
nouveaux).

**Non fait cette session, noté explicitement dans features.md** : le
volet `Ctrl+C`/sortie propre du bug 10 (`Traceback`/`KeyboardInterrupt`
brut) n'a **pas** de rapport avec GVfs/GOA — ce n'est pas couvert par ce
correctif, contrairement à ce que le regroupement initial de
l'utilisateur («  4 rapports … probablement une cause commune ») aurait
pu laisser supposer pour l'ensemble du point 10. Reformulé comme point
ouvert distinct plutôt que refermé à tort. Également non fait :
vérification empirique du segfault exact rapporté (l'environnement de
reproduction de cette session produit un avertissement de la même
famille mais pas un crash — `gvfs` plus complet/stable ici que sur le
poste RDP/xrdp d'origine de l'utilisateur) — la disparition de
l'avertissement est un signal fort mais pas une preuve directe pour le
segfault précis ; à confirmer si l'utilisateur peut retester sur son
poste d'origine.

