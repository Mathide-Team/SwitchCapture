# Session 31 — 01/09/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Filtrage ACL pour `switch-capture mirror` — core + CLI (01/09/2026, 2e session du jour)

Piste d'amélioration notée dans la session précédente (voir ci-dessus,
« Pistes d'amélioration envisagées, non implémentées ») **traitée cette
session, côté core + CLI**. La GUI GTK4 n'est pas câblée — reste ouvert.

### Ce qui a été fait

- `MirrorConfig` (`switch_capture_core.py`) : nouveaux champs
  `filter_mode` (`"port"` par défaut, comportement `mirroring-group`
  historique inchangé, ou `"acl"`), `acl_number` (3000 par défaut),
  `acl_rules` (liste de règles ACL avancée complètes, ex. `"rule 0 permit
  ip source 10.0.0.5 0"`, envoyées telles quelles), `classifier_name`/
  `behavior_name`/`qos_policy_name` (optionnels, déduits de `group_id` si
  omis — ex. `SWCAP_CLS_1`/`SWCAP_BEH_1`/`SWCAP_POL_1`).
  `__post_init__` valide `acl_number` dans 3000-3999 hors 3998/3999
  (réservés cluster management — plage confirmée par recherche web cette
  session, cohérente avec `acl advanced 3000` déjà utilisé comme exemple
  dans `CAPTURE-METHODS.md` section 4 depuis la session précédente).
  En mode `"gre"` + `filter_mode="acl"`, `tunnel_ip` n'est **plus** requis
  (contrairement au mode `"gre"` historique) : aucune interface Tunnel
  n'est créée, l'encapsulation ERSPAN est inline dans le `mirror-to`.
- Deux nouvelles fonctions dans `switch_capture_core.py`, au même niveau
  que `configure_local_mirror`/`configure_gre_mirror`/`teardown_mirror`
  déjà existantes (aucune des trois n'avait de test dédié avant cette
  session — voir plus bas) :
  - `configure_acl_mirror(conn, cfg)` : `acl advanced <n>` + règles +
    `quit` → `traffic classifier <nom>` + `if-match acl <n>` + `quit` →
    `traffic behavior <nom>` + `mirror-to interface <if>` (local) ou
    `mirror-to interface destination-ip <ip> source-ip <ip>` (GRE) +
    `quit` → `qos policy <nom>` + `classifier ... behavior ...` + `quit`
    → pour chaque interface source : `qos apply policy <nom> inbound`
    et/ou `outbound` selon `direction`.
  - `teardown_acl_mirror(conn, cfg)` : ordre inverse — retire d'abord
    `qos apply policy` de chaque interface (`undo qos apply policy
    inbound`/`outbound`, sans nom de policy — un seul type par sens et
    par interface, confirmé par recherche web cette session), puis
    `undo qos policy`/`undo traffic behavior`/`undo traffic classifier`/
    `undo acl advanced`, dans cet ordre (une qos policy encore appliquée
    ne peut pas être supprimée).
  - Piège repris de `CAPTURE-METHODS.md` section 4 (vérifié contre la
    doc H3C en session précédente) : `qos apply policy` n'accepte jamais
    `both`, contrairement à `mirroring-group ... mirroring-port ...
    both` — une commande par sens dans les deux fonctions.
- `MirrorThread.run()` : dispatch vers `configure_acl_mirror`/
  `teardown_acl_mirror` quand `self.mirror_cfg.filter_mode == "acl"`,
  sinon comportement `"port"` inchangé (branche `if/elif` ajoutée avant
  les branches `mode == "local"`/`else` existantes).
- CLI (`switch_capture_cli.py`) : 6 nouvelles options ajoutées au
  sous-parseur `mirror` — `--filter-mode {port,acl}` (défaut `port`),
  `--acl-number` (int, défaut 3000), `--acl-rule` (`action="append"`,
  répétable), `--classifier-name`, `--behavior-name`, `--qos-policy-name`.
  Câblage automatique côté `run_mirror` via `_MIRROR_CONFIG_FIELDS`
  (dérivé de `dataclasses.fields(MirrorConfig)`) — aucune modification
  nécessaire de `run_mirror` lui-même, seulement l'ajout des arguments
  argparse avec les bons `dest=`. `help=` de `mirror` et de `--teardown`
  légèrement reformulés pour mentionner le nouveau mode.
- i18n : les nouveaux `help=` enveloppés dans `_(...)` comme le reste de
  la CLI (point 13). `xgettext --language=Python --from-code=UTF-8 -o
  locale/switch-capture.pot switch_capture_cli.py switch_capture_gtk.py`
  ré-exécuté depuis `src/` (même commande que les sessions
  précédentes) → 137 `msgid` contre 131 avant (6 entièrement nouvelles +
  2 dont le texte source a changé, remplaçant les anciennes). En-tête du
  `.pot` restauré à la main après extraction (`xgettext` réécrit
  `Project-Id-Version`/`Copyright` avec ses valeurs par défaut à chaque
  régénération — déjà le cas les sessions précédentes, pas un problème
  nouveau, juste réappliqué). `msgmerge --update --backup=none` sur le
  `.po` `en_US` existant : 6 nouvelles entrées vides + 2 marquées `fuzzy`
  (l'ancienne traduction reprise comme point de départ, texte source
  proche) — les 8 traduites à la main en anglais, flag `fuzzy` levé,
  0 entrée non traduite/fuzzy/obsolète restante (136 `msgid`
  traduisibles au total). Recompilé en `.mo` avec `msgfmt` (le paquet
  `gettext`, absent du sandbox en début de session, installé via
  `apt-get install gettext` — réseau apt disponible cette session,
  contrairement à plusieurs sessions précédentes).

### Vérifié réellement cette session

- **32 nouveaux tests** (`tests/test_mirror_acl_filter.py`), sur le
  modèle `FakeConn` de `test_inspect.py` (le seul autre fichier de test
  à mocker `config_mode`/`send_command`/`exit_config_mode` directement) :
  validation `MirrorConfig` (plage `acl_number` avec cas limites
  3000/3500/3997 acceptés et 2999/4000/3998/3999/1 rejetés, noms par
  défaut dérivés de `group_id`, noms explicites respectés, non-régression
  du mode `"port"` par défaut — `acl_rules` non requis, `tunnel_ip`
  toujours requis en mode `"gre"` classique), séquence exacte de
  commandes envoyées par `configure_acl_mirror`/`teardown_acl_mirror`
  (comparaison de liste complète, pas seulement des sous-chaînes ;
  local et GRE ; direction `both`/`inbound`/`outbound`, avec vérification
  explicite qu'aucune commande ne contient jamais `"both"` ; plusieurs
  interfaces source ; plusieurs règles ACL, ordre préservé), et dispatch
  `MirrorThread.run()` (`switch_capture_core.ConnectHandler` monkeypatché
  vers un `FakeConn`, `configure_local_mirror`/`configure_gre_mirror`
  remplacées par une fonction qui lève `AssertionError` si appelée à
  tort — aucune connexion SSH réelle).
- Suite complète : `python3 -m pytest tests/ -q` → **258 passés** (226
  préexistants + les 32 nouveaux), **4 échecs, 7 skips** — mêmes échecs
  qu'en tout début de session, avant toute modification (vérifié en
  lançant la suite sur le zip tel qu'uploadé avant d'y toucher) :
  `test_gvfs_env_workaround.py` (×3, GTK4/typelib absent de ce sandbox)
  et `test_taphelper_end_to_end_as_real_nonroot_user` (binaire `ip`
  absent) — sans lien avec ce changement, 0 régression introduite.
- `ruff check --line-length 120 --no-cache` sur `switch_capture_core.py`
  et `switch_capture_cli.py` : comparé à une copie du zip original
  extraite à part et jamais modifiée — **exactement les 17 mêmes
  erreurs préexistantes** des deux côtés (mêmes codes de règle, mêmes
  occurrences, seuls les numéros de ligne diffèrent, cohérent avec le
  code ajouté), 0 nouvelle erreur. `awk 'length > 120'` sur les 3
  fichiers touchés (les deux fichiers core + le nouveau fichier de
  test) : les seules lignes dépassant 120 caractères sont dans
  `switch_capture_cli.py`, déjà présentes avant cette session à
  l'identique (même nombre, mêmes longueurs, juste décalées).
  `py_compile` OK sur les 3 fichiers.
- `switch-capture -c mirror --help` comparé français (défaut) vs
  `LANGUAGE=en_US` : les 6 nouvelles options et les 2 aides reformulées
  s'affichent traduites et complètes dans les deux langues (`grep -A2`
  sur chaque nouvelle option, les deux sorties comparées ligne à ligne).
  `msgfmt --check` sur le `.po` final : OK, aucune erreur de format.

### Résultat

`switch-capture mirror` gère désormais deux modes de filtrage :
`--filter-mode port` (mirroring-group historique, comportement par
défaut inchangé) et `--filter-mode acl` (flow mirroring filtré par ACL
avancée + politique QoS, nouveau). `CAPTURE-METHODS.md` section 4 n'est
plus « non pilotée par switch-capture » — nouvelle sous-section « Ce que
fait switch-capture automatiquement » sur le modèle des sections 1-3 ;
table de vue d'ensemble et section « Laquelle choisir ? » mises à jour
en conséquence. `USAGE.md` : tableau de référence des options `mirror`
complété (6 lignes) et nouvel exemple ajouté. `features.md` : nouvelle
sous-section datée, décompte de sessions mis à jour (35 → 37, incluant
la session doc-only précédente qui n'avait pas encore été comptée côté
`features.md` — seul `CLAUDE.md` en gardait trace jusqu'ici), intro
« Capture — 3 méthodes distinctes » devenue « 4 méthodes distinctes ».

### Reste ouvert

- **Câblage GUI** de `--filter-mode acl` et des options associées
  (`--acl-number`/`--acl-rule`/`--classifier-name`/`--behavior-name`/
  `--qos-policy-name`) : non fait cette session, CLI uniquement — voir
  « Câblage GUI de 4 réglages core/CLI déjà traités » (28/08/2026) pour
  le pattern déjà suivi sur `--mode local/gre`, réutilisable ici
  (probablement un `Gtk.ComboBoxText` pour `filter_mode`, un champ
  `Gtk.Entry` répétable ou multi-lignes pour `acl_rules`, et les
  widgets se révèlent/masquent selon le mode choisi, comme le fait déjà
  le formulaire pour `mode == "gre"`).
- Comme depuis plusieurs sessions, sans changement : le volet
  durée-SCP réelle (« Pas fait » n°1, switch physique requis) et la
  relecture du `.po` `en_US` par une personne anglophone native
  (8 entrées de plus depuis cette session, jamais relues par un
  locuteur natif comme le reste du fichier).
- Le débit en direct côté switch (2e piste d'amélioration listée dans la
  session précédente) reste non implémenté — nécessite un switch réel
  pour vérifier le format exact de sortie CLI avant de l'implémenter,
  non abordé cette session (une seule tâche traitée par session, comme
  demandé).

