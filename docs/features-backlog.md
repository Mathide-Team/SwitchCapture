# Backlog — switch_capture

## État

- 20/20 demandes numérotées historiques traitées. 0 point numéroté encore ouvert.
- Suite de tests : 661 passés (632 + 29), 1 échec préexistant sans rapport
  (absence d'`ip`/`iproute2` dans ce sandbox), 10 skips (GTK4/PyGObject indisponible) —
  dernière exécution complète : [session 62](sessions/session-62.md) (15/09/2026).
- `ruff check .` (dépôt entier) : **0 erreur** — 53 erreurs pré-existantes
  (`BLE001`/`C408`/`RUF100`/`PLW1510`, jamais traitées en un seul passage sur l'ensemble du
  dépôt jusqu'ici) corrigées en [session 58](sessions/session-58.md). `ruff format --check .` :
  **0 fichier à reformater** depuis la [session 61](sessions/session-61.md) (les 16 fichiers
  non conformes de la session 58 traités, neutralité prouvée par comparaison d'AST). Plus
  aucune dette `ruff` en attente.
- ⚠️ Le reformatage de la [session 61](sessions/session-61.md) **décale les numéros de ligne**
  de `src/` : toute référence de ligne d'une session ≤ 60 (y compris celles citées plus bas
  dans ce fichier) est périmée. Table de correspondance des références encore vivantes dans
  [session 61](sessions/session-61.md).
- Couverture (`coverage.py`) : `switch_capture_cli.py` 99 % (**1062-1063 seules lignes
  restantes**, ex-998-999, voir [session 55](sessions/session-55.md)),
  `switch_capture_core.py` **88 %** (177 lignes, 84→88 % en
  [session 64](sessions/session-64.md), lot mirroring ; 80→84 % en
  [session 62](sessions/session-62.md)), `switch_capture_gtk.py`
  10 % (attendu, voir section « Tests automatisés (pytest) » plus bas). **Triage par
  fonction** des lignes restantes de `switch_capture_core.py` :
  [session 62](sessions/session-62.md) — il remplace la liste de plages de
  [session 54](sessions/session-54.md), périmée (numéros décalés en session 61, contenu
  couvert en session 62).
- [Session 55](sessions/session-55.md) : fusion de deux branches de développement divergentes
  (deux livraisons zip distinctes ayant chacune mené sa propre « session 53 » en parallèle à
  partir du même point de départ) — aucune régression, +4 tests nets après élimination des
  doublons de couverture entre les deux branches.
- Reste ouvert : mesure réelle de durée de transfert SCP contre un switch physique
  (voir « Pas fait » ci-dessous, bloqué faute de switch réel dans ce sandbox) ; alias de
  détection modèle `5510`/`5520` au format collé plutôt qu'à tiret réel HPE (voir « Modèles
  matériels » ci-dessous, bloqué faute d'exemple réel vérifié pour ces modèles).
- [Session 56](sessions/session-56.md) (12/09/2026) : audit ciblé, via Context7, de la
  documentation à jour de 6 dépendances externes (PyGObject/GTK4, netmiko, paramiko, `scp`,
  `keyring`, pykeepass, ruff) contre l'usage actuel du code — 5 candidats identifiés, voir
  section dédiée ci-dessous. **Aucun code modifié cette session** (demande explicite : audit
  et proposition seulement, sans enchaîner sur l'implémentation) — suite de tests revérifiée
  à l'identique pour confirmer l'absence d'effet de bord : toujours 490 passés, même échec
  préexistant sans rapport, mêmes 10 skips.
- [Session 57](sessions/session-57.md) (12/09/2026, 3e session du jour) : traitement du point
  7 ci-dessous (keepalive netmiko) — un seul candidat de l'audit Context7 traité par session,
  comme demandé. Voir « Connexion SSH de contrôle (netmiko) » sous « Fait » ci-dessous. 491
  passés (490 + 1 nouveau test), même échec préexistant, mêmes 10 skips.
- [Session 58](sessions/session-58.md) (13/09/2026) : deux volets — nettoyage complet de la
  dette `ruff` du dépôt entier (53→0 erreurs, détail ci-dessus) et couverture des imports
  optionnels en tête de `switch_capture_core.py` (candidat de couverture, sous-piste 1 du
  point 4 de `CLAUDE.md`), voir « Tests automatisés (pytest) » ci-dessous pour le détail de
  cette dernière. 496 passés (491 + 5 nouveaux tests), même échec préexistant, mêmes 10 skips.
- [Session 59](sessions/session-59.md) (13/09/2026) : traitement du point 8 ci-dessous
  (fichier de clé KeePass additionnel, `--keepass-keyfile`) — un seul candidat de l'audit
  Context7 traité, comme les deux sessions précédentes. Voir « Fait » ci-dessous. 509 passés
  (496 + 13 nouveaux tests), même échec préexistant, mêmes 10 skips.
- [Session 60](sessions/session-60.md) (14/09/2026) : deux candidats traités — point 5
  (`pyproject.toml` centralisant ruff/pytest/coverage) et point 6 (callback de progression
  SCP, côté cœur uniquement). Le `ruff check` demandé en début de session était déjà à 0
  erreur depuis la session 58. 522 passés (509 + 13 nouveaux tests), même échec préexistant,
  mêmes 10 skips.
- [Session 61](sessions/session-61.md) (15/09/2026) : deux volets — (1) dernier reste de dette
  `ruff` traité (`ruff format` sur 15 fichiers `src/`/`tests/`, AST vérifié identique sur les
  44 fichiers Python ; 16ᵉ fichier = journal de session archivé, exclu du seul formateur) ;
  (2) sous-piste 2 du point 4 de `CLAUDE.md` close — branche « modèle inconnu » de
  `_prepare_switch` confirmée inatteignable, laissée non couverte, ses 3 prémisses
  verrouillées par tests (voir « Tests automatisés (pytest) » ci-dessous). 632 passés
  (522 + 110 nouveaux tests, majoritairement paramétrés depuis `MODEL_PROFILES`), même échec
  préexistant, mêmes 10 skips.
- [Session 62](sessions/session-62.md) (15/09/2026) : poursuite du point 4 — triage par
  fonction des 291 lignes non couvertes de `switch_capture_core.py` (croisement
  `coverage json` × AST), jamais fait jusqu'ici, puis traitement du plus gros bloc désigné
  par ce triage : `UninstallThread.run` (50 lignes). **Un vrai bug trouvé et corrigé** :
  préfixe média dupliqué (`flash:/flash:/...`) dans la commande de désactivation, sur le
  chemin emprunté sans `--feature-bin-path`. `core` 80→84 % (291→234 lignes), 661 passés
  (632 + 29 nouveaux tests), même échec préexistant, mêmes 10 skips.

## Candidats proposés — audit Context7 (session 56, 12/09/2026)

Cinq candidats identifiés en comparant l'usage actuel du code contre la documentation à jour
(consultée via Context7) de six dépendances externes du projet. Format identique aux candidats
numérotés de `CLAUDE.md` (« un seul à traiter à la fois », non bloqués par un facteur externe
sauf mention contraire) — numérotés 5 à 9 à la suite des 4 candidats déjà存 existants de
`CLAUDE.md`. **Aucun n'est implémenté** : cette section documente le constat, la proposition et
le plan de test envisagé pour une future session, elle ne modifie aucun fichier `tests/`.
Raisonnement complet et sources précises : [session 56](sessions/session-56.md).

### 5. `pyproject.toml` centralisant `ruff`/`pytest`/`coverage` — ✅ **Fait (session 60, 14/09/2026)**

**Constat** : `ruff` découvre nativement un `[tool.ruff]` dans `pyproject.toml` (ou un
`ruff.toml` séparé, confirmé contre la documentation Astral/Ruff à jour) ; aucun des deux
n'existe dans ce dépôt, d'où `--line-length 120` répété sur les deux commandes `ruff` de
`CLAUDE.md` à chaque session (risque d'oubli). De même, aucun `pytest.ini`/`[tool.pytest.
ini_options]` (`tests/` doit être précisé à chaque invocation) ni `[tool.coverage.run]`
(`--source=src` répété).

**Proposition** : un `pyproject.toml` limité aux sections `[tool.ruff]` (`line-length = 120`),
`[tool.pytest.ini_options]` (`testpaths = ["tests"]`) et `[tool.coverage.run]`
(`source = ["src"]`) — sans `[build-system]`/`[project]`. **Point d'attention** :
`tests/conftest.py` documente explicitement l'absence actuelle de `pyproject.toml`/`setup.py`
comme un choix délibéré (pas de packaging, `src/` copié tel quel par les 3 méthodes
d'installation) — un `pyproject.toml` limité à la config des outils ne remet pas en cause ce
choix, mais le commit qui l'introduit devra le dire explicitement pour éviter toute confusion
future, y compris dans `tests/conftest.py` lui-même (mettre à jour son commentaire).

**Tests prévus** : aucun test de comportement (fichier de configuration seul) — vérification
par exécution réelle : `ruff check .`/`ruff format --check` et `pytest`/`coverage run -m
pytest` sans flags doivent produire un résultat identique aux invocations avec flags actuelles.

**Réalisé** : `pyproject.toml` créé à la racine, exactement comme proposé (3 sections
`[tool.*]`, aucun `[build-system]`/`[project]`), avec un commentaire en tête rappelant que le
dépôt reste non packagé. `tests/conftest.py` mis à jour comme prévu par le point d'attention.
Les 4 commandes ci-dessus lancées **sans aucun flag** donnent bien un résultat identique aux
variantes avec flags (comparaison consignée dans [session 60](sessions/session-60.md)).
Vérifié également que les 3 scripts d'installation copient `src/` nommément, jamais la racine :
`pyproject.toml` ne peut pas se retrouver embarqué par erreur dans un paquet.

### 6. Callback de progression SCP en direct — ✅ **Fait côté cœur (session 60, 14/09/2026)**

**Constat** : le paquet `scp` (`scp>=0.14`, classe `SCPClient`) accepte un paramètre `progress`
— `function(filename, size, sent)`, appelé pendant le transfert (confirmé contre le code
source/README du paquet, `scp` n'étant pas indexé sur Context7 — vérifié par recherche web
directe sur le dépôt `jbardin/scp.py`) — jamais utilisé par `scp_get`/`scp_put`
(`switch_capture_core.py`) aujourd'hui, qui ne calculent un débit qu'une fois le fichier
entièrement rapatrié (voir section « Débit de transfert moyen en direct » plus haut).

**Proposition** : passer un callback optionnel à `SCPClient` dans `scp_get`/`scp_put`, remonté
jusqu'à la page « Journal » de la GUI et au CLI verbeux — pourcentage de progression par
fichier, utile en particulier pour les fichiers de capture volumineux pendant le polling de
rotation.

**Tests prévus** : fonction pure testable en isolation (callback injecté, comme les tests
existants de `test_transfer_rate.py`) — nouveau fichier `test_scp_progress_callback.py` ou
extension de `test_transfer_rate.py`, aucun switch réel ni connexion SSH requise.

**Réalisé (cœur uniquement)** : `progress_callback` optionnel ajouté à `scp_get`/`scp_put`
(dernier paramètre, `None` par défaut — rétrocompatible), transmis tel quel à
`SCPClient(progress=...)`. Nouvelle fonction publique `make_scp_progress_logger(context,
threshold_percent=10)` : le paquet `scp` rappelle son callback à **chaque bloc**, ce qui
noierait le journal — ce callback ne journalise donc qu'au franchissement d'un nouveau palier,
**par nom de fichier** (un même callback est réutilisable pour plusieurs fichiers successifs
sans mélanger leurs paliers). `filename` accepté en `bytes` ou `str` selon la version de
`paramiko`/`scp`, décodé avant journalisation. Câblé sur les deux appelants réels
(`_push_feature_file`, et un callback unique par `CaptureRotationThread`). 12 nouveaux tests
dans `test_scp_transfer.py` (plutôt qu'un nouveau fichier : les faux backends SCP y sont déjà).

**Non fait, délibérément** : la remontée **jusqu'à la page « Journal » de la GUI** et au CLI
verbeux, pourtant au cœur de la proposition d'origine. Le callback journalise en DEBUG via
loguru ; il n'alimente aucun widget GTK. À traiter séparément si le besoin se confirme — ne pas
lire ce point comme entièrement clos.

**Bug trouvé par les tests écrits pour ce point** : la première version journalisait une ligne
« 0% » parasite avant le premier palier (`0 > -1` sur le palier initial). Corrigé, détail dans
[session 60](sessions/session-60.md).

### 7. Keepalive netmiko sur la connexion de polling longue durée — ✅ **Fait (session 57, 12/09/2026)**

**Constat** : le profil `hp_comware` de netmiko accepte un paramètre `keepalive` (paquets
périodiques, confirmé contre la documentation du module HP de netmiko) ; le dict `device`
construit par `connect_switch()` (`switch_capture_core.py`) ne le positionne pas (seuls
`device_type`/`host`/`username`/`password`/`fast_cli` sont présents).

**Proposition** : même famille que le bug SCP déjà corrigé le 23/08/2026 (le switch semble
fermer les sessions SSH inactives) — un `keepalive` réduirait ce risque sur la connexion de
polling (`_poll_conn`), potentiellement ouverte plus longtemps qu'une connexion SCP par
fichier (déjà réouverte à chaque transfert depuis la correction du 23/08/2026). Changement
lui-même trivial (un paramètre de dict) ; l'effet réel resterait à confirmer contre un switch
physique, comme le point « Pas fait » ci-dessus sur la mesure SCP réelle.

**Réalisé** : voir section « Connexion SSH de contrôle (netmiko) » sous « Fait — capacités
actuelles » ci-dessous, et [session 57](sessions/session-57.md) pour le détail complet.
`keepalive=30` ajouté au dict `device` (`NETMIKO_KEEPALIVE_SECONDS`, valeur documentée en
commentaire au-dessus de `connect_switch()`), `tests/test_connect_switch.py` étendu (3 tests
existants + 1 nouveau), suite complète revérifiée sans régression.

### 8. Support d'un keyfile PyKeePass en plus du mot de passe maître

**Constat** : `PyKeePass(path, password=..., keyfile=...)` accepte un fichier clé en plus ou à
la place du mot de passe maître (confirmé contre la documentation pykeepass — `CredentialsError`
couvre aussi un keyfile incorrect/manquant) ; `_open_keepass_db` (`switch_capture_core.py`)
n'accepte aujourd'hui que le mot de passe maître seul.

**Proposition** : ajout rétrocompatible d'un `--keepass-keyfile`/clé YAML `keepass_keyfile`
optionnel (`None` par défaut, comportement actuel inchangé si absent) — pratique de
durcissement KeePass courante (mot de passe + keyfile), non supportée aujourd'hui par le repli
KeePass de cet outil.

**Tests prévus** : extension de `test_keepass_password.py` (faux backend `PyKeePass` déjà en
place) — cas avec keyfile fourni/absent/invalide, aucun vrai fichier `.kdbx`/`.keyx` requis.

**Réalisé** : voir [session 59](sessions/session-59.md) pour le détail complet. `_open_keepass_db`
et les 3 fonctions publiques (`save_ssh_password_to_keepass`/`load_ssh_password_from_keepass`/
`delete_ssh_password_from_keepass`) étendues avec `keepass_keyfile: str | None = None` en
dernier paramètre (rétrocompatible) ; `--keepass-keyfile` ajouté sur `capture`/`inspect`, fil
de transmission complet jusqu'à `build_config`/`_apply_password_keyring_actions`. 13 nouveaux
tests dans `test_keepass_password.py`, dont un second faux backend
(`FakePyKeePassRequiringKeyfile`) qui vérifie réellement la valeur de `keyfile` reçue — le faux
backend d'origine l'accepte sans la contrôler, insuffisant pour prouver la transmission. Deux
tests de complétude documentaire mis à jour en conséquence (voir « Tests automatisés
(pytest) » ci-dessous), `USAGE.md` complété. GUI volontairement pas étendue (scope cœur + CLI
cette session).

### 9. Migration GTK4 `Gtk.FileChooserNative`/`Gtk.MessageDialog` → `Gtk.FileDialog`/`Gtk.AlertDialog`

**Constat** : les deux classes utilisées aujourd'hui dans `switch_capture_gtk.py` (sélecteurs
de dossier, `Gtk.FileChooserNative` lignes **853/870** ; confirmations, `Gtk.MessageDialog`
lignes **1793/2045/2085/2549** — numéros remis à jour après le reformatage de la
[session 61](sessions/session-61.md), ex-~845/862 et ~1664/1902/1942/2355) sont dépréciées
depuis GTK 4.10 au profit de `Gtk.FileDialog`/
`Gtk.AlertDialog` (API asynchrone `*_async`/`*_finish` plutôt que le signal `response` actuel
— confirmé contre la documentation PyGObject à jour). Ni cassé ni supprimé aujourd'hui : dette
technique, pas un bug actif.

**Proposition** : chantier plus lourd que les points 5 à 8 (6 sites d'appel + réécriture des
scripts ad hoc Xvfb qui les valident, la GUI restant hors périmètre pytest — voir section
« Tests automatisés » plus haut). **À ne pas traiter à l'aveugle** : vérifier d'abord la
version GTK4 réellement disponible sur les cibles de packaging actuelles (Debian, Rocky/RHEL 9
— paquet système `gtk4`, voir `packaging-rpm/switch-capture.spec`) avant de s'engager sur la
nouvelle API asynchrone, même principe que la vérification d'alias 5510/5520 ci-dessus (ne
jamais deviner sans preuve).

**Tests prévus** : pas de nouveau fichier `tests/` pytest (comportement GTK4 hors périmètre,
comme le reste de la GUI) — mise à jour des scripts ad hoc Xvfb existants qui valident déjà les
6 sites d'appel actuels.

## Fait — capacités actuelles

### Capture — 4 méthodes distinctes (voir `CAPTURE-METHODS.md`)

- **packet-capture local** (`--output-mode fifo`/`tap`) : détection de
  modèle, activation SCP, installation de la feature si nécessaire,
  lancement avec filtre inline optionnel, rotation de fichiers, arrêt
  propre.
- **packet-capture remote / RPCAP natif Comware** (`--output-mode rpcap`) :
  `packet-capture remote interface ... port ...`, pas de fichier local,
  Wireshark se connecte directement au switch.
- **Port mirroring** (`switch-capture mirror`) : SPAN local et ERSPAN/GRE
  distant, syntaxe Comware vérifiée contre la doc H3C officielle
  (`mirroring-group`, `interface tunnel ... mode gre`,
  `service-loopback type tunnel`), avec teardown.
- **Flow mirroring filtré par ACL** (`switch-capture mirror --filter-mode
  acl`, ajouté le 01/09/2026) : ne duplique que le trafic correspondant à
  une ACL avancée (`traffic classifier`/`traffic behavior`/`qos policy`),
  local ou ERSPAN/GRE distant, avec teardown — CLI et GUI, cette
  dernière câblée le 02/09/2026 (voir section dédiée plus bas).
- **Mirroring vers VLAN sonde + VXLAN L2** (`switch-capture mirror
  --mode vxlan`, ajouté le 05/09/2026) ⚠️ **expérimental** : achemine le
  trafic mirroré jusqu'au collecteur par extension L2 VXLAN plutôt qu'un
  trunk physique ou un tunnel GRE — combinaison non officiellement
  documentée par H3C, imposée par retour d'expérience direct d'un
  utilisateur sur un 5520 HI (voir section dédiée plus bas) ; jamais
  vérifiée contre un switch réel dans ce dépôt. CLI et GUI toutes deux
  câblées (GUI le 06/09/2026, voir section dédiée).

### Connexion SSH de contrôle (netmiko)

- Une seule fonction, `connect_switch()`, pour toutes les connexions SSH de
  contrôle (commandes `display`/`install`/... — distincte de la connexion
  SCP dédiée au transfert de fichiers ci-dessous) : profil `device_type:
  hp_comware`, `fast_cli: False`.
- **Keepalive (12/09/2026, session 57)** — paquets de maintien de connexion
  SSH toutes les 30 s (`keepalive=30` via la constante
  `NETMIKO_KEEPALIVE_SECONDS`, paramètre natif de netmiko, désactivé par
  défaut côté netmiko). Vise en particulier la connexion de polling
  `_poll_conn` (`CaptureRotationThread`), qui peut rester ouverte bien plus
  longtemps qu'une connexion SCP par fichier (déjà réouverte à chaque
  transfert depuis la correction du 23/08/2026 ci-dessous) — même famille
  de risque que ce bug SCP déjà corrigé (le switch semble fermer les
  sessions SSH inactives). Valeur choisie par analogie avec
  `ServerAliveInterval` d'OpenSSH (30 s, usuel contre des pare-feux/NAT à
  état) — **non vérifiée empiriquement contre un switch réel** (comme la
  mesure de durée SCP réelle, voir « Pas fait » ci-dessous) ; le
  changement de code lui-même (un paramètre du dict `device`) est en
  revanche testé et sans risque de régression.
  Testé réellement (pas juste relu) : `pytest tests/test_connect_switch.py`
  (3 tests existants étendus + 1 nouveau garde-fou sur la valeur de la
  constante) puis suite complète (`pytest tests/`) revérifiée sans
  régression — 491 passés, même échec préexistant sans rapport (absence
  de `ip`/iproute2 dans ce sandbox), mêmes 10 skips.

### Transfert de fichiers

- **SCP par défaut** (`transfer_mode: scp`) : liste (`dir flash:/...`),
  rapatriement (`scp_get`) et suppression (`delete flash:/...`) via une
  connexion paramiko dédiée, sans montage FUSE. Testé de bout en bout
  contre un vrai serveur SSH local (put+get réels, parsing de sortie `dir`
  réaliste).
  - **Correction (23/08/2026)** — deux bugs remontés en usage réel :
    1. Le chemin passé au protocole SCP lui-même ne doit **pas** porter le
       préfixe `flash:` — celui-ci n'existe que côté syntaxe CLI Comware
       (`dir flash:/...`, `delete flash:/...`, `install activate feature
       flash:/...`), pas côté serveur SCP, dont la racine EST la flash
       (`10.0.0.1:/capture...`, pas `10.0.0.1:flash:/capture...`). `scp_get`
       et `scp_put` reçoivent désormais `/<fichier>` ; seules les commandes
       CLI (`dir`/`delete`/`install activate`) gardent `flash:/<fichier>`.
    2. `CaptureRotationThread` ouvrait une connexion SCP unique en début de
       capture et la réutilisait à chaque fichier rapatrié tout au long du
       polling. Le switch semble fermer la session SSH dédiée au SCP après
       un transfert, ce qui provoquait un `Bad file descriptor` dès le
       deuxième fichier (réutilisation d'un transport devenu invalide).
       `_process_closed_file_scp` ouvre maintenant une connexion SCP dédiée
       par fichier rapatrié, refermée juste après (même schéma que
       `_push_feature_file`, qui n'était pas concerné).
    Testé réellement (pas juste relu) : `sshd` local, rapatriement séquentiel
    de 2 fichiers avec reconnexion à chaque fichier + contenu vérifié
    octet pour octet, et `scp_put` isolé avec le chemin sans `flash:` — les
    deux au niveau protocole SCP réel, pas mocké. `py_compile` sur les 3
    fichiers source Python après modification.
- **sshfs conservé en mode legacy** (`transfer_mode: sshfs`) pour
  compatibilité avec l'existant.
- `scp server enable` (pas `sftp server enable`) activé automatiquement.

### Réinjection live

- **FIFO + Wireshark auto-lancé** (mode historique).
- **Interfaces TAP** pour captures multiples simultanées dans une seule
  instance Wireshark : création (`ip tuntap add ... mode tap`), injection
  de trames brutes via `TUNSETIFF`/`/dev/net/tun` (`TapFrameWriter`),
  extraction de trames depuis un `.pcap` classique (`iter_pcap_frames`).
  Testé de bout en bout : fichier `.pcap` → extraction → injection TAP →
  `tcpdump` a réellement reçu la trame.

### NTP

Vérification (`display ntp-service status`, avec une regex qui distingue
correctement `synchronized`/`unsynchronized` — piège identifié et corrigé)
et configuration automatique (`ntp-service enable` +
`ntp-service unicast-server <ip>`) si non synchronisé et qu'un serveur est
fourni. Statut écrit dans un sidecar `capture-meta.json` (avec
`capture_label`, switch, interface, filtre, modèle, horodatage) pour
qu'un outil tiers de comparaison de traces (hors périmètre de ce projet)
puisse corréler plusieurs captures d'un même trafic prises à des points
différents.

### Modèles matériels

`5130`/`5140`/`5510`/`5520` : tous nécessitent l'installation de la
feature `packet-capture` (aucun n'est natif à l'image — correction
apportée suite à un retour direct, une version antérieure de ce dépôt
supposait à tort 5510/5520 natifs). `3600 V2` (Comware 5) : non supporté,
signalé explicitement.

**Limite connue (session 08, verrouillée par des tests en [session
50](sessions/session-50.md))** : les alias de détection automatique
(`detect_model`) pour `5130`/`5140` ont été élargis au format réel HPE à
tiret (`5130-28-EI`) après une régression, mais `5510`/`5520` (ainsi que
`MSR4000`/`3600v2`) n'ont **pas** été audités faute de sortie `display
version` réelle disponible pour ces modèles — leurs alias sont restés
sous forme collée (`"5510HI"`), qui ne correspondrait vraisemblablement
pas à une sortie switch réelle si elle suit le même schéma que 5130/5140.
Nécessite un exemple réel vérifié avant correction (voir
`tests/test_model_detection.py`, section « 5510/5520 »).

### Installation — 3 méthodes équivalentes

`install.sh` (Ubuntu/Debian/Rocky/RHEL/CentOS 8-9), paquet `.deb`, paquet
`.rpm` (avec bascule automatique `python3.11` sur el8 / `python3` système
sur el9). Dépendances système privilégiées sur pip partout où c'est
possible (`python3-netmiko`, `python3-loguru`, `python3-paramiko`,
`python3-scp` avant repli pip), `iproute2`/`iproute` pour le mode TAP.
Les trois méthodes lisent le même `src/` (aucune duplication de code de
build en build) et ont été reconstruites/réinstallées réellement à
plusieurs reprises au fil du développement, y compris après chaque
changement de fond.

### CLI

Sous-commandes `capture`, `uninstall`, `mirror`, `import-bin`. Un seul
point d'entrée (`src/switch-capture`) qui bascule automatiquement entre
CLI et GUI GTK4 selon les arguments fournis (`-c`/`-g` pour forcer).

### GUI GTK4 — multi-captures

5 pages (Configuration / Installation / Démarrage / Journal / Résultats)
pilotant potentiellement **plusieurs captures simultanées**
(`CaptureSession`), avec :
- champs de formulaire qui s'affichent/se masquent selon `transfer_mode`/
  `output_mode` choisi (visibilité conditionnelle testée programmatiquement
  sur les 4 combinaisons) ;
- démarrage des captures **gaté** par l'installation complète de toutes
  les captures planifiées (bouton désactivé tant que ce n'est pas le cas —
  demande explicite, testée) ;
- bouton de désinstallation de la feature par capture déjà ajoutée ;
- import d'un dépôt `.bin` local sans quitter la fenêtre ;
- scrollbars classiques toujours visibles (jamais de barre flottante qui
  se cache, jamais de scroll horizontal).

Testé par introspection directe des widgets (comptage de lignes de
`Gtk.ListBox`) et par capture d'écran réelle sous Xvfb (fenêtre ciblée par
ID, pas `import -window root` qui s'est révélé retourner des images
périmées dans ce Xvfb sans compositeur — piège identifié en cours de
route).

### Journalisation — audit systématique des commandes envoyées au switch

Passage dédié sur les ~34 sites d'appel `conn.send_command`/
`send_command_timing` de `switch_capture_core.py` (`list_remote_pcap_files`,
`delete_remote_file`, `_prepare_switch`, `_ensure_transfer_service`,
`_ensure_ntp`, `_activate_feature`, `UninstallThread.run`,
`configure_local_mirror`, `configure_gre_mirror`, `teardown_mirror`) :
chaque commande est désormais loguée juste avant son envoi, y compris les
confirmations `y` sur prompt `[Y/N]`, avec un niveau choisi pour ne pas
noyer le niveau `info` existant : `debug` pour les requêtes en lecture
seule (`display ...`), les confirmations `y`, et le détail commande par
commande des séquences de configuration (mirroring local/GRE, teardown) ;
`info` conservé pour les actions ponctuelles déjà à ce niveau
(activation SCP, activation de la feature, suppression d'un fichier
distant, configuration NTP, résumé mirroring). `configure_local_mirror`/
`configure_gre_mirror`/`teardown_mirror` ont été réécrites avec une liste
de commandes + boucle (plutôt que des appels littéraux séparés), même
ordre et mêmes commandes qu'avant, pour loguer chacune sans dupliquer le
texte de log par site d'appel.

Testé réellement (pas juste relu) : script avec un faux `conn` (`FakeConn`)
qui enregistre chaque commande reçue, `connect_switch` monkeypatché pour
l'injecter à la place d'une vraie session SSH, `logger` de loguru redirigé
vers une liste en mémoire (niveau `TRACE`). Pour chacune des 43 commandes
effectivement envoyées sur tous les chemins ci-dessus (y compris les
branches avec confirmation `y`, la branche GRE avec `loopback_interface`,
et la désinstallation avec suppression du `.bin`), vérification
automatique qu'elle apparaît littéralement dans un message de log capturé
— 0 commande manquante. `py_compile` sur les 4 fichiers sources + import
réel de `switch_capture_core`/`switch_capture_cli` pour confirmer qu'aucune
signature publique n'a changé.

### Tests automatisés (pytest)

Dossier `tests/` à la racine du dépôt, indépendant de GTK4/PyGObject et
d'un switch réel — exécutable avec `uv sync` puis `uv run pytest tests/`
(gestion des dépendances via `uv`, session 63 ; voir CLAUDE.md) :

- `conftest.py` : ajoute `src/` à `sys.path` — `pyproject.toml` gère les
  dépendances (`uv`) mais ne définit aucun `[build-system]`, ce dépôt n'est
  donc pas installable comme un paquet pip, voir CLAUDE.md — `src/` est copié
  tel
  quel par les trois méthodes d'installation).
- `test_capture_templates.py` (22 tests) : couvre la fonctionnalité
  « Modèles de capture réutilisables » ci-dessus — sérialisation/
  désérialisation, non-fuite du mot de passe, validation des noms,
  listing/erreurs.
- `test_uninstall_confirm.py` (10 tests, 23/08/2026) : couvre la
  fonctionnalité « Confirmation renforcée avant désinstallation »
  ci-dessus — `confirm_ip_matches` en isolation (correspondance exacte,
  espaces, casse, saisie vide) et `run_uninstall(..., confirm_ip=...)`
  avec `UninstallThread` remplacée par un faux thread (aucune connexion
  SSH réellement tentée dans ces tests).
- `test_inspect.py` (20 tests, 23/08/2026) : couvre le mode dry run
  ci-dessus — `is_ntp_synchronized` et `format_inspect_report` en
  isolation, validation `InspectConfig`, `inspect_switch` avec `FakeConn`
  (modèle installable actif/pas actif, non supporté, inconnu, forcé), et
  `run_inspect` de bout en bout (succès, config invalide, échec de
  connexion).
- `test_tap_pacing.py` (16 tests, 24/08/2026) : couvre le lissage de
  réinjection TAP ci-dessus — `iter_pcap_frames` avec/sans timestamps sur
  un `.pcap` synthétique, `compute_pacing_delays` en isolation, validation
  `Config.tap_pace_max_gap_seconds`, et `_feed_into_tap` avec
  `FakeTapWriter` + `time.sleep` monkeypatché (délais attendus, ordre,
  plafonnement, non-régression du chemin sans pacing).
- `test_transfer_rate.py` (16 tests, 24/08/2026) : couvre le débit de
  transfert moyen en direct ci-dessus — `compute_average_throughput` et
  `format_transfer_rate` en isolation (aucune dépendance, fonctions pures).
- `test_keyring_password.py` (22 tests, 25/08/2026) : couvre le trousseau
  système pour le mot de passe SSH ci-dessus — `keyring_account_id` en
  isolation, `save`/`load`/`delete_ssh_password_from_keyring` avec un faux
  backend `keyring` en mémoire (`FakeKeyringModule`), comportement sans le
  module `keyring` installé, et le câblage CLI
  (`_maybe_fill_password_from_keyring`, `build_config` de bout en bout,
  `_apply_password_keyring_actions`). Le round-trip contre un **vrai**
  service Secret Service (`gnome-keyring-daemon` sous une session D-Bus
  dédiée) a été validé séparément, hors de cette suite pytest — voir
  section dédiée ci-dessus et CLAUDE.md.
- `test_gvfs_env_workaround.py` (7 tests, 28/08/2026) : couvre le
  contournement GVfs/GOA ci-dessus — positionnement des deux variables
  d'environnement par `switch_capture_gtk.py` et `src/switch-capture`
  (absentes/déjà présentes/partiellement présentes), et un test
  d'intégration bout en bout (Xvfb + session D-Bus réelle) confirmant la
  disparition de l'avertissement `GVFS-RemoteVolumeMonitor`.
- `test_cli_uncovered_pure_functions.py` (14 tests, 10/09/2026, session 51) :
  couvre trois fonctions de `switch_capture_cli.py` repérées à 0 % par un
  premier audit `coverage.py` (jamais utilisé dans ce dépôt avant cette
  session) — `load_yaml` (mapping simple, fichier vide, fichier absent),
  `run_import_bin` (dossier source absent, copie, fusion sans suppression
  côté cible, écrasement d'un fichier en conflit, absence de `.bin` après
  import, résolution du dossier par défaut) et `run_analyze_pacing`
  (fichier valide, fichier absent, magic pcap invalide, valeurs candidates
  explicites, liste vide retombant sur le défaut) — sans dupliquer
  `analyze_pacing_gaps`/`format_pacing_analysis_report` eux-mêmes, déjà
  couverts par `test_pacing_gap_analysis.py`.
- `test_tap_helper_nonroot.py` (+1 test, 10/09/2026, session 51) : ajout de
  `test_ensure_tap_interface_helper_up_failure_raises`, seule ligne de
  `_ensure_tap_interface_via_helper` encore non exercée (branche d'échec de
  l'étape `up`, distincte de celle de `add` déjà couverte).
- Exécuté réellement, en plusieurs lots (voir section dédiée ci-dessus) :
  **415 tests passés, 1 échec préexistant sans rapport** au total sur
  l'ensemble du dépôt (chiffre historique le plus ancien de cette liste,
  106, correspond au seul socle initial + modèles de capture, avant les
  nombreux ajouts ultérieurs documentés section par section ci-dessus).
- **Audit de couverture (`coverage.py`, session 51)** : première exécution
  de `coverage run --source=src -m pytest tests/` de ce dépôt — piste
  explicitement laissée ouverte en fin de [session 50](sessions/session-50.md)
  (« un futur audit de couverture pourrait en révéler d'autres non
  repérées par simple recherche de noms de fonctions »). Résultat :
  `switch_capture_cli.py` 69→78 %, `switch_capture_core.py` 75→76 %
  après les tests ajoutés ci-dessus ; `switch_capture_gtk.py` 10 %, chiffre
  attendu et non traité ici — code GTK4 volontairement hors du périmètre
  pytest de ce dépôt (voir portée ci-dessous), déjà validé par des scripts
  ad hoc Xvfb séparés. Détail complet des lignes encore non couvertes et de
  la méthode d'audit : [session 51](sessions/session-51.md).
- `test_cli_config_yaml_merge.py` (7 tests, 10/09/2026, session 52) et
  +1 test dans `test_keepass_password.py` : poursuite de l'audit de
  couverture (session 52) — `build_config`/`build_inspect_config` avec un
  vrai fichier `--config` YAML sur disque (chargement, priorité des
  arguments CLI sur le YAML, `keepass_path` lu depuis le YAML, garde-fou
  « `load_yaml` non appelée sans `--config` »), et la branche
  `RuntimeError` (jusque-là non exercée) de la sauvegarde de repli KeePass
  dans `_apply_password_keyring_actions`. `switch_capture_cli.py` 78→79 %,
  `switch_capture_core.py` 76 % inchangé (branche déjà côté `cli.py`).
  Détail : [session 52](sessions/session-52.md).
- **`switch_capture_cli.py` 79→99 % (11/09/2026, session 53) — clôture de
  l'audit de couverture entamé en session 51 pour ce fichier.** +5 tests
  dans `test_cli_uncovered_pure_functions.py` (`_configure_logging`,
  `_default_feature_bin_dir`, jusque-là seulement contournée par
  monkeypatch) ; +1 dans `test_uninstall_confirm.py` (branche échec de
  `run_uninstall`, jamais exercée) ; trois nouveaux fichiers —
  `test_run_capture_dispatch.py` (6 tests, dont une livraison réelle de
  `SIGINT` via `os.kill` pour couvrir le corps du gestionnaire, pas
  seulement son installation), `test_run_mirror_command.py` (6 tests,
  `run_mirror` entièrement à 0 % auparavant) et
  `test_cli_main_dispatch.py` (10 tests, dispatch réel des 6
  sous-commandes de `main()`, jamais testée avant cette session). Au
  passage, un vrai bug trouvé et corrigé dans `switch_capture_core.py` :
  `switch_ip`/`ssh_user` sans valeur par défaut dans `Config`/
  `InspectConfig`/`MirrorConfig` faisaient lever un `TypeError` brut
  (au lieu du `ValueError` convivial attendu par `__post_init__`) quand
  ces champs étaient entièrement omis en CLI — `switch-capture capture`
  sans `--switch-ip`/`--ssh-user` plantait avec une trace Python au lieu
  du message d'usage prévu. 28 nouveaux tests au total, 3 lignes restent
  non couvertes à ce stade (998-999, 1003) — la ligne 1003 (garde
  `if __name__ == "__main__"`) sera finalement couverte via `runpy` en
  [session 55](sessions/session-55.md). Détail complet, y compris la
  piste `caplog`/loguru explorée puis abandonnée :
  [session 53](sessions/session-53.md).
- **`switch_capture_core.py` 76→79 % (12/09/2026, session 54) — poursuite de l'audit de
  couverture, cette fois sur `core.py` (candidat #4 de CLAUDE.md, seul non bloqué par un
  facteur externe).** 35 nouveaux tests sur 9 fichiers (3 nouveaux : `test_tap_frame_writer.py`,
  `test_config_validation.py`, `test_connect_switch.py`) : `TapFrameWriter` et `connect_switch`
  (0 % chacune auparavant — remplacées entièrement par des mocks partout où elles sont
  appelées, jamais exercées elles-mêmes), 5 branches de validation de `Config.__post_init__`
  plus `resolve_default_mount_point` (aucun test dédié auparavant, contrairement à sa classe
  sœur `InspectConfig`), la branche "builtin"/MSR4000 de `inspect_switch` et 3 branches de
  `format_inspect_report` (builtin/unsupported/modèle détecté mais inconnu), 3 branches
  d'erreur du repli KeePass, 2 branches manquantes de `ensure_tap_interface`/
  `delete_tap_interface` (repli `ip` réel), la troncature de fin de fichier dans
  `iter_pcap_frames`, l'en-tête trop court dans `convert_pcap_to_pcapng`, et le chemin normal
  de `SetupAndCaptureThread.start_capture_blocking`. 0 régression (486 passés au total,
  mêmes échec préexistant et skips qu'avant). Deux points identifiés puis délibérément laissés
  ouverts plutôt que forcés : les imports optionnels en tête de fichier (testables via
  `importlib.reload`, analyse de sécurité faite mais pas implémentée cette session) et une
  ligne probablement morte dans `SetupAndCaptureThread._prepare_switch` (même principe que
  les lignes closes de `switch_capture_cli.py` en session 53). Le reste des lignes non
  couvertes (mirroring GRE/VXLAN, `UninstallThread.run`, injection TAP/FIFO, polling
  SCP/sshfs — pas encore examinés) reste candidat de continuation. Détail complet, y compris
  le triage bloc par bloc : [session 54](sessions/session-54.md).
- **Fusion de deux branches divergentes (12/09/2026, session 55).** Deux livraisons zip
  distinctes, développées dans deux conversations séparées à partir du même point de départ
  (fin de session 52), ayant chacune mené sa propre « session 53 » (même cible de backlog,
  implémentations différentes) — l'une des deux poursuivie ensuite en session 54. Retenue comme
  base : celle avec le correctif `switch_ip`/`ssh_user` de `switch_capture_core.py` et la
  session 54. Trois scénarios de test de l'autre branche apportaient une couverture réelle en
  plus (non dupliqués ailleurs) et ont été rapatriés : couverture de la ligne 1003 de
  `switch_capture_cli.py` via `runpy` (`TestDunderMainBlock`, 2 tests), vérification du niveau
  de log affiché sur la console selon `verbose` (`capsys`, 2 tests dont 1 déjà existant enrichi),
  et un cas supplémentaire pour `_default_feature_bin_dir` (chemin existant mais qui n'est pas
  un dossier). Le reste des tests « session 53 » de l'autre branche testait les mêmes lignes que
  la base par un chemin différent — non dupliqué. +4 tests nets (490 au total), 0 régression,
  `switch_capture_cli.py` 99 % (998-999 seules lignes restantes). Détail complet :
  [session 55](sessions/session-55.md).
- **Nettoyage `ruff` complet du dépôt + imports optionnels de `switch_capture_core.py`
  couverts (13/09/2026, session 58).** Deux volets indépendants dans la même session (demande
  explicite couvrant les deux) :
  - `ruff check --line-length 120 .` sur l'ensemble du dépôt (jamais fait en un seul passage
    jusqu'ici — seuls les fichiers modifiés par session l'étaient) : 53 erreurs pré-existantes
    corrigées, 0 restante. `C408` (13, `dict()` → littéral) et `RUF100` (13, `noqa: E402`
    devenus inutiles) par autofix ; `PLW1510` (5, `subprocess.run` sans `check=`) par ajout
    manuel de `check=False` ; `BLE001` (22, `except Exception` large) par `# noqa: BLE001`
    après relecture individuelle des 22 sites — tous des frontières d'exception délibérées
    (boucles de threads, nettoyage best-effort, callbacks GTK, commande CLI de premier
    niveau), pas des bugs à corriger en rétrécissant le type intercepté. Annule le choix
    ponctuel de la session 54 de garder 2 `C408` « pour cohérence de style » — demande
    explicite de cette session-ci.
  - `tests/test_optional_imports_absent.py` (5 tests, nouveau fichier) : couvre les 4 blocs
    `try/except ImportError` en tête de `switch_capture_core.py` (`netmiko`, `paramiko`+`scp`,
    `keyring`, `pykeepass`), lignes 33-59, jamais exercés jusqu'ici (seule leur conséquence
    l'était via `monkeypatch.setattr`). Une première approche par `importlib.reload()` du
    module partagé a été **essayée puis rejetée** : elle redéfinit les classes du module
    (dataclasses incluses) en nouveaux objets `class`, cassant `isinstance()` dans
    `test_pacing_gap_analysis.py` (constaté réellement, pas anticipé) pour tout fichier de
    test ayant déjà fait `from switch_capture_core import <Classe>` avant le reload. Approche
    retenue : chargement d'une copie de module isolée via `importlib.util`, jamais enregistrée
    sous `sys.modules["switch_capture_core"]` — le module partagé n'est jamais touché.
    `switch_capture_core.py` : 79→80 %. 496 tests au total, 0 régression (ordre de collecte
    testé dans les deux sens pour confirmer l'absence de fuite d'état). Détail complet,
    y compris le piège `dataclasses`/`sys.modules[cls.__module__]` rencontré en cours de
    route : [session 58](sessions/session-58.md).
- **Fichier de clé KeePass additionnel (13/09/2026, session 59).** Point 8 ci-dessus. 13
  nouveaux tests dans `test_keepass_password.py` : `FakePyKeePass` étendu pour accepter et
  mémoriser `keyfile` ; second faux backend `FakePyKeePassRequiringKeyfile` qui le vérifie
  réellement (le premier, par construction, ne peut prouver que « accepté sans erreur », pas
  « transmis avec la bonne valeur ») — utilisé pour le round-trip save/load/delete avec
  keyfile, le cas keyfile incorrect (traité comme un mot de passe maître incorrect, même
  `CredentialsError` chez pykeepass), et le câblage CLI de bout en bout
  (`_maybe_fill_password_from_keyring`, `_apply_password_keyring_actions`, `build_config`).
  Plus : exposition argparse sur `capture`/`inspect` (valeur fournie et défaut `None`), garde-fou
  de non-régression explicite (les 3 fonctions publiques restent utilisables sans jamais
  mentionner `keepass_keyfile`), attribut `keepass_keyfile` absent d'un `argparse.Namespace`
  traité comme `None` sans lever. A aussi fait apparaître (et corriger) une dépendance
  croisée avec deux tests de garde-fou de complétude documentaire (voir ci-dessus, section
  « État ») — les deux vérifient qu'aucun flag CLI n'est ajouté sans mise à jour de
  `USAGE.md`/`config.yaml.example`, exactement leur rôle. 509 tests au total, 0 régression.
  Détail complet : [session 59](sessions/session-59.md).
- **Callback de progression SCP (14/09/2026, session 60).** Point 6 ci-dessus. 12 nouveaux
  tests dans `test_scp_transfer.py` : transmission de `progress_callback` jusqu'à
  `SCPClient(progress=...)` pour `scp_get` et `scp_put` (plus le cas « paramètre omis →
  `progress=None` », non-régression explicite), et comportement de
  `make_scp_progress_logger` en isolation — paliers successifs, non-répétition dans un même
  palier, plafonnement à 100 % si `sent > size`, `size=0` silencieux (pas de
  `ZeroDivisionError`), `filename` en `bytes` comme en `str`, suivi indépendant par nom de
  fichier, `threshold_percent` personnalisé. **Deux de ces tests ont trouvé un vrai bug**
  (ligne « 0% » parasite avant le premier palier) avant tout câblage réel — corrigé dans la
  foulée. Deux effets de bord traités : `FakeSCPClient.__init__` accepte et mémorise désormais
  `progress`, et `patch_scp_push._fake_put` (`test_setup_and_capture_thread.py`) accepte
  `progress_callback=None` — une signature publique modifiée se répercute au-delà de son
  propre fichier de test, même constat qu'en session 59 avec les tests de complétude
  documentaire. Une fixture `debug_log_messages` retire son sink loguru dans un `finally`
  plutôt que de le laisser enregistré pour le reste de la suite (même préoccupation de fuite
  d'état que la session 58). 522 tests au total, 0 régression. Détail complet :
  [session 60](sessions/session-60.md).
- **Invariant « modèle » de `_prepare_switch` (15/09/2026, session 61).** Sous-piste 2 du
  point 4 de `CLAUDE.md`. Nouveau fichier `tests/test_prepare_switch_model_invariant.py`
  (110 tests) — cas **construits par compréhension depuis `MODEL_PROFILES`** (8 profils,
  28 alias) plutôt qu'écrits à la main : un modèle ajouté demain est automatiquement soumis
  aux mêmes invariants sans toucher ce fichier. Ce fichier **ne couvre pas** la ligne
  concernée (`raise RuntimeError("Modèle inconnu")`), délibérément — il verrouille les trois
  prémisses dont dépend son inatteignabilité : (A) `detect_model()` ne renvoie que `None` ou
  une clé réelle, pour chaque alias déclaré comme sur entrée arbitraire ; (B)
  `Config.__post_init__` refuse tout modèle hors clés, alias compris (`"5510hi"`,
  `"5130-28-EI"` n'en sont pas), sans normalisation implicite des sosies, et
  `dataclasses.replace()` revalide ; (C) aucun code de `src/` ne réaffecte `cfg.model` après
  construction — **vérifiée sur le source** (balayage de `src/*.py`), donc une régression
  future échoue au lieu de rendre l'analyse silencieusement fausse. Deux tests de bout en
  bout exercent le chemin réel (chaque alias, puis chaque clé forcée) et vérifient que le
  message « Modèle inconnu » ne sort jamais. Deux tests sont des **garde-fous des
  garde-fous** : l'un échoue si tous les alias devenaient des clés (prémisse A alors
  triviale), l'autre si la regex de (C) ne matchait plus rien après un renommage de champ.
  Les 110 tests étant passés au vert du premier coup, ils ont été validés par **3 mutations**
  sur une copie jetable du dépôt (`detect_model` renvoyant l'alias → 36 échecs et ligne 2415
  réellement atteinte ; validation `Config` retirée → 30 échecs ; `cfg.model = ...` injecté
  dans `src/` → le seul test de prémisse C). Couverture **inchangée** (291 lignes non
  couvertes sur `core`, même compte qu'en session 60) : attendu et assumé, ces tests
  exercent des chemins déjà couverts. 632 tests au total, 0 régression. Détail complet :
  [session 61](sessions/session-61.md).
- **`UninstallThread.run` (15/09/2026, session 62).** Point 4, plus gros bloc du triage.
  Nouveau fichier `tests/test_uninstall_thread.py` (29 tests). `FakeConn` qui **journalise
  toutes les commandes reçues dans l'ordre** : sur la seule séquence destructrice du projet
  (`install deactivate`, `install commit`, `delete /unreserved`, suppression des `.pcap`),
  vérifier qu'une commande est partie ne suffit pas — il faut pouvoir vérifier l'ordre et
  surtout les **absences**. Couvre : priorité `cfg.model` > `state.model` > `detect_model` ;
  modèle indéterminable → échec propre **et aucune commande destructrice émise** ; modèles
  non installables (paramétré sur les profils `builtin`/`unsupported`) → nettoyage des
  `.pcap` sans désactivation ; découverte du nom via `display install active` vs nom
  configuré ; `deactivate` avant `commit` ; réponse `y` aux deux motifs d'invite et absence
  de `y` parasite sinon ; suppression du `.bin` absente par défaut et postérieure au commit
  quand demandée ; `disconnect()` y compris sur coupure en plein `install deactivate`.
  **A trouvé un vrai bug** : `(\S*packet-capture\S*\.bin)` capturait le préfixe média listé
  par Comware, d'où `install deactivate feature flash:/flash:/...` — commande rejetée par le
  switch, donc désinstallation impossible sans `--feature-bin-path` (chemin du bouton
  « Désinstaller » de la GUI après redémarrage). Format réel vérifié contre la command
  reference HPE Comware 7 **avant** de conclure au bug, correctif (`[\w.-]` au lieu de `\S`)
  prouvé porteur par restauration de l'ancienne expression (3 échecs). Un test fige aussi un
  constat non corrigé : le message de sortie annonce « packet-capture natif » y compris pour
  `3600v2`, dont le profil est `unsupported` — conclusion exacte, justification trompeuse, à
  trancher plus tard plutôt que modifiée au passage. `switch_capture_core.py` 80→84 %.
  661 tests au total, 0 régression. Détail complet : [session 62](sessions/session-62.md).

Portée volontairement limitée aux comportements testables sans GTK4/
PyGObject ni switch réel ; le reste du projet — y compris, pour
l'instant, le dialogue GTK de confirmation ajouté aujourd'hui — reste
validé par les scripts ad hoc décrits section par section ci-dessus
(FakeConn, sshd local, Xvfb...), pas encore converti en suite `pytest` —
prochaine étape naturelle d'une session future.

### Packaging / distribution

`.deb` et `.rpm` avec dépendances correctement déclarées (`Depends`/
`Requires` vs `Recommends` selon ce qui est strictement nécessaire),
groupe système `switch-capture` pour le partage des dossiers de données,
scripts d'installation/désinstallation propres. `README.md`,
`CAPTURE-METHODS.md` (packet-capture / rpcap / mirroring+GRE, procédures
manuelles multi-constructeurs HPE/Cisco/Juniper/Arista), `LICENSE`
(placeholder MIT), `.gitignore` — dépôt prêt à pousser sur GitHub.


## Historique des demandes (points 1 à 20)

20 points numérotés au total depuis la création de cette liste ; **tous traités**, 0 point
numéroté encore ouvert. Détail du raisonnement de chaque résolution : voir la session liée
dans `docs/sessions/`. Détail « côté tests » d'origine : voir
`docs/sessions/_archive-fait-detaille-pre-2026-09-08.md`.

| # | Demande | Résolu | Session(s) |
|---|---------|--------|------------|
| 1 | Bouton menu hamburger en haut à gauche | 29/08/2026 | [21](sessions/session-21.md) |
| 2 | Contenu du menu : Préférences puis Quitter | 29/08/2026 | [21](sessions/session-21.md) |
| 3 | Page Préférences regroupant les réglages épars | 29/08/2026 | [21](sessions/session-21.md) |
| 4 | Mot de passe SSH jamais en clair (trousseau système + repli KeePass) | 25→29/08/2026 | [3](sessions/session-03.md), [4](sessions/session-04.md), [14](sessions/session-14.md), [19](sessions/session-19.md), [21](sessions/session-21.md) |
| 5 | Filtre de capture : masquage du trafic SSH/SCP outil↔switch | 26/08/2026 | [9](sessions/session-09.md), [15](sessions/session-15.md) |
| 6 | Capture bidirectionnelle (inbound + outbound) | 26/08/2026 | [11](sessions/session-11.md), [15](sessions/session-15.md) |
| 7 | Bloquer la désinstallation pendant une capture en cours | 28/08/2026 | [16](sessions/session-16.md) |
| 8, 9, 11, 12 | Bugs GVFS/GOA du sélecteur de fichiers GTK | 28/08/2026 | [20](sessions/session-20.md) |
| 10 | Arrêt propre sur Ctrl+C / SIGINT | 29/08/2026 | [22](sessions/session-22.md), [23](sessions/session-23.md) |
| 13 | Internationalisation CLI + GUI | 30→31/08/2026 | [25](sessions/session-25.md), [26](sessions/session-26.md), [28](sessions/session-28.md) |
| 14 | Lancement automatique de Wireshark en mode TAP | 26→28/08/2026 | [12](sessions/session-12.md), [15](sessions/session-15.md) |
| 15 | Squelette de projet GTK4 futur (`gtk4-project-skeleton`) | 29/08/2026 | [24](sessions/session-24.md) |
| 16 | Étude de faisabilité : plugin extcap Wireshark | 27/08/2026 | [13](sessions/session-13.md) |
| 17 | Mode non-root pour le mode TAP | 28/08/2026 | [17](sessions/session-17.md) |
| 18 | Sélection packet-capture / port mirroring dans le formulaire GUI | 28/08/2026 | [18](sessions/session-18.md) |
| 19 | Archivage automatique en pcapng | 26→28/08/2026 | [10](sessions/session-10.md), [15](sessions/session-15.md) |
| 20 | Mirroring distant VLAN + VXLAN L2 (switch 5520 HI) | 04→06/09/2026 | [36](sessions/session-36.md), [37](sessions/session-37.md), [38](sessions/session-38.md) |


## Pas fait — demandé mais reporté faute de temps

Ce point a été demandé explicitement et reste **partiellement non
implémenté** — les parties packaging pur + core + CLI + GUI, ainsi que le
découplage téléchargement/injection (voir section dédiée ci-dessus,
26/08/2026), ont désormais toutes été traitées et testées ; seule la
partie qui suit nécessite un switch réel et n'a pas pu être traitée dans
cette session :

1. **Mesure réelle du timing spool → injection TAP, en conditions
   réelles.** La question posée à l'origine — avec une rotation à 20 s,
   un décalage d'injection de 30 s (l'hypothèse « 10 s pour collecter et
   lire le fichier » restant à vérifier, "faut peut-être plus")
   permettrait-il une arrivée plus fluide des données côté TAP —
   nécessite de mesurer réellement la durée SCP + extraction de trames
   sur un fichier de taille représentative contre un switch réel, puis de
   comparer l'expérience "live" avec et sans `--tap-pace-playback`/valeur
   de `--tap-pace-max-gap` en pratique. Le mécanisme de lissage lui-même,
   son câblage CLI/GUI et le découplage téléchargement/injection sont
   tous implémentés et testés en isolation (voir sections ci-dessus) ; ce
   qui reste hors de portée sans switch : la mesure empirique et le
   réglage fin des valeurs par défaut. Non testable en isolation par
   construction. **Volet analyse ajouté le 31/08/2026** (voir CLAUDE.md,
   section dédiée) : `analyze_pacing_gaps` + `format_pacing_analysis_report`
   (`switch_capture_core.py`) et nouvelle sous-commande
   `switch-capture analyze-pacing <fichier.pcap>` — étant donné un .pcap
   déjà rapatrié (réel ou, en attendant, synthétique), calcule la
   distribution des écarts inter-trames (min/médiane/p90/p95/p99/max) et
   simule l'effet de plusieurs valeurs candidates de `--tap-pace-max-gap`
   sur ce fichier précis (combien d'écarts seraient raccourcis, durée de
   rejeu résultante). Ceci répond au volet « quelle valeur de
   `--tap-pace-max-gap` choisir, une fois qu'on a une vraie capture » —
   **ne répond toujours pas** au volet « combien de temps prend le SCP
   lui-même », qui reste la seule chose bloquée par l'absence de switch
   réel dans ce sandbox. 19 tests unitaires dédiés
   (`tests/test_pacing_gap_analysis.py`, dont 7 ajoutés en [session
   50](sessions/session-50.md) pour `format_pacing_analysis_report`),
   tous passés réellement (percentile
   vérifié contre un calcul de référence indépendant, cas limites 0/1
   trame, écarts négatifs, cohérence stricte avec `compute_pacing_delays`
   déjà existant). Testé en conditions réelles (vraie invocation CLI, pas
   seulement `py_compile`) sur un fichier .pcap synthétique de 50 trames à
   écarts variés, en français et en anglais (i18n étendue en conséquence,
   voir section « Internationalisation » plus bas).

## Autres limites connues, déjà documentées ailleurs

- GUI : « Modifier » une capture déjà ajoutée (voir section dédiée
  ci-dessus, 25/08/2026) retire la session puis repeuple le formulaire —
  ce n'est donc toujours pas de l'édition in-place au sens strict (le
  clic sur « + Ajouter cette capture » reste nécessaire pour valider), la
  ressaisie manuelle complète a simplement disparu.
- `packet-capture remote` (rpcap) : disponibilité réelle non garantie sur
  tous les modèles/versions. **Vérification ajoutée le 07/09/2026** (3e
  session du jour) : `switch-capture inspect` envoie désormais aussi
  `display packet-capture status` et affiche sa sortie brute (nouvelle clé
  `rpcap_status_raw` dans `inspect_switch()`, restituée telle quelle par
  `format_inspect_report()` — partagé par CLI et GUI, donc le bouton
  GTK4 « Inspecter (dry run) » en bénéficie automatiquement sans aucun
  câblage GUI supplémentaire à écrire). Volontairement **non parsée en
  booléen** : faute d'un exemple de sortie réelle vérifié contre un
  switch physique, transformer ce texte en `True`/`False` aurait été une
  supposition non testable plutôt qu'une vérification — la limite
  documentée ici (« à vérifier au cas par cas ») reste donc entière sur le
  fond, seul le moyen de le faire (une commande de plus dans le rapport
  dry run existant, au lieu d'une commande manuelle séparée) a changé.
  `None` distingue explicitement « commande vide/non reconnue par ce
  switch » d'une chaîne vide, même logique que le reste du rapport dry
  run (`feature_already_active`, etc.). Testé réellement (`pytest`, pas
  seulement relu) : 6 nouveaux tests dans `tests/test_inspect.py`
  (`FakeConn`, aucun switch réel) — sortie présente multi-lignes, absente
  (`None`, pas de chaîne vide), garde-fou « toujours un `display`, jamais
  de config » identique aux autres vérifications du mode dry run, rendu
  texte (`format_inspect_report`) avec et sans la clé, et compatibilité
  ascendante si un appelant fournit un `report` sans cette clé
  (`report.get(...)`, ne plante pas). Suite complète repassée après ce
  changement : 314 passés (308 + 6), 4 échecs et 7 skips inchangés (même
  cause pré-existante et sans rapport, voir en tête de ce document),
  `ruff` revérifié sur les deux fichiers touchés (mêmes 16 erreurs
  pré-existantes qu'avant ce changement, aucune nouvelle introduite),
  `py_compile` sur les deux fichiers. CLI et GUI toutes deux couvertes
  sans code GTK4 à écrire ni à tester séparément, grâce au partage
  `format_inspect_report` déjà en place — aucun besoin d'environnement
  GTK4/PyGObject/Xvfb pour cette tâche, contrairement à la plupart des
  ajouts GUI de ce dépôt.
- Comparaison de traces entre plusieurs points de capture : hors périmètre
  de cet outil par choix (un autre projet s'en charge) — switch-capture se
  limite à produire des traces propres, horodatées de façon fiable (NTP)
  et étiquetées (`capture_label` + sidecar JSON).
