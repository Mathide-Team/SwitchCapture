# Session 54 — 12/09/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Poursuite de l'audit de couverture : switch_capture_core.py 76→79 % (12/09/2026)

Point de départ : candidat #4 de `CLAUDE.md` (« Prochaine feature »), seul
non bloqué par un facteur externe — les trois autres (mesure SCP réelle,
alias 5510/5520, relecture `.po` en_US) restent inchangés depuis la
session 51. Contrairement à la session 53 (`switch_capture_cli.py`, un
seul fichier), le point de départ ici était la liste brute des 347 lignes
non couvertes de `switch_capture_core.py` laissée en fin de session 53,
répartie sur ~30 fonctions/méthodes différentes, avec une consigne
explicite non encore appliquée : trier d'abord entre fonctions pures
testables et code dépendant d'un switch réel par construction (à
exclure), avant d'écrire le moindre test.

### Méthode

Chaque bloc de la liste examiné directement dans le code source (jamais
deviné depuis le seul numéro de ligne), avec à chaque fois une recherche
croisée dans `tests/*.py` pour confirmer ce qui est déjà exercé
indirectement et ce qui ne l'est pas — même méthode qu'en session 53.
Contrairement à `switch_capture_cli.py`, `core.py` mélange des fonctions
pures, des fonctions déjà testées via un `FakeConn`/mock et qu'il ne
restait qu'à compléter d'une branche, et des méthodes de threads
d'orchestration switch réel encore jamais examinées cette session (voir
« Reste ouvert »). Étant donné le volume, la session s'est concentrée sur
les blocs pour lesquels un chemin de test réaliste (mock simple, sans
nouvelle infrastructure de test) était déjà clairement identifiable après
lecture du code — le reste, non moins volumineux, est trié et documenté
mais pas encore traité (voir « Reste ouvert »).

### Blocs traités

- **33-59** (imports optionnels `netmiko`/`paramiko`+`scp`/`keyring`/
  `pykeepass`) : examinés puis **délibérément pas testés cette session**
  — voir « Reste ouvert ».
- **395, 403** (`ensure_tap_interface`) et **425, 432**
  (`delete_tap_interface`) : `test_tap_helper_nonroot.py` couvrait déjà
  le repli aide-privilégiée et le repli `ip` pour une interface absente,
  mais jamais la branche « interface déjà présente » (`show` réussit) ni
  l'échec de `up`/`delete` via `ip` directement (root ou aide
  introuvable) — confirmé par lecture des `fake_run` existants
  (`returncode` toujours forcé à l'échec pour `show`, jamais au succès).
- **462-465, 474, 478-481** (`TapFrameWriter` en entier) : confirmé par
  `grep -rn "TapFrameWriter" tests/*.py` que seuls
  `test_tap_pacing.py`/`test_tap_injector_thread.py` la mentionnent, et
  uniquement dans le nom de leur `FakeTapWriter` de remplacement (jamais
  instanciée réellement) — seul le test d'intégration root-gated de
  `test_tap_helper_nonroot.py` l'exerce de bout en bout. Vérifié
  réellement en sandbox avant d'écrire les tests : `/dev/net/tun` existe
  et est accessible (ce sandbox tourne en root), l'ouverture + l'ioctl
  `TUNSETIFF` réussissent et créent bien l'interface côté noyau, mais
  `write_frame` échoue ensuite avec `OSError: [Errno 5] Input/output
  error` — l'interface n'est jamais passée "up" faute du binaire `ip`
  dans ce sandbox (même absence que l'unique échec préexistant sans
  rapport de la suite). Tester réellement nécessiterait donc `ip` (absent
  ici) ou une syscall netlink dédiée rien que pour ce test — écarté au
  profit du mock, cohérent avec le reste de la suite (`subprocess.run`
  mocké partout ailleurs pour la même raison).
- **526** (`iter_pcap_frames`) : seule la branche « magic invalide » était
  testée (`test_tap_pacing.py`), jamais la troncature d'un dernier
  enregistrement en cours d'écriture (capture coupée brutalement).
- **585** (`convert_pcap_to_pcapng`) : `test_convert_raises_on_invalid_source`
  existant écrit exactement 24 octets (= `PCAP_GLOBAL_HEADER_LEN`), donc
  déclenche la branche "magic inattendu" (588) et jamais la branche
  "trop petit" propre à cette fonction (585, copie indépendante de la
  même vérification dans `iter_pcap_frames`, pas seulement propagée).
- **1038-1066** (`Config.__post_init__`, 5 branches de validation, et
  `resolve_default_mount_point`) : recherche des messages d'erreur exacts
  (« Mot de passe SSH manquant », « Modèle invalide », « output_mode
  invalide », « tap_interface requis », « transfer_mode invalide »,
  `resolve_default_mount_point`) dans tout `tests/*.py` : **aucun
  résultat**. `InspectConfig` (classe sœur, mêmes règles) a bien les
  siens dans `test_inspect.py` — `Config` elle-même n'en avait aucun,
  seuls `capture_direction` et `tap_pace_max_gap_seconds` (champs propres
  à `Config`, ajoutés à des sessions dédiées ultérieures) étaient
  couverts par leurs fichiers respectifs.
- **1506-1507, 1548-1549, 1611-1612** (KeePass) : `test_keepass_password.py`
  couvrait déjà `CredentialsError` et « fichier absent » pour
  `_open_keepass_db`, mais pas sa branche `except Exception` générique
  (fichier corrompu/format invalide) ; pas non plus l'`except Exception`
  propre à `save_ssh_password_to_keepass` autour de l'écriture elle-même
  (distinct du test existant qui remplace `save_ssh_password_to_keepass`
  entièrement au niveau CLI, sans jamais exercer son propre corps) ; ni
  la conversion `RuntimeError` → `False` de `delete_ssh_password_from_keepass`
  (l'équivalent côté `load_*` était déjà couvert).
- **1833-1843** (`connect_switch` en entier) : `grep -rn "connect_switch"
  tests/*.py` confirme que les six appelants (`inspect_switch`,
  `SetupAndCaptureThread` ×4, `CaptureRotationThread`, `UninstallThread`,
  la GUI) sont *tous* testés en remplaçant `connect_switch` lui-même par
  un faux — la fonction réelle (garde `ConnectHandler is None`, dict
  `device`, retour de `ConnectHandler(**device)`) n'était donc exercée
  nulle part.
- **1924-1929, 1989, 2008-2009, 2011** (`inspect_switch`/
  `format_inspect_report`) : `MODEL_PROFILES["MSR4000"]` est le seul
  modèle avec `packet_capture: "builtin"` (voir le commentaire au-dessus
  de `MODEL_PROFILES` — mécanisme conservé « au cas où », jamais exercé
  par aucun test existant, qui ne couvrent que "installable"/
  "unsupported"/modèle inconnu). Côté formatage, les branches "builtin"/
  "unsupported"/"modèle détecté mais absent de MODEL_PROFILES" de
  `format_inspect_report` (fonction pure, dict construit à la main comme
  le reste de cette section de tests) n'avaient jamais été exercées —
  seule "installable" et "aucun modèle détecté" l'étaient.
- **2356-2358** (`SetupAndCaptureThread.start_capture_blocking`, chemin
  normal) : le garde-fou (`RuntimeError` si `prepare()` pas encore
  appelé) est testé, ainsi que l'enchaînement complet via `run()` — mais
  ce dernier remplace `start_capture_blocking` entièrement par un mock
  (`test_run_calls_prepare_then_start_capture_blocking_in_order`), donc
  le corps réel de la méthode (mise à jour de `state.started_at`/
  `state.capture_started`, délégation à `_run_capture_blocking`)
  n'était jamais exécuté.

### Nouveaux tests (35 au total, 9 fichiers dont 3 nouveaux)

- **`tests/test_tap_frame_writer.py`** (nouveau, 6 tests) : `TapFrameWriter`
  entièrement mockée (`os.open`/`fcntl.ioctl`/`os.write`/`os.close`) —
  ouverture + attachement à l'interface (flags `IFF_TAP|IFF_NO_PI`
  vérifiés octet à octet dans le struct pack), écriture de trame brute,
  fermeture normale et fermeture qui avale un `OSError`, propagation d'un
  échec d'ioctl.
- **`tests/test_config_validation.py`** (nouveau, 14 tests) : les 5
  branches de validation de `Config.__post_init__` (mot de passe manquant
  avec repli env, modèle/output_mode/transfer_mode invalides,
  `tap_interface` requis en mode "tap") côté échec *et* côté acceptation,
  et `resolve_default_mount_point` (défaut `"./mount"` remplacé, chaîne
  vide remplacée, valeur personnalisée laissée intacte).
- **`tests/test_connect_switch.py`** (nouveau, 3 tests) : `RuntimeError`
  si `ConnectHandler is None`, dict `device` construit correctement et
  valeur de retour propagée (mock de `ConnectHandler`), fonctionne aussi
  bien avec `Config` qu'`InspectConfig`.
- **`tests/test_tap_helper_nonroot.py`** (+2) : interface déjà présente
  puis échec de `up` (`ensure_tap_interface`, repli `ip` réel) ; repli
  `ip link delete` réel avec échec avalé en warning
  (`delete_tap_interface`).
- **`tests/test_tap_pacing.py`** (+1) : dernier enregistrement tronqué
  d'un `.pcap` (capture coupée en cours d'écriture) — trames complètes
  précédentes toujours récupérées, pas d'exception.
- **`tests/test_pcap_to_pcapng.py`** (+1) : en-tête global < 24 octets,
  distinct du cas "magic invalide" déjà couvert.
- **`tests/test_keepass_password.py`** (+3) : `_open_keepass_db` avec une
  erreur pykeepass générique (format de fichier invalide, simulé) ;
  `save_ssh_password_to_keepass` dont l'écriture échoue (disque plein,
  simulé) ; `delete_ssh_password_from_keepass` avec un fichier absent.
- **`tests/test_inspect.py`** (+4) : modèle "builtin" (MSR4000,
  `packet-capture ?` avec bascule de `packet_capture_cmd` quand "local"
  apparaît dans le résumé) ; trois branches de `format_inspect_report`
  (builtin, unsupported, modèle détecté mais absent de MODEL_PROFILES).
- **`tests/test_setup_and_capture_thread.py`** (+1) : `start_capture_blocking`
  après `prepare()`, `_run_capture_blocking` mockée (hors périmètre de ce
  fichier par choix documenté, voir sa docstring) — vérifie
  `state.started_at`/`state.capture_started` et la délégation.

### Vérifié réellement cette session

- Chaque fichier de test lancé isolément d'abord, puis la suite complète.
- Suite complète : **486 passés (451 + 35), 1 échec préexistant sans
  rapport inchangé (`ip`/iproute2 absent de ce sandbox), 10 skips
  inchangés (GTK4/PyGObject)** — 0 régression.
- `coverage run --source=src -m pytest tests/ -q && coverage report -m` :
  **`switch_capture_core.py` 76→79 %** (347→301 lignes non couvertes) ;
  `switch_capture_cli.py` 99 % inchangé, `switch_capture_gtk.py` 10 %
  inchangé.
- `ruff check --line-length 120 tests/ src/` : **53 erreurs, inchangé au
  total** — 2 nouveaux `C408` (`dict(...)` plutôt qu'un littéral) dans
  les fonctions `_base_kwargs`/`make_config` des deux fichiers de test
  entièrement nouveaux (`test_config_validation.py`,
  `test_connect_switch.py`), délibérément gardés pour cohérence avec le
  style établi partout ailleurs dans la suite (même choix que documenté
  en session 53) ; compensés par la suppression d'un import mort
  (`keyring_account_id`, jamais utilisé dans `test_keepass_password.py`,
  oubli préexistant sans rapport avec cette session mais corrigé au
  passage puisque ce fichier était déjà modifié) et un tri d'imports
  (`test_tap_pacing.py`, même situation).
- `ruff format --line-length 120 --check` : les 3 fichiers entièrement
  nouveaux + les 6 fichiers modifiés confirmés conformes, à l'exception
  de `test_inspect.py` et `test_pcap_to_pcapng.py`, qui ressortent non
  conformes mais **entièrement sur du code préexistant** (le style
  `FakeConn({...})` à accolade ouvrante sur la même ligne, utilisé dans
  la quasi-totalité des tests déjà présents dans `test_inspect.py` avant
  cette session) — vérifié en confirmant que les lignes signalées
  correspondent à des tests non touchés cette session, à une exception
  près : le nouveau test `test_inspect_switch_builtin_model` reprend
  volontairement ce même style pour rester visuellement cohérent avec le
  reste du fichier plutôt que de mélanger deux conventions dans un même
  fichier. Une remise en forme complète de ces deux fichiers est laissée
  hors périmètre (même raisonnement qu'en session 53 pour
  `switch_capture_core.py` — diff sans rapport avec le travail de cette
  session).
- `py_compile` sur les 9 fichiers touchés/créés : OK.

### Résultat

`CLAUDE.md` mis à jour (compteurs de tests et de couverture, candidat #4
recentré sur cette session, avec les deux sous-pistes ci-dessous
explicitement notées pour la suite). `docs/features-backlog.md` :
compteurs en tête de fichier mis à jour, section « Tests automatisés
(pytest) » complétée d'une entrée dédiée à cette session.

### Reste ouvert

Les trois points bloqués par un facteur externe (mesure SCP réelle, alias
5510/5520, relecture `.po` en_US) restent inchangés.

**Deux points identifiés puis délibérément laissés de côté cette
session**, plutôt que forcés :

- **Imports optionnels (lignes 33-59)** — `try: import netmiko`/
  `paramiko`+`scp`/`keyring`/`pykeepass` `except ImportError: ... = None`.
  Un précédent existe dans ce dépôt pour tester ce genre de garde
  (`test_gtk_i18n_translations.py` mocke déjà `sys.modules["gi"]` et
  force un réimport de `switch_capture_gtk` via `sys.modules.pop(...)`).
  Analyse de sécurité faite avant de décider quoi que ce soit : `grep -rn
  "from switch_capture_core import"` sur tout `tests/*.py` montre que
  plusieurs fichiers font à la fois `import switch_capture_core as
  core`/`core_mod` *et* `from switch_capture_core import Config, ...` —
  un `importlib.reload(switch_capture_core)` recrée de nouveaux objets
  classe (`Config`, `SharedState`, `SetupAndCaptureThread`...) à chaque
  appel, ce qui casserait un `isinstance()` comparant un objet construit
  via l'un des deux styles d'import contre l'autre si jamais un test
  mélangeait les deux. Vérifié un par un (`grep -n "core\."` /
  `core_mod\."` dans chacun des fichiers concernés,
  `test_setup_and_capture_thread.py`/`test_keyring_password.py`/
  `test_keepass_password.py`) : aucun n'utilise en réalité le préfixe
  `core.`/`core_mod.` pour construire un objet dont l'`isinstance` est
  vérifié ailleurs via le nom importé nu — donc pas de conflit dans
  l'état actuel du dépôt. `switch_capture_cli.py` (qui construit
  `Config`/`SharedState` en interne) importe lui aussi ces noms au niveau
  module (`from switch_capture_core import (...)`), jamais réimporté,
  donc ses propres références restent stables quel que soit le nombre de
  reloads de `switch_capture_core`. Un test candidat serait : patcher
  `sys.modules["netmiko"]`/`"paramiko"`/`"keyring"`/`"pykeepass"` à
  `None`, `importlib.reload(switch_capture_core)`, vérifier
  `ConnectHandler is None`/`paramiko is None`/`SCPClient is None`/
  `keyring is None`/`PyKeePass is None`/`CredentialsError is Exception`,
  puis **impérativement** restaurer `sys.modules` et recharger une
  seconde fois avant la fin du test (`try`/`finally`), et faire tourner
  la suite complète juste après pour confirmer l'absence de régression —
  exactement la méthode de vérification empirique déjà utilisée partout
  ailleurs dans ce dépôt. Non implémenté cette session : technique
  fondamentalement différente (manipulation d'import/reload) du reste du
  lot traité (mocks simples d'attributs/fonctions), mieux isolée dans sa
  propre session plutôt que mélangée ici. Une alternative par
  sous-processus (`subprocess.run([sys.executable, "-c", ...])`, plus
  sûre car totalement isolée du process pytest principal) a aussi été
  considérée mais écartée : le code exécuté dans un sous-processus
  n'est pas comptabilisé par `coverage run --source=src -m pytest
  tests/ -q` tel qu'invoqué aujourd'hui (pas de
  `COVERAGE_PROCESS_START`/`coverage combine` configuré dans ce dépôt) —
  changer cette invocation documentée dans `CLAUDE.md` pour 15 lignes de
  code trivial (`X = None`) a semblé disproportionné.
- **`SetupAndCaptureThread._prepare_switch`, ligne 2373**
  (`if model not in MODEL_PROFILES: raise RuntimeError(...)`) —
  probablement du code mort. `model = self.cfg.model or
  detect_model(version_output)` : si `self.cfg.model` est renseigné,
  `Config.__post_init__` a déjà validé qu'il s'agit d'une clé réelle de
  `MODEL_PROFILES` (sinon `ValueError` levée bien avant, à la
  construction) ; si `self.cfg.model` est vide, `detect_model` ne renvoie
  jamais que `None` ou une clé authentique de `MODEL_PROFILES` (elle
  boucle sur `MODEL_PROFILES.items()` et renvoie la `key` elle-même,
  jamais une valeur construite) — vérifié en lisant `detect_model` en
  entier. Le cas `model` non vide mais absent de `MODEL_PROFILES` ne
  semble donc atteignable par aucun chemin d'invocation réel, un peu
  comme les lignes 998-999 de `switch_capture_cli.py` closes en
  session 53 (branche défensive protégée en amont par construction).
  Le forcer nécessiterait de muter `cfg.model` après construction pour
  contourner la validation du dataclass — écarté pour la même raison que
  la session 53 évite les mocks ne reflétant aucun chemin réel. À
  confirmer/documenter formellement (pas fait cette session, seulement
  identifié) avant de clore ce point.

**Reste non examiné cette session** — le plus gros du volume restant
(301 lignes), pas encore trié bloc par bloc contrairement à ce qui a été
fait ci-dessus :

```
switch_capture_core.py : 33-34, 39-41, 46-50, 55-59, 2373, 2554-2573,
                          2578, 2593-2597, 2632-2635, 2644-2675,
                          2689-2718, 2776-2801, 2812-2821, 2845,
                          2861-2864, 2868-2879, 2895-2898, 2904-2907,
                          2911-2923, 2927-2942, 2951-3000, 3008-3034,
                          3074-3078, 3115, 3128-3131, 3138-3142,
                          3146-3151, 3175, 3186-3189, 3210, 3213-3222,
                          3280-3284, 3288-3362, 3371-3372, 3515, 3522,
                          3524, 3534, 3538, 3610-3624, 3648-3683,
                          3981-3993, 4031-4032, 4043-4051, 4067-4078,
                          4085-4087, 4097
```

Repéré au passage, sans l'examiner en détail (à confirmer en début de
prochaine session) : les zones 2554-3222 (montage sshfs, lancement
Wireshark, polling SCP/sshfs, injection TAP/FIFO, nettoyage) et
3288-3362 (`UninstallThread.run`, jamais testée directement — seul
`test_uninstall_confirm.py` existe, et il remplace le thread entièrement
par un faux, exactement comme `connect_switch` l'était pour les blocs
traités cette session) sont les plus volumineuses. 3515-3538
(`MirrorConfig.__post_init__`) ressemble probablement à la situation
trouvée cette session pour `Config.__post_init__` (validations pures
sans doute partiellement non testées) mais pas vérifié. 3610-3993
(`configure_local_mirror`/`configure_gre_mirror`/`teardown_mirror`) sont
déjà partiellement exercées par `test_mirror_acl_filter.py`/
`test_mirror_vxlan.py` selon un premier coup d'œil, donc probablement des
branches précises manquantes plutôt que des fonctions entières à 0 % —
à vérifier comme pour `switch_capture_cli.py` en session 53, pas supposé.
Piste connexe toujours ouverte : reformatage complet de
`switch_capture_core.py` (`ruff format`), non conforme sur des lignes
préexistantes sans rapport avec cette session ni la précédente.
