"""Cohérence entre les options CLI de `switch-capture capture`/`inspect`/
`mirror`/`analyze-pacing` et les tables « Référence des options »
correspondantes de `src/docs/USAGE.md` (features.md, 06/09/2026, 6e session
du jour ; complété le 07/09/2026 avec la table `inspect`, puis avec les
tables `mirror` et `analyze-pacing` dans la même journée).

Contexte (`capture`) : `--no-hide-capture-traffic`, `--tap-pace-playback` et
`--tap-pace-max-gap` sont des flags CLI réels de `_add_common_config_args`
(switch_capture_cli.py), déjà documentés dans `config.yaml.example` (session
précédente) et câblés en GUI depuis fin août 2026, mais étaient restés
absents de la table de référence de USAGE.md — un utilisateur parcourant
uniquement cette table n'avait aucun moyen de savoir que ces 3 options
existaient. Ce test rend ce type d'oubli détectable automatiquement,
plutôt que de dépendre d'une relecture manuelle comme celle qui a trouvé ce
trou-ci (même logique que `tests/test_config_example_completeness.py`).

Contexte (`inspect`, 07/09/2026) : même trou, cette fois sur la sous-commande
`inspect` — `--remember-password`, `--forget-password` et `--keepass-path`
sont des flags CLI réels de `inspect_parser` (bien exploités par
`build_inspect_config`/`run_inspect`, mêmes mécanismes que `capture`), mais
étaient restés absents de la table « Référence des options — `inspect` ».

Contexte (`mirror`/`analyze-pacing`, 07/09/2026, 4e session du jour) : les
tables correspondantes avaient été vérifiées complètes par la même
introspection manuelle lors d'une session précédente du même jour (aucun
trou trouvé), mais sans le garde-fou automatisé équivalent — un oubli futur
sur l'une de ces deux tables ne serait donc pas détecté (voir features.md,
« Autres limites connues »/« Reste ouvert »). Ces deux tests ferment ce
point : ils passent dès maintenant (aucune régression trouvée), mais
verrouillent la complétude pour l'avenir, comme `capture`/`inspect` depuis
les sessions précédentes. Pour `analyze-pacing`, l'argument positionnel
`pcap_file` (sans `--`) est documenté par son nom nu dans la table, pas par
un flag long — géré séparément des options `--xxx`.

Sans dépendance GTK4/PyGObject ni switch réel : uniquement `switch_capture_cli`
(le module CLI n'importe pas `gi`) et un fichier texte.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import switch_capture_cli as cli

DOCS_DIR = Path(__file__).resolve().parents[1] / "src" / "docs"
USAGE_MD_PATH = DOCS_DIR / "USAGE.md"

# Flags CLI de `capture` délibérément documentés ailleurs dans USAGE.md (section
# dédiée « Mémoriser le mot de passe SSH entre deux lancements ») plutôt que
# dans la table de référence rapide : pas un oubli, un choix de présentation
# déjà existant avant ce test.
_DOCUMENTED_ELSEWHERE = {"remember_password", "forget_password", "keepass_path", "keepass_keyfile"}

# `--config` et `-v`/`--verbose` sont documentés séparément (colonne dédiée /
# option globale du parseur), pas dans cette table.
_NOT_APPLICABLE = {"config", "verbose"}


def _capture_subparser() -> argparse.ArgumentParser:
    parser = cli.build_arg_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices["capture"]
    raise AssertionError("aucune sous-commande trouvée sur le parseur CLI")


def _capture_flags() -> dict[str, str]:
    """dest -> flag long (`--xxx`) pour chaque option de `capture`."""
    capture_parser = _capture_subparser()
    flags = {}
    for action in capture_parser._actions:
        if action.dest in ("help",):
            continue
        long_opts = [s for s in action.option_strings if s.startswith("--")]
        if long_opts:
            flags[action.dest] = long_opts[0]
    return flags


def _inspect_subparser() -> argparse.ArgumentParser:
    parser = cli.build_arg_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices["inspect"]
    raise AssertionError("aucune sous-commande trouvée sur le parseur CLI")


def _inspect_flags() -> dict[str, str]:
    """dest -> flag long (`--xxx`) pour chaque option de `inspect`."""
    inspect_parser = _inspect_subparser()
    flags = {}
    for action in inspect_parser._actions:
        if action.dest in ("help",):
            continue
        long_opts = [s for s in action.option_strings if s.startswith("--")]
        if long_opts:
            flags[action.dest] = long_opts[0]
    return flags


# `--config` est documenté séparément (colonne dédiée) dans la table `inspect`.
_INSPECT_NOT_APPLICABLE = {"config"}


def _mirror_subparser() -> argparse.ArgumentParser:
    parser = cli.build_arg_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices["mirror"]
    raise AssertionError("aucune sous-commande trouvée sur le parseur CLI")


def _mirror_flags() -> dict[str, str]:
    """dest -> flag long (`--xxx`) pour chaque option de `mirror`."""
    mirror_parser = _mirror_subparser()
    flags = {}
    for action in mirror_parser._actions:
        if action.dest in ("help",):
            continue
        long_opts = [s for s in action.option_strings if s.startswith("--")]
        if long_opts:
            flags[action.dest] = long_opts[0]
    return flags


def _analyze_pacing_subparser() -> argparse.ArgumentParser:
    parser = cli.build_arg_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices["analyze-pacing"]
    raise AssertionError("aucune sous-commande trouvée sur le parseur CLI")


def _analyze_pacing_flags() -> dict[str, str]:
    """dest -> texte attendu dans la table (flag long `--xxx`, ou nom nu de
    l'argument positionnel, ex. `pcap_file`) pour chaque option de
    `analyze-pacing`."""
    analyze_pacing_parser = _analyze_pacing_subparser()
    flags = {}
    for action in analyze_pacing_parser._actions:
        if action.dest in ("help",):
            continue
        long_opts = [s for s in action.option_strings if s.startswith("--")]
        if long_opts:
            flags[action.dest] = long_opts[0]
        elif not action.option_strings:
            # Argument positionnel (ex. pcap_file) : documenté par son nom nu
            # dans la table, pas par un flag --xxx.
            flags[action.dest] = action.dest
    return flags


class TestUsageMdCompleteness:
    def test_reference_table_documents_every_capture_flag(self):
        flags = _capture_flags()
        documentable = {
            dest: flag
            for dest, flag in flags.items()
            if dest not in _DOCUMENTED_ELSEWHERE and dest not in _NOT_APPLICABLE
        }
        assert documentable, "aucun flag à vérifier : la détection elle-même a un problème"

        text = USAGE_MD_PATH.read_text(encoding="utf-8")
        # On se limite à la table capture/uninstall (avant la table mirror).
        table_start = text.index("Référence des options — `capture` / `uninstall`")
        table_end = text.index("Référence des options — `mirror`")
        table_text = text[table_start:table_end]

        missing = sorted(flag for flag in documentable.values() if not re.search(rf"`{re.escape(flag)}`", table_text))
        assert not missing, f"Flag(s) CLI de `capture` absents de la table de référence USAGE.md : {missing}"

    def test_documented_elsewhere_flags_still_exist(self):
        # Garde-fou : si l'un de ces flags disparaissait de la CLI, l'exclusion
        # ci-dessus deviendrait silencieusement fausse.
        flags = _capture_flags()
        for dest in _DOCUMENTED_ELSEWHERE:
            assert dest in flags, f"{dest} n'existe plus côté CLI, exclusion à revoir"

    def test_reference_table_documents_every_inspect_flag(self):
        flags = _inspect_flags()
        documentable = {dest: flag for dest, flag in flags.items() if dest not in _INSPECT_NOT_APPLICABLE}
        assert documentable, "aucun flag à vérifier : la détection elle-même a un problème"

        text = USAGE_MD_PATH.read_text(encoding="utf-8")
        # On se limite à la table inspect (avant la table analyze-pacing).
        table_start = text.index("Référence des options — `inspect`")
        table_end = text.index("Référence des options — `analyze-pacing`")
        table_text = text[table_start:table_end]

        missing = sorted(flag for flag in documentable.values() if not re.search(rf"`{re.escape(flag)}`", table_text))
        assert not missing, f"Flag(s) CLI de `inspect` absents de la table de référence USAGE.md : {missing}"

    def test_reference_table_documents_every_mirror_flag(self):
        flags = _mirror_flags()
        assert flags, "aucun flag à vérifier : la détection elle-même a un problème"

        text = USAGE_MD_PATH.read_text(encoding="utf-8")
        # On se limite à la table mirror (avant la table inspect).
        table_start = text.index("Référence des options — `mirror`")
        table_end = text.index("Référence des options — `inspect`")
        table_text = text[table_start:table_end]

        missing = sorted(flag for flag in flags.values() if not re.search(rf"`{re.escape(flag)}`", table_text))
        assert not missing, f"Flag(s) CLI de `mirror` absents de la table de référence USAGE.md : {missing}"

    def test_reference_table_documents_every_analyze_pacing_flag(self):
        flags = _analyze_pacing_flags()
        assert flags, "aucun flag à vérifier : la détection elle-même a un problème"

        text = USAGE_MD_PATH.read_text(encoding="utf-8")
        # On se limite à la table analyze-pacing (avant la section Exemples).
        table_start = text.index("Référence des options — `analyze-pacing`")
        table_end = text.index("## Exemples")
        table_text = text[table_start:table_end]

        missing = sorted(flag for flag in flags.values() if not re.search(rf"`{re.escape(flag)}`", table_text))
        assert not missing, f"Flag(s) CLI de `analyze-pacing` absents de la table de référence USAGE.md : {missing}"
