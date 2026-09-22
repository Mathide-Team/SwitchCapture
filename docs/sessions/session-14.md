# Session 14 — 27/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Repli KeePass pour le mot de passe SSH (`pykeepass`, 27/08/2026)

Traite la partie « repli sur un fichier KeePass si aucun trousseau système
n'est installé » de la piste listée dans features.md (section « Menu et
préférences », point 4) — le trousseau système (`keyring`, voir section
dédiée plus haut) reste le mécanisme principal et **toujours prioritaire** ;
ce repli ne sert que sur une machine sans trousseau système (headless,
service Secret Service absent) où `keyring` est indisponible.

- **`switch_capture_core.py`** : import optionnel de `pykeepass`
  (`PyKeePass`, `CredentialsError`), même motif que `keyring` juste
  au-dessus — `ImportError` capturé, `KEEPASS_AVAILABLE = PyKeePass is not
  None`. Trois nouvelles fonctions, même signature/sémantique que leurs
  équivalents `keyring` (même `keyring_account_id` comme titre d'entrée,
  pour rester cohérent entre les deux mécanismes) :
  - `save_ssh_password_to_keepass(switch_ip, ssh_user, password, keepass_path, keepass_master_password)` :
    lève `RuntimeError` si `pykeepass` est absent, si le fichier `.kdbx`
    n'existe pas (**cette fonction n'en crée jamais** — la base doit être
    créée au préalable par l'utilisateur, ex. avec KeePassXC), si le mot de
    passe maître est incorrect, ou si l'écriture échoue pour toute autre
    raison.
  - `load_ssh_password_from_keepass(switch_ip, ssh_user, keepass_path, keepass_master_password)` :
    renvoie `None` dans tous les cas d'échec (module absent, chemin/mot de
    passe maître non fournis, fichier absent, mot de passe maître
    incorrect) — volontairement silencieux, même raisonnement que
    `load_ssh_password_from_keyring`.
  - `delete_ssh_password_from_keepass(...)` : idempotente, `True`/`False`,
    jamais d'exception.
  - `_open_keepass_db(keepass_path, keepass_master_password)` : factorise
    l'ouverture (vérification d'existence du fichier + `PyKeePass(...)`)
    avec des messages d'erreur explicites (`RuntimeError`), utilisée par
    les trois fonctions ci-dessus.
- **`switch_capture_cli.py`** : un nouveau flag `--keepass-path` (sur
  `capture`/`uninstall`, via `_add_common_config_args`, et sur `inspect`
  séparément) — **n'est volontairement pas un champ de `Config`** (même
  statut que `--remember-password`/`--forget-password` : un réglage du
  mécanisme de mémorisation, pas de la capture elle-même), donc extrait de
  `raw`/`args` par `build_config`/`build_inspect_config` **avant** le
  filtrage sur `_CONFIG_FIELDS`/`_INSPECT_CONFIG_FIELDS` qui l'aurait sinon
  éliminé silencieusement. Le mot de passe maître de la base, comme
  `SWITCH_SSH_PASSWORD`, n'est **jamais** accepté en argument CLI en
  clair : uniquement via la variable d'environnement
  `SWITCH_CAPTURE_KEEPASS_PASSWORD` (`_resolve_keepass_master_password()`).
  - `_maybe_fill_password_from_keyring(raw, keepass_path=None)` : signature
    étendue (compatible, `keepass_path` optionnel) — tente d'abord le
    trousseau système comme avant ; si celui-ci ne renvoie rien (absent,
    aucune entrée, verrouillé), tente le repli KeePass **seulement** si
    `keepass_path` et `SWITCH_CAPTURE_KEEPASS_PASSWORD` sont tous les deux
    disponibles. Ordre de priorité complet, inchangé pour les trois
    premiers niveaux : CLI/YAML > `SWITCH_SSH_PASSWORD` > trousseau système
    > repli KeePass.
  - `_apply_password_keyring_actions(...)` : le repli KeePass n'est utilisé
    pour `--remember-password`/`--forget-password` que si `KEYRING_AVAILABLE`
    est faux **et** que `--keepass-path`/`SWITCH_CAPTURE_KEEPASS_PASSWORD`
    sont fournis (`keepass_fallback_ready`) — jamais en plus du trousseau
    système quand celui-ci est disponible, même si `--keepass-path` traîne
    dans la configuration (ex. réglage laissé après une migration de
    machine). Si `--remember-password` est demandé sans qu'aucun des deux
    mécanismes ne soit disponible, un `warning` explicite est journalisé
    (ancien comportement : silence total dans ce cas précis, seul le futur
    échec de connexion l'aurait révélé) — ne lève toujours jamais.
- **`requirements.txt`/`requirements-dev.txt`** : `pykeepass` documenté
  comme dépendance strictement optionnelle, même statut que `keyring`
  (jamais ajoutée à `install.sh`/`build_deb.sh`/`build_rpm.sh`). Pas de
  paquet système équivalent identifié pour Debian/Ubuntu/Fedora/RHEL à ce
  jour (contrairement à `python3-keyring`) : seul `pip install pykeepass`
  est documenté.
- **`src/docs/USAGE.md`** : nouvelle sous-section « Mémoriser le mot de
  passe SSH entre deux lancements » (section Exemples), couvrant à la fois
  le trousseau système (déjà utilisable depuis le 25/08/2026 mais jusqu'ici
  non documenté dans ce fichier) et ce repli KeePass — traite la partie
  « documentation utilisateur » du point 4 de features.md.

**Limite assumée, identique à celle du trousseau système** :
`--remember-password` mémorise dans le fichier KeePass le mot de passe
*résolu pour cette invocation*, avant toute tentative de connexion réelle
au switch — même raisonnement que pour `keyring` (voir section dédiée plus
haut), pas de remaniement propre à ce repli.

**Portée volontairement restreinte** : `save_ssh_password_to_keepass` ne
crée jamais de nouvelle base `.kdbx` — un fichier absent est une erreur
explicite (`RuntimeError`), jamais une création silencieuse. Cohérent avec
le principe déjà appliqué au trousseau système (cet outil ne configure
jamais de service système à sa place, il consulte/alimente ce qui existe
déjà) et évite une gestion de groupes/permissions de fichier `.kdbx`
nouvellement créé, hors périmètre.

**Testé dans cette session, avec les limites d'environnement suivantes**
(pas d'accès réseau/pip dans ce sandbox, contrairement aux sessions
précédentes — ni `pykeepass`, ni `pytest`, ni `loguru`/`netmiko`/
`paramiko`/`keyring` eux-mêmes ne sont installables ici) :
- `py_compile` sur les deux fichiers source Python modifiés
  (`switch_capture_core.py`, `switch_capture_cli.py`) : aucune erreur de
  syntaxe.
- Modules tiers absents (`loguru`, `netmiko`, `paramiko`, `scp`, `PyYAML`)
  remplacés par des bouchons minimalistes (`sys.path` dédié) pour permettre
  l'import réel de `switch_capture_core`/`switch_capture_cli` malgré
  l'absence de réseau — **`keyring` non bouché** : son absence réelle dans
  ce sandbox reproduit fidèlement le scénario ciblé par ce repli (poste
  sans trousseau système), `KEYRING_AVAILABLE` vaut donc `False` sans
  artifice.
- `pykeepass` bouché par un faux backend en mémoire (`FakePyKeePass`, un
  dict par chemin de fichier, aucune vraie base `.kdbx` chiffrée lue/écrite)
  — même principe que `FakeKeyringModule`/`FakeConn` déjà utilisés ailleurs
  dans ce dépôt pour tester sans dépendance externe réelle.
- Sur ces bases, exécution réelle (pas juste relue) de : le cycle complet
  save/load/delete + non-fuite entre comptes + écrasement d'une entrée
  existante + idempotence de la suppression + mot de passe maître
  incorrect (lecture silencieuse à `None`, écriture avec `RuntimeError`) +
  fichier absent (`RuntimeError`, jamais de création) directement sur les
  fonctions `switch_capture_core` ; puis le câblage CLI de bout en bout :
  priorité trousseau système > KeePass, priorité `SWITCH_SSH_PASSWORD` >
  KeePass, non-consultation du repli si `keyring` est disponible,
  `--remember-password`/`--forget-password` avec et sans `--keepass-path`,
  et `build_config` bout en bout avec mot de passe résolu depuis le repli
  KeePass ; enfin présence de `--keepass-path` dans l'analyseur
  d'arguments (`capture`, `inspect`) et son absence sans erreur sur
  `mirror`.
- Ce même travail de vérification a ensuite été transcrit en une suite
  `pytest` dédiée committée dans le dépôt (`tests/test_keepass_password.py`,
  27 tests, même style que `tests/test_keyring_password.py` : fixtures
  `fake_pykeepass`/`keepass_unavailable`, `monkeypatch` sur
  `switch_capture_core.PyKeePass`/`CredentialsError`) — **non exécutable
  par un vrai `pytest` dans ce sandbox précis** (absent, pas d'accès
  réseau pour l'installer), mais exécutée réellement ici via un mini-shim
  compatible (fixtures/`monkeypatch`/`tmp_path`/`raises`, non committé,
  strictement pour cette vérification) reproduisant l'API `pytest` utilisée
  par ce fichier : **27 passed, 0 failed**. À ré-exécuter avec un vrai
  `pytest` dès qu'un environnement avec accès réseau est disponible, pour
  confirmation — même réserve que celle déjà documentée dans ce fichier
  pour d'autres validations dépendant de l'environnement (Xvfb/GTK4,
  service Secret Service réel).
- `ruff` non disponible dans ce sandbox (pas d'accès réseau) : pas
  d'exécution de `ruff check` sur les fichiers modifiés cette session,
  contrairement aux sessions précédentes qui y avaient accès — à refaire
  dès que possible.

**Non fait dans cette session** : câblage GUI (`switch_capture_gtk.py`) —
champ « chemin du fichier KeePass » et lecture de
`SWITCH_CAPTURE_KEEPASS_PASSWORD`/prompt dédié, sur le modèle de
l'intégration GUI du trousseau système ci-dessus ; nécessiterait aussi de
décider où stocker `--keepass-path` de façon persistante côté GUI (futur
`config.yaml`/page Préférences, encore à créer — voir features.md, point
1-4) puisque ce n'est pas un champ de `Config`. GTK4/PyGObject et Xvfb ne
sont de toute façon pas disponibles dans ce sandbox pour le valider
visuellement, comme pour d'autres tâches GUI de ce projet.

