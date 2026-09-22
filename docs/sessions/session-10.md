# Session 10 — 26/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Archivage en pcapng (26/08/2026, suite)

Tâche suivante traitée dans `features.md` (« Reste à corriger et à
faire », point 19, « Privilégier pcapng à pcap »). Même contrainte
d'environnement que les sessions précédentes de cette journée : pas de
GTK4/PyGObject/Xvfb disponible, donc portée limitée au core/CLI,
testable en isolation (`pytest`).

**Choix de portée.** Le format `.pcap` classique écrit par
`packet-capture` sur la flash du switch est imposé par le firmware
Comware (hors de portée de cet outil), et la réinjection live
(FIFO/TAP) continue de lire ces `.pcap` classiques rapatriés sans
changement — `iter_pcap_frames` reste le seul parseur utilisé à ce
stade, inchangé. Le point d'application choisi pour « privilégier
pcapng » est donc l'**archivage** (`Config.archive_dir`) : c'est la
seule étape qui produit des fichiers destinés à être conservés
durablement (sinon suppression immédiate après fusion), donc le seul
endroit où le format de stockage a un intérêt à long terme.

**`convert_pcap_to_pcapng(pcap_path, pcapng_path)`** (nouvelle fonction
pure) : réécrit un `.pcap` classique en `.pcapng` (RFC 9292) valide —
Section Header Block, une Interface Description Block reprenant le
`LinkType` (champ `network` du header pcap classique, mêmes valeurs
numériques dans les deux formats) du fichier source, puis une Enhanced
Packet Block par trame — en réutilisant `iter_pcap_frames(with_timestamps=
True)` pour le parsing. Aucune dépendance externe ajoutée (pas de
scapy/tshark) : uniquement `struct`, comme le reste du parsing pcap déjà
présent dans ce module. Un helper interne `_pcapng_block(block_type,
body)` factorise l'enveloppe commune à tous les blocs (longueur répétée
en début/fin, bourrage à 4 octets).

**`archive_capture_file(pcap_file, archive_dir, as_pcapng=True)`**
(nouvelle fonction) : factorise le code d'archivage jusqu'ici dupliqué à
l'identique entre `_feed_into_tap` et `_feed_into_fifo` (un simple
`shutil.move`). Point de conception : que faire si la conversion pcapng
échoue (fichier déjà corrompu, par exemple) ? Repli explicite sur
l'archivage `.pcap` classique plutôt que de propager l'exception — un
échec de conversion ne doit jamais faire perdre le fichier source, la
préservation des données prime sur la préférence de format. Capturé par
`except (ValueError, OSError)` avec `logger.warning`, comportement
vérifié par un test dédié (fichier corrompu → archivé quand même, en
`.pcap`, contenu intact).

**Nouveau champ `Config.archive_as_pcapng: bool = True`** — actif par
défaut, cohérent avec la formulation de la demande (« privilégier »).
Sans effet si `archive_dir` n'est pas défini. **CLI** :
`--no-archive-as-pcapng`, même convention opt-out que
`--no-ensure-ntp`/`--no-hide-capture-traffic` (`store_const` +
`default=None`, récupéré automatiquement par `_CONFIG_FIELDS` dans
`switch_capture_cli.py` sans code de câblage supplémentaire — même
mécanisme générique que pour les champs booléens précédents).

`_feed_into_tap`/`_feed_into_fifo` appellent désormais
`archive_capture_file` au lieu de leur `shutil.move` inline respectif ;
la réinjection live elle-même (avant l'étape d'archivage) est strictement
inchangée dans les deux modes.

`tests/test_pcap_to_pcapng.py` (12 tests nouveaux) : structure du fichier
`.pcapng` produit (un parseur pcapng minimal écrit dans le test lui-même,
indépendant du code testé, pour vérifier l'ordre des blocs SHB/IDB/EPB),
préservation exacte des octets de trame et du `LinkType`, préservation
des timestamps (résolution microseconde, comme le pcap source), erreur
propagée sur pcap source invalide, cas d'un pcap sans aucune trame,
`archive_capture_file` avec/sans conversion et son repli sur corruption,
câblage réel dans `_feed_into_tap`/`_feed_into_fifo` (fichier
effectivement archivé en `.pcapng` par défaut, en `.pcap` si
`archive_as_pcapng=False`), et défaut du nouveau champ de `Config`.

`pytest tests/ -v` : **135 passed** (123 précédents + 12 nouveaux, aucune
régression). `ruff check --line-length 120 src/` : toujours **20**
erreurs, toutes `BLE001` préexistantes — aucune nouvelle catégorie
introduite par ce changement (un `RUF046` et un `C408` détectés en cours
de route sur du code nouveau ont été corrigés avant la validation
finale : `int(round(...))` → `round(...)`, `dict(...)` → littéral `{...}`
dans le fichier de test).

**Non fait** : intégration GUI (case à cocher dans la future page
Préférences, sur le modèle exact de `hide_capture_traffic`/
`tap_pace_playback` — voir section dédiée plus haut), faute
d'environnement GTK4/Xvfb dans cette session. Tous les autres points de
la todo-list `features.md` restent également non traités, notamment les
deux priorités urgentes (mode non-root, sélection
packet-capture/mirroring/rpcap dans le formulaire).

