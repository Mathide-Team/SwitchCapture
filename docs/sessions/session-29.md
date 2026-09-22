# Session 29 — 31/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Collecte pytest bloquée par `gi.require_version()` sans filet (31/08/2026, 4e session du jour)

Constat en début de session : tous les points numérotés de features.md
sont clos, seul reste ouvert le volet durée-SCP du point « Pas fait »
n°1 (bloqué sans switch réel). Cette session traite la remarque annexe
notée en session du 29/08/2026 (« Gestion propre de Ctrl+C (SIGINT) dans
l'app GTK4 » ci-dessus) et jusque-là explicitement laissée de côté :
`pytest.importorskip("gi")`, utilisé par 6 fichiers de test GTK4, ne
protège que l'absence du module `gi` lui-même — pas la combinaison
précise où `gi` est installé mais où le typelib `gir1.2-gtk-4.0` ne
l'est pas. Dans ce cas, `gi.require_version("Gtk", "4.0")` lève un
`ValueError` non intercepté **au moment de la collecte pytest**, ce qui
interrompt la collecte de la suite *entière* (`Interrupted: N errors
during collection`), pas seulement des 6 fichiers concernés.

### Diagnostic

Reproduit pour de vrai avant tout correctif : ce sandbox présente
exactement cette combinaison (`python3 -c "import gi; gi.require_version
('Gtk', '4.0')"` échoue avec `ValueError: Namespace Gtk not available`,
alors que `import gi` seul réussit — PyGObject 3.48.2 installé, mais pas
`gir1.2-gtk-4.0`). `pytest tests/` depuis `src/`, sans aucune exclusion,
échoue avec 6 erreurs de collecte et **0 test exécuté**, y compris pour
les 16 autres fichiers de test sans aucun rapport avec GTK4 (ils ne sont
simplement jamais atteints, pytest interrompant la collecte dès la
première erreur non filtrée par défaut).

Fichiers concernés : `test_gtk_sigint.py`, `test_gui_keepass_wiring.py`,
`test_install_guard_while_running.py`, `test_gui_preferences_window.py`,
`test_gui_new_fields.py`, `test_gui_mirroring.py` — chacun reproduisait à
l'identique le motif à 3 lignes (`gi = pytest.importorskip("gi")` +
2×`gi.require_version(...)`). `test_gvfs_env_workaround.py` n'est pas
concerné : ses deux classes de test sondent GTK4 via un `subprocess.run`
dédié, à l'intérieur d'une fonction de test (donc après le début de la
collecte), avec un `pytest.skip()` déjà correctement placé — pas un
`gi.require_version()` nu au niveau module.

Rétrospectivement, c'est cette combinaison précise qui obligeait les 3
dernières sessions (i18n CLI le 30/08, i18n GUI puis pérennisation du
test i18n le 31/08 — voir sections dédiées ci-dessus) à invoquer pytest
avec une exclusion manuelle de ces mêmes 6 fichiers, plus
`test_taphelper_end_to_end_as_real_nonroot_user` (bloqué séparément par
l'absence du binaire `ip`) : un contournement répété à chaque session
plutôt qu'un correctif écrit une fois.

### Ce qui a été fait

- Nouvelle fonction `require_gtk4()` dans `tests/conftest.py` :
  `gi = pytest.importorskip("gi")` (protège toujours l'absence du module
  `gi` lui-même), puis `gi.require_version("Gtk", "4.0")` +
  `gi.require_version("Gdk", "4.0")` dans un `try`/`except ValueError`,
  qui appelle `pytest.skip(f"...", allow_module_level=True)` en cas
  d'échec plutôt que de laisser l'exception remonter brute. Retourne
  `gi`.
- `allow_module_level=True` s'est révélé nécessaire en cours de session,
  pas anticipé au premier jet : ces 6 fichiers appellent `require_gtk4()`
  au niveau module (avant toute fonction de test, pour que les `from
  gi.repository import ...` qui suivent immédiatement fonctionnent), et
  `pytest.skip()` sans ce paramètre lève une `RuntimeError` explicite
  (« Using pytest.skip outside of a test will skip the entire module »)
  plutôt que de sauter proprement — repéré en relançant la suite juste
  après le premier correctif, pas anticipé à la lecture de la
  documentation pytest seule.
- Les 6 fichiers concernés remplacent leurs 3 lignes dupliquées par
  `from conftest import require_gtk4` + `gi = require_gtk4()` — logique
  centralisée une seule fois plutôt que redupliquée dans un 7e filet par
  fichier, pour que tout futur fichier de test GUI en bénéficie
  automatiquement sans avoir à connaître ce piège.

### Vérifié réellement cette session

- Bug reproduit avant correctif (6 erreurs de collecte, 0 test exécuté),
  disparu après.
- `python3 -m py_compile` OK sur les 7 fichiers modifiés.
- `ruff check --line-length 120`, comparé fichier par fichier à une copie
  pristine du zip d'entrée (`--no-cache` des deux côtés, comme la
  méthode déjà utilisée par les sessions précédentes) : le premier jet
  introduisait 6 nouvelles erreurs `I001` (tri d'imports), à cause d'une
  ligne vide laissée entre `import pytest` et `from conftest import
  require_gtk4` — repéré par cette comparaison avant livraison, corrigé
  (ligne vide retirée), re-vérifié : **exactement les 13 mêmes erreurs
  préexistantes sur ces 7 fichiers, aucune nouvelle**. Aucune ligne
  ajoutée ne dépasse 120 caractères (`awk 'length > 120'`).
- Suite complète rejouée avec un simple `pytest tests/` **sans aucune
  exclusion manuelle**, une première documentée dans ce dépôt : **226
  passés, 4 échecs, 7 skips** (6 skips de module — un par fichier
  corrigé, 65 fonctions de test au total dans ces 6 fichiers — plus le
  skip déjà préexistant de `test_gvfs_env_workaround.py`). Les 4 échecs
  sont préexistants et sans rapport avec ce correctif, tous déjà
  documentés par des sessions précédentes pour ce sandbox précis : 3 dans
  `test_gvfs_env_workaround.py` (relance `switch_capture_gtk.py` dans un
  vrai sous-processus, qui nécessite donc lui aussi un vrai typelib
  GTK4) et 1 dans `test_tap_helper_nonroot.py`
  (`test_taphelper_end_to_end_as_real_nonroot_user`, `Permission denied`
  sur l'attachement TAP en tant qu'utilisateur non-root — restriction
  kernel déjà documentée comme fluctuante d'une session à l'autre depuis
  le 28/08/2026). `iproute2` (commande `ip`), absente au tout début de
  cette session, a dû être réinstallée — comme plusieurs fois par le
  passé, confirmant une fois de plus qu'un environnement constaté ne
  présage pas de celui d'une session ultérieure.

### Reste ouvert

- Rien de nouveau ouvert par ce correctif — toujours uniquement le volet
  durée-SCP réelle du point « Pas fait » n°1 (switch physique requis) et
  la relecture du `.po` `en_US` par une personne anglophone native.
- Un 7e fichier de test GTK4 qui appellerait directement
  `gi.require_version(...)` sans passer par `require_gtk4()`
  réintroduirait le même risque : rien ne l'empêche mécaniquement (pas
  de test dédié ni de règle `ruff` custom vérifiant ce motif), seule
  cette section documente la convention à suivre. Signalé pour mémoire,
  pas traité ici (ajouter un tel garde-fou serait lui-même une tâche à
  part entière, hors périmètre de cette session).

