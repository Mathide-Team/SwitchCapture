"""Cohérence entre les options CLI de `switch-capture capture` et
`src/docs/config.yaml.example` (features.md, 06/09/2026, 5e session du jour).

Contexte : `hide_capture_traffic`/`tap_pace_playback`/`tap_pace_max_gap_seconds`
sont des champs `Config` réels, câblés en CLI (`_add_common_config_args`,
`switch_capture_cli.py`) et en GUI depuis fin août 2026, mais étaient restés
absents de `config.yaml.example` — un utilisateur lisant uniquement ce fichier
n'avait aucun moyen de savoir que ces 3 réglages existaient. Ce test rend cet
oubli détectable automatiquement pour tout futur réglage du même genre,
plutôt que de dépendre d'une relecture manuelle comme celle qui a trouvé ce
trou-ci.

Sans dépendance GTK4/PyGObject ni switch réel : uniquement `switch_capture_cli`
(le module CLI n'importe pas `gi`) et un fichier texte.
"""

from __future__ import annotations

import argparse
import dataclasses
import re
from pathlib import Path

import switch_capture_cli as cli
from switch_capture_core import Config

DOCS_DIR = Path(__file__).resolve().parents[1] / "src" / "docs"
CONFIG_EXAMPLE_PATH = DOCS_DIR / "config.yaml.example"

# Champs Config techniquement acceptés par --config (voir _CONFIG_FIELDS dans
# switch_capture_cli.py) mais sans flag CLI ni entrée dans le docstring
# Config, donc jamais présentés comme un réglage utilisateur ailleurs dans le
# projet (GUI/USAGE.md) : les documenter dans config.yaml.example comme les
# autres clés induirait en erreur plutôt qu'aider. Si ce champ gagnait un jour
# un vrai flag CLI, test_packet_capture_cmd_still_has_no_cli_flag ci-dessous
# échouerait et forcerait à revisiter cette exclusion plutôt qu'à la laisser
# devenir silencieusement fausse.
_KNOWN_INTERNAL_ONLY_FIELDS = {"packet_capture_cmd"}


def _capture_subparser() -> argparse.ArgumentParser:
    parser = cli.build_arg_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices["capture"]
    raise AssertionError("aucune sous-commande trouvée sur le parseur CLI")


def _capture_cli_dests() -> set[str]:
    """Les `dest=` du sous-parseur `capture` (mêmes options que --config)."""
    capture_parser = _capture_subparser()
    return {action.dest for action in capture_parser._actions if action.dest != "help"}


def _config_field_names() -> set[str]:
    return {f.name for f in dataclasses.fields(Config) if f.init}


class TestConfigExampleCompleteness:
    def test_every_capture_cli_dest_is_a_real_config_field(self):
        # Garde-fou inverse, pour que ce test lui-même reste fiable : si un
        # flag CLI de `capture` ne correspondait à aucun champ Config (donc
        # silencieusement ignoré par le filtre _CONFIG_FIELDS au chargement
        # de --config), on veut le savoir plutôt que de fausser le calcul
        # ci-dessous.
        config_fields = _config_field_names()
        # Dests CLI délibérément hors de Config, voir build_config()
        # (switch_capture_cli.py) : --config lui-même, et le quatuor
        # remember/forget-password + keepass_path/keepass_keyfile qui pilote
        # le mécanisme de mémorisation du mot de passe (trousseau/KeePass),
        # pas la capture elle-même.
        non_config_dests = {"config", "remember_password", "forget_password", "keepass_path", "keepass_keyfile"}
        for dest in _capture_cli_dests() - non_config_dests:
            assert dest in config_fields, f"--{dest.replace('_', '-')} n'a pas de champ Config correspondant"

    def test_packet_capture_cmd_still_has_no_cli_flag(self):
        # Voir _KNOWN_INTERNAL_ONLY_FIELDS ci-dessus : ce test échoue si
        # packet_capture_cmd devient un jour un vrai réglage utilisateur,
        # pour forcer une décision explicite plutôt qu'un oubli silencieux.
        assert "packet_capture_cmd" not in _capture_cli_dests()

    def test_config_example_documents_every_cli_exposed_field(self):
        cli_exposed_config_fields = _capture_cli_dests() & _config_field_names()
        documentable = cli_exposed_config_fields - _KNOWN_INTERNAL_ONLY_FIELDS
        assert documentable, "aucun champ à vérifier : la détection elle-même a un problème"

        text = CONFIG_EXAMPLE_PATH.read_text(encoding="utf-8")
        missing = sorted(name for name in documentable if not re.search(rf"\b{re.escape(name)}\b", text))
        assert not missing, f"Clé(s) paramétrables en CLI/--config mais absentes de config.yaml.example : {missing}"
