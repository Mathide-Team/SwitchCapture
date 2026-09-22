# Index des sessions — switch_capture

Une ligne par session de développement documentée dans l'ancien `CLAUDE.md`
(23/08/2026 → 08/09/2026), reclassée en ordre chronologique réel. Remplace
l'ancien pavé « Suivi des sessions » de `features.md`.

> Note sur la numérotation : ces 49 fichiers correspondent aux 49 entrées
> effectivement rédigées comme sections distinctes dans l'ancien `CLAUDE.md`.
> Quelques sessions très courtes des tout premiers jours (23-25/08/2026) ont
> été absorbées dans la doc d'architecture ou dans la session voisine plutôt
> que de recevoir leur propre section à l'époque — ce nouvel index ne les
> invente donc pas rétroactivement.

| # | Date | Session |
|---|------|---------|
| 01 | 23/08/2026 | [Mode dry run (`InspectConfig` + `inspect_switch`, 23/08/2026)](session-01.md) |
| 02 | 24/08/2026 | [Débit de transfert moyen en direct (`compute_average_throughput`, 24/08/2026)](session-02.md) |
| 03 | 25/08/2026 | [Trousseau système pour le mot de passe SSH (`keyring`, 25/08/2026)](session-03.md) |
| 04 | 25/08/2026 | [Intégration GUI du trousseau système (25/08/2026, session ultérieure)](session-04.md) |
| 05 | 26/08/2026 | [Correctif : `sudo` + interface graphique + RDP (26/08/2026)](session-05.md) |
| 06 | 26/08/2026 | [Icône de l'application (26/08/2026)](session-06.md) |
| 07 | 26/08/2026 | [Découplage téléchargement/injection TAP (26/08/2026)](session-07.md) |
| 08 | 26/08/2026 | [Correctif régression : détection auto 5130EI/5130HI/5140EI/5140HI (26/08/2026, suite)](session-08.md) |
| 09 | 26/08/2026 | [Ménage ruff + filtre de capture core/CLI (26/08/2026, suite)](session-09.md) |
| 10 | 26/08/2026 | [Archivage en pcapng (26/08/2026, suite)](session-10.md) |
| 11 | 26/08/2026 | [Sens de capture : inbound / outbound / bidirection (26/08/2026, suite)](session-11.md) |
| 12 | 26/08/2026 | [Lancement automatique de Wireshark en mode TAP (`tap_launch_wireshark`, 26/08/2026, suite)](session-12.md) |
| 13 | 27/08/2026 | [Étude de faisabilité : switch-capture comme plugin extcap Wireshark (27/08/2026)](session-13.md) |
| 14 | 27/08/2026 | [Repli KeePass pour le mot de passe SSH (`pykeepass`, 27/08/2026)](session-14.md) |
| 15 | 28/08/2026 | [Câblage GUI de 4 réglages core/CLI déjà traités (28/08/2026)](session-15.md) |
| 16 | 28/08/2026 | [Garde-fou installation pendant une capture en cours (28/08/2026, suite)](session-16.md) |
| 17 | 28/08/2026 | [Mode non-root pour le mode TAP — `switch-capture-taphelper` (28/08/2026, suite)](session-17.md) |
| 18 | 28/08/2026 | [Session du 28/08/2026 (suite, 4e session du jour) — point 18 traité](session-18.md) |
| 19 | 28/08/2026 | [Câblage GUI du repli KeePass (28/08/2026, suite)](session-19.md) |
| 20 | 28/08/2026 | [Session du 28/08/2026 (suite, 6e session du jour) — bugs GVFS/GOA (features.md 8/9/11/12)](session-20.md) |
| 21 | 29/08/2026 | [Menu hamburger et page Préférences (29/08/2026)](session-21.md) |
| 22 | 29/08/2026 | [Gestion propre de Ctrl+C (SIGINT) dans l'app GTK4 (29/08/2026, suite)](session-22.md) |
| 23 | 29/08/2026 | [Vérification empirique du fix Ctrl+C/SIGINT — point 10 clos (29/08/2026, 3e session du jour)](session-23.md) |
| 24 | 29/08/2026 | [Squelette de projet futur — point 15 de features.md (29/08/2026, 4e session du jour)](session-24.md) |
| 25 | 30/08/2026 | [Internationalisation de la CLI — point 13 de features.md (30/08/2026)](session-25.md) |
| 26 | 31/08/2026 | [Internationalisation de la GUI — point 13 de features.md (31/08/2026)](session-26.md) |
| 27 | 31/08/2026 | [Analyse des écarts de lissage TAP — volet du point « Pas fait » n°1 (31/08/2026, suite)](session-27.md) |
| 28 | 31/08/2026 | [Pérennisation en test automatisé de la vérification i18n GUI (31/08/2026, 3e session du jour)](session-28.md) |
| 29 | 31/08/2026 | [Collecte pytest bloquée par `gi.require_version()` sans filet (31/08/2026, 4e session du jour)](session-29.md) |
| 30 | 01/09/2026 | [Documentation : flow mirroring QoS ajouté à CAPTURE-METHODS.md (01/09/2026)](session-30.md) |
| 31 | 01/09/2026 | [Filtrage ACL pour `switch-capture mirror` — core + CLI (01/09/2026, 2e session du jour)](session-31.md) |
| 32 | 02/09/2026 | [Câblage GUI du filtrage ACL pour `switch-capture mirror` (02/09/2026)](session-32.md) |
| 33 | 02-03/09/2026 | [Relecture linguistique du `.po` `en_US` (02-03/09/2026)](session-33.md) |
| 34 | 03/09/2026 | [Mise à jour du README pour la 4e méthode de capture (03/09/2026)](session-34.md) |
| 35 | 03/09/2026 | [Correctif `ruff` `UP037` sur `_open_keepass_db` (03/09/2026)](session-35.md) |
| 36 | 04-05/09/2026 | [Piste de capture distante : mirroring vers VLAN + VXLAN L2 sur switch 5520 HI (04-05/09/2026)](session-36.md) |
| 37 | 05/09/2026 | [Implémentation core + CLI du mode `--mode vxlan` (05/09/2026)](session-37.md) |
| 38 | 06/09/2026 | [Câblage GUI du mode `--mode vxlan` (06/09/2026)](session-38.md) |
| 39 | 06/09/2026 | [Correctif i18n GUI : 3 messages de dialogue oubliés (06/09/2026, 2e session du jour)](session-39.md) |
| 40 | 06/09/2026 | [Documentation : options `--mode vxlan` manquantes dans USAGE.md (06/09/2026, 3e session du jour)](session-40.md) |
| 41 | 06/09/2026 | [Documentation : sous-commande `analyze-pacing` absente de USAGE.md (06/09/2026, 4e session du jour)](session-41.md) |
| 42 | 06/09/2026 | [Complétude de `config.yaml.example` : 3 réglages Config non documentés (06/09/2026, 5e session du jour)](session-42.md) |
| 43 | 06/09/2026 | [Documentation : 3 flags `capture` absents de la table de référence USAGE.md (06/09/2026, 6e session du jour)](session-43.md) |
| 44 | 07/09/2026 | [Documentation/bug : `-v` mal placé dans un exemple de USAGE.md (07/09/2026)](session-44.md) |
| 45 | 07/09/2026 | [Documentation : 3 flags `inspect` absents de la table de référence USAGE.md (07/09/2026, 2e session du jour)](session-45.md) |
| 46 | 07/09/2026 | [Vérification rpcap dans le mode dry run (07/09/2026, 3e session du jour)](session-46.md) |
| 47 | 07/09/2026 | [Tests de complétude automatisés pour les tables `mirror` et `analyze-pacing` de USAGE.md (07/09/2026, 4e session du jour)](session-47.md) |
| 48 | 08/09/2026 | [Correctif : 3 tests `test_gvfs_env_workaround.py` échouaient au lieu de sauter proprement sans typelib GTK4 (08/09/2026)](session-48.md) |
| 49 | 08/09/2026 | [Couverture de tests ajoutée pour le transfert SCP (08/09/2026, 2e session du jour)](session-49.md) |
| 50 | 10/09/2026 | [Couverture de tests ajoutée pour les 6 fonctions repérées en session 49 (10/09/2026)](session-50.md) |
| 51 | 10/09/2026 | [Premier audit `coverage.py` du dépôt : 3 fonctions CLI à 0 % couvertes (10/09/2026, 2e session du jour)](session-51.md) |
| 52 | 10/09/2026 | [Poursuite de l'audit de couverture : fusion YAML de build_config/build_inspect_config (10/09/2026, 3e session du jour)](session-52.md) |
| 53 | 11/09/2026 | [Poursuite de l'audit de couverture : clôture de switch_capture_cli.py à 99 % (11/09/2026)](session-53.md) |
| 54 | 12/09/2026 | [Poursuite de l'audit de couverture : switch_capture_core.py 76→79 % (12/09/2026)](session-54.md) |
| 55 | 12/09/2026 | [Fusion de deux branches de développement divergentes (12/09/2026)](session-55.md) |
| 56 | 12/09/2026 | [Audit Context7 de 6 dépendances externes — 5 candidats proposés, aucun implémenté (12/09/2026, 2e session du jour)](session-56.md) |
| 57 | 12/09/2026 | [Keepalive netmiko sur `connect_switch()` — candidat #7 de l'audit Context7 (12/09/2026, 3e session du jour)](session-57.md) |
| 58 | 13/09/2026 | [Nettoyage complet de la dette ruff (53→0 erreurs) et couverture des imports optionnels de switch_capture_core.py (13/09/2026)](session-58.md) |
| 59 | 13/09/2026 | [Support d'un fichier de clé KeePass additionnel — candidat #8 de l'audit Context7 (13/09/2026)](session-59.md) |
| 60 | 14/09/2026 | [pyproject.toml (ruff/pytest/coverage) et callback de progression SCP — candidats #5 et #6 de l'audit Context7 (14/09/2026)](session-60.md) |
| 61 | 15/09/2026 | [Reformatage complet du dépôt (`ruff format`) et clôture de la branche « modèle inconnu » de `_prepare_switch` (15/09/2026)](session-61.md) |
| 62 | 15/09/2026 | [Triage des 291 lignes non couvertes, couverture de `UninstallThread` et correctif du préfixe `flash:/` dupliqué (15/09/2026, 2e session du jour)](session-62.md) |
| 63 | 16/09/2026 | [Adoption d'uv pour la gestion des dépendances (« remplacer poetry », jamais utilisé sur ce projet) — préserve le choix « pas de packaging » (16/09/2026)](session-63.md) |
