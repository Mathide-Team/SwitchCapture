# Session 07 — 26/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Découplage téléchargement/injection TAP (26/08/2026)

Traite le point du backlog `features.md` (section « Pas fait ») : avant ce
changement, `_feed_into_tap` — et son éventuel délai de lissage
(`tap_pace_playback`, voir section dédiée plus haut) — s'exécutait de
façon synchrone dans le même thread que le polling/téléchargement
(`CaptureRotationThread.run`), donc bloquait le rapatriement du fichier
suivant pendant toute la durée d'un lissage sur le fichier courant.

**Architecture retenue** : une `queue.Queue` (`self._tap_queue`) et un
thread dédié (`self._injector_thread`, `_injector_loop`), démarrés par
`_setup_tap` (mode `tap` uniquement — le mode `fifo` n'a pas de lissage,
donc rien à découpler). `_dispatch_for_injection`, appelée par
`_process_closed_file_scp`/`_process_closed_file_sshfs`, remplace l'appel
direct à `_feed_into_tap` : en mode `tap`, dépose simplement le fichier
sur la file (jamais bloquant, `Queue.put` sur une file non bornée) ; en
mode `fifo`, appelle `_feed_into_fifo` directement, comportement inchangé.
`_injector_loop` dépile et appelle `_feed_into_tap` (logique de lissage
elle-même inchangée), sur son propre thread — c'est là, et uniquement là,
qu'un délai de lissage est maintenant subi, sans jamais retarder le
thread de polling.

**Arrêt propre** : `_cleanup` doit arrêter `_injector_loop` **avant** de
fermer `self._tap_writer` (sinon le thread injecteur pourrait encore
écrire dessus, ou sur l'interface TAP si `tap_cleanup_on_stop` la supprime
juste après) — sentinelle `None` posée sur la file pour un réveil immédiat
plutôt que d'attendre le prochain timeout de `Queue.get`, puis
`join(timeout=5.0)`. Seul `.join()` de toute cette classe : tous les
autres threads sont volontairement « fire-and-forget » vis-à-vis de
`stop_event` (aucun autre ne partage une ressource avec le thread qui la
ferme). `_injector_loop` s'arrête aussi de lui-même sur `stop_event` seul
(sans sentinelle), sans tenter de drainer une éventuelle file restante —
cohérent avec le reste de la classe, qui n'essaie pas non plus de « finir »
un cycle de poll en cours à l'arrêt.

**`except Exception` volontairement large dans `_injector_loop`** (+1 ruff
`BLE001` par rapport à la session précédente : 35 au lieu de 34 sur
`src/`) : cohérent avec l'idiome déjà utilisé partout ailleurs dans cette
classe pour le même besoin (thread de fond best-effort qui ne doit jamais
mourir silencieusement sur un fichier problématique) — voir par exemple
`_process_closed_file_scp` juste au-dessus. Restreindre à `OSError` aurait
été possible mais aurait rendu ce thread moins robuste que ses voisins
pour un gain de cohérence de style discutable ; assumé et documenté ici
plutôt que masqué par un `# noqa` que le reste du fichier n'utilise nulle
part pour ce genre de cas.

**Testé réellement**, `tests/test_tap_injector_thread.py` (9 tests,
nouveaux) :
- `_dispatch_for_injection` : aiguillage correct par `output_mode` (file
  vs appel direct), y compris que `_tap_queue` reste à `None` en mode
  `fifo` (jamais créée, puisque `_setup_tap` n'est jamais appelée).
- `_injector_loop` : dépile et réinjecte dans l'ordre, s'arrête sur
  sentinelle ET sur `stop_event` seul, survit à un fichier corrompu
  (`ValueError`, cas déjà géré par `_feed_into_tap`) et à une exception
  totalement inattendue (`RuntimeError`) sans mourir ni bloquer les
  fichiers suivants.
- **Le test qui motive tout ce découplage** : un 2ᵉ fichier déposé
  PENDANT qu'un `time.sleep` de lissage bloque le 1ᵉʳ (bloqué
  délibérément via un `threading.Event` contrôlé par le test, à la place
  d'un vrai sleep) est accepté immédiatement (< 0,5 s) sur son propre
  thread séparé — puis, une fois débloqué, les deux fichiers sont
  injectés dans le bon ordre, avec le bon compteur `files_merged`.
- `_cleanup` (mode tap) : le thread injecteur est bien joint (fichier en
  attente traité) avant que `self._tap_writer.close()` ne soit appelé ;
  robuste aussi si `_setup_tap` n'a jamais tourné (`_tap_queue`/
  `_injector_thread` restés à `None`).

`pytest tests/ -v` : **115 passed** (106 précédents + 9 nouveaux, aucune
régression). `ruff check --line-length 120 tests/test_tap_injector_thread.py` :
0 erreur.

**Non fait** (nécessite un switch réel, voir features.md, section « Pas
fait » — inchangé par cette session) : mesure du timing réel spool →
injection TAP en conditions réelles.


