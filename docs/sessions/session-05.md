# Session 05 — 26/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Correctif : `sudo` + interface graphique + RDP (26/08/2026)

**Symptôme rapporté** : `sudo ./switch-capture` (nécessaire pour le mode
`tap`) plantait systématiquement sur une session RDP (xrdp) avec en tête
du message `Authorization required, but no authorization protocol
specified`, puis un `Traceback` Python se terminant par `RuntimeError: Gtk
couldn't be initialized` — alors que la même commande fonctionnait sans
`sudo`, sur la même session.

**Diagnostic, reproduit fidèlement** (pas juste déduit) : environnement de
test avec un vrai `Xvfb` + un vrai cookie X11 généré via `xauth add`,
d'abord avec `XAUTHORITY` correct (reproduit le cas « sans sudo » : ça
marche), puis avec `HOME=/root` et `XAUTHORITY` pointant vers un fichier
inexistant (reproduit exactement ce que fait `sudo` par défaut) → message
d'erreur et traceback strictement identiques à ceux rapportés, ligne par
ligne. Cause : `sudo` réinitialise `HOME` par défaut (donc `XAUTHORITY`),
donc root ne trouve plus le cookie d'autorisation X11 de la session —
cookie qui vit dans le `.Xauthority` de l'utilisateur normal, pas dans
celui de root. Une session console locale bénéficie souvent d'un `xhost`
automatique pour `localuser:root` mis en place par le gestionnaire de
connexion ; une session xrdp, non — d'où l'écart RDP/local rapporté.

**Piste explorée et abandonnée** : détecter ce cas en amont via
`Gtk.init_check()`, appelé explicitement dans `main()` avant de construire
la fenêtre. Rejetée après test réel : dans ce contexte précis (appel
direct hors de `Gtk.Application.run()`), `Gtk.init_check()` renvoie `True`
même quand l'affichage n'est pas accessible — le flag réellement fiable
est `gi.overrides.Gtk.initialized`, calculé UNE SEULE FOIS à l'import de
`gi.repository.Gtk`, donc déjà figé (correctement, en l'occurrence) avant
même que `main()` ne s'exécute. Le lire directement aurait été fragile
(attribut interne non public de PyGObject) — et une session précédente de
ce projet a déjà obtenu un `Segmentation fault` en manipulant ce même flag
à la main (voir « Intégration GUI du trousseau système », piège
d'environnement ci-dessus). Retenu à la place : laisser PyGObject lever
son propre `RuntimeError` (comportement déjà déterministe, confirmé par la
reproduction ci-dessus) et le capturer précisément là où il se produit.

**Fix retenu**, dans `switch_capture_gtk.py` : `CaptureApp.do_activate`
encadre la construction de `CaptureWindow` dans un `try/except
RuntimeError` qui vérifie le message exact
(`_DISPLAY_INIT_ERROR_MARKER = "Gtk couldn't be initialized"`, pour ne
jamais masquer sous ce diagnostic un `RuntimeError` différent qui
surviendrait par ailleurs dans la fenêtre) avant d'afficher un diagnostic
actionnable (`_print_display_error`, les 3 solutions détaillées dans
USAGE.md) et d'arrêter proprement l'app (`self.quit()`). Corrige aussi un
bug annexe découvert pendant le diagnostic : `Gtk.Application.run()`
renvoyait `0` malgré ce crash (l'exception ne remonte jamais hors du
callback `do_activate`, avalée par le dispatch de signal de PyGObject) —
`main()` renvoie désormais explicitement `1` via `CaptureApp.exit_code`,
positionné par `do_activate`.

**Testé réellement** :
- Reproduction fidèle du bug original avec le vrai `switch_capture_gtk.py`
  (avant correctif) sous Xvfb + `XAUTHORITY` cassé : message et traceback
  strictement identiques à ceux rapportés.
- Même scénario après correctif : diagnostic clair affiché, exit code 1,
  plus de traceback.
- Non-régression : lancement complet de l'app sous Xvfb + `XAUTHORITY`
  correct → fenêtre s'ouvre normalement (capture d'écran prise), icône
  appliquée (voir section suivante).
- Sans rapport direct avec `pytest tests/` (entrée GTK4, non couvert par
  la suite headless existante — même raisonnement que les autres
  validations GTK sous Xvfb de ce dépôt) ; aucune régression sur la suite
  existante par ailleurs.

Documenté côté utilisateur dans USAGE.md, section « Dépannage ».

