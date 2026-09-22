# Session 06 — 26/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Icône de l'application (26/08/2026)

L'app n'avait jusqu'ici aucune icône ni entrée de menu applications.
Ajout minimal mais complet : icône SVG (thème hicolor standard) + fichier
`.desktop`, câblés dans les 3 méthodes d'installation ET en lancement non
installé (le cas d'usage réel de ce dépôt — livré par zip à chaque
session, pas forcément installé via `install.sh`).

**Fichiers** : `src/icons/hicolor/scalable/apps/org.transcende.
switch_capture.svg` (dessiné à la main : châssis de switch stylisé avec
ports/LEDs + loupe de capture) et `src/org.transcende.
switch_capture.desktop` (`Icon=org.transcende.switch_capture`,
`Exec=switch-capture -g` — force la GUI explicitement, cohérent avec un
lancement depuis un menu sans terminal visible ; `StartupWMClass` aligné
sur l'`application_id` GTK4). Le nom reprend tel quel l'`application_id`
GTK4 déjà existant, par convention freedesktop/GNOME (même identifiant
pour l'app, son icône et son `.desktop`) — désormais une constante
partagée `APP_ID` dans `switch_capture_gtk.py` plutôt qu'une chaîne
littérale dupliquée.

**API GTK4 vérifiée empiriquement, pas supposée** (comme le reste de ce
fichier — pas d'environnement GTK4 fiable en mémoire, chaque comportement
d'API est donc vérifié pour de vrai avant d'être utilisé) :
- `Gtk.Window.set_icon_name`/`set_default_icon_name` existent toujours en
  GTK4 4.14 : confirmé par introspection directe.
- `Gtk.IconTheme.add_search_path(chemin)` attend un chemin **racine
  contenant les dossiers de thème** (ex. `.../icons/`, qui contient
  `hicolor/`) — PAS le dossier `hicolor/` lui-même. Contre-intuitif, et
  faux à la première tentative : `add_search_path(".../icons/hicolor")`
  compile sans erreur mais `theme.has_icon(...)` renvoie silencieusement
  `False` (repli sur une icône générique via `lookup_icon`, qui ne lève
  jamais — `has_icon` est le bon test d'existence). Confirmé en testant
  les deux structures côte à côte avant de trancher.
- Bout en bout, dans le vrai contexte d'exécution (`do_activate`, sous
  `Gtk.Application.run()` — le comportement diffère d'un script nu) :
  `_NET_WM_ICON` et `_GTK_APPLICATION_ID` vérifiés via `xprop` sur la
  fenêtre réellement ouverte sous Xvfb, capture d'écran à l'appui.

**Résolution en mode non installé** (`_register_app_icon`, appelée en
tout début de `do_activate`) : ajoute `<dossier du script>/icons` comme
chemin de recherche du thème d'icônes courant, sans effet (dossier absent)
une fois installé — où la même arborescence est déjà fusionnée dans
`/usr/share/icons/hicolor`, couverte par le thème système par défaut, et
où c'est alors `_GTK_APPLICATION_ID` + le `.desktop` qui font la
correspondance côté environnement de bureau. `Gtk.Window.
set_default_icon_name(APP_ID)` est appelé dans tous les cas (inoffensif si
l'affichage n'est pas disponible, voir correctif sudo/RDP ci-dessus).

**Packaging**, les 3 méthodes, chacune construite/installée réellement
(pas juste relue) :
- `install.sh` : nouveaux `ICON_DIR`/`DESKTOP_DIR`
  (`/usr/share/icons/hicolor/scalable/apps`, `/usr/share/applications`),
  copie + `gtk-update-icon-cache`/`update-desktop-database` best-effort
  (`command -v ... || true`, jamais bloquant). **Testé avec `--prefix` sur
  un répertoire réellement vide** (pas un chroot déjà pourvu d'un
  `usr/bin`) — a révélé au passage un bug latent préexistant, voir
  plus bas.
- `packaging/build_deb.sh` + `debian/DEBIAN/postinst`/`postrm` : mêmes
  fichiers copiés dans l'arbre FHS du `.deb`, même rafraîchissement
  best-effort dans les scripts de maintenance. **`.deb` réellement
  construit avec `dpkg-deb`** et contenu vérifié (`dpkg-deb -c`).
- `packaging-rpm/switch-capture.spec` + `build_rpm.sh` : mêmes fichiers
  dans `%files`, même rafraîchissement best-effort en `%post`/`%postun`
  (filet de sécurité — `hicolor-icon-theme`/`desktop-file-utils`
  fournissent normalement des *file triggers* équivalents sur el9+).
  **`.rpm` réellement construit avec `rpmbuild`** (qui a détecté et
  déclaré tout seul `Provides: application(org.transcende.
  switch_capture.desktop)`) et contenu vérifié (`rpm -qlp`).

**Bug latent découvert en testant `install.sh --prefix` sur un répertoire
vide** (préexistant, sans rapport avec l'icône — jamais visible en usage
réel où `PREFIX=""` et `/usr/bin` existe toujours déjà) : `$BIN_DIR`
n'était jamais créé par un `install -d`. Corrigé (une ligne), retesté avec
succès.

