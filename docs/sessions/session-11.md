# Session 11 — 26/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Sens de capture : inbound / outbound / bidirection (26/08/2026, suite)

Tâche suivante traitée dans `features.md` (« Comportement de capture »,
point 6 : « À rechercher (recherche internet) : `packet-capture` semble
ne pas capter les trames émises par le switch lui-même »). Même
contrainte d'environnement que le reste de cette journée : pas de
GTK4/PyGObject/Xvfb disponible, portée limitée au core/CLI, testable en
isolation (`pytest`).

**Recherche effectuée** (web) contre la documentation officielle H3C
(« Packet capture commands », plusieurs révisions du Command Reference
V7, cohérentes entre elles) : l'hypothèse posée par l'utilisateur est
**confirmée**, ce n'est pas un artefact de ce dépôt. La syntaxe exacte,
identique pour `packet-capture local` et `packet-capture remote` :

```
packet-capture local interface <iface> [ bidirection | outbound ]
    [ capture-filter <expr> | limit-frame-size <n> | ... ] * write ...
packet-capture remote interface <iface> [ bidirection | outbound ]
    [ port <port> ]
```

Sans `bidirection` ni `outbound`, seul le trafic **entrant** est capté —
il n'existe pas de mot-clé `inbound` explicite côté Comware, l'absence
des deux autres mots-clés EST le sens entrant. `bidirection` capture les
deux sens, `outbound` uniquement le trafic sortant.

**`build_capture_direction_clause(capture_direction)`** (nouvelle
fonction pure, `switch_capture_core.py`, même principe que
`build_capture_filter`) : retourne `"bidirection "`/`"outbound "` pour
ces deux valeurs, chaîne vide pour `"inbound"` (aucune clause n'est
envoyée dans ce cas, plutôt que d'inventer un mot-clé `inbound` qui
n'existe pas).

**Nouveau champ `Config.capture_direction: str = "bidirection"`**.
Point de conception délibéré : le défaut retenu ici est **différent** du
défaut Comware (qui serait "inbound" en l'absence de tout mot-clé) —
switch-capture capture désormais les deux sens par défaut, conformément
à l'objectif explicitement formulé par l'utilisateur (« capturer les
deux sens (both) »), plutôt que de reproduire silencieusement le défaut
historique du switch. Validé dans `Config.__post_init__`
(`inbound`/`outbound`/`bidirection` uniquement, `ValueError` sinon, même
style que la validation de `output_mode`/`transfer_mode`).

**CLI** : `--capture-direction {inbound,outbound,bidirection}` sur
`switch-capture capture` — un choix explicite à 3 valeurs (`choices=`),
pas un flag opt-out `store_const` comme `--no-hide-capture-traffic`,
puisqu'il n'y a pas de booléen naturel ici. Récupéré automatiquement par
`_CONFIG_FIELDS` sans code de câblage supplémentaire (même mécanisme
générique que pour `--output-mode`/`--transfer-mode`).

**Câblage dans les deux points d'entrée qui parlent réellement à
`packet-capture`** : `_run_capture_blocking_local` (`output_mode`
"fifo"/"tap") insère `direction_clause` juste après `interface <iface>`
et avant `filter_clause`, dans le même ordre que la doc H3C
(`[ bidirection | outbound ] [ capture-filter ... ]`) ; `_run_rpcap_blocking`
(`output_mode` "rpcap") l'insère juste avant `port <port>`. Vérifié
manuellement (pas juste relu) que la concaténation ne produit jamais de
double espace ni d'espace parasite dans aucune des combinaisons
(`inbound`/`outbound`/`bidirection` × filtre présent/absent).

`tests/test_capture_direction.py` (13 tests nouveaux) : les 3 valeurs de
`build_capture_direction_clause` (dont l'absence de clause pour
"inbound", espace final présent/absent selon le cas), le rejet d'une
valeur invalide par la fonction pure et par `Config.__post_init__`, le
défaut `"bidirection"` de `Config.capture_direction`, l'acceptation des
3 valeurs explicites côté `Config`, et le câblage CLI bout en bout
(`build_arg_parser` + `build_config` : `--capture-direction` répercuté
dans le `Config` construit, défaut `bidirection` conservé si l'option
est omise, `SystemExit` argparse sur un choix hors liste `choices=`).

`pytest tests/ -v` : **148 passed** (135 précédents + 13 nouveaux, aucune
régression). `ruff check --line-length 120 src/` : toujours **20**
erreurs, toutes `BLE001` préexistantes — aucune nouvelle catégorie
introduite par ce changement. `py_compile` sur
`switch_capture_core.py`/`switch_capture_cli.py` : OK.

**Non fait** : intégration GUI (sélecteur à 3 valeurs dans la future
page Préférences ou le formulaire principal, sur le modèle de
`hide_capture_traffic`/`archive_as_pcapng` — la page Préférences
elle-même n'existe pas encore), faute d'environnement GTK4/Xvfb dans
cette session. **Non vérifié empiriquement contre un switch réel** : la
syntaxe vient uniquement de la documentation H3C officielle (aucun
switch disponible dans cette session) — en particulier la disponibilité
réelle du mot-clé `bidirection` sur `packet-capture remote` reste à
confirmer au cas par cas selon modèle/version, comme le reste de
`packet-capture remote` (voir `CAPTURE-METHODS.md`). Tous les autres
points de la todo-list `features.md` restent également non traités,
notamment les deux priorités urgentes (mode non-root, sélection
packet-capture/mirroring/rpcap dans le formulaire).

