# Session 44 — 07/09/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Documentation/bug : `-v` mal placé dans un exemple de USAGE.md (07/09/2026)

### Contexte

En reprenant la todo-list le lendemain de la 6e et dernière session du
06/09/2026, toujours aucune tâche numérotée nouvelle faisable sans
switch réel ni relecture humaine native (voir les 6 sessions de la
veille ci-dessus, même constat à chaque fois — aucune évolution
entre-temps). Recherche élargie cette fois à l'ensemble des
sous-commandes plutôt qu'à une seule table : comparaison empirique de
tous les flags longs de `capture`, `uninstall`, `mirror`, `inspect`,
`analyze-pacing`, `import-bin` (introspection réelle de
`build_arg_parser()` via un script Python jetable) au contenu textuel
de `USAGE.md`.

### Ce qui a été trouvé

D'abord une fausse piste : la table « Référence des options — `mirror` »
semblait a priori manquer `-v`/`--verbose` — présent dans la table
`capture`/`uninstall` mais absent des 3 autres tables
(`mirror`/`inspect`/`analyze-pacing`). Vérification : `-v`/`--verbose`
est ajouté sur le parseur **racine** (`switch_capture_cli.build_arg_parser`,
avant `add_subparsers()`), donc mécaniquement disponible pour les 6
sous-commandes, pas seulement `capture`/`uninstall` — confirmé
empiriquement, `parser.parse_args(["-v", "mirror", ...])` retourne bien
`verbose=True`. Pas un flag manquant par sous-commande, donc, mais une
option globale documentée une seule fois — a priori défendable, à
condition que le placement documenté soit correct.

En creusant précisément ce placement, trouvé le vrai bug : l'exemple
« Config de base + surcharge ponctuelle du filtre » de `USAGE.md`
plaçait `-v` **après** `capture` :

```
switch-capture capture --config /etc/switch-capture/site-a.yaml \
  --capture-filter "host 10.10.10.2 and proto gre" -v
```

Testé tel quel contre le vrai parseur :

```python
cli.build_arg_parser().parse_args(
    ["capture", "--switch-ip", "10.0.0.1", "--ssh-user", "test",
     "--capture-interface", "Gi1/0/1", "-v"]
)
# -> SystemExit: 2
# switch-capture: error: unrecognized arguments: -v
```

Confirmé pour les 6 sous-commandes (`-v` avant : succès systématique ;
`-v` après : `unrecognized arguments: -v` systématique, même message).
Différent de `-c`/`-g` : ces deux-là sont filtrés séparément de
`argv`, **n'importe où dans la liste**, par la boucle `for arg in
argv:` du lanceur `src/switch-capture::main()` (`_CLI_FLAGS = ("-c",
"--cli")` / `_GTK_FLAGS = ("-g", "--gtk")`, lignes 59-60), donc
utilisables avant ou après la sous-commande sans distinction —
vraisemblablement l'origine de la confusion dans l'exemple d'origine,
`-v` ayant été placé comme s'il suivait la même règle que `-c`/`-g`,
alors qu'il suit la règle standard d'`argparse` (option du parseur
parent, pas propagée aux sous-parseurs).

### Ce qui a été fait

- Exemple corrigé dans `USAGE.md` (`-v` déplacé avant `capture`).
- Note ajoutée juste après le bloc « Aide intégrée » (avant la première
  table de référence) expliquant explicitement : `-v`/`--verbose` est
  une option globale du parseur racine, à placer avant la sous-commande,
  valable pour les 6 sous-commandes ; message d'erreur exact si mal
  placée ; contraste explicite avec `-c`/`-g`.
- Rappel ajouté dans la table `capture`/`uninstall` elle-même (seule
  table où `-v` apparaît — choix délibéré de ne pas dupliquer la ligne
  dans les 3 autres tables, la note générale suffisant, même principe
  que le trio mot-de-passe/KeePass documenté une seule fois plutôt que
  répété partout).
- Nouveau `tests/test_cli_verbose_flag_position.py` (15 tests, 2
  classes) :
  - `TestVerboseIsGlobalBeforeSubcommand` : paramétré sur les 6
    sous-commandes, `-v` avant → `parse_args` réussit et `ns.verbose is
    True` ; `-v` après → `SystemExit` ; plus un test de la valeur par
    défaut (`False`).
  - `TestUsageMdVerboseDocumentation` : vérifie que la note existe bien
    entre les titres `## Aide intégrée` et `## Référence des options`
    (contient `-v` et le mot « avant ») ; et surtout,
    `test_filter_override_example_parses_as_written` extrait le bloc
    `` ```bash `` suivant le titre « Config de base + surcharge
    ponctuelle du filtre » directement depuis le contenu actuel de
    `USAGE.md` (pas une copie codée en dur qui pourrait diverger), le
    tokenise avec `shlex.split` après avoir recollé la continuation de
    ligne (`\` + retour à la ligne), et vérifie qu'il parse sans lever
    `SystemExit`, avec les bonnes valeurs (`ns.action == "capture"`,
    `ns.verbose is True`, `ns.config`, `ns.capture_filter`).

### Vérifié réellement cette session

- Test rejoué contre la version d'origine (celle du zip d'entrée) :
  `USAGE.md` restauré temporairement (bloc de l'exemple remis à
  l'identique de l'original, `-v` après `capture`) →
  `test_filter_override_example_parses_as_written` échoue bien,
  `SystemExit: 2` / `unrecognized arguments: -v` confirmé dans le
  message d'erreur capturé. Note retirée séparément →
  `test_note_after_aide_integree_explains_placement` échoue bien
  (assertion `"-v" in note` qui devient fausse). Les deux corrections
  réappliquées → suite complète du fichier repasse à 15/15.
- `ruff format --line-length 120 tests/test_cli_verbose_flag_position.py` :
  1 fichier reformaté (les deux listes `argv` condensées éclatées en un
  élément par ligne, style déjà en usage dans ce projet) ; `ruff check
  --line-length 120 --no-cache` sur le fichier : 0 erreur après.
- `ruff check --line-length 120 --no-cache src/` : toujours exactement
  22 erreurs préexistantes, strictement identique aux sessions
  précédentes (`USAGE.md` n'est pas du Python, aucun fichier `.py` de
  `src/` touché cette session).
- Repéré au passage, hors périmètre de cette session : `ruff check
  --line-length 120 --no-cache tests/` sur l'ensemble du dossier (pas
  seulement le nouveau fichier) remonte 27 erreurs préexistantes,
  réparties sur d'autres fichiers de test plus anciens non touchés ici
  — 13 `RUF100` (`noqa` non applicable — probablement une évolution de
  version de `ruff` entre deux sessions plutôt qu'un vrai `noqa`
  superflu au moment où il a été écrit), 7 `C408`, 5 `PLW1510`, 1
  `I001`, 1 `F401`. Non corrigé — mentionné ici pour que ça ne soit pas
  (re)découvert en silence par une session future qui lancerait `ruff
  check` sur tout `tests/` en pensant tomber sur du neuf.
- Suite complète : **307 passés** (292 + 15 nouveaux), **4 échecs
  préexistants, 7 skips** — identiques en nature aux 6 sessions de la
  veille (06/09/2026) pour la cause des 4 échecs et des 7 skips : GTK4/PyGObject absent (`gi` présent mais
  `gi.require_version("Gtk", "4.0")` lève `ValueError: Namespace Gtk
  not available` — confirmé en sous-processus, cause exacte des 3
  échecs `test_gvfs_env_workaround.py` et de l'auto-skip des
  `test_gui_*.py`) ; `ip`/iproute2 absent (`FileNotFoundError: [Errno
  2] No such file or directory: 'ip'`, cause du 4e échec
  `test_taphelper_end_to_end_as_real_nonroot_user`).

### Résultat

`src/docs/USAGE.md` : l'exemple identifié comme cassé ne l'est plus —
copié/collé, il s'exécute désormais sans erreur de parsing.
Comportement de `-v`/`--verbose` (global, à placer avant la
sous-commande) désormais documenté explicitement plutôt que déductible
seulement en lisant `switch_capture_cli.py`. `features.md` : nouvelle
sous-section datée ; total du « Suivi des sessions » corrigé de 48 à 50
(la 6e session avait annoncé 49 dans son propre texte de « Résultat »
sans mettre à jour la liste énumérée ni le total affiché — les deux
entrées manquantes, 6e et 7e, ajoutées cette session).

### Reste ouvert

Inchangé par rapport aux 6 sessions de la veille (06/09/2026) : jamais
testé contre un switch réel, le volet durée-SCP réelle (« Pas fait »
n°1, switch physique requis), la relecture du `.po` `en_US` par une
personne anglophone native humaine, et les messages dynamiques du
Journal/corps `str(exc)` qui restent un choix de périmètre assumé
(point 13) plutôt qu'un oubli. Nouveau : les tables de référence
`mirror`/`inspect`/`analyze-pacing` n'ont pas de test de complétude
automatisé comparable à `tests/test_usage_md_completeness.py` (qui ne
couvre que `capture`/`uninstall`) — vérifiées manuellement complètes
cette session par introspection systématique, mais sans garde-fou
automatisé contre un oubli futur. Les 27 erreurs `ruff check`
préexistantes de `tests/` dans son ensemble ne sont pas corrigées non
plus (hors périmètre).

