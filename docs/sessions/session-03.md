# Session 03 — 25/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Trousseau système pour le mot de passe SSH (`keyring`, 25/08/2026)

Traite la piste « Trousseau système (libsecret/GNOME Keyring) pour
mémoriser le mot de passe SSH entre deux lancements sans le stocker en
clair », listée dans « Pistes d'amélioration envisagées » ci-dessus,
désormais retirée de cette liste. Cohérent avec l'écosystème GNOME déjà
utilisé pour GCM : sous Linux, le backend retenu par le module `keyring`
est GNOME Keyring/libsecret via le service D-Bus standard « Secret
Service » — aucun mot de passe n'est jamais écrit en clair sur disque par
ce mécanisme, contrairement à un modèle de capture (`models/*.yaml`, voir
section dédiée plus haut) qui exclut délibérément `ssh_password` pour
cette même raison.

- **`switch_capture_core.py`** : import optionnel de `keyring` (même
  motif que `netmiko`/`paramiko` en tête de fichier — `ImportError` capturé,
  `KEYRING_AVAILABLE = keyring is not None`, jamais un `ImportError` brut
  qui casserait tout le reste de l'outil pour qui n'a pas installé cette
  dépendance). Quatre nouvelles fonctions, service `KEYRING_SERVICE_NAME =
  "switch-capture"`, une entrée par couple switch/utilisateur
  (`keyring_account_id(switch_ip, ssh_user)` → `"<user>@<ip>"`, fonction
  pure) :
  - `save_ssh_password_to_keyring(switch_ip, ssh_user, password)` : lève
    `RuntimeError` si `keyring` est absent ou si l'écriture échoue
    (trousseau verrouillé, service Secret Service absent...) — une demande
    explicite de mémorisation qui échoue silencieusement serait trompeuse
    pour l'utilisateur.
  - `load_ssh_password_from_keyring(switch_ip, ssh_user)` : renvoie `None`
    dans tous les cas d'échec (absent, `keyring` non installé, trousseau
    inaccessible) — volontairement silencieux, une lecture automatique ne
    doit jamais bloquer un usage CLI disposant d'un autre moyen de fournir
    le mot de passe (`--ssh-password`/`SWITCH_SSH_PASSWORD`).
  - `delete_ssh_password_from_keyring(switch_ip, ssh_user)` : idempotente,
    renvoie `True`/`False` selon qu'une entrée a effectivement été
    supprimée, jamais d'exception.
- **`switch_capture_cli.py`** : deux nouveaux flags, en groupe
  mutuellement exclusif au niveau argparse, sur `capture`, `uninstall` (via
  `_add_common_config_args`, partagé par les deux) et `inspect` (ajoutés
  séparément, ce sous-parseur ne passant pas par `_add_common_config_args`) :
  - `--remember-password` : mémorise, dans le trousseau système, le mot de
    passe effectivement résolu pour cette invocation (quelle qu'en soit la
    source — `--ssh-password`, `SWITCH_SSH_PASSWORD` ou déjà le trousseau).
  - `--forget-password` : retire l'entrée mémorisée pour ce couple
    switch/utilisateur.
  - `_apply_password_keyring_actions(args, switch_ip, ssh_user, ssh_password)` :
    factorise l'application des deux flags une fois la config validée
    (appelée depuis `main()` pour `capture`/`uninstall`, et depuis
    `run_inspect()`), ne lève jamais (un échec de `--remember-password` est
    journalisé en `warning` sans interrompre la commande).
  - **Résolution automatique, sans flag dédié** — `_maybe_fill_password_from_keyring(raw)`,
    appelée par `build_config`/`build_inspect_config` juste avant de
    construire `Config`/`InspectConfig` : si aucun mot de passe n'a été
    fourni par CLI/YAML ni par `SWITCH_SSH_PASSWORD`, et que `switch_ip`/
    `ssh_user` sont connus, tente une lecture dans le trousseau — **même
    ordre de priorité** que celui déjà appliqué en interne par
    `Config.__post_init__` pour la variable d'environnement (CLI/YAML >
    `SWITCH_SSH_PASSWORD` > trousseau), pour que les deux mécanismes ne
    divergent jamais sur l'ordre de résolution. Symétrique au principe déjà
    en place pour `SWITCH_SSH_PASSWORD` : aucun flag n'est nécessaire pour
    *profiter* d'un mot de passe déjà mémorisé, seul `--remember-password`
    est nécessaire pour l'y déposer la première fois.
- **`requirements.txt`/`requirements-dev.txt`** : `keyring` documenté comme
  dépendance strictement optionnelle (`Recommends`, jamais `Depends` — même
  statut que PyGObject), avec les paquets système équivalents
  (`python3-keyring` Debian/Ubuntu et Fedora/RHEL) en repli pip. Non ajoutée
  aux scripts de packaging (`install.sh`/`build_deb.sh`/`build_rpm.sh`) —
  volontairement, pour rester cohérent avec le traitement déjà réservé à
  PyGObject dans ces mêmes scripts (dépendance recommandée mais jamais
  installée de force).

**Limite assumée** : `--remember-password` mémorise le mot de passe
*résolu pour cette invocation*, avant toute tentative de connexion réelle
au switch — pas seulement après un succès. Un mot de passe erroné fourni
avec ce flag est donc mémorisé tel quel (et devra être corrigé via un
nouveau `--remember-password` ou retiré via `--forget-password`) ; ce choix
garde la sémantique simple et prévisible (« mémorise ce que je viens de
taper »/« comme SWITCH_SSH_PASSWORD, mais persistant ») plutôt que de
coupler la mémorisation au résultat de la connexion, qui aurait demandé un
remaniement plus large des trois sous-commandes concernées pour un gain
incertain.

**Testé réellement (pas juste relu)** :
- 22 tests `pytest` nouveaux (voir `tests/test_keyring_password.py`,
  section Tests automatisés ci-dessus) — `keyring_account_id` en isolation ;
  `save`/`load`/`delete_ssh_password_from_keyring` avec un faux backend
  `keyring` en mémoire (`FakeKeyringModule`, même principe que `FakeConn`
  pour l'audit de commandes) monkeypatché sur `switch_capture_core.keyring`,
  couvrant le round-trip, la non-fuite entre comptes, l'idempotence de la
  suppression, et l'échec d'écriture (`RuntimeError`) ; comportement avec
  `KEYRING_AVAILABLE = False` (module absent) sur les trois fonctions ;
  `_maybe_fill_password_from_keyring` (priorité CLI/YAML > env >
  trousseau, non-consultation du trousseau si l'env var est déjà
  positionnée, no-op sans `switch_ip`/`ssh_user`) et `build_config` de bout
  en bout ; `_apply_password_keyring_actions` (remember, forget, aucun
  flag, échec de remember non levé, attributs absents traités comme
  `False` pour un sous-parseur qui n'exposerait pas ces options).
- **Round-trip validé contre un vrai service Secret Service** (pas
  seulement le faux backend ci-dessus) : `gnome-keyring` installé dans
  l'environnement de cette session (`apt install gnome-keyring`), une vraie
  session D-Bus dédiée (`dbus-run-session -- bash -c '...'`) avec
  `gnome-keyring-daemon --unlock --daemonize --components=secrets` (mot de
  passe fourni sur l'entrée standard, motif classique pour un trousseau
  headless en CI — crée le trousseau de connexion s'il n'existe pas encore,
  l'unlock à l'identique s'il existe déjà). Scénario CLI complet exécuté
  dans cette session sous cette session D-Bus : `switch-capture inspect
  --remember-password` avec un mot de passe fourni en clair → mémorisé
  (log `INFO` confirmé) ; relance de `switch-capture inspect` **sans**
  `--ssh-password` ni `SWITCH_SSH_PASSWORD` → mot de passe retrouvé
  automatiquement et identique à l'original (log `DEBUG` confirmé) ;
  `delete_ssh_password_from_keyring` appelée directement → suppression
  réelle confirmée (`True`, puis `load_...` renvoie `None`) ; nouvelle
  tentative de construction de `InspectConfig` sans mot de passe disponible
  par aucun moyen → `ValueError` explicite comme attendu (pas de
  régression du garde-fou existant de `InspectConfig.__post_init__`).
  Script de validation ad hoc, non committé (même choix que les
  validations GTK sous Xvfb de ce dépôt) — ce round-trip nécessite un vrai
  service Secret Service D-Bus, indisponible dans l'environnement habituel
  de `pytest tests/`, donc pas intégrable à cette suite (même raisonnement
  que pour GTK4/PyGObject, voir section Tests automatisés ci-dessus).
- `py_compile` + import réel de `switch_capture_core.py`/`switch_capture_cli.py` :
  aucune régression de signature (`KEYRING_AVAILABLE` exposée et vraie dans
  cet environnement, puisque `keyring` y est installé pour les tests).
- `pytest tests/ -v` : **106 passed** (84 précédents + 22 nouveaux, aucune
  régression).
- `ruff check --line-length 120 src/` : 34 erreurs, strictement identique à
  l'état du dépôt avant ce changement (même version de ruff que la session
  précédente, 0.16.4) ; sur `switch_capture_core.py`/`switch_capture_cli.py`
  seuls, 25 erreurs, également identique — aucune sur les lignes
  ajoutées/modifiées ici. `tests/test_keyring_password.py` est ruff-clean
  (`ruff check --fix` a réordonné les imports une fois, avant validation).

**Non fait dans cette session (25/08/2026, session CLI/core)** :
intégration GUI (case à cocher « Se souvenir du mot de passe » dans le
formulaire GTK4, bouton « Oublier le mot de passe mémorisé ») — champ
transversal aux trois sous-commandes CLI mais pas encore câblé côté
`switch_capture_gtk.py` ; le mécanisme lui-même (core + CLI) est complet
et testé, voir ci-dessus. **Traité dans une session ultérieure, voir
« Intégration GUI du trousseau système » plus bas.**

