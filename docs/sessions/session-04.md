# Session 04 — 25/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Intégration GUI du trousseau système (25/08/2026, session ultérieure)

Câble le mécanisme core/CLI ci-dessus dans `switch_capture_gtk.py` :
case à cocher « mémoriser dans le trousseau système » + bouton
« Oublier le mot de passe mémorisé » sous le champ mot de passe SSH
(`_row_remember_password`), écriture au moment de l'ajout d'une capture
si la case est cochée (`_maybe_remember_password`, tâche de fond),
suppression réelle sur clic du bouton (`_on_forget_password`), et
auto-remplissage silencieux du mot de passe quand le focus quitte
`switch_ip`/`ssh_user` si une entrée est déjà mémorisée
(`_maybe_autofill_password`, `Gtk.EventControllerFocus`) — sans jamais
écraser une saisie existante. Aucun de ces éléments n'est un champ de
`Config` : ni lus par `_build_config`, ni sérialisés dans les modèles de
capture réutilisables, même principe que `ssh_password` lui-même. Case et
bouton désactivés avec infobulle si `KEYRING_AVAILABLE` est faux. Détail
complet, y compris la méthodologie de test, dans features.md.

**Piège d'environnement rencontré et contourné** (spécifique à cette
session, sans rapport avec le code livré) : lancer l'environnement
GTK4/Xvfb via `dbus-run-session` (comme pour les validations CLI/trousseau
précédentes) provoquait un échec systématique et déterministe de
`Gtk.init_check()` au tout premier appel dans chaque nouveau processus (le
flag `initialized` de l'override PyGObject se figeant à `False` avant que
la connexion X11 ne soit pleinement établie — confirmé en reproduisant
l'échec avec un `XOpenDisplay` Xlib direct, hors GTK). Contourner ce flag
en le forçant manuellement à `True` provoquait un `Segmentation fault` à
la création de la première fenêtre (état interne GDK déjà corrompu par
l'échec initial, pas récupérable après coup). Cause racine réelle,
distincte de ce symptôme : `Xvfb`/`dbus-daemon`/`gnome-keyring-daemon`
lancés en arrière-plan simple (`cmd &`) ne survivaient pas d'un appel
d'outil à l'autre dans cette session (processus enfant d'un shell
lui-même éphémère) — remplacés par un lancement détaché
(`setsid cmd > log 2>&1 < /dev/null &`), stable d'un appel à l'autre, ce
qui a fait disparaître le symptôme GTK sans qu'aucun contournement du
flag ne soit nécessaire.

