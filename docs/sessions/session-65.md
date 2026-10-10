# Session 65 — 10/10/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

Issue #70 : remonter la progression SCP jusqu'à la page « Journal » de la
GUI (reste du candidat #6 de l'audit Context7, cœur fait en
[session 60](session-60.md)).

## Besoin

Pendant le polling de rotation, un fichier de capture volumineux peut
mettre plusieurs dizaines de secondes à être rapatrié : la ligne de la
capture n'affichait que le cumul et le débit moyen, calculés après coup.
Les paliers étaient journalisés en DEBUG, donc visibles dans les logs de la
page et avec `-v` en CLI, mais noyés parmi les autres lignes.

## Conception

- **Cœur** : `make_scp_progress_logger(context, threshold_percent=10,
  on_progress=None)`. `on_progress` reçoit un `ScpProgress(context, name,
  percent, sent, size)` à chaque palier journalisé (même filtrage, même
  suivi par fichier). Une exception levée par `on_progress` est journalisée
  et n'interrompt jamais le transfert. Sans `on_progress`, comportement
  inchangé.
- **État partagé** : `SharedState.scp_progress` (None tant qu'aucun palier).
  `SetupAndCaptureThread._push_feature_file` et `CaptureRotationThread`
  y publient le palier via `_record_scp_progress` : affectation d'un objet
  immuable, atomique sous le GIL, même principe que les compteurs existants.
- **GUI** : `_refresh_journal` (déjà appelé chaque seconde par
  `GLib.timeout_add`, sur le thread GTK) ajoute `format_scp_progress(...)`
  à la ligne de la capture, par exemple
  « en cours — 3 fichier(s), 12.0 Mo — 1.2 Mo/s — SCP cap_00003.pcap : 40 % (4.0 Mo / 10.0 Mo) ».
  Aucun appel GTK depuis le thread de transfert, aucune attente bloquante.
- **CLI** : `-v` affiche déjà chaque palier (niveau DEBUG) ; rien à ajouter.

## Tests

- `tests/test_scp_progress_journal.py` (11, sans GTK) : paliers transmis à
  `on_progress`, suivi par fichier, fichier vide, callback en échec sans
  interruption, rétrocompatibilité, formatage, câblage réel des deux
  threads vers `SharedState.scp_progress` (SCP remplacé).
- `tests/test_gui_scp_progress_journal.py` (2, GTK4 + Xvfb, sautés sans
  PyGObject comme les autres tests GUI) : texte de la ligne de progression
  avec et sans palier, cas rpcap.

## Résultat (mesuré)

`uv run --group quality coverage run -m pytest -q` : **697 passés,
12 ignorés** (+11 passés ; le module GUI, sans PyGObject, compte pour 1 ignoré). Les 2 tests GUI
passent sous `xvfb-run` avec PyGObject (`uv run --with pygobject --with
pycairo`). `ruff check .` et `ruff format --check .` : 0 erreur.
