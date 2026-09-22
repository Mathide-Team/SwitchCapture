# Session 15 — 28/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Câblage GUI de 4 réglages core/CLI déjà traités (28/08/2026)

Tâche suivante traitée dans `features.md` (« Menu et préférences »/
« Filtre de capture »/« Comportement de capture », points 5, 6, 14, 19).
Détail complet, y compris le résultat des tests, dans `features.md`
(section datée du même jour) — résumé ici du côté « pourquoi/comment ».

**Changement d'environnement, à noter pour les sessions suivantes** :
contrairement aux 3 sessions précédentes (25 au 27/08/2026), ce sandbox
dispose de GTK4/PyGObject (`gir1.2-gtk-4.0`, installable via `apt-get`,
`archive.ubuntu.com`/`security.ubuntu.com` étant autorisés), d'Xvfb, et
d'`iproute2` (`ip`), ainsi que d'un accès pip/PyPI complet. Les trois
manquaient jusqu'ici et étaient explicitement cités comme bloquants pour
tout le câblage GUI en attente et pour les deux priorités urgentes (17,
18). **Ne pas supposer que cet accès persistera** d'une session à
l'autre : revérifier à chaque fois plutôt que de se fier à cette note.

**Ce qui a été fait** : `hide_capture_traffic` (case à cocher),
`capture_direction` (menu déroulant) — tous deux dans la section
« Capture », visibles quel que soit `output_mode`, puisque le filtre et
le sens de capture ne dépendent pas du mode de sortie choisi —,
`archive_as_pcapng` (case à cocher, juste après « Dossier d'archivage »,
visible seulement en mode fichier `fifo`/`tap`) et `tap_launch_wireshark`
(case à cocher, rejoint `tap_cleanup_on_stop`/`tap_pace_playback`,
visible seulement en mode `tap`). Câblés dans les 4 points d'entrée du
formulaire (`_build_config`, `_collect_raw_form_values`/
`_apply_form_values`, `_config_to_raw_dict`) — même discipline que les
champs existants, aucun raccourci pris.

**Pourquoi pas la future page Préférences** : comme déjà noté pour
`tap_cleanup_on_stop`/`tap_pace_playback` (24-25/08/2026) et
`tap_launch_wireshark` (26/08/2026), la page Préférences n'existe pas
encore et n'est de toute façon pas la bonne destination pour des réglages
qui s'appliquent à *une* capture donnée plutôt qu'à l'application dans
son ensemble — seuls l'utilisateur par défaut, le dépôt `.bin`, NTP et
« Sortie live » dans leur ensemble sont candidats à cette page (voir
point 3, « Menu et préférences », dans `features.md`).

**Testé réellement**, premier câblage GUI de ce projet vérifié avec un
vrai GTK4/PyGObject/Xvfb plutôt que différé faute d'environnement :
suite pytest existante rejouée à l'identique (175 tests, aucune
régression), nouvelle suite `tests/test_gui_new_fields.py` (9 tests,
construction réelle de fenêtre via `Gtk.Application.run()`/Xvfb, avec
repli `pytest.skip` propre si aucun affichage n'est accessible — vérifié
explicitement en désactivant `DISPLAY`), capture d'écran réelle ciblée
par `xdotool`/ID de fenêtre (piège `import -window root` déjà documenté
le 26/08/2026, toujours évité). **184 tests réels passés, 0 échec.**

**Piège rencontré** : la première tentative d'ouvrir une fenêtre GTK4
sous Xvfb échouait avec `Gtk couldn't be initialized` malgré
`Gtk.init_check()` retournant `True` et `DISPLAY`/`GDK_BACKEND=x11`
correctement positionnés — cause identifiée : chaque appel d'outil bash
de ce sandbox démarre un shell indépendant, donc un `Xvfb &` lancé dans
un appel précédent ne survit pas jusqu'à l'appel suivant (le process est
tué avec le shell qui l'a lancé). Il faut démarrer Xvfb et exécuter le
script Python GTK4 **dans la même invocation shell**.

**Non fait** : les deux priorités urgentes (17 — mode non-root pour la
création d'interface TAP ; 18 — sélection packet-capture/mirroring/rpcap
dans le formulaire) restent non traitées, cette session ayant porté
volontairement sur une tâche plus petite et moins risquée à livrer en une
seule réponse. Contrairement aux sessions précédentes, ce n'est **plus**
un problème d'environnement (`ip` et GTK4/Xvfb sont désormais
disponibles) : ces deux points sont donc réellement prêts à être
attaqués dès la prochaine session, sans blocage restant côté outillage.

