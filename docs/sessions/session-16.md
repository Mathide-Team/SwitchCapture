# Session 16 — 28/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Garde-fou installation pendant une capture en cours (28/08/2026, suite)

Traite le point 7 de `features.md` (section « Comportement de
capture ») : *« Empêcher le lancement d'une installation si une trace
est déjà en cours : bouton grisé et/ou pop-up d'alerte. »* Détail
complet, y compris le résultat des tests, dans `features.md` (section
datée du même jour, juste après « Câblage GUI de 4 réglages core/CLI
déjà traités ») — résumé ici du côté pourquoi/comment.

**Pourquoi cette tâche** : explicitement identifiée dans le « Suivi des
sessions » de la session précédente comme petite et pouvant « se greffer
à un point proche », donc raisonnable à traiter entièrement en une seule
réponse. L'environnement GTK4/PyGObject/Xvfb retrouvé lors de la session
précédente (câblage GUI des 4 réglages) était toujours disponible dans
ce sandbox, permettant à nouveau un test réel plutôt qu'une livraison en
aveugle — **ne pas supposer que cette disponibilité persistera** d'une
session à l'autre pour autant, à revérifier systématiquement.

**Ce qui a été fait** dans `switch_capture_gtk.py` : `_on_install_all`
(bouton « Lancer l'installation de toutes les captures », page
Installation) vérifie désormais `capture_running` sur chaque session
avant de préparer quoi que ce soit — si au moins une capture tourne,
aucun `_start_prepare` n'est appelé et une pop-up (`_show_dialog`) liste
la ou les capture(s) concernée(s) par leur libellé. En parallèle,
`_refresh_install_list` grise le bouton en continu (pas seulement au
moment du clic) dès qu'une capture est en cours, avec une info-bulle
explicative, et le réactive dès qu'il n'y en a plus. Ce rafraîchissement
est déclenché à trois endroits : construction de la fenêtre (déjà
existant), immédiatement après `_on_start_all` (pour un retour visuel
sans attendre le prochain tick), et à chaque tick du minuteur `~1s` déjà
utilisé par la page Journal (`_refresh_journal`) — ce dernier point
couvre aussi bien la fin naturelle d'une capture que son arrêt manuel
sans code de suivi supplémentaire à écrire ou maintenir.

**Pas de garde équivalent côté CLI** : décision volontaire, pas un
oubli. Le point 7 tel que formulé par l'utilisateur décrit un
comportement d'interface graphique (bouton grisé, pop-up) ; le CLI
(`switch_capture_cli.py`) n'a ni bouton ni notion de « capture déjà en
cours en tâche de fond pendant qu'on relance une installation » — son
exécution est strictement séquentielle, un seul flux à la fois. À
reconsidérer si l'utilisateur signale explicitement un besoin CLI
équivalent (ex. usage scripté avec plusieurs processus `switch-capture`
lancés en parallèle par l'utilisateur lui-même — cas non couvert
aujourd'hui, ni avant ni après ce changement).

**Testé réellement**, sur le modèle déjà établi par
`tests/test_gui_new_fields.py`/`tests/test_uninstall_confirm.py` :
nouvelle suite `tests/test_install_guard_while_running.py` (5 tests) —
construction réelle de `CaptureWindow` via `Gtk.Application`/Xvfb ; test
du grisage du bouton dans les 3 états (aucune capture en cours, une
capture en cours, capture arrêtée à nouveau) via `_refresh_install_list`
directement ; test de `_on_install_all` avec `_start_prepare` et
`_show_dialog` remplacés par des espions via `monkeypatch` (aucune
connexion SSH réelle, aucun thread réellement lancé) pour vérifier à la
fois le cas bloqué (pop-up affichée, rien démarré, statut resté
`pending`) et le cas normal (préparation lancée, statut passé à
`running`). Suite `pytest` complète rejouée sans aucune régression ni
modification requise ailleurs : **189 tests réels passés, 0 échec**
(184 précédents de la session câblage GUI + ces 5 nouveaux). `ruff`
disponible cette fois (installé via pip, accès PyPI confirmé) :
`ruff check --line-length 120 src/` toujours **4 erreurs** dans
`switch_capture_gtk.py`, toutes `BLE001` pré-existantes (mêmes lignes
qu'avant ce changement, aucune nouvelle introduite) ; sur le nouveau
fichier de test, seul le bruit `RUF100`/`noqa: E402` déjà présent à
l'identique dans `tests/test_gui_new_fields.py` (conservé
volontairement : `flake8`, utilisé par le pre-commit du projet,
applique bien `E402` contrairement à `ruff` seul — voir en-tête de
`test_gui_new_fields.py` pour la même justification). `ruff format
--check` sur le fichier modifié : signale un reformatage massif,
mais **identique en nature et en étendue à l'état du fichier avant ce
changement** (style de mise en forme du projet, jamais passé au
formateur automatique jusqu'ici) — aucune ligne de mon changement
spécifiquement pointée par le diff produit ; pas d'action prise, comme
pour les sessions précédentes qui n'ont jamais fait tourner `ruff
format` sur l'existant.

**Non fait** : les deux priorités urgentes (17, 18) restent non
traitées, comme la session précédente — ce n'était toujours pas l'objet
de cette tâche, choisie précisément pour rester petite et livrable en
une réponse. Le reste des points `reste à faire` sans lien avec le
garde-fou (menu hamburger/page Préférences, bugs GVFS/GOA, i18n,
squelette projet futur) non plus.

