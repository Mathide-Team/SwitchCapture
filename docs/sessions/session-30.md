# Session 30 — 01/09/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Documentation : flow mirroring QoS ajouté à CAPTURE-METHODS.md (01/09/2026)

Session sans développement : l'utilisateur a déposé un texte (extrait
d'une conversation avec une autre IA) décrivant du mirroring/capture
« service loopback mirror » et `mirror-to destination-ip` sur H3C/HPE
Comware, Nokia SR OS, Extreme EXOS et Huawei VRP, avec la demande
explicite de vérifier les informations avant de les intégrer.

### Vérification effectuée

Chaque affirmation technique a été confrontée à la doc officielle (H3C
support/download center, Extreme documentation portal, Huawei support,
Nokia infocenter/documentation.nokia.com) avant intégration :

- **Confirmé exact** : la syntaxe Comware `mirror-to interface [<if>]
  destination-ip <ip> source-ip <ip> [dscp/vlan/erspan-id/
  vrf-instance]` (flow mirroring via ACL + traffic behavior + qos
  policy) — vérifiée contre plusieurs versions du guide H3C « Mirroring
  configuration », y compris pour les séries 5130 HI et 5510 HI
  explicitement nommées dans la doc constructeur. Extreme EXOS `create
  mirror ... to port-list ... loopback-port ... remote-tag ...` —
  vérifié également, exact.
- **Erreur repérée et corrigée** : `service-loopback interface loopback
  1` / `type mirror` n'existe pas sur Comware — la doc H3C (« Service
  loopback group configuration ») ne liste aucun type de service
  `mirror`, seulement `tunnel`/`multicast-tunnel`/`multiport`/
  `vsi-gateway` (et `inter-vpn-fwd`/`telemetry-stream` selon la
  plateforme). La bonne commande, déjà correctement résumée dans
  `CAPTURE-METHODS.md` avant cette session (« service-loopback type
  tunnel »), a été complétée avec la syntaxe précise et vérifiée
  (`service-loopback group <id> type tunnel` puis `port
  service-loopback group <id>` en vue d'interface).
- **Erreur repérée et corrigée** : `qos apply policy ... both` n'existe
  pas — seuls `inbound`/`outbound` sont acceptés (un seul sens par
  commande et par interface), confirmé par plusieurs guides H3C. Pour
  mirrorer les deux sens il faut deux commandes `qos apply policy`
  distinctes, pas une seule avec `both` (contrairement à
  `mirroring-group ... mirroring-port ... both`, qui lui accepte bien
  `both`).
- **Non retenu, non confirmé** : `observe-server-ip` (Huawei) —
  introuvable dans la doc Huawei consultée ; le terme réel pour la
  destination locale est `observe-port`. La partie ERSPAN/IP distante
  de Huawei existe mais sa syntaxe exacte n'a pas pu être confirmée
  dans le temps de cette session — non reproduite dans la doc, juste
  mentionnée avec renvoi vers la doc du modèle précis.
- **Partiellement confirmé, hiérarchie CLI incertaine** : Nokia SR OS
  `mirror-dest`/`mirror-source` existe bien dans ce découpage
  conceptuel, mais certaines sources documentent `mirror-source` sous
  `debug>` plutôt que sous `configure>mirror>` comme l'affirmait le
  texte déposé — divergence non tranchée (varie possiblement selon la
  plateforme/version SR OS) ; présenté avec cette réserve plutôt que
  comme un exemple de commandes complet.

### Résultat

`src/docs/CAPTURE-METHODS.md` gagne une section 4 « Flow mirroring
(QoS) » (nouvelle méthode de référence, filtrage par ACL, **non
pilotée par switch-capture** — rien codé cette session), plus des
entrées Extreme/Huawei/Nokia dans la liste multi-constructeurs de la
section 3, et une précision des commandes `service-loopback` déjà
présentes en section 3. Table de vue d'ensemble et section « Laquelle
choisir ? » mises à jour en conséquence. Piste d'amélioration ajoutée
ci-dessus (filtrage ACL pour `switch-capture mirror`).

### Reste ouvert

- Le flow mirroring QoS n'est pas piloté par switch-capture : un futur
  mode ACL pour `switch-capture mirror` reste une piste d'amélioration
  (voir ci-dessus), pas une fonctionnalité livrée.
- La syntaxe Huawei ERSPAN/IP distante et la hiérarchie CLI exacte de
  `mirror-source` chez Nokia restent à vérifier si un jour pertinentes
  pour ce projet — aucun de ces deux constructeurs n'est dans le
  périmètre actuel de switch-capture, qui cible exclusivement HPE
  Comware.

