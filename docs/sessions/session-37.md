# Session 37 — 05/09/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Implémentation core + CLI du mode `--mode vxlan` (05/09/2026)

Suite directe de la session précédente (ci-dessus) : l'utilisateur a
fourni la syntaxe exacte manquante — VLAN 666, groupe de mirroring 10,
VSI `mirror`, VNI 666, Tunnel 0 en mode vxlan, raccordement du VLAN à la
VSI par `service-instance` — permettant de passer à l'implémentation.
Portée volontairement limitée à **core + CLI** cette session, la GUI
suivra dans une session ultérieure : même séquencement que pour le
filtrage ACL (core+CLI le 01/09/2026, GUI le 02/09/2026).

### Ce qui a été fait

**`switch_capture_core.py`** :

- `MirrorConfig.mode` accepte désormais `"vxlan"` en plus de
  `"local"`/`"gre"`. 5 nouveaux champs : `remote_probe_vlan` (VLAN
  sonde), `vsi_name`, `vxlan_vni`, `service_instance_id` (optionnel,
  déduit de `group_id` si omis — même schéma que `classifier_name` et
  consorts en `filter_mode="acl"`), `reflector_interface` (obligatoire —
  port physique dédié au mécanisme classique de reflector-port ET au
  raccordement VSI). Réutilise directement `group_id`/`tunnel_id`/
  `tunnel_local_ip`/`remote_ip`/`source_interfaces` déjà existants
  (mêmes concepts que pour `--mode gre` : numéro de groupe, numéro et
  source/destination de l'interface Tunnel).
- Docstring de `MirrorConfig` (paramètre `reflector_interface`)
  documente explicitement le statut de cette fonctionnalité : combine
  un mécanisme H3C officiellement documenté (remote-probe VLAN +
  reflector port) avec un autre documenté séparément (VSI/VXLAN/
  service-instance) — la combinaison précise n'a pas été retrouvée
  telle quelle dans un exemple H3C officiel unique, traitée comme
  valide sur la foi du retour d'expérience direct de l'utilisateur
  (05/09/2026), séquence de commandes best-effort à vérifier contre le
  switch réel avant tout déploiement en production.
- Validation dans `__post_init__` : les 6 champs requis en mode vxlan
  (`remote_probe_vlan`/`vsi_name`/`vxlan_vni`/`tunnel_local_ip`/
  `remote_ip`/`reflector_interface`), plage `remote_probe_vlan` (1-4094)
  et `vxlan_vni` (0-16777215). **Piège repéré et corrigé en cours de
  session** : la vérification « champ manquant » utilisait initialement
  `if not v` (calquée sur le style déjà en place pour `gre_required`) —
  or `remote_probe_vlan`/`vxlan_vni` sont des entiers où `0` est une
  valeur à valider par plage, pas une valeur « absente » ; `not 0` vaut
  `True` en Python, donc un VLAN ou VNI à `0` était incorrectement
  rejeté comme « champ manquant » plutôt que « hors plage » — repéré
  par un test dédié qui échouait avec le mauvais message d'erreur,
  corrigé en `v is None or v == ""` (traite `None` et chaîne vide comme
  manquants, mais pas l'entier `0`).
- `mode="vxlan"` **non combinable avec `filter_mode="acl"`** pour
  l'instant : refusé explicitement (`ValueError`) plutôt que
  silencieusement mal géré — les interactions entre les deux mécanismes
  (mirror-to inline de l'ACL vs. mirroring-group + VSI classiques) n'ont
  pas été étudiées.
- `configure_vxlan_mirror()`/`teardown_vxlan_mirror()`, nouvelles
  fonctions, même style que `configure_gre_mirror`/`configure_acl_mirror`
  (liste de commandes, `conn.send_command`, logs `debug`/`info`).
  Séquence de configuration : VLAN sonde → VSI + VNI → interface Tunnel
  en mode vxlan (source/destination, **sans** adresse IP contrairement
  au mode gre — un tunnel vxlan est un transport L2 pur, pas une
  interface L3) → raccordement tunnel↔VSI → `service-instance` sur le
  port réflecteur (`encapsulation s-vid <vlan>` + `xconnect vsi <nom>`)
  → `mirroring-group` (`remote-probe vlan` + `mirroring-port` +
  `reflector-port`). Teardown dans l'ordre inverse (groupe d'abord,
  puis service-instance, puis tunnel↔VSI, puis interface Tunnel avec
  gestion de la confirmation « Continue? [Y/N] » comme `teardown_mirror`
  en mode gre, puis VSI, puis VLAN) — un élément encore référencé ne
  peut pas être supprimé, même logique que `teardown_acl_mirror`.
- `MirrorThread.run()` : nouvelle branche de dispatch pour
  `mode == "vxlan"`, configure et teardown, messages de statut dédiés.

**`switch_capture_cli.py`** :

- `--mode` accepte `vxlan` (choix étendu, aide reformulée pour
  mentionner les 3 modes). 5 nouvelles options :
  `--remote-probe-vlan`, `--vsi-name`, `--vxlan-vni`,
  `--service-instance-id`, `--reflector-interface`. Aide de
  `--tunnel-local-ip`/`--remote-ip` reformulée (« mode gre ou vxlan »
  au lieu de « mode gre » seul, ces champs étant réutilisés tels quels).
- Câblage automatique via `_MIRROR_CONFIG_FIELDS` (dérivé de
  `dataclasses.fields(MirrorConfig)`) — **aucune modification de
  `run_mirror` nécessaire**, seulement l'ajout des arguments argparse
  avec les bons `dest=`, exactement comme pour l'ajout de l'ACL le
  01/09/2026.

**i18n CLI** (point 13) :

- Nouvelles/modifiées `help=` enveloppées dans `_(...)` comme le reste
  de la CLI. `xgettext --language=Python --from-code=UTF-8 -o
  locale/switch-capture.pot switch_capture_cli.py switch_capture_gtk.py`
  ré-exécuté depuis `src/` (même commande que toutes les sessions i18n
  précédentes) → 142 `msgid` contre 137 avant (5 entièrement nouvelles +
  3 dont le texte source a changé, remplaçant les anciennes — msgmerge
  les a marquées `fuzzy` avec l'ancienne traduction proche comme point
  de départ). En-tête du `.pot` restauré à la main après extraction
  (`xgettext` réécrit `Project-Id-Version`/`Copyright` par défaut à
  chaque régénération, comme toutes les sessions précédentes).
  `msgmerge --update --backup=none` sur le `.po` `en_US` existant : 6
  entrées vides + 3 `fuzzy` — les 9 traduites à la main en anglais via
  un petit script `polib` (plus fiable qu'une édition manuelle du `.po`
  généré pour appliquer plusieurs traductions d'un coup), flags `fuzzy`
  levés, `PO-Revision-Date` mis à jour, `.mo` recompilé
  (`msgfmt --check` propre).

**`src/docs/CAPTURE-METHODS.md`** :

- Nouvelle section 5, **explicitement marquée expérimentale** :
  bandeau d'avertissement en tête de section (statut, ce qui n'a pas
  été vérifié), principe du mécanisme (VLAN sonde → VSI VXLAN plutôt
  que trunk L2 classique), séquence de commandes équivalente à la main,
  configuration côté collecteur Linux (`ip link add ... type vxlan`,
  hors périmètre de switch-capture — même philosophie que « pousse
  uniquement la configuration de mirroring sur le switch » déjà en
  vigueur pour les sections 3 et 4), réponse à la question de
  l'utilisateur sur l'authentification, et une section « Limites et
  réserves connues » dédiée (VXLAN matériel a priori réservé aux
  modèles HI, reflector port supposé par analogie mais non confirmé
  indépendamment, MTU non géré automatiquement, non combinable avec
  `--filter-mode acl`, jamais testé contre un switch réel).
- En-tête du document et tableau de vue d'ensemble mis à jour
  (« quatre façons » → « cinq façons », nouvelle ligne de tableau avec
  ⚠️), entrée ajoutée dans « Laquelle choisir ? ».
- **Réponse à la question de l'utilisateur sur l'authentification** :
  le VXLAN standard (RFC 7348) n'a **aucune** authentification ni
  chiffrement natifs — le VNI est un identifiant de segment, pas un
  secret. Même posture que GRE/ERSPAN (sections 3 et 4), déjà sans
  chiffrement ni authentification dans ce dépôt. Mitigation pratique
  documentée : restreindre par pare-feu/ACL le port UDP 4789 du
  collecteur à la seule IP source du switch — pas de mécanisme
  d'authentification supplémentaire prévu par switch-capture lui-même.

**`README.md`** : « Quatre façons » → « Cinq façons », nouvelle
section 5 (plus courte que les autres, avec avertissement explicite en
tête, renvoi vers `CAPTURE-METHODS.md` pour le détail complet des
réserves), 2 mentions numériques mises à jour (« quatre méthodes » →
« cinq », tableau de structure du dépôt).

### Vérifié réellement cette session

- Génération de la séquence de commandes exacte testée avec les
  paramètres **exacts** fournis par l'utilisateur (VLAN 666, groupe 10,
  vsi=mirror, vni=666, tunnel 0, service-instance) via un faux `conn`
  qui journalise chaque commande — séquence conforme à la conception,
  relue et validée avant d'écrire les tests dessus.
- **26 nouveaux tests** dans `tests/test_mirror_vxlan.py` (nouveau
  fichier, même style que `test_mirror_acl_filter.py` : `FakeConn`
  minimal journalisant `send_command`/`send_command_timing`, sans
  connexion SSH réelle) — validation complète de `MirrorConfig` en
  mode vxlan (y compris le piège VLAN/VNI=0 ci-dessus, capturé par
  `test_remote_probe_vlan_out_of_range_rejected[0]`), séquence exacte
  de commandes pour configure/teardown, gestion de la confirmation
  Y/N, non-régression des modes local/gre existants — tous passés.
- Suite complète (`pytest tests/`, Xvfb réel + GTK4 typelib) : **364
  passés (338 + 26 nouveaux), 2 échecs préexistants sans rapport, 0
  skip** — 0 régression. Les 2 échecs confirmés une fois de plus
  identiques et sans rapport : `test_gvfs_env_workaround.py` et
  `test_taphelper_end_to_end_as_real_nonroot_user` (`ip`/iproute2
  absent).
- `ruff check --line-length 120` sur `src/` : toujours 22 erreurs (les
  mêmes `BLE001` préexistants), aucune nouvelle. Aucune ligne ajoutée
  ne dépasse 120 caractères — vérifié avec `awk 'length > 120
  {print FILENAME":"FNR}'` (`FNR`, pas `NR`, pour ne pas fausser le
  décompte en passant plusieurs fichiers à `awk` en une seule
  invocation — piège repéré et corrigé en cours de vérification).
  `py_compile` OK sur `switch_capture_core.py`/`switch_capture_cli.py`.
- `tests/test_gtk_i18n_translations.py` (17 tests, complétude i18n
  **GUI**) intégralement repassé après régénération du `.pot`/`.po`/
  `.mo` — toujours 17/17, aucune régression malgré l'extraction commune
  CLI+GUI.
- `switch-capture mirror --help`, en français et avec
  `LANGUAGE=en_US`, relu visuellement dans les deux langues — rendu
  propre, nouvelles options correctement documentées et traduites.
- Les 2 commandes d'exemple ajoutées (`CAPTURE-METHODS.md` et
  `README.md`) parsées avec succès contre le vrai `build_arg_parser()`
  de `switch_capture_cli.py` — jamais un exemple non testé, comme le
  reste de ce dépôt.

### Résultat

`switch-capture mirror --mode vxlan` pilotable en CLI, entièrement
testé (hors switch réel), documenté dans `CAPTURE-METHODS.md`/
`README.md` avec ses réserves explicites. `features.md` : point 20 mis
à jour avec le détail complet de l'implémentation, intro remesurée
(lignes de code, 364 passés/2 échecs/0 skip), décompte de sessions
incrémenté (42 → 43).

### Reste ouvert

- **Câblage GUI** : le menu déroulant `mirror_mode` du formulaire GTK4
  reste limité à `local`/`gre` (`self._mirror_mode_options`), et les 5
  nouveaux champs n'ont pas de widgets — même schéma que pour l'ACL
  (core+CLI d'abord le 01/09, GUI ensuite le 02/09). Point de départ
  pour une future session : `_row_multiline` n'est pas nécessaire ici
  (pas de liste répétable côté vxlan), seulement des `_row`/`_row_spin`
  classiques + extension de `_apply_mirror_mode_visibility` pour un
  3e cas de figure.
- **Jamais testé contre un switch réel** : toute la séquence de
  commandes reste une reconstruction best-effort (voir
  `CAPTURE-METHODS.md` section 5 et le docstring de
  `MirrorConfig.reflector_interface`) — à valider par l'utilisateur
  contre son 5520 HI avant tout déploiement en production. En
  particulier : le rôle exact du reflector port combiné au
  raccordement VSI n'a pas été confirmé indépendamment de la parole de
  l'utilisateur ; l'absence d'adresse IP sur l'interface Tunnel en mode
  vxlan (contrairement au mode gre) est déduite du modèle Comware
  général observé ailleurs, pas spécifiquement confirmée pour ce
  switch.
- Sans changement par ailleurs : le volet durée-SCP réelle (« Pas fait »
  n°1, switch physique requis) et la relecture du `.po` `en_US` par une
  personne anglophone native humaine.

