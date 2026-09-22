# Session 36 — 04-05/09/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Piste de capture distante : mirroring vers VLAN + VXLAN L2 sur switch 5520 HI (04-05/09/2026)

Signalé par l'utilisateur : sur un switch 5520 (HI), possibilité de
faire un `mirroring-group` vers un VLAN dédié (ex. VLAN 666), puis
d'amener ce VLAN jusqu'au Linux de capture via du VXLAN L2 — une 5e
méthode de capture potentielle, distincte des 4 déjà implémentées
(`packet-capture` local, `packet-capture remote`/RPCAP, port mirroring
SPAN/GRE, flow mirroring filtré par ACL).

Session **purement documentaire** : recherche web sur la documentation
officielle H3C/HPE pour vérifier la faisabilité et comprendre la
syntaxe réelle avant d'envisager du code — même standard de rigueur que
le reste de ce dépôt (« syntaxe Comware vérifiée contre la doc H3C
officielle » avant toute implémentation, jamais l'inverse). Aucun
fichier `.py` touché, aucun test exécuté : rien à vérifier côté
`pytest`/`ruff` cette session.

### Ce qui a été trouvé

Deux mécanismes Comware confirmés indépendamment, mais dont la
combinaison précise n'a pas été retrouvée telle quelle dans un exemple
officiel unique combinant les deux :

1. **Remote-probe VLAN mirroring** (`mirroring-group remote-source` +
   `mirroring-group remote-probe vlan <id>` + port réflecteur) : bien
   documenté côté H3C, de longue date (S3100 jusqu'aux séries
   actuelles). Le switch source recopie le trafic mirroré vers un port
   réflecteur qui le réinjecte dans le VLAN sonde ; celui-ci doit
   ensuite être « autorisé à traverser » les équipements intermédiaires
   jusqu'au switch de destination. Dans tous les documents officiels
   H3C consultés, cette traversée est décrite comme un VLAN réellement
   trunké de proche en proche sur un réseau commuté L2 — **pas**
   nativement via VXLAN dans les exemples trouvés.
2. **VXLAN L2 gateway matériel** : documenté spécifiquement pour la
   gamme **5520 HI** — « VXLAN L2/L3 gateway support for up to 1024
   unicast tunnels with 511 VXLAN/per tunnel » (QuickSpecs HPE) et un
   guide dédié complet, « HPE FlexNetwork 5520 HI Switch Series VXLAN
   Configuration Guide » (référence 5200-8313, HPE, 2021). **Non
   retrouvée confirmée pour un 5520 non-HI** dans les sources
   consultées — point de vigilance à vérifier sur le modèle exact de
   l'utilisateur avant toute suite. Modèle Comware général pour le
   VXLAN L2 (confirmé par ailleurs sur d'autres familles H3C/Comware,
   ex. S6520X) : VSI (ou bridge-domain) associée à un VNI, interface
   `Tunnel` en `mode vxlan` (source/destination en boucle locale) ou
   interface `Nve` (mode multipoint, `peer-list`), raccordement du VLAN
   local à la VSI via `service-instance`/`encapsulation` sur le port,
   ou association VLAN↔VSI directe selon la plateforme exacte.

L'idée de l'utilisateur combine ces deux mécanismes indépendamment
confirmés : au lieu de trunker le VLAN sonde de proche en proche sur un
réseau L2 classique (adjacence L2 bout en bout requise, contraignante),
le lier localement à une VSI/VNI VXLAN pour l'acheminer par-dessus un
réseau routé jusqu'au site de capture. Architecturalement cohérent avec
le fonctionnement de chaque brique séparément, mais **pas** une
combinaison retrouvée telle quelle dans une doc officielle — à
confirmer en pratique (comportement du switch quand un VLAN est à la
fois « sonde de mirroring » et « raccordé à une VSI VXLAN », impact
MTU de l'encapsulation VXLAN, ~50 octets ajoutés, etc.) avant tout code.

C�té Linux (site de capture) : rien de spécifique à développer pour la
réception elle-même — le noyau sait nativement créer une interface
VXLAN (`ip link add vxlanN type vxlan id <vni> ...`), Wireshark/tcpdump
capture directement dessus comme une interface Ethernet ordinaire (VLAN
déjà décapsulé, contrairement au mode `--mode gre` existant qui
nécessite la dissection ERSPAN-dans-GRE côté capture).

### Intérêt potentiel vs. l'existant (`--mode gre`)

- VXLAN utilise l'UDP (port 4789 par défaut), souvent plus simple à
  laisser passer par des pare-feux/NAT que le GRE brut (protocole IP
  47, sans notion de port).
- Permettrait en théorie d'agréger plusieurs groupes de mirroring vers
  le même VLAN sonde, donc un seul tunnel VXLAN pour plusieurs sources.
- Évite la dépendance à la dissection ERSPAN-dans-GRE côté Wireshark.
- Inconvénient principal : dépendance à une fonctionnalité matérielle a
  priori réservée aux modèles « HI », donc moins portable que GRE
  (disponible plus largement sur Comware) — à confirmer précisément sur
  le modèle exact avant de généraliser cette piste.

### Résultat

`features.md` : nouveau point 20 dans la liste numérotée (noté, pas
implémenté), nouvelle sous-section datée documentant la recherche,
décompte de sessions mis à jour (41 → 42). **Volontairement pas ajouté
à `CAPTURE-METHODS.md`** (qui documente les méthodes réellement
supportées) tant que cette piste n'est pas implémentée et vérifiée.

### Confirmation de l'utilisateur (05/09/2026)

L'utilisateur a explicitement tranché la question laissée ouverte plus
haut (« architecturalement cohérent mais pas retrouvé comme
combinaison officielle ») : *« ce n'est pas officiel mais je t'impose
la méthode »*. La méthode est donc désormais traitée comme valide pour
ce projet sur la base de l'expérience directe de l'utilisateur avec ce
matériel, au même titre qu'une documentation H3C officielle l'aurait
été — l'absence de source officielle combinée cesse d'être un obstacle
de principe.

Ce que cette confirmation change, et ce qu'elle ne change pas :
- **Change** : plus besoin d'un switch 5520 HI réel pour trancher « est-ce
  que cette combinaison fonctionne en principe » — c'est acquis.
- **Ne change pas** : la syntaxe Comware exacte (numéros de VLAN, de
  groupe de mirroring, nom de VSI, VNI, numéro d'interface Tunnel/Nve,
  méthode précise de raccordement du VLAN à la VSI) reste à obtenir de
  l'utilisateur avant d'écrire le moindre code — la confirmation porte
  sur le principe, pas sur des paramètres concrets qui n'ont pas été
  donnés. Continuer à ne jamais deviner une commande Comware reste la
  règle, comme pour tout le reste de ce dépôt.

`features.md` mis à jour en conséquence (point 20 et section dédiée) :
statut de la méthode passé de « à valider contre du matériel réel » à
« validée de principe par l'utilisateur, syntaxe exacte encore à
fournir ». Aucun fichier `.py` touché, aucun test à relancer.

### Reste ouvert

- La syntaxe Comware exacte utilisée en pratique par l'utilisateur
  (VLAN/groupe de mirroring/VSI/VNI/interface tunnel) : à demander avant
  toute conception de code (`MirrorConfig`/CLI/GUI). Une fois obtenue,
  cette piste devient implémentable sans dépendre d'un accès matériel
  pour la session qui s'en chargera.
- Sans changement par ailleurs : le volet durée-SCP réelle (« Pas fait »
  n°1, switch physique requis) et la relecture du `.po` `en_US` par une
  personne anglophone native humaine.

