# Session 43 — 06/09/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Documentation : 3 flags `capture` absents de la table de référence USAGE.md (06/09/2026, 6e session du jour)

### Contexte

En reprenant la todo-list une 6e fois dans la même journée, toujours
aucune tâche numérotée nouvelle faisable sans switch réel ni relecture
humaine native (voir sessions précédentes ci-dessus, même constat 5
fois de suite). Recherche élargie une nouvelle fois à la cohérence
documentaire, cette fois sur `USAGE.md` lui-même — la session
précédente avait traité `config.yaml.example`.

### Ce qui a été trouvé

En comparant systématiquement les flags longs réels de
`_add_common_config_args` (`switch_capture_cli.py`, introspection de
`build_arg_parser()`, pas une relecture visuelle) à la table
« Référence des options — `capture` / `uninstall` » de `USAGE.md` :
`--no-hide-capture-traffic`, `--tap-pace-playback` et
`--tap-pace-max-gap` sont des flags CLI bien réels — câblés en GUI
depuis fin août 2026, déjà documentés dans `config.yaml.example`
depuis la session précédente — mais absents de **toute** section de
`USAGE.md`. Seul `--tap-pace-max-gap` était mentionné en passant, dans
le contexte de `analyze-pacing`, sans jamais expliquer ce que fait le
flag côté `capture` lui-même.

Différence de nature relevée avant correctif, sur le même principe que
`packet_capture_cmd` la session précédente : le trio
`--remember-password`/`--forget-password`/`--keepass-path` est lui
aussi absent de cette table, mais **délibérément** — déjà documenté en
détail dans la section dédiée « Mémoriser le mot de passe SSH entre
deux lancements ». Exclusion assumée, pas un oubli supplémentaire.

### Ce qui a été fait

- 3 nouvelles lignes dans la table de référence `capture`/`uninstall`
  de `USAGE.md` : `--no-hide-capture-traffic` juste après
  `--capture-filter` (même emplacement logique que
  `hide_capture_traffic` dans `config.yaml.example`), et
  `--tap-pace-playback`/`--tap-pace-max-gap` dans le bloc `--tap-*`
  existant, juste après `--tap-launch-wireshark` — reprenant les
  défauts et la portée déjà décrits dans le `help=` CLI (`switch_capture_cli.py`).
- Nouveau fichier `tests/test_usage_md_completeness.py` (2 tests) :
  compare automatiquement les flags longs du sous-parseur CLI
  `capture` au contenu de la table de référence de `USAGE.md`, même
  logique que `tests/test_config_example_completeness.py` (session
  précédente) pour que ce type d'oubli soit détecté par la suite
  pytest plutôt que par une relecture manuelle ponctuelle. Le trio
  `remember-password`/`forget-password`/`keepass-path` est exclu
  explicitement (documenté ailleurs), avec un test dédié
  (`test_documented_elsewhere_flags_still_exist`) qui échouerait si
  l'un de ces flags disparaissait un jour de la CLI, pour forcer une
  décision explicite plutôt que de laisser l'exclusion devenir
  silencieusement fausse.

### Vérifié réellement cette session

- Le nouveau test de complétude vérifié dans les deux sens, pas
  seulement écrit : version d'origine de `USAGE.md` (celle du zip
  d'entrée, table sans les 3 lignes) restaurée temporairement → échec
  confirmé, listant exactement les 3 flags manquants
  (`--no-hide-capture-traffic`, `--tap-pace-max-gap`,
  `--tap-pace-playback`) ; version corrigée réappliquée → passe.
- `ruff format --line-length 120` sur le nouveau fichier de test : 1
  ligne reformatée (compréhension multi-ligne condensée), revérifiée
  propre ensuite ; `ruff check --line-length 120 --no-cache` : 0
  erreur.
- `ruff check --line-length 120 --no-cache src/` : toujours exactement
  22 erreurs préexistantes (`USAGE.md` n'est pas du Python, aucun
  fichier `.py` de `src/` touché cette session).
- Suite complète : **292 passés** (290 + 2 nouveaux), **4 échecs
  préexistants sans rapport, 7 skips** — identique aux 2e/3e/4e/5e
  sessions du jour pour la cause des 4 échecs et des 7 skips.
  Environnement inchangé : GTK4/PyGObject absent (`test_gui_*.py`
  auto-skippés), `ip`/iproute2 et `gvfs` toujours non installables
  (dépôts miroir en 404).

### Résultat

`src/docs/USAGE.md` documente désormais, dans sa table de référence
rapide `capture`/`uninstall`, tous les flags CLI correspondants sauf
le trio mot-de-passe/KeePass (déjà documenté ailleurs en détail,
exclusion assumée et vérifiée par test). `features.md` : nouvelle
sous-section datée, compteur de sessions incrémenté (48 → 49).

### Reste ouvert

Inchangé par rapport aux sessions précédentes du jour : jamais testé
contre un switch réel, le volet durée-SCP réelle (« Pas fait » n°1,
switch physique requis), la relecture du `.po` `en_US` par une personne
anglophone native humaine, et les messages dynamiques du Journal/corps
`str(exc)` qui restent un choix de périmètre assumé (point 13) plutôt
qu'un oubli.

