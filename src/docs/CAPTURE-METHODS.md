# Méthodes de capture — packet-capture, mirroring+GRE, rpcap, VXLAN

switch-capture automatise cinq façons distinctes de récupérer du
trafic réseau depuis un switch HPE Comware. Elles ne se valent pas dans
tous les contextes : ce document explique ce que fait chacune, ses
limites, et comment la mettre en œuvre **à la main, sans switch-capture**,
sur HPE Comware, Cisco, et d'autres constructeurs. La quatrième méthode
(flow mirroring, section 4), ajoutée le 01/09/2026, est pilotée par
`switch-capture mirror --filter-mode acl` côté CLI, et depuis le
02/09/2026 également depuis la GUI GTK4 (bloc « Port mirroring », menu
déroulant « Mode de filtrage » — voir features.md). La cinquième
(mirroring vers VLAN sonde + VXLAN L2, section 5, `--mode vxlan`),
ajoutée le 05/09/2026, est **expérimentale** : contrairement aux 4
premières, elle n'a pas été vérifiée contre la documentation H3C
officielle ni contre un switch réel — elle repose sur le retour
d'expérience direct d'un utilisateur de ce dépôt sur un modèle 5520 HI,
qui en a explicitement demandé l'implémentation malgré l'absence de
source officielle combinant les deux mécanismes en jeu (voir section 5
pour le détail complet des réserves).

## Vue d'ensemble

| Méthode | Ce qui capture | Débit | Fichiers sur le switch ? | Multi-capture simultané | Disponibilité |
|---|---|---|---|---|---|
| **packet-capture (local)** | le CPU du switch, en aval du forwarding matériel | limité (CPU) | oui, ring-buffer | via TAP (voir ci-dessous) | selon modèle/version |
| **packet-capture remote (rpcap)** | idem, mais streamé en direct sur le réseau | limité (CPU) | non | oui, nativement (une session rpcap par switch) | selon modèle/version, souvent absente |
| **mirroring (SPAN) + GRE** | le plan de données (ASIC), avant tout traitement CPU | débit ligne | non | oui (un flux GRE par groupe de mirroring) | quasi universelle |
| **flow mirroring (QoS)** | le plan de données (ASIC), mais seulement le trafic filtré par une ACL | débit ligne | non | oui (plusieurs traffic behaviors) | 5130 HI et 5510 HI confirmés dans la doc H3C ; à vérifier ailleurs |
| **mirroring + VXLAN L2** ⚠️ expérimental | le plan de données (ASIC), tout le trafic du/des port(s) source | débit ligne (théorique — non mesuré) | non | à vérifier (un VLAN sonde/VSI par groupe a priori) | 5520 HI confirmé par un utilisateur ; VXLAN matériel a priori restreint aux modèles « HI », non vérifié ailleurs |

**En résumé** : `packet-capture` (local ou remote) est pratique et rapide à
mettre en place via switch-capture, mais voit le trafic *après* qu'il ait
traversé le CPU de management du switch — sur beaucoup de plateformes, ça
veut dire qu'il ne voit que le trafic déjà remonté au CPU (contrôle,
management, exceptions), pas nécessairement tout le trafic commuté en
matériel. Le mirroring (SPAN/RSPAN/ERSPAN) copie le trafic *au niveau de
l'ASIC*, avant tout traitement — c'est la méthode qui reflète fidèlement ce
qui transite réellement sur le fil, à débit ligne, sans limite CPU. Si vous
comparez des traces prises à plusieurs points (client/routeur/serveur) pour
analyser une latence ou une perte réseau fine, le mirroring est
généralement le choix le plus fiable.

## 1. packet-capture (local) — `--output-mode fifo` ou `--output-mode tap`

### Ce que fait switch-capture automatiquement

- Détecte le modèle et active/installe la feature `packet-capture` si
  nécessaire (5130/5140/5510/5520 : `.bin` séparé pour tous — aucun modèle
  actuellement supporté n'est natif à l'image, voir `CLAUDE.md`).
- Lance `packet-capture interface <if> ... capture-ring-buffer ... write
  flash:/...`, rapatrie les fichiers clôturés via SCP, les réinjecte en
  direct (FIFO + Wireshark auto-lancé, ou interface TAP pour plusieurs
  captures simultanées — voir `CLAUDE.md`).

```bash
switch-capture -c capture --switch-ip 10.0.0.1 --ssh-user mathilde \
  --capture-interface GigabitEthernet1/0/1 --output-mode fifo
```

### Manuellement, sans switch-capture (HPE Comware)

```
<Switch> system-view
[Switch] scp server enable
[Switch] quit
<Switch> packet-capture interface GigabitEthernet1/0/1 capture-filter "host 10.0.0.5" \
    limit-captured-frames 0 capture-ring-buffer duration 20 capture-ring-buffer files 10 \
    write flash:/capture.pcap
```
Puis, depuis un poste tiers : `scp user@10.0.0.1:flash:/capture2_00001_....pcap .` pour
chaque fichier clôturé (garder toujours le dernier fichier de côté, encore
en cours d'écriture), et `Ctrl+C` sur la session switch pour arrêter.

### Manuellement sur d'autres constructeurs

Il n'y a pas d'équivalent direct standardisé : chaque constructeur a sa
propre commande de capture locale sur le CPU de management, si elle
existe :
- **Cisco IOS-XE** : `monitor capture <name> interface <if> both`, `monitor
  capture <name> start`, puis `monitor capture <name> export
  flash:capture.pcap` (Embedded Packet Capture, EPC — buffer en RAM, taille
  limitée, pas de ring-buffer disque comme sur Comware).
- **Juniper Junos** : `monitor traffic interface <if> write-file
  capture.pcap` (mode CLI interactif, arrêt par Ctrl+C).
- **Arista EOS** : pas de capture CPU native équivalente ; le mirroring
  (voir section 3) est la voie recommandée par le constructeur.

## 2. packet-capture remote / RPCAP — `--output-mode rpcap`

### Ce que c'est

`packet-capture remote` est une commande Comware native qui fait du switch
un **serveur RPCAP** (le protocole utilisé par Wireshark/libpcap pour la
capture distante) : Wireshark se connecte directement en réseau au switch
(`rpcap://<switch_ip>:<port>/<interface>`), sans fichier intermédiaire, sans
FIFO ni interface TAP locale. Chaque switch expose son propre flux RPCAP
(port 2002 par défaut) : pour comparer plusieurs points de capture, il
suffit d'ouvrir plusieurs interfaces distantes dans la même instance
Wireshark, une par switch — pas besoin de TAP.

**Important, comme signalé** : tous les modèles/versions Comware ne
supportent pas `packet-capture remote` — c'est le même moteur
`packet-capture` que le mode local (voir `MODEL_PROFILES` dans
`switch_capture_core.py`), donc soumis aux mêmes limites de disponibilité
et, sur les plateformes concernées, au même besoin d'installer la feature.
Vérifiez avec `display packet-capture status` ou `packet-capture remote
interface ... ?` en CLI si la commande existe sur votre plateforme/version
avant de vous y fier.

### Ce que fait switch-capture automatiquement

```bash
switch-capture -c capture --switch-ip 10.0.0.1 --ssh-user mathilde \
  --capture-interface GigabitEthernet1/0/1 --output-mode rpcap --rpcap-port 2014
```

Détecte le modèle, installe la feature si nécessaire, vérifie NTP, lance
`packet-capture remote interface <if> port <port>`, attend l'arrêt
(`Ctrl+C`), envoie alors `packet-capture stop`. Aucun `CaptureRotationThread`
n'est utilisé dans ce mode : pas de fichier à rapatrier.

### Manuellement, sans switch-capture (HPE Comware)

```
<Switch> packet-capture remote interface GigabitEthernet1/0/1 port 2014
```
Puis dans Wireshark : **Capture > Options > Manage Interfaces > Remote
Interfaces > +**, IP du switch, port 2014. La liste des interfaces
distantes disponibles apparaît, sélectionnez la vôtre et démarrez. Pour
arrêter côté switch : `packet-capture stop`.

### RPCAP sur un hôte de capture générique (Linux, tout constructeur)

RPCAP n'est pas propre à Comware : c'est un protocole libpcap standard.
Sur n'importe quel hôte Linux servant de **collecteur** (par exemple
recevant du trafic mirroré, voir section 3), vous pouvez exposer une
interface locale en RPCAP avec `rpcapd` (fourni avec les paquets
wireshark/libpcap sur la plupart des distributions) :

```bash
sudo apt install wireshark-common   # fournit rpcapd (Debian/Ubuntu)
sudo dnf install wireshark-cli      # fournit rpcapd (Rocky/RHEL/CentOS)

sudo rpcapd -p 2003 -n   # -n : pas d'authentification (réseau de confiance uniquement)
```
Puis dans Wireshark, comme ci-dessus : IP du collecteur, port 2003. C'est
la solution à utiliser quand le switch/routeur lui-même ne parle pas RPCAP
nativement (Cisco, Juniper, Arista...) : on mirrore le trafic (section 3)
vers un port physique relié à un Linux, et c'est ce Linux qui expose RPCAP.

## 3. Mirroring (SPAN local) + GRE distant — `switch-capture mirror`

### Ce que c'est

Copie du trafic au niveau du plan de données (ASIC), avant tout traitement
CPU — débit ligne, aucune limite liée à `packet-capture`. Deux variantes :
- **local (SPAN)** : le port miroir est un port physique du même switch,
  câblé directement à l'hôte de capture.
- **GRE (ERSPAN tunnel-mode)** : le trafic mirroré est encapsulé en GRE
  (protocole 0x88BE, format ERSPAN) et routé vers un collecteur distant —
  pas besoin de câble direct ni d'un même VLAN/switch.

### Ce que fait switch-capture automatiquement

```bash
# SPAN local
switch-capture -c mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --mode local --source-interface GigabitEthernet1/0/1 \
  --monitor-interface GigabitEthernet1/0/24

# ERSPAN/GRE distant
switch-capture -c mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --mode gre --source-interface GigabitEthernet1/0/1 \
  --tunnel-local-ip 10.0.0.1 --tunnel-ip 192.168.100.1 --remote-ip 203.0.113.10

# Retirer la configuration
switch-capture -c mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --mode gre --source-interface GigabitEthernet1/0/1 --teardown
```

Pousse la configuration puis se termine (pas de thread persistant : le
mirroring continue de fonctionner sur le switch sans supervision une fois
configuré). Côté collecteur, Wireshark décode l'ERSPAN nativement — aucune
interface de réception à créer, `tcpdump -i eth0 proto gre` ou une capture
Wireshark classique sur l'interface physique suffit.

### Manuellement, sans switch-capture (HPE Comware)

```
<Switch> system-view
[Switch] mirroring-group 1 local
[Switch] mirroring-group 1 mirroring-port GigabitEthernet1/0/1 both
[Switch] mirroring-group 1 monitor-port GigabitEthernet1/0/24
[Switch] interface GigabitEthernet1/0/24
[Switch-GigabitEthernet1/0/24] undo stp enable
[Switch-GigabitEthernet1/0/24] quit
```

Pour l'ERSPAN/GRE distant :
```
[Switch] interface tunnel 1 mode gre
[Switch-Tunnel1] ip address 192.168.100.1 255.255.255.0
[Switch-Tunnel1] source 10.0.0.1
[Switch-Tunnel1] destination 203.0.113.10
[Switch-Tunnel1] quit
[Switch] mirroring-group 1 local
[Switch] mirroring-group 1 mirroring-port GigabitEthernet1/0/1 both
[Switch] mirroring-group 1 monitor-port tunnel 1
```
Sur certaines plateformes, un port physique inutilisé doit être assigné
à un groupe de service loopback de type tunnel pour que le trafic GRE
soit traité correctement :
```
[Switch] service-loopback group 1 type tunnel
[Switch] interface GigabitEthernet1/0/23
[Switch-GigabitEthernet1/0/23] port service-loopback group 1
```
(toute la configuration existante du port choisi est perdue à
l'affectation — utilisez un port encore libre, jamais celui qui sert de
`monitor-port`). Si le tunnel ne remonte aucun trafic malgré une
configuration par ailleurs correcte, c'est la première chose à
vérifier ; voir la doc H3C « Service loopback group configuration » de
votre modèle pour les limites exactes (types de service disponibles,
nombre de ports), qui varient selon la plateforme.

### Manuellement sur Cisco

Cisco a l'équivalent exact de cette distinction locale/distante, avec des
noms différents :

**SPAN local** :
```
Switch(config)# monitor session 1 source interface GigabitEthernet1/0/1
Switch(config)# monitor session 1 destination interface GigabitEthernet1/0/24
```

**RSPAN** (mirroring distant *dans le même domaine L2*, via VLAN dédié) :
```
! Switch source
Switch(config)# vlan 999
Switch(config-vlan)# remote-span
Switch(config)# monitor session 1 source interface GigabitEthernet1/0/1
Switch(config)# monitor session 1 destination remote vlan 999

! Switch destination
Switch(config)# monitor session 1 source remote vlan 999
Switch(config)# monitor session 1 destination interface GigabitEthernet1/0/24
```

**ERSPAN** (équivalent Cisco du mode GRE Comware — routé, pas besoin d'être
dans le même domaine L2) :
```
Switch(config)# monitor session 1 type erspan-source
Switch(config-mon-erspan-src)# source interface GigabitEthernet1/0/1
Switch(config-mon-erspan-src)# destination
Switch(config-mon-erspan-src-dst)# erspan-id 1
Switch(config-mon-erspan-src-dst)# ip address 203.0.113.10
Switch(config-mon-erspan-src-dst)# origin ip address 10.0.0.1
```
Le format ERSPAN (0x88BE) est décodé par Wireshark de la même façon, que
la source soit un switch Cisco ou HPE Comware.

### Manuellement sur d'autres constructeurs

- **Juniper (EX/QFX, Junos)** : `set ethernet-switching-options analyzer
  <name> input ingress interface <if>` puis `output interface <if>`
  (local) ou `output ip-address <ip>` pour un mirroring routé (équivalent
  ERSPAN, appelé simplement "analyzer" chez Juniper).
- **Arista EOS** : `monitor session <name> source interface <if>` puis
  `monitor session <name> destination interface <if>` (local), ou
  `... destination tunnel mode gre ...` pour la variante routée.
- **Extreme Networks (EXOS)** : `create mirror <nom> to port-list
  <ports> loopback-port <port> remote-tag <vlan>` pour mirrorer vers
  plusieurs ports (le `loopback-port` est un port physique dédié,
  inutilisable pour du trafic normal, requis dès qu'il y a plus d'une
  destination) ; ou `create mirror <nom> to remote-ip <ip> from
  <ip-locale>` pour la variante routée (depuis EXOS 22.4).
- **Huawei (VRP)** : terminologie différente — le port cible s'appelle
  un « observe-port » (`observe-port <index> interface <if>`, puis
  `port-mirroring to observe-port <index> both` en vue d'interface pour
  du mirroring de port simple, ou `mirror to observe-port` dans un
  traffic behavior pour l'équivalent du flow mirroring). Huawei propose
  aussi un ERSPAN/GRE pour le routé niveau 3, mais la syntaxe exacte
  varie beaucoup selon la gamme (S5700, S6700, CloudEngine...) — se
  référer à la doc « Mirroring Configuration Commands » du modèle
  précis plutôt qu'à un exemple générique.
- **Nokia (SR OS)** : mécanisme orienté service plutôt que port — on
  crée un service de destination (`configure mirror mirror-dest <id>
  create`, avec un type d'encapsulation) puis on y associe des sources
  de trafic (port, SAP...). La hiérarchie exacte des commandes et les
  mots-clés varient significativement selon la gamme (7210 SAS, 7750
  SR...) et la version SR OS — se référer au guide « OAM and
  Diagnostics » du modèle précis plutôt qu'à un exemple générique.
- **Générique/non documenté** : chercher "port mirroring" ou "SPAN" dans la
  doc du constructeur ; la terminologie ASIC/plan de données est
  suffisamment standard (SPAN pour local, RSPAN pour VLAN dédié L2, ERSPAN
  pour routé/GRE) que la plupart des constructeurs s'en inspirent, même
  avec une syntaxe CLI différente.

## 4. Flow mirroring (QoS) — filtré par ACL — `switch-capture mirror --filter-mode acl`

### Ce que c'est

Différent du mirroring de port (section 3, qui duplique *tout* le trafic
d'un port) : le flow mirroring Comware duplique seulement les paquets
qui correspondent à une ACL, via une politique QoS (`traffic
classifier` + `traffic behavior` + `qos policy`). Utile pour isoler un
hôte, un protocole ou une plage horaire précise sans mirrorer tout un
port chargé de trafic non pertinent.

### Ce que fait switch-capture automatiquement

```bash
# Local (mirror-to interface, sans encapsulation)
switch-capture -c mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --filter-mode acl --acl-number 3000 \
  --acl-rule "rule 0 permit ip source 10.0.0.5 0" \
  --source-interface GigabitEthernet1/0/1 --monitor-interface GigabitEthernet1/0/2

# ERSPAN/GRE distant (mirror-to interface destination-ip/source-ip)
switch-capture -c mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --filter-mode acl --mode gre --acl-number 3000 \
  --acl-rule "rule 0 permit ip source 10.0.0.5 0" \
  --source-interface GigabitEthernet1/0/1 \
  --tunnel-local-ip 10.0.0.1 --remote-ip 203.0.113.10

# Retirer la configuration
switch-capture -c mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --filter-mode acl --source-interface GigabitEthernet1/0/1 --teardown
```

Même logique que la section 3 : pousse la configuration (ACL + traffic
classifier + traffic behavior + qos policy, appliquée sur chaque
`--source-interface` dans le(s) sens de `--direction`) puis se termine —
pas de thread persistant, le flow mirroring continue de fonctionner sur
le switch sans supervision une fois configuré. `--acl-rule` est
répétable ; chaque règle est envoyée telle quelle en vue ACL avancée
(donc toute syntaxe `rule ...` valide côté Comware est acceptée, pas
seulement `permit ip source`). Les noms de classifier/behavior/policy
sont dérivés de `--group-id` si `--classifier-name`/`--behavior-name`/
`--qos-policy-name` ne sont pas fournis. Piloté aussi bien par le CLI
que par la GUI GTK4 (bloc « Port mirroring », menu déroulant « Mode de
filtrage » → `acl`, câblé le 02/09/2026 — voir features.md) ; les deux
partagent le même `MirrorConfig`/`configure_acl_mirror` côté core.

L'action `mirror-to` d'un `traffic behavior` accepte plusieurs
destinations, dont deux qui nous intéressent ici :
- `mirror-to interface <if>` — vers un port local (équivalent flux d'un
  SPAN local).
- `mirror-to interface [<if>] destination-ip <ip> source-ip <ip> [dscp
  <n>] [vlan <n>] [vrf-instance <nom>]` — encapsule en ERSPAN (GRE,
  0x88BE) et route vers une IP distante. `<if>` est optionnel : omis,
  le switch choisit l'interface de sortie par recherche de route sur
  `destination-ip`, plutôt que de figer un port. Le mot-clé
  `erspan-id` existe sur certaines plateformes/versions pour taguer les
  paquets — absent sur d'autres ; vérifiez avec `mirror-to interface
  destination-ip ?` en CLI sur votre modèle.

Contrairement à la variante « mirroring-group + tunnel GRE » de la
section 3, cette forme encapsulée n'a **pas besoin** de
`service-loopback group ... type tunnel` sur les versions logicielles
actuelles : H3C documente un ancien « mode loopback » qui en avait
besoin, mais le signale explicitement comme obsolète et fourni pour
information seulement — seul le « mode paramètres d'encapsulation »
ci-dessus (directement `destination-ip`/`source-ip` dans le
`mirror-to`) est supporté sur le logiciel actuel.

Disponibilité vérifiée dans la doc constructeur : le flow mirroring
(`mirror-to`) est documenté pour les séries **5130 HI** et **5510
HI** — donc a priori disponible sur une bonne partie du parc que
switch-capture cible déjà. Pour le 5520 ou tout autre modèle, vérifiez
avec `display traffic behavior` et `mirror-to interface destination-ip
?` en CLI ; la doc constructeur par plateforme n'est pas garantie
identique à 100 % sur toute la gamme.

### Manuellement, sans switch-capture (HPE Comware)

```
<Switch> system-view
[Switch] acl advanced 3000
[Switch-acl-ipv4-adv-3000] rule 0 permit ip source 10.0.0.5 0
[Switch-acl-ipv4-adv-3000] quit
[Switch] traffic classifier C_HOST
[Switch-classifier-C_HOST] if-match acl 3000
[Switch-classifier-C_HOST] quit
[Switch] traffic behavior B_ERSPAN
[Switch-behavior-B_ERSPAN] mirror-to interface destination-ip 203.0.113.10 source-ip 10.0.0.1
[Switch-behavior-B_ERSPAN] quit
[Switch] qos policy P_HOST
[Switch-qospolicy-P_HOST] classifier C_HOST behavior B_ERSPAN
[Switch-qospolicy-P_HOST] quit
[Switch] interface GigabitEthernet1/0/1
[Switch-GigabitEthernet1/0/1] qos apply policy P_HOST inbound
[Switch-GigabitEthernet1/0/1] qos apply policy P_HOST outbound
```
Ici, seul le trafic vers/depuis `10.0.0.5` sur GigabitEthernet1/0/1 est
dupliqué, encapsulé en ERSPAN et routé vers `203.0.113.10` — au lieu du
port entier comme en section 3.

**Piège fréquent** : `qos apply policy` ne prend **pas** de mot-clé
`both`, contrairement à `mirroring-group ... mirroring-port ... both`
en section 3. Une politique QoS ne s'applique qu'à un seul sens par
commande (`inbound` ou `outbound`) sur une interface donnée ; pour
capturer les deux sens il faut les deux lignes `qos apply policy`
ci-dessus, pas une seule avec `both`.

Côté collecteur : identique à la section 3, Wireshark décode l'ERSPAN
nativement.

## 5. Mirroring vers VLAN sonde + VXLAN L2 — `switch-capture mirror --mode vxlan` ⚠️ expérimental

**Statut particulier, à lire avant toute utilisation** : contrairement
aux sections 1 à 4, la syntaxe ci-dessous n'a été vérifiée ni contre la
documentation H3C officielle, ni contre un switch réel dans ce dépôt.
Elle combine deux mécanismes Comware documentés séparément (mirroring
vers VLAN sonde + reflector port d'une part, VSI/VXLAN L2 d'autre part)
dont la combinaison précise n'a pas été retrouvée telle quelle dans un
exemple officiel unique. Elle a été implémentée sur demande explicite
d'un utilisateur de ce dépôt (« ce n'est pas officiel mais je t'impose
la méthode », 05/09/2026), qui en atteste le fonctionnement de par sa
pratique directe d'un switch 5520 HI, avec les paramètres qu'il a
fournis (VLAN 666, groupe de mirroring 10, VSI `mirror`, VNI 666,
Tunnel 0, raccordement par `service-instance`). **À vérifier
impérativement contre votre propre switch avant tout déploiement en
production.**

### Principe

Au lieu de dupliquer le trafic vers un port physique (section 3) ou de
l'encapsuler en GRE (section 3 aussi, mode distant), cette méthode :

1. mirrore le trafic vers un **VLAN sonde** dédié (mécanisme Comware
   « remote-probe VLAN », habituellement utilisé pour acheminer du
   trafic mirroré *de proche en proche* sur un réseau L2 commuté
   jusqu'à un switch de destination distant) ;
2. au lieu de trunker ce VLAN sonde sur un réseau L2 classique
   (adjacence L2 bout en bout requise), le raccorde localement à une
   **VSI VXLAN**, qui l'achemine par-dessus un réseau **routé** jusqu'au
   collecteur — pas besoin d'adjacence L2, juste d'une route IP.

Le collecteur (Linux) reçoit le trafic VXLAN et le décapsule lui-même
(voir « Côté collecteur » ci-dessous) — switch-capture ne pousse que la
configuration côté switch, comme pour les sections 3 et 4.

### Ce que fait switch-capture automatiquement

Pousse, dans l'ordre : création du VLAN sonde, VSI + VNI, interface
Tunnel en mode VXLAN (source/destination), raccordement du tunnel à la
VSI, `service-instance` sur le port réflecteur (raccorde le VLAN sonde
à la VSI), puis le groupe de mirroring (`remote-probe vlan` +
`mirroring-port` + `reflector-port`). `--teardown` retire le tout dans
l'ordre inverse.

```bash
switch-capture mirror --switch-ip 10.0.0.1 --ssh-user mathilde \
  --mode vxlan --group-id 10 --source-interface GigabitEthernet1/0/1 \
  --remote-probe-vlan 666 --vsi-name mirror --vxlan-vni 666 \
  --tunnel-id 0 --tunnel-local-ip 10.0.0.1 --remote-ip 203.0.113.10 \
  --reflector-interface GigabitEthernet1/0/24
```

Équivalent manuel (reconstruction best-effort, non confirmée commande
par commande — voir avertissement ci-dessus) :

```
vlan 666
quit
vsi mirror
 vxlan 666
quit
interface Tunnel0
 mode vxlan
 source 10.0.0.1
 destination 203.0.113.10
quit
vsi mirror
 tunnel 0
quit
interface GigabitEthernet1/0/24
 service-instance 10
  encapsulation s-vid 666
  xconnect vsi mirror
quit
mirroring-group 10 remote-probe vlan 666
mirroring-group 10 mirroring-port GigabitEthernet1/0/1 both
mirroring-group 10 reflector-port GigabitEthernet1/0/24
```

### Côté collecteur (Linux) — hors du périmètre de switch-capture

Contrairement à GRE/ERSPAN (Wireshark décode nativement sur n'importe
quelle interface d'écoute), le VXLAN doit être décapsulé par le noyau
Linux via une interface `vxlan` dédiée, à créer **manuellement** (pas
géré par switch-capture, même philosophie que « pousse uniquement la
configuration de mirroring sur le switch » déjà en vigueur pour les
sections 3 et 4) :

```bash
ip link add vxlan666 type vxlan id 666 dstport 4789 \
  remote 10.0.0.1 local <ip_du_linux_de_capture> dev <interface_de_sortie>
ip link set vxlan666 up
```

Wireshark/tcpdump capture ensuite directement sur `vxlan666` comme une
interface Ethernet ordinaire — le trafic y arrive déjà décapsulé (VLAN
666 d'origine), sans dissecteur particulier à activer.

**Authentification** : le VXLAN standard (RFC 7348) n'a **aucune**
authentification ni chiffrement natifs — le VNI n'est qu'un identifiant
de segment, pas un secret, et n'importe qui capable d'atteindre le port
UDP 4789 du collecteur peut en principe y injecter du trafic. Même
posture que GRE/ERSPAN (sections 3 et 4), déjà sans chiffrement ni
authentification. Mitigation pratique : restreindre par pare-feu/ACL le
port 4789 du collecteur à la seule IP source du switch — pas de
mécanisme d'authentification supplémentaire prévu par switch-capture.

### Limites et réserves connues

- **VXLAN matériel a priori restreint aux modèles « HI »** : la
  documentation HPE trouvée (QuickSpecs + guide de configuration VXLAN
  dédié) ne confirme cette capacité que pour la gamme 5520 **HI** — non
  retrouvée pour un 5520 non-HI. À vérifier sur votre modèle exact.
- **Reflector port** : le mécanisme classique H3C de mirroring vers VLAN
  sonde nécessite un port réflecteur dédié (`reflector-port`) — supposé
  nécessaire ici aussi par analogie, mais son rôle exact combiné au
  raccordement VSI n'a pas été confirmé indépendamment.
- **MTU** : l'encapsulation VXLAN ajoute ~50 octets — non pris en compte
  automatiquement par switch-capture (pas de vérification/ajustement de
  MTU sur le chemin).
- **Pas combinable avec `--filter-mode acl` pour l'instant** :
  volontairement refusé (`ValueError`) plutôt que silencieusement mal
  géré — les interactions entre les deux n'ont pas été étudiées.
- **Jamais testé contre un switch réel dans ce dépôt** : la séquence de
  commandes ci-dessus a été vérifiée uniquement par relecture et par
  test unitaire (simulation de connexion SSH), jamais poussée à un vrai
  5520 HI.

## Laquelle choisir ?

- **Diagnostic ponctuel, rapide, sans câblage supplémentaire** :
  `packet-capture` (fifo/tap), éventuellement `rpcap` si le modèle le
  supporte — tout se pilote depuis switch-capture sans toucher à un câble.
- **Débit élevé, ou trafic qui doit refléter fidèlement ce qui transite
  réellement sur le fil** : mirroring (SPAN/ERSPAN+GRE) — pas de limite
  CPU, mais nécessite un port de destination (câble direct ou tunnel GRE
  routé) et un collecteur (Wireshark/tcpdump/rpcapd) qui écoute côté
  destination.
- **Isoler un hôte, un protocole ou une plage horaire précise, sans
  mirrorer tout un port chargé de trafic non pertinent** : flow
  mirroring (section 4, `switch-capture mirror --filter-mode acl`) —
  même débit ligne que le mirroring de port, mais filtré par ACL en
  amont ; disponible en CLI et en GUI.
- **Collecteur non joignable en L2 mais joignable en IP routé, sur un
  switch 5520 HI (ou équivalent VXLAN matériel)** : mirroring + VXLAN L2
  (section 5, `--mode vxlan`) — ⚠️ expérimental, non vérifié contre la
  doc H3C officielle ni contre un switch réel dans ce dépôt, à valider
  vous-même avant tout déploiement en production.
- **Comparer plusieurs points de capture du même trafic (client, routeur,
  serveur)** : synchronisez d'abord NTP sur tous les points capturés
  (`--ntp-server`, voir `CLAUDE.md`) — sans ça, les timestamps ne sont pas
  comparables entre les traces, quelle que soit la méthode utilisée.
  Ensuite, `rpcap` (si disponible partout) ou le mirroring+GRE vers un
  collecteur commun sont les options les plus directes pour observer
  plusieurs flux simultanément dans une même instance Wireshark.
