# Session 22 — 29/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Gestion propre de Ctrl+C (SIGINT) dans l'app GTK4 (29/08/2026, suite)

**Point traité** : features.md, point 10 (reformulé le 28/08/2026) — «
Ctrl+C remonte toujours un Traceback/KeyboardInterrupt brut au lieu
d'une sortie propre », dernier volet resté ouvert des bugs rapportés par
l'utilisateur (8/9/10/11/12), sans rapport avec les autres (GVFS/GOA,
déjà tous corrigés le 28/08/2026).

**Diagnostic** — raisonné à partir du fonctionnement documenté de
GLib/PyGObject, **pas reproduit empiriquement cette session** (voir
« Environnement de cette session » ci-dessous : GTK4 totalement
indisponible ici, contrairement à la plupart des diagnostics précédents
de ce journal, qui reproduisent d'abord le bug avant de corriger) :
`switch_capture_gtk.py` ne posait jusqu'ici aucun gestionnaire pour
`SIGINT` (seule la CLI, dans `switch_capture_cli.py::run_capture`, en a
un via `signal.signal`). Sans gestionnaire explicite, le comportement par
défaut de Python s'applique : lever `KeyboardInterrupt` au prochain
retour à la boucle d'évaluation de bytecode. Or tant que
`Gtk.Application.run()` tourne, ce retour ne se produit que
ponctuellement, à l'intérieur des callbacks GLib déjà en place
(`GLib.timeout_add(_drain_log_queue)`, `GLib.timeout_add(_refresh_journal)`,
ou tout callback de widget) — un `KeyboardInterrupt` levé là remonte à
travers la boucle événementielle GLib (code C, pas prévu pour une
exception Python) plutôt que par `_on_close_request`, ce qui correspond
au traceback brut rapporté. C'est un piège bien connu de PyGObject/GLib
(pas spécifique à ce projet) ; la solution documentée par le projet GNOME
lui-même est `GLib.unix_signal_add()`, qui s'intègre nativement à la
boucle GLib (source dédiée, indépendante du mécanisme `signal` de Python)
au lieu de compter sur le mécanisme Python standard.

**Fix retenu**, dans `switch_capture_gtk.py` :
- `CaptureApp.__init__` gagne deux attributs : `self._window` (référence
  vers la `CaptureWindow` créée par `do_activate`, `None` seulement dans
  le cas d'échec d'affichage déjà géré — voir « Correctif sudo/RDP »
  ci-dessus) et `self._sigint_source_id` (identifiant de la source GLib,
  sert de garde d'idempotence).
- `CaptureApp.do_activate` pose `self._window` puis appelle la nouvelle
  méthode `_install_sigint_handler()` juste avant `window.present()`.
- `_install_sigint_handler()` : `GLib.unix_signal_add(GLib.
  PRIORITY_DEFAULT, signal.SIGINT, self._on_sigint)`, gardé par
  `_sigint_source_id` pour ne jamais empiler une deuxième source si
  `do_activate` était un jour appelé plus d'une fois (ex. réactivation
  D-Bus d'une instance déjà lancée).
- `_on_sigint()` : **ne duplique pas** la logique de fermeture propre —
  appelle `self._window.close()`, exactement comme le fait déjà l'action
  `win.quit-app` du menu hamburger (`CaptureWindow.__init__`, voir « Menu
  hamburger et page Préférences » ci-dessus), ce qui déclenche le signal
  `close-request` déjà connecté à `_on_close_request` (arrêt des captures
  en cours via `state.stop_event`, fermeture de la fenêtre Préférences si
  ouverte). Retourne `False` (= `GLib.SOURCE_REMOVE`, en style booléen nu
  pour rester cohérent avec le reste du fichier — voir
  `_drain_log_queue`/`_on_close_request`) : un seul déclenchement suffit,
  la fermeture étant déjà engagée. La fenêtre étant la seule que
  `CaptureApp` possède, sa fermeture met fin à `Gtk.Application.run()`
  sans appel explicite à `self.quit()` (même mécanisme, déjà en place,
  que pour la fermeture par la souris ou par « Quitter »).
- `import signal` ajouté en tête de fichier ; `loguru.logger`, déjà
  disponible, journalise la réception du signal au même niveau que le
  message déjà émis côté CLI (`run_capture`).

**Tests ajoutés** (`tests/test_gtk_sigint.py`, nouveau fichier, même
convention `pytest.importorskip("gi")` + squelette `_make_.../
_pump_main_loop` que les 5 fichiers `test_gui_*.py` existants) : 5 tests
dans 2 classes — enregistrement de la source GLib après activation +
idempotence (`TestSigintHandlerInstalled`), et `_on_sigint` arrête bien
une capture en cours (`state.stop_event`), ferme la fenêtre Préférences
si ouverte, et est un no-op inoffensif si appelé avant qu'une fenêtre
n'existe (`TestOnSigintClosesLikeCloseRequest`). Comme
`test_gui_preferences_window.py::TestPreferencesWindowLifecycle` le fait
déjà pour `_on_close_request`, `_on_sigint` est appelé directement plutôt
que de simuler un vrai signal OS : la plomberie SIGINT bas niveau
elle-même est une responsabilité interne de GLib, sans valeur à
re-vérifier ici.

**Non testé réellement cette session** — écart assumé par rapport à la
pratique habituelle de ce journal (reproduire le bug, corriger,
re-tester sous Xvfb) : voir « Environnement de cette session »
ci-dessous, aucune des deux étapes n'était possible. Seule vérification
effectuée : `python3 -m py_compile` sur `switch_capture_gtk.py` et
`tests/test_gtk_sigint.py` (syntaxe uniquement, aucune exécution), plus
un contrôle manuel de longueur de ligne (`awk 'length > 120'`, palliatif
à `ruff check --line-length 120`, lui aussi indisponible cette session) :
aucune ligne ajoutée ne dépasse 120 caractères (la seule trouvée dans
tout le fichier, ligne 1397, est préexistante — comparée à une copie
pristine du zip d'entrée — et hors périmètre de ce changement). Le point
10 passe donc de « reste non traité » à « traité, mais non vérifié
empiriquement » — nuance volontairement différente de l'« entièrement
traité » utilisé ailleurs dans features.md pour les points où Xvfb +
GTK4 réel avaient permis une vérification comportementale complète.
`pytest tests/test_gtk_sigint.py` (et l'ensemble de la suite, GTK et
non-GTK confondus) reste à exécuter dès qu'une session disposera à
nouveau d'un environnement complet.

**Remarque annexe, hors périmètre de cette session, signalée pour
arbitrage** : `pytest.importorskip("gi")`, utilisé par les 5 fichiers
`test_gui_*.py` existants et repris à l'identique dans le nouveau
`test_gtk_sigint.py`, protège contre l'absence du module `gi` lui-même,
mais pas contre un `gi` présent avec le namespace `Gtk 4.0` absent (le
cas précis de ce sandbox — voir ci-dessous) : `gi.require_version("Gtk",
"4.0")` lèverait alors une `ValueError` non interceptée à la collecte
plutôt qu'un skip propre. Observation faite hors pytest (celui-ci étant
lui-même absent cette session, voir ci-dessous), via un `python3 -c`
direct ; non corrigée ici (toucherait 5 fichiers existants sans rapport
avec le point 10, et resterait de toute façon invérifiable cette
session).

**Environnement de cette session** — le plus contraint rencontré à ce
jour sur ce projet, à documenter précisément pour la prochaine (voir
« Suivi des sessions » de features.md pour l'historique complet des
environnements précédents, tous différents) : **réseau totalement
désactivé** (`x-deny-reason: host_not_allowed` sur toute requête
sortante, y compris `pypi.org`/`archive.ubuntu.com` — vérifié
explicitement, pas supposé), contrairement à toutes les sessions
précédentes documentées ici, qui avaient toujours eu au moins un accès
partiel. Résultat : aucun paquet manquant n'a pu être installé, ni via
`apt` ni via `pip`. Étaient absents et RESTÉS absents (contrairement au
29/08/2026 plus tôt dans la journée, où les mêmes paquets avaient pu
être installés en tout début de session) : `pytest`, `ruff`, `loguru`,
`netmiko`, `paramiko`, `scp`, `keyring`, `pykeepass`. `python3-gi`/
PyGObject 3.48.2 lui-même **était** présent (à la différence des
sessions « GTK4/PyGObject absents » précédemment documentées), mais pas
le typelib `gir1.2-gtk-4.0` (`gi.require_version("Gtk", "4.0")` lève
`ValueError: Namespace Gtk not available`) — combinaison inédite dans
l'historique de ce projet (jusque-là, soit PyGObject était présent EN
BLOC avec son typelib GTK4, soit absent en bloc). `Xvfb` était présent
mais inutile dans ces conditions (rien à afficher sans le typelib GTK4).
Conséquence directe : aucun des trois fichiers source principaux
(`switch_capture_core.py`, `switch_capture_cli.py`,
`switch_capture_gtk.py`) n'est importable dans ce sandbox (les deux
premiers échouent dès `from loguru import logger`), et la suite `pytest`
existante (19 fichiers `test_*.py` avant cette session) n'a pas pu être
exécutée, ne serait-ce qu'une seule fois, à titre de non-régression.

