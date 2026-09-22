# Session 40 — 06/09/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Documentation : options `--mode vxlan` manquantes dans USAGE.md (06/09/2026, 3e session du jour)

En reprenant la todo-list une 3e fois dans la même journée, aucune
tâche numérotée nouvelle n'était faisable sans switch réel ni relecture
humaine native — recherche d'un oubli de documentation, sur le modèle
de la session du 03/09/2026 (README resté à « trois méthodes » après
l'ajout de la 4e ; voir « Mise à jour du README pour la 4e méthode de
capture » ci-dessus).

`src/docs/USAGE.md` affirmait encore « quatre méthodes de capture »
(intro de la section sous-commandes CLI) et sa table « Référence des
options — `mirror` » ne documentait `--mode` que pour `local`/`gre` —
aucune trace des 5 options propres à `--mode vxlan`
(`--remote-probe-vlan`, `--vsi-name`, `--vxlan-vni`,
`--service-instance-id`, `--reflector-interface`), ni d'exemple de
commande — alors que ce mode est implémenté core+CLI depuis le 05/09
(voir « Implémentation core + CLI du mode `--mode vxlan` » ci-dessus)
et câblé en GUI depuis le 06/09 (voir « Câblage GUI du mode `--mode
vxlan` » ci-dessus). `README.md` et `CAPTURE-METHODS.md`, eux, étaient
déjà à jour (5 méthodes, section 5 dédiée) — seul `USAGE.md`, resté en
retard d'une session, n'avait pas suivi.

### Ce qui a été fait

- « quatre méthodes » → « cinq méthodes » dans l'intro de la section
  sous-commandes CLI, liste complétée avec le mirroring VXLAN.
- Table `mirror` : ligne `--mode` complétée pour citer `vxlan` (avec
  renvoi à `CAPTURE-METHODS.md` section 5) ; 5 nouvelles lignes pour
  les options dédiées, reprenant exactement les descriptions déjà
  écrites côté `help=` de `switch_capture_cli.py` (`build_arg_parser`,
  lignes ~599-625) pour rester cohérent avec l'aide intégrée
  (`--help`) ; `--tunnel-local-ip`/`--remote-ip` reformulées « mode
  `gre` ou `vxlan` » — elles étaient déjà partagées par les deux modes
  côté CLI, simplement pas documentées comme telles jusqu'ici.
- Nouvelle sous-section d'exemple « Mirroring vers VLAN sonde + VXLAN L2
  (⚠️ expérimental) », même gabarit que les 3 exemples `mirror`
  existants (local/GRE/ACL), renvoyant vers `CAPTURE-METHODS.md`
  section 5 pour le détail de la config poussée sur le switch (VSI,
  service-instance, tunnel VXLAN) et la commande `ip link add ... type
  vxlan` à lancer manuellement côté collecteur.

### Vérifié réellement cette session

- La commande d'exemple ajoutée (`switch-capture mirror --mode vxlan
  --group-id 10 --source-interface GigabitEthernet1/0/1
  --remote-probe-vlan 666 --vsi-name mirror --vxlan-vni 666
  --reflector-interface GigabitEthernet1/0/2 --tunnel-local-ip
  10.0.0.1 --remote-ip 203.0.113.10`) parsée avec succès contre le vrai
  `build_arg_parser()` de `switch_capture_cli.py` — pas seulement
  relue visuellement — avec vérification explicite des attributs
  résultants (`mode`, `vsi_name`, `vxlan_vni`, `reflector_interface`),
  un exemple non testé aurait été contraire à la rigueur du reste de
  ce dépôt.
- Suite complète (aucun fichier `.py` touché cette session, uniquement
  `src/docs/USAGE.md`) : **287 passés, 4 échecs préexistants sans
  rapport, 7 skips** — identique à la session précédente (correctif
  i18n GUI), confirme l'absence d'impact. Environnement inchangé :
  GTK4/PyGObject absent (`test_gui_*.py` auto-skippés), `ip`/iproute2
  et `gvfs` toujours non installables (dépôts miroir en 404).

### Résultat

`src/docs/USAGE.md` aligné avec `README.md`/`CAPTURE-METHODS.md` sur
les 5 méthodes de capture disponibles et le détail complet des options
`--mode vxlan`. `features.md` : nouvelle sous-section datée, compteur
de sessions incrémenté (45 → 46).

### Reste ouvert

Inchangé par rapport à la session précédente : jamais testé contre un
switch réel, le volet durée-SCP réelle (« Pas fait » n°1, switch
physique requis), la relecture du `.po` `en_US` par une personne
anglophone native humaine, et les messages dynamiques du
Journal/corps `str(exc)` qui restent un choix de périmètre assumé
(point 13) plutôt qu'un oubli.

