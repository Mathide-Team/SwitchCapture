"""Placement de `-v`/`--verbose` sur la ligne de commande — option globale
du parseur racine (features.md, 06/09/2026, 7e session du jour).

Contexte : `-v`/`--verbose` est ajoutée sur le parseur `argparse` racine
(`switch_capture_cli.build_arg_parser`), *avant* `add_subparsers()` — donc
utilisable uniquement avant le nom de la sous-commande
(`switch-capture -v capture ...`), jamais après
(`switch-capture capture ... -v` échoue avec
`unrecognized arguments: -v`) — contrairement à `-c`/`-g`, filtrés
séparément de `argv` par le lanceur `src/switch-capture` (voir sa
fonction `main()`) et donc acceptés n'importe où sur la ligne de commande.

L'exemple « Config de base + surcharge ponctuelle du filtre » de
`src/docs/USAGE.md` plaçait `-v` après `capture` : copié/collé tel quel,
il échouait. Corrigé dans cette session (avec une note explicite sous
« Aide intégrée » et un rappel dans la table de référence
`capture`/`uninstall`) ; ce module verrouille le comportement pour que la
régression inverse (ex. si `-v` est un jour ajouté à chaque sous-parseur,
ce qui rendrait les deux placements valides) soit une décision consciente
plutôt qu'un oubli silencieux — même logique que
`tests/test_usage_md_completeness.py::test_documented_elsewhere_flags_still_exist`.
Le dernier test rejoue l'exemple corrigé directement depuis le fichier
`USAGE.md` (pas une copie codée en dur qui pourrait diverger).

Sans dépendance GTK4/PyGObject ni switch réel : uniquement
`switch_capture_cli` (le module CLI n'importe pas `gi`) et un fichier
texte.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

import switch_capture_cli as cli

DOCS_DIR = Path(__file__).resolve().parents[1] / "src" / "docs"
USAGE_MD_PATH = DOCS_DIR / "USAGE.md"

# Une invocation minimale mais syntaxiquement valide par sous-commande —
# juste assez pour que argparse accepte le reste de la ligne, la question
# posée ici est uniquement la position de -v, pas la validité métier.
_MINIMAL_ARGV_BY_SUBCOMMAND = {
    "capture": [
        "capture",
        "--switch-ip",
        "10.0.0.1",
        "--ssh-user",
        "mathilde",
        "--capture-interface",
        "GigabitEthernet1/0/1",
    ],
    "uninstall": ["uninstall", "--switch-ip", "10.0.0.1", "--ssh-user", "mathilde"],
    "import-bin": ["import-bin", "./feature-bin"],
    "mirror": [
        "mirror",
        "--switch-ip",
        "10.0.0.1",
        "--ssh-user",
        "mathilde",
        "--source-interface",
        "GigabitEthernet1/0/1",
        "--monitor-interface",
        "GigabitEthernet1/0/2",
    ],
    "inspect": ["inspect", "--switch-ip", "10.0.0.1", "--ssh-user", "mathilde"],
    "analyze-pacing": ["analyze-pacing", "dummy.pcap"],
}


def _extract_bash_block(markdown_text: str, heading: str) -> str:
    """Retourne le contenu du premier bloc ```bash suivant `heading` dans `markdown_text`."""
    start = markdown_text.index(heading)
    fence_start = markdown_text.index("```bash", start) + len("```bash")
    fence_end = markdown_text.index("```", fence_start)
    return markdown_text[fence_start:fence_end].strip()


class TestVerboseIsGlobalBeforeSubcommand:
    """`-v` fonctionne avant n'importe quelle sous-commande, jamais après."""

    @pytest.mark.parametrize("name", sorted(_MINIMAL_ARGV_BY_SUBCOMMAND))
    def test_verbose_before_subcommand_succeeds(self, name):
        parser = cli.build_arg_parser()
        ns = parser.parse_args(["-v", *_MINIMAL_ARGV_BY_SUBCOMMAND[name]])
        assert ns.verbose is True

    @pytest.mark.parametrize("name", sorted(_MINIMAL_ARGV_BY_SUBCOMMAND))
    def test_verbose_after_subcommand_fails(self, name):
        parser = cli.build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([*_MINIMAL_ARGV_BY_SUBCOMMAND[name], "-v"])

    def test_verbose_defaults_to_false(self):
        parser = cli.build_arg_parser()
        ns = parser.parse_args(_MINIMAL_ARGV_BY_SUBCOMMAND["inspect"])
        assert ns.verbose is False


class TestUsageMdVerboseDocumentation:
    """La doc reflète bien le comportement ci-dessus, pas juste par relecture."""

    def test_note_after_aide_integree_explains_placement(self):
        text = USAGE_MD_PATH.read_text(encoding="utf-8")
        aide_integree = text.index("## Aide intégrée")
        reference_options = text.index("## Référence des options")
        note = text[aide_integree:reference_options]
        assert "-v" in note
        assert "avant" in note.lower()

    def test_filter_override_example_parses_as_written(self):
        # Reproduit tel quel l'exemple « Config de base + surcharge
        # ponctuelle du filtre » : doit parser sans erreur, -v inclus,
        # directement depuis le contenu actuel de USAGE.md.
        text = USAGE_MD_PATH.read_text(encoding="utf-8")
        block = _extract_bash_block(text, "Config de base + surcharge ponctuelle du filtre")
        joined = block.replace("\\\n", " ")
        tokens = shlex.split(joined)
        assert tokens[0] == "switch-capture", tokens

        parser = cli.build_arg_parser()
        ns = parser.parse_args(tokens[1:])  # ne doit PAS lever SystemExit

        assert ns.action == "capture"
        assert ns.verbose is True
        assert ns.config == "/etc/switch-capture/site-a.yaml"
        assert ns.capture_filter == "host 10.10.10.2 and proto gre"
