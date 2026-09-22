# Session 01 — 23/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Mode dry run (`InspectConfig` + `inspect_switch`, 23/08/2026)

`InspectConfig` est délibérément une classe séparée de `Config`, pas une
variante avec des champs optionnels en plus : `Config.__post_init__`
exige `capture_interface` (voir plus haut), ce qui aurait forcé
`switch-capture inspect` à demander une interface de capture pour une
commande qui ne capture rien — même logique que `MirrorConfig`, gardée
séparée de `Config` pour la même raison. `connect_switch()` accepte les
deux (`Config | InspectConfig`) par duck typing sur `switch_ip`/
`ssh_user`/`ssh_password` — `MirrorThread`, lui, ne réutilise pas
`connect_switch()` et reconstruit son propre dict `ConnectHandler`
inline (`switch_capture_core.py`, dans `MirrorThread.run()`) ; à
harmoniser si `MirrorThread` est retouché un jour, pas fait ici pour ne
pas toucher à du code qui fonctionne hors du périmètre de cette session.

`inspect_switch()` n'appelle jamais `config_mode()` — c'est la garantie
de fond du mode dry run, pas une option. Contrairement à
`SetupAndCaptureThread._prepare_switch()`, qui peut activer scp/sftp
server ou configurer NTP au passage si besoin, `inspect_switch()` se
limite structurellement à des commandes `display` : aucune branche du
code n'appelle quoi que ce soit d'autre, donc il n'y a pas de flag
`dry_run` à respecter quelque part — la fonction elle-même ne sait pas
faire de configuration.

