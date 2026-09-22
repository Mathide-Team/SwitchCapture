# Session 12 — 26/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Lancement automatique de Wireshark en mode TAP (`tap_launch_wireshark`, 26/08/2026, suite)

Tâche suivante traitée dans `features.md` (« Fonctionnalités », point
14). Contexte d'environnement inhabituel pour cette session : en plus de
l'absence habituelle de GTK4/PyGObject/Xvfb, **aucune dépendance du
projet n'était installée** (ni `loguru`, ni `pytest`, ni `paramiko`/
`netmiko`/`scp`/`keyring`, pas d'accès réseau pour les installer) — un
environnement plus contraint que les sessions précédentes, qui pouvaient
toutes lancer `pytest tests/ -v` directement. Portée limitée au
core/CLI, comme le reste de cette journée.

**`_launch_wireshark_tap()`** (nouvelle méthode de
`CaptureRotationThread`, juste après `_launch_wireshark` dans
`switch_capture_core.py`) : `subprocess.Popen(["wireshark", "-k", "-i",
tap_interface])`, appelée depuis `_setup_tap()` juste après
`ensure_tap_interface()` si `Config.tap_launch_wireshark` est activé.
Différence de fond avec `_launch_wireshark` (mode "fifo") : celle-ci
**ne bloque jamais**. `_launch_wireshark` doit ouvrir le FIFO en
écriture (`open(fifo_path, "wb")`), ce qui bloque tant que Wireshark n'a
pas ouvert l'autre bout en lecture — d'où le lancement de Wireshark
*avant* cette ouverture. En mode TAP, l'interface existe déjà comme
périphérique réseau noyau dès le retour de `ensure_tap_interface()` (un
`ip tuntap add` + `ip link set up` déjà synchrones) : Wireshark s'y
attache via pcap comme sur n'importe quelle interface, sans poignée de
main à orchestrer. Les trames écrites par `TapFrameWriter` avant que
Wireshark n'ait fini de démarrer sont simplement perdues, comme pour
toute capture réseau démarrée après le début du trafic — ce n'est pas
un bug à corriger, juste la sémantique normale d'une interface réseau.

**Nouveau champ `Config.tap_launch_wireshark: bool = False`**. Point de
conception délibéré, différent du choix fait pour `_launch_wireshark`
(mode "fifo", qui lance Wireshark inconditionnellement, sans option pour
désactiver) : la docstring de `CaptureRotationThread` présente
explicitement le mode TAP comme un moyen d'observer **plusieurs**
captures simultanées dans une **unique** instance Wireshark, lancée
manuellement par l'utilisateur et attachée à toutes les interfaces TAP à
la fois. Chaque `CaptureRotationThread` tourne indépendamment et ignore
les autres (aucun état partagé entre threads de capture différents) :
un auto-lancement inconditionnel casserait ce cas d'usage en ouvrant une
fenêtre distincte par capture. D'où un opt-in explicite, désactivé par
défaut, avec la docstring qui documente ce compromis plutôt que de le
laisser implicite. Sans effet en `output_mode` "fifo" (déjà couvert par
`_launch_wireshark`) ou "rpcap" (Wireshark s'y connecte nativement en
réseau, aucun processus local à lancer) — non validé dans
`__post_init__`, même choix que `tap_pace_playback`/`tap_cleanup_on_stop`
(un champ sans effet hors mode "tap" n'est pas une erreur de
configuration, juste un réglage ignoré).

**CLI** : `--tap-launch-wireshark` (`store_true`, `default=None`) sur
`switch-capture capture`, même style que `--tap-cleanup-on-stop`/
`--tap-pace-playback` — un flag d'activation plutôt qu'un opt-out
`store_const` comme `--no-hide-capture-traffic`, puisque `Config` vaut
déjà `False` par défaut ici (l'opt-out sert quand le défaut `Config` est
`True` et qu'il faut préserver ce défaut si l'option YAML est absente ;
ici c'est l'inverse). Récupéré automatiquement par `_CONFIG_FIELDS` sans
câblage supplémentaire.

**Documentation** : entrée ajoutée à la table d'options et à l'exemple
« Captures multiples simultanées via TAP » de `USAGE.md` (avec le même
avertissement sur le compromis multi-fenêtres qu'ici), et à
`config.yaml.example`.

**Méthodologie de test inhabituelle pour cette session**, documentée ici
pour que la prochaine session comprenne pourquoi les chiffres ne
ressemblent pas à `pytest tests/ -v` : sans réseau pour installer quoi
que ce soit, `loguru` (seule dépendance importée sans garde
`try/except ImportError` dans `switch_capture_core.py` — `netmiko`/
`paramiko`/`scp`/`keyring` le sont déjà tous, seul `loguru` bloquait
même l'import du module) a été remplacé par un stub minimal local (un
`logger` qui accepte n'importe quel appel sans effet), placé hors du
dépôt et jamais copié dans le zip livré, uniquement pour permettre
d'exécuter réellement le code de vérification de cette session. De même
un mini-runner reproduisant `tmp_path`/`monkeypatch`/`pytest.raises`/
`pytest.approx`/`capsys` (sans `@pytest.mark.parametrize`) a permis de
faire tourner pour de vrai la suite existante : **117 tests réels
passés, 0 échec**, sur 9 des 10 fichiers `test_*.py` (tout sauf
`test_keyring_password.py`, fixtures dédiées non reproduites, module
`keyring` de toute façon absent et sans lien avec ce changement). Plus
12 vérifications ciblées nouvelles sur `tap_launch_wireshark` (Popen
appelé/non appelé selon le flag et avec les bons arguments, ordre
d'appel après `ensure_tap_interface`, `_wireshark_proc` correctement
affecté, câblage CLI avec/sans le flag, non-écrasement d'une valeur
YAML par le défaut `argparse`), et un aller-retour explicite par
`config_to_template_dict`/`save_capture_template`/`load_capture_template`/
`template_dict_to_config_kwargs` confirmant que le nouveau champ survit
à la sérialisation d'un modèle réutilisable. `py_compile` sur les deux
fichiers modifiés : OK. `ruff` non disponible non plus dans cette
session (pas de vérification de style possible).

**Non fait** : câblage GUI. Ici la « future page Préférences » n'est
**pas** forcément la bonne réponse — contrairement à
`hide_capture_traffic`/`archive_as_pcapng`/`capture_direction` (26/08),
`tap_cleanup_on_stop` et `tap_pace_playback` (24-25/08), les deux
options `tap_*` les plus proches de celle-ci, sont **déjà** câblées
comme cases à cocher directement dans le formulaire principal
(`switch_capture_gtk.py`, `_row_check("tap_cleanup_on_stop", ...)` /
`_row_check("tap_pace_playback", ...)`, visibles seulement si
`output_mode == "tap"` via `_apply_output_mode_visibility`) : la case
`tap_launch_wireshark` devrait logiquement les rejoindre au même
endroit plutôt que d'attendre une page qui n'existe pas encore. Toujours
faute d'environnement GTK4/PyGObject/Xvfb dans cette session. **Non
vérifié empiriquement** : ni contre un switch réel, ni même avec un
binaire `wireshark` réel (absent également de cette session) — seul
l'appel `subprocess.Popen` et ses arguments ont été vérifiés par
substitution, pas le comportement de Wireshark une fois lancé pour de
vrai. Tous les autres points de la todo-list `features.md` restent
également non traités, notamment les deux priorités urgentes (mode
non-root, sélection packet-capture/mirroring/rpcap dans le formulaire).

