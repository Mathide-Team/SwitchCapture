# switch_capture — orchestrateur de capture réseau HPE Comware

Automatise, sur un switch HPE Comware 7, 4 méthodes de capture réseau
(packet-capture local, packet-capture remote/RPCAP, port mirroring
SPAN/ERSPAN, mirroring distant VLAN+VXLAN L2) ainsi que la désinstallation
propre de la configuration poussée. Détail : `docs/architecture.md`.

## État courant

- 63 sessions de développement documentées (23/08 → 16/09/2026) —
  index : `docs/sessions/index.md`
- 20/20 demandes numérotées historiques traitées, 0 point numéroté encore
  ouvert
- **Dépendances gérées par `uv` depuis la session 63** (remplace `pip` +
  `requirements.txt`/`requirements-dev.txt`, supprimés) : `pyproject.toml`
  porte désormais `[project]` (métadonnées + dépendances runtime) et
  `[dependency-groups]` (`dev` synchronisé par défaut, `quality` — ruff/
  coverage — sur demande via `--group quality`), verrouillées dans
  `uv.lock` (nouveau fichier, 65 paquets résolus). Toujours aucun
  `[build-system]` : le choix « pas de packaging » (voir
  `tests/conftest.py`) n'a pas changé, voir `docs/sessions/session-63.md`
  pour la vérification complète (doc `uv` officielle citée, projet
  effectivement non installé dans son propre venv). Ni `install.sh` ni
  `build_deb.sh`/`build_rpm.sh` ne touchent à `uv` : ils listaient déjà
  leurs dépendances indépendamment de `requirements.txt`, donc
  inchangés — voir « Commandes de qualité » ci-dessous pour les nouvelles
  commandes de développement.
- Suite de tests : 661 passés (632 + 29), 1 échec préexistant sans
  rapport (`ip`/`iproute2` absent de ce sandbox), 10 skips
  (GTK4/PyGObject indisponible) — inchangé numériquement depuis la
  session 62, revérifié via `uv run pytest -q` en session 63
- `uv run --group quality ruff check .` (dépôt entier, pas seulement les
  fichiers modifiés) :
  **0 erreur** — 53 erreurs pré-existantes
  (`BLE001`/`C408`/`RUF100`/`PLW1510`, accumulées sur plusieurs sessions)
  corrigées en session 58, détail : `docs/sessions/session-58.md`
- `uv run --group quality ruff format --check .` : **0 fichier à
  reformater** (56 conformes) —
  les 16 fichiers non conformes constatés en session 58 traités en
  session 61 (neutralité prouvée par comparaison d'AST avant/après sur
  les 44 fichiers Python), détail : `docs/sessions/session-61.md`. Plus
  aucune dette `ruff` en attente dans le dépôt : à garder conforme au fil
  de l'eau.
- ⚠️ Le reformatage de la session 61 **décale les numéros de ligne** de
  `src/` : toute référence de ligne d'une session ≤ 60 est périmée (table
  de correspondance des références encore vivantes dans
  `docs/sessions/session-61.md`).
- Couverture (`coverage.py`) : `switch_capture_cli.py` 99 % (**1062-1063
  seules restantes**, ex-998-999 avant reformatage — ligne `__main__`
  couverte depuis la session 55, détail : `docs/sessions/session-55.md`),
  `switch_capture_core.py` **88 %** (177 lignes, 84→88 % en session 64,
  lot mirroring de l'issue #68 ; 80→84 % en session 62 —
  triage complet des lignes restantes par fonction dans
  `docs/sessions/session-62.md`), `switch_capture_gtk.py` 10 % (attendu —
  code GTK4, non couvert par la suite pytest par construction, voir
  @docs/features-backlog.md)
- Session 55 : fusion de deux branches de développement divergentes
  (session 53 menée en parallèle dans deux conversations distinctes à
  partir du même point de départ) — détail : `docs/sessions/session-55.md`
- Session 56 : audit ciblé, via Context7, de la documentation à jour de
  6 dépendances externes (PyGObject/GTK4, netmiko, paramiko, `scp`,
  `keyring`, pykeepass, ruff) contre l'usage actuel du code — 5
  candidats identifiés (dette technique GTK4, progression SCP en direct,
  keepalive netmiko, keyfile PyKeePass, `pyproject.toml` ruff/pytest/
  coverage), tous ajoutés au backlog, **aucun implémenté** (demande
  explicite : audit + proposition seulement). Suite de tests revérifiée
  sans aucune modification de code : toujours 490 passés, même échec
  préexistant, mêmes 10 skips — détail : `docs/sessions/session-56.md`
- Session 57 : traitement du point 7 ci-dessous (keepalive netmiko,
  `keepalive=30` sur `connect_switch()`) — un seul candidat de l'audit
  Context7 traité par session, comme demandé. `tests/test_connect_switch.py`
  étendu (3 tests modifiés + 1 nouveau) ; suite complète revérifiée sans
  régression : 491 passés, même échec préexistant, mêmes 10 skips —
  détail : `docs/sessions/session-57.md`
- Session 58 : deux volets — (1) nettoyage complet de la dette `ruff`
  jamais traitée en un seul passage sur l'ensemble du dépôt (53→0
  erreurs : `C408`/`RUF100` corrigés par autofix, `PLW1510` par ajout
  manuel de `check=False`, `BLE001` par `# noqa` justifié après relecture
  individuelle des 22 sites, tous des frontières d'exception délibérées) ;
  (2) sous-piste 1 du point 4 ci-dessous traitée : les imports optionnels
  en tête de `switch_capture_core.py` sont désormais couverts
  (`tests/test_optional_imports_absent.py`, 5 nouveaux tests, via une
  copie de module isolée plutôt qu'un `importlib.reload()` — ce dernier
  a été essayé puis rejeté après avoir cassé `isinstance()` ailleurs dans
  la suite, voir détail). 496 passés, même échec préexistant, mêmes 10
  skips — détail : `docs/sessions/session-58.md`
- Session 59 : traitement du point 8 ci-dessous (fichier de clé KeePass
  additionnel, `--keepass-keyfile`) — un seul candidat de l'audit
  Context7 traité, comme les sessions 57/58. Cœur + CLI étendus
  (`_open_keepass_db` et les 3 fonctions publiques, nouveau flag sur
  `capture`/`inspect`, fil de transmission complet jusqu'à `build_config`/
  `_apply_password_keyring_actions`) ; `tests/test_keepass_password.py`
  étendu (13 nouveaux tests, dont un faux backend qui vérifie
  réellement la valeur reçue) ; deux tests de complétude documentaire
  (`test_config_example_completeness.py`, `test_usage_md_completeness.py`)
  mis à jour en conséquence, `USAGE.md` complété. GUI volontairement pas
  étendue cette session (scope cœur + CLI). 509 passés, même échec
  préexistant, mêmes 10 skips — détail : `docs/sessions/session-59.md`
- Session 60 : deux candidats de l'audit Context7 traités (le `ruff
  check` demandé en début de session était déjà à 0 erreur depuis la
  session 58, rien à corriger). (1) Point 5 : `pyproject.toml` créé,
  limité aux sections `[tool.*]` (ruff/pytest/coverage), sans
  `[build-system]`/`[project]` — le dépôt reste non packagé ; vérifié
  par exécution réelle que les commandes sans flags donnent des
  résultats identiques. (2) Point 6 : `progress_callback` optionnel sur
  `scp_get`/`scp_put` + `make_scp_progress_logger()` qui journalise par
  paliers de 10% par fichier (plutôt qu'à chaque bloc), câblé sur les
  deux appelants réels ; 12 nouveaux tests, dont deux qui ont trouvé un
  vrai bug (ligne « 0% » parasite avant le premier palier) corrigé dans
  la foulée. Deux faux backends d'autres fichiers de test mis à jour
  (signature publique modifiée). 522 passés, même échec préexistant,
  mêmes 10 skips — détail : `docs/sessions/session-60.md`
- Session 61 : deux volets. (1) Dernier reste de dette `ruff` traité —
  `ruff check` était déjà à 0 depuis la session 58, c'est `ruff format`
  qui restait en attente : 15 fichiers `src/`/`tests/` reformatés, AST
  vérifié identique avant/après sur les 44 fichiers Python du dépôt ; le
  16ᵉ fichier signalé était un journal de session archivé
  (`ruff` reformate aussi les blocs ```` ```python ```` du Markdown), exclu du
  seul formateur par `[tool.ruff.format]` pour ne pas réécrire
  l'historique. (2) Sous-piste 2 du point 4 ci-dessous close : la branche
  « modèle inconnu » de `_prepare_switch` est confirmée inatteignable,
  **pas couverte pour autant** — ses 3 prémisses sont verrouillées par
  `tests/test_prepare_switch_model_invariant.py` (110 tests paramétrés
  depuis `MODEL_PROFILES`, dont un qui interdit toute réaffectation de
  `cfg.model` dans `src/`), validées par 3 mutations. 632 passés, même
  échec préexistant, mêmes 10 skips — détail :
  `docs/sessions/session-61.md`
- Session 62 : poursuite du point 4 — triage des 291 lignes non couvertes
  de `switch_capture_core.py` par fonction (croisement `coverage json` ×
  AST), jamais fait jusqu'ici ; puis traitement du plus gros bloc désigné
  par ce triage, `UninstallThread.run` (50 lignes, 17 % de la dette, à
  0 % parce que `test_uninstall_confirm.py` remplace délibérément la
  classe par un faux thread). `tests/test_uninstall_thread.py`, 29 tests.
  **A trouvé un vrai bug** : sur le chemin de découverte du `.bin`
  (sans `feature_bin_path`), le préfixe média était capturé dans le nom
  de fichier et la commande devenait
  `install deactivate feature flash:/flash:/...`, rejetée par le switch —
  format réel vérifié contre la command reference HPE avant de conclure,
  correctif prouvé porteur par restauration de l'ancienne expression.
  `core` 80→84 %, 661 passés, même échec préexistant, mêmes 10 skips —
  détail : `docs/sessions/session-62.md`
- Session 63 : « on passe uv pour remplacer poetry » — vérifié d'abord
  que le projet n'a **jamais** utilisé Poetry (aucune trace, aucun
  `poetry.lock`) ; interprété comme adopter `uv` pour la gestion des
  dépendances de développement, en remplacement de `pip` +
  `requirements.txt`/`requirements-dev.txt` (supprimés). `[project]`
  ajouté à `pyproject.toml` (aucun `[build-system]`, `[tool.uv]
  package = false` explicite) : documentation `uv` officielle vérifiée
  avant d'écrire quoi que ce soit
  (https://docs.astral.sh/uv/concepts/projects/config/#build-systems)
  pour confirmer que cela ne revient pas sur le choix « pas de
  packaging » (session 60/`tests/conftest.py`) — c'est l'absence de
  `[build-system]`, pas celle de `[project]`, qui en décide. Deux groupes
  de dépendances (`dev` synchronisé par défaut, `quality` sur demande,
  reprenant la distinction déjà en place). `uv.lock` généré (65 paquets ;
  `netmiko` s'y résout en deux versions selon la plage Python — utile
  pour le plancher `python3.9` réel d'el8, jamais garanti par l'ancien
  `requirements.txt` non verrouillé). Toutes les commandes revérifiées
  par exécution réelle (`uv sync`, `uv run pytest -q` : 661 passés
  inchangé ; `uv run --group quality ruff check .`/`coverage report -m` :
  résultats identiques à la session 62). `README.md`/
  `docs/architecture.md`/`docs/features-backlog.md` mis à jour partout où
  ils citaient les fichiers supprimés. `.gitignore` ajouté (n'existait
  pas), couvre aussi les fichiers `switch_capture*.log` parasites
  repérés en session 62. Point 4 (couverture) non touché cette
  session — détail : `docs/sessions/session-63.md`
- Backlog et limites connues à jour : @docs/features-backlog.md

## Prochaine feature

Aucun point numéroté restant. Candidats pour la prochaine session (un
seul à traiter à la fois) :

1. Mesurer la durée SCP réelle contre un switch physique dès qu'un accès
   est disponible — seul point technique encore ouvert (voir « Pas fait »
   dans le backlog).
2. Corriger la limite connue (documentée depuis la session 08, verrouillée
   par des tests dédiés en session 50) sur les alias de détection modèle
   `5510`/`5520` : forme collée (`"5510HI"`) plutôt que le format à tiret
   réel HPE confirmé pour 5130/5140 (`"5130-28-HI"`) — nécessite un
   exemple réel de sortie `display version` pour un 5510/5520 avant de
   corriger à l'aveugle (aucun disponible dans ce dépôt à ce jour).
3. Relecture linguistique du `.po` en_US par une personne anglophone
   native — tâche non automatisable, en attente depuis la session 33.
4. Poursuivre l'audit de couverture (session 51-52-53-54-58-61-62) sur les
   lignes restantes de `switch_capture_core.py` (**88 %, 177 lignes non
   couvertes** depuis la session 64). Le **triage par fonction**, jamais fait avant la session
   62, est désormais disponible dans `docs/sessions/session-62.md` :
   tableau ligne/fonction complet et regroupement en 3 familles par coût
   de test. À reprendre par là plutôt que par la liste de plages brutes
   de `docs/sessions/session-54.md`, devenue périmée (numéros décalés en
   session 61, contenu couvert en session 62). Candidat naturel de
   continuation, pas bloqué par un facteur externe contrairement aux trois
   points ci-dessus. Lot mirroring (`configure_gre_mirror`,
   `MirrorThread.run`, `teardown_mirror`, `configure_local_mirror`)
   **traité en session 64** (issue #68, `tests/test_mirror_port_sequences.py`,
   plus aucune ligne non couverte dans ces quatre fonctions) : reprendre
   par les familles suivantes du triage de la session 62. Trois sous-pistes précises traitées, aucune encore
   ouverte :
   - ~~Les imports optionnels en tête de fichier (`netmiko`/`paramiko`/
     `keyring`/`pykeepass`, lignes 33-59)~~ **✅ Fait (session 58,
     13/09/2026)** — `tests/test_optional_imports_absent.py` (5 tests),
     via une copie de module isolée (`importlib.util`), pas un
     `importlib.reload()` du module partagé : ce dernier a été essayé
     puis rejeté après un essai réel (casse `isinstance()` ailleurs dans
     la suite selon l'ordre de collecte pytest — voir
     `docs/sessions/session-58.md` pour le détail du piège et de la
     correction).
   - ~~`SetupAndCaptureThread._prepare_switch`, ligne 2373 (`if model not
     in MODEL_PROFILES`) : probablement du code mort — à
     confirmer/documenter plutôt qu'à forcer par une mutation
     post-construction du dataclass.~~ **✅ Fait (session 61,
     15/09/2026)** — confirmé inatteignable, ligne **délibérément laissée
     non couverte** (2415 après reformatage) comme 1062-1063 côté CLI.
     Les 3 prémisses du raisonnement sont verrouillées par
     `tests/test_prepare_switch_model_invariant.py` plutôt que consignées
     en prose : `detect_model` ne renvoie que `None` ou une clé réelle,
     `Config` refuse tout modèle hors clés (alias compris), et aucun code
     de `src/` ne réaffecte `cfg.model` après construction — cette
     dernière vérifiée sur le source, donc une régression future échoue
     au lieu de rendre l'analyse silencieusement fausse. Une mutation de
     `detect_model` atteint réellement la ligne : ce n'est pas du code
     impossible à exécuter, c'est une garde défensive neutralisée en
     amont — à conserver telle quelle, pas à supprimer.
   - ~~`UninstallThread.run` (50 lignes, le plus gros bloc jamais
     exercé du fichier)~~ **✅ Fait (session 62, 15/09/2026)** —
     `tests/test_uninstall_thread.py` (29 tests), classe intégralement
     couverte. À 0 % jusque-là parce que `test_uninstall_confirm.py`
     remplace délibérément la classe par un faux thread : les deux
     fichiers sont complémentaires, le nouveau teste ce que l'ancien
     remplace. **A trouvé un vrai bug** (préfixe `flash:/` dupliqué dans
     la commande de désactivation sur le chemin de découverte du `.bin`),
     corrigé dans la foulée — détail : `docs/sessions/session-62.md`.
   La piste connexe « reformatage complet du dépôt » est close
   (session 61, voir « État courant »).
5. **(Session 56, audit Context7)** ~~`pyproject.toml` centralisant
   `[tool.ruff]` (`line-length = 120`), `[tool.pytest.ini_options]`
   (`testpaths = ["tests"]`) et `[tool.coverage.run]` (`source = ["src"]`)
   — évite de répéter les mêmes flags sur chaque commande de la section
   « Commandes de qualité » ci-dessus. Non bloqué, risque quasi nul
   (fichier de config seul, aucune ligne de code touchée) ; point
   d'attention : documenter explicitement que ce fichier ne change pas
   le choix délibéré « pas de packaging » (voir `tests/conftest.py`) —
   voir `docs/features-backlog.md` pour le détail complet.~~ **✅ Fait
   (session 60, 14/09/2026)** — `pyproject.toml` créé à la racine,
   limité à `[tool.ruff]`/`[tool.pytest.ini_options]`/
   `[tool.coverage.run]`, aucun `[build-system]`/`[project]`. Vérifié par
   exécution réelle (`ruff check .`, `ruff format --check .`,
   `pytest -q`, `coverage run -m pytest -q` sans aucun flag) : résultat
   identique aux invocations avec flags. `tests/conftest.py` mis à jour.
   *(Mise à jour session 63 : `[project]` ajouté pour la gestion des
   dépendances via `uv` — `[build-system]` toujours absent, le choix
   « pas de packaging » n'a pas changé, seule sa mise en œuvre précise
   l'a fait. Voir « État courant » et `docs/sessions/session-63.md`.)*
6. **(Session 56, audit Context7)** ~~Callback de progression SCP en
   direct (`scp.SCPClient(progress=...)`, jamais utilisé aujourd'hui par
   `scp_get`/`scp_put`) — permettrait un pourcentage par fichier remonté
   jusqu'à la page « Journal » de la GUI, en complément du débit moyen
   déjà calculé après coup. Non bloqué, testable en isolation (callback
   injecté, pas de switch réel requis).~~ **✅ Fait côté cœur (session
   60, 14/09/2026)** — `progress_callback` optionnel sur `scp_get`/
   `scp_put` + `make_scp_progress_logger()` (journalisation par paliers,
   suivi par nom de fichier), câblé sur `_push_feature_file` et
   `CaptureRotationThread`. 12 nouveaux tests ; un bug de palier « 0% »
   trouvé par ces tests et corrigé. **✅ Remontée jusqu'à la page
   « Journal » faite en session 65 (issue #70)** : `on_progress` de
   `make_scp_progress_logger` publie chaque palier dans
   `SharedState.scp_progress` (`ScpProgress`), affiché par
   `_refresh_journal` (`format_scp_progress`) sur le thread GTK — aucun
   appel GTK depuis le thread de transfert. Côté CLI, `-v` affichait déjà
   les paliers DEBUG. Voir `docs/sessions/session-60.md` et
   `docs/sessions/session-65.md`.
7. **(Session 56, audit Context7)** ~~Keepalive netmiko (paramètre
   `keepalive` du profil `hp_comware`, absent du dict `device` de
   `connect_switch()`) sur la connexion de polling longue durée
   (`_poll_conn`) — même famille que le bug SCP corrigé le 23/08/2026
   (sessions fermées côté switch).~~ **✅ Fait (session 57, 12/09/2026)**
   — `keepalive=30` ajouté au dict `device` (constante
   `NETMIKO_KEEPALIVE_SECONDS`) ; l'effet réel sur un switch physique
   reste à confirmer, comme la mesure SCP réelle du point 1 — voir
   `docs/sessions/session-57.md`.
8. **(Session 56, audit Context7)** ~~Support d'un keyfile PyKeePass en
   plus du mot de passe maître (`PyKeePass(path, password=...,
   keyfile=...)`, non exposé aujourd'hui par `_open_keepass_db`) —
   `--keepass-keyfile` optionnel, rétrocompatible. Non bloqué, testable
   avec le faux backend déjà utilisé par `test_keepass_password.py`.~~
   **✅ Fait (session 59, 13/09/2026)** — cœur (`_open_keepass_db` et les
   3 fonctions publiques) + CLI (`--keepass-keyfile` sur `capture`/
   `inspect`, fil de transmission complet) étendus, 13 nouveaux tests.
   GUI volontairement pas étendue (scope cœur + CLI cette session) —
   voir `docs/sessions/session-59.md`.
9. **(Session 56, audit Context7)** Migration `Gtk.FileChooserNative`/
   `Gtk.MessageDialog` (dépréciés depuis GTK 4.10) vers `Gtk.FileDialog`/
   `Gtk.AlertDialog` (API asynchrone). Plus gros chantier que les points
   5 à 8 (6 sites d'appel dans `switch_capture_gtk.py` + scripts Xvfb
   associés) et à ne pas traiter à l'aveugle : vérifier d'abord la
   version GTK4 réellement disponible sur les cibles de packaging
   actuelles (Debian, Rocky/RHEL 9) avant de s'engager sur la nouvelle
   API, même principe que la vérification d'alias 5510/5520 (point 2).

## Commandes de qualité

Dépendances gérées par `uv` depuis la session 63 (remplace `pip` +
`requirements.txt`/`requirements-dev.txt`, supprimés — voir
`docs/sessions/session-63.md`). `pyproject.toml` reste par ailleurs ce
qu'il était depuis la session 60 : `line-length`/`testpaths`/`source`
y sont centralisés, donc les commandes ci-dessous fonctionnent sans
flags explicites. Les variantes avec flags (`--line-length 120`,
`tests/`, `--source=src`) restent équivalentes et documentées dans
`docs/sessions/session-60.md` — à garder en tête si un jour ce fichier
disparaît ou est modifié par erreur. Il porte aussi, depuis la session
61, un `[tool.ruff.format] exclude` sur `docs/**/*.md` (ne pas reformater
les blocs de code des journaux de session archivés).

Deux groupes de dépendances (`[dependency-groups]`, PEP 735) :
`dev` (pytest + keyring/pykeepass, nécessaires pour que la suite passe
sans rien sauter d'autre que les 10 tests GTK4) est synchronisé par
défaut par `uv sync`/`uv run` ; `quality` (ruff + coverage) ne l'est
**pas** — comportement `uv` documenté pour tout groupe autre que `dev`,
pas une option choisie ici — et demande `--group quality` explicite,
comme `ruff`/`coverage` étaient déjà hors `requirements-dev.txt`
auparavant (« optionnel — audit ponctuel seulement »). `uv run` invoque
la commande demandée après avoir vérifié que `uv.lock` correspond à
`pyproject.toml` et que `.venv/` correspond à `uv.lock` — pas d'étape
d'installation séparée à retenir.

```bash
uv sync                                           # groupe dev seulement (défaut)
uv run pytest -q
uv run --group quality coverage run -m pytest -q && uv run --group quality coverage report -m   # audit ponctuel
uv run --group quality ruff check .
uv run --group quality ruff format --check .
python3 -m py_compile <fichiers modifiés>          # hors venv, inchangé
```

Depuis la session 61, le dépôt **entier** est conforme aux deux
commandes `ruff` : les lancer sur `.` plutôt que sur les seuls fichiers
modifiés ne coûte rien et empêche une nouvelle dette de s'accumuler sur
plusieurs sessions, comme cela s'est produit deux fois (53 erreurs
`check` en session 58, 16 fichiers `format` en session 61).

Ajouter une dépendance : `uv add <paquet>` (runtime, `[project.dependencies]`),
`uv add --dev <paquet>` (groupe `dev`) ou `uv add --group quality <paquet>`
— jamais éditer `pyproject.toml`/`uv.lock` à la main pour ça, `uv`
maintient les deux fichiers en cohérence. `.venv/` n'est jamais livré
dans le zip horodaté (recréé par `uv sync`, voir `.gitignore` ajouté en
session 63).

## Convention de travail

- Une seule tâche faisable traitée par réponse, tirée du backlog.
- Livraison en zip nommé `switch-capture-{YYYYMMDD-HHMMSS}.zip`, avec ce
  `CLAUDE.md` et `docs/features-backlog.md` à jour dedans.
- En fin de session : mettre à jour « État courant » et « Prochaine
  feature » ci-dessus, puis ajouter `docs/sessions/session-NN.md` pour le
  raisonnement détaillé (voir `docs/sessions/session-50.md` pour le
  format) — ne pas réécrire l'historique dans ce fichier-ci.

## Pour aller plus loin

- Architecture et choix techniques (comment/pourquoi) :
  `docs/architecture.md`
- Historique détaillé, session par session : `docs/sessions/` (partir de
  l'index, ne pas tout charger)
- Documentation utilisateur : `src/docs/` (`USAGE.md`,
  `CAPTURE-METHODS.md`, `INSTALL.md`)
