# Session 13 — 27/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Étude de faisabilité : switch-capture comme plugin extcap Wireshark (27/08/2026)

Tâche suivante traitée dans `features.md` (« Projet futur », point 16).
Tâche purement de recherche — aucun code produit cette session. Sources
en fin de section, résumées/reformulées ici (voir aussi la version plus
détaillée dans `features.md`, section datée du même jour).

**Constat central** : le mode "fifo" actuel produit déjà exactement le
format qu'exigerait un extcap. `_feed_into_fifo()` écrit un en-tête pcap
classique une seule fois (`self._wrote_global_header`), puis concatène
les trames de chaque fichier `.pcap` rapatrié à la suite dans le même
flux — c'est très précisément ce qu'un extcap doit écrire dans le FIFO
que Wireshark lui fournit via `--fifo` lors du lancement de la capture
(protocole en 4 étapes : `--extcap-interfaces`, puis `--extcap-interface
IFACE --extcap-dlts`, puis `--extcap-interface IFACE --extcap-config`
pour découvrir les options, puis `--extcap-interface IFACE [options]
--capture --fifo CHEMIN` pour la capture elle-même). Seule
l'orchestration change de sens : aujourd'hui `_setup_fifo()` +
`_launch_wireshark()` créent le FIFO et lancent Wireshark ; en extcap
c'est Wireshark qui crée le FIFO et lance l'outil.

**Ce qui se transposerait bien** : les types de champs de configuration
extcap (texte, entier, sélecteur, radio, case à cocher, **mot de passe
masqué**, sélection de fichier) couvrent la plupart des champs actuels
de `Config` sans effort particulier. Les pipes de contrôle optionnels
(`--extcap-control-in`/`-out`) permettraient de remonter un message de
statut dans la barre de statut Wireshark pendant les phases longues
avant le premier paquet (upload de la feature `packet-capture`, attente
côté switch, transfert SCP/TFTP) — un rôle que joue aujourd'hui la page
« Journal » de la GUI.

**Ce qui se transposerait mal (évaluation de cette session)** : extcap
expose un formulaire de configuration plat, pas un assistant multi-
écrans. La détection de modèle, les modèles de capture réutilisables,
l'orchestration de plusieurs captures TAP simultanées et le mirroring de
port (`switch-capture mirror`, commande séparée) n'ont pas d'équivalent
naturel dans ce cadre. Le trousseau système utilisé aujourd'hui pour le
mot de passe SSH n'a par ailleurs aucun lien avec le champ « password »
extcap (Wireshark ne consulterait pas `keyring` à la place de l'outil).

**Recommandation (évaluation, pas une conclusion à valeur de fait)** :
ne pas remplacer l'application GTK par un extcap. Un extcap
**complémentaire et délibérément plus simple** (équivalent du mode
"fifo", capture unique, sans assistant ni gestion de modèles) resterait
envisageable comme point d'entrée rapide, sur le modèle de `sshdump`
(extcap officiel livré avec Wireshark pour la capture SSH distante
générique — précédent direct, mais générique : il suppose un outil de
capture déjà présent côté distant et ne connaît rien à Comware, donc ne
remplace pas ce que fait switch-capture). Non creusé plus avant : hors
périmètre d'une étude de faisabilité, à valider seulement si la demande
se confirme.

**Piste croisée pour le point 17** (urgent, toujours non traité — voir
plus bas) : le man page officiel extcap mentionne en passant le modèle
de privilèges de `dumpcap` (bits setuid/setgid conservés uniquement pour
le groupe système « wireshark ») comme approche déjà éprouvée par le
projet Wireshark pour capturer sans être root. Une piste à évaluer pour
la création d'interface TAP de switch-capture — probablement adaptée
via `setcap`/un groupe dédié plutôt que ce mécanisme setuid précis,
la création de TAP n'ayant pas exactement les mêmes contraintes qu'une
capture passive — mais aucune mise en œuvre ni vérification faite ici.

**Non fait, et pourquoi, une nouvelle fois** : les deux priorités
urgentes (17, 18) n'ont pas été traitées cette session non plus. Le
formulaire de sélection de méthode (18) reste bloqué par l'absence de
GTK4/Xvfb, comme tout le reste des tâches GUI. Le mode non-root (17)
demanderait de pouvoir tester réellement la création d'une interface
TAP sans privilège root complet — impossible ici : ni le binaire
`ip`/iproute2, ni aucun réseau pour l'installer, ne sont disponibles
dans ce bac à sable (confirmé par un essai direct :
`ip tuntap add ... mode tap` échoue avec « commande introuvable », alors
même que le compte d'exécution est root). Livrer un changement de
gestion de privilèges — sujet sensible par nature — sans pouvoir le
vérifier réellement aurait été contraire à la rigueur de test appliquée
au reste de ce projet ; mieux vaut le documenter comme bloqué que de
livrer du code non vérifié sur un sujet sécurité.

**Sources** (recherche web, paraphrasées ci-dessus) : Wireshark
Developer's Guide, chapitre Extcap
(`wireshark.org/docs/wsdg_html_chunked/ChCaptureExtcap.html`) ; page de
manuel `extcap(4)` (`wireshark.org/docs/man-pages/extcap.html`,
`man7.org/linux/man-pages/man4/extcap.4.html`) ; Wireshark Wiki,
Development/Extcap ; exemple officiel `doc/extcap_example.py` du dépôt
Wireshark ; extcap `sshdump` et exemples tiers (`n2disk`, `wlan-extcap`,
`pyspinel`) pour les emplacements d'installation et patterns d'usage.

