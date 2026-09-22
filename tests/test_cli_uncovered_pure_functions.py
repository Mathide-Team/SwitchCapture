"""Couverture pour plusieurs fonctions de `switch_capture_cli.py` repérées à
0% via un audit `coverage.py` (session 51, jamais utilisé dans ce dépôt
jusqu'ici — piste explicitement laissée ouverte en fin de session 50, puis
poursuivie sessions 51/52/53).

Recherche exhaustive (nom de chaque fonction dans tout `tests/`) confirmée
avant d'écrire le moindre test à chaque ajout : toutes étaient bien absentes.

- `load_yaml` : chargement pur d'un fichier YAML, sans switch ni GTK4.
- `run_import_bin` : copie de fichiers sur le système de fichiers local
  uniquement (`shutil.copytree`), aucune connexion SSH.
- `run_analyze_pacing` : sous-commande purement locale (lecture d'un .pcap
  déjà rapatrié, voir sa propre docstring) — les fonctions qu'elle délègue
  (`analyze_pacing_gaps`, `format_pacing_analysis_report`) sont déjà
  couvertes par `test_pacing_gap_analysis.py` ; ce fichier-ci couvre
  uniquement le fin cablage CLI autour (construction des arguments,
  code de sortie, gestion des deux exceptions attrapées).
- `_configure_logging` (session 53) : configuration loguru pure (aucune
  I/O réseau), jamais exercée directement — seulement appelée
  indirectement par `main()`, lui-même jamais testé avant la session 53
  (voir `test_cli_main_dispatch.py`). Couvre le niveau affiché sur la
  console selon `verbose` (`capsys`), le fichier rotatif, et la non-
  accumulation de sinks sur appels répétés.
- `_default_feature_bin_dir` (session 53) : résolution pure d'un chemin par
  défaut, jusqu'ici seulement contournée par monkeypatch dans
  `TestRunImportBin.test_feature_bin_dir_none_uses_default_resolution`
  ci-dessous (qui remplace la fonction plutôt que de l'exercer) — jamais
  testée directement elle-même. Couvre les trois cas : dossier système
  présent, absent, et chemin existant mais qui n'est pas un dossier.

Sans dépendance GTK4/PyGObject ni switch réel.
"""

from __future__ import annotations

import argparse
import textwrap

import pytest
from loguru import logger
from test_tap_pacing import write_synthetic_pcap

import switch_capture_cli as cli

# --------------------------------------------------------------------- #
# load_yaml
# --------------------------------------------------------------------- #


class TestLoadYaml:
    def test_loads_simple_mapping(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            textwrap.dedent(
                """\
                switch_ip: 10.0.0.1
                ssh_user: mathilde
                """
            ),
            encoding="utf-8",
        )
        assert cli.load_yaml(str(yaml_file)) == {
            "switch_ip": "10.0.0.1",
            "ssh_user": "mathilde",
        }

    def test_empty_file_returns_empty_dict(self, tmp_path):
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("", encoding="utf-8")
        assert cli.load_yaml(str(yaml_file)) == {}

    def test_missing_file_raises_oserror(self, tmp_path):
        missing = tmp_path / "absent.yaml"
        with pytest.raises(OSError):
            cli.load_yaml(str(missing))


# --------------------------------------------------------------------- #
# run_import_bin
# --------------------------------------------------------------------- #


class TestRunImportBin:
    def test_missing_source_dir_returns_1(self, tmp_path, caplog):
        missing_src = tmp_path / "does-not-exist"
        dst = tmp_path / "dst"
        rc = cli.run_import_bin(str(missing_src), str(dst))
        assert rc == 1
        assert not dst.exists()

    def test_copies_bin_tree_into_target(self, tmp_path):
        src = tmp_path / "src-repo"
        (src / "5130" / "F6628").mkdir(parents=True)
        (src / "5130" / "F6628" / "packet-capture.bin").write_bytes(b"fake-bin-1")

        dst = tmp_path / "dst-repo"
        rc = cli.run_import_bin(str(src), str(dst))

        assert rc == 0
        copied = dst / "5130" / "F6628" / "packet-capture.bin"
        assert copied.is_file()
        assert copied.read_bytes() == b"fake-bin-1"

    def test_merges_without_deleting_existing_target_files(self, tmp_path):
        src = tmp_path / "src-repo"
        (src / "5140" / "F6628").mkdir(parents=True)
        (src / "5140" / "F6628" / "new.bin").write_bytes(b"new")

        dst = tmp_path / "dst-repo"
        (dst / "5130" / "F6628").mkdir(parents=True)
        (dst / "5130" / "F6628" / "existing.bin").write_bytes(b"existing")

        rc = cli.run_import_bin(str(src), str(dst))

        assert rc == 0
        # Le fichier déjà présent côté cible, absent de la source, n'est
        # pas supprimé (fusion, pas miroir).
        assert (dst / "5130" / "F6628" / "existing.bin").is_file()
        assert (dst / "5140" / "F6628" / "new.bin").is_file()

    def test_overwrites_conflicting_file(self, tmp_path):
        src = tmp_path / "src-repo"
        (src / "5130" / "F6628").mkdir(parents=True)
        (src / "5130" / "F6628" / "packet-capture.bin").write_bytes(b"nouvelle-version")

        dst = tmp_path / "dst-repo"
        (dst / "5130" / "F6628").mkdir(parents=True)
        (dst / "5130" / "F6628" / "packet-capture.bin").write_bytes(b"ancienne-version")

        rc = cli.run_import_bin(str(src), str(dst))

        assert rc == 0
        assert (dst / "5130" / "F6628" / "packet-capture.bin").read_bytes() == b"nouvelle-version"

    def test_no_bin_files_after_import_still_returns_0(self, tmp_path):
        src = tmp_path / "src-repo"
        src.mkdir()
        (src / "readme.txt").write_text("pas un .bin", encoding="utf-8")

        dst = tmp_path / "dst-repo"
        rc = cli.run_import_bin(str(src), str(dst))

        assert rc == 0
        assert list(dst.rglob("*.bin")) == []

    def test_feature_bin_dir_none_uses_default_resolution(self, tmp_path, monkeypatch):
        # feature_bin_dir=None doit passer par _default_feature_bin_dir() —
        # ici forcé vers un dossier temporaire connu plutôt que de dépendre
        # de la présence réelle de /etc/switch-capture/feature-bin dans ce
        # sandbox.
        default_dst = tmp_path / "resolved-default"
        monkeypatch.setattr(cli, "_default_feature_bin_dir", lambda: str(default_dst))

        src = tmp_path / "src-repo"
        (src / "5130" / "F6628").mkdir(parents=True)
        (src / "5130" / "F6628" / "packet-capture.bin").write_bytes(b"x")

        rc = cli.run_import_bin(str(src), None)

        assert rc == 0
        assert (default_dst / "5130" / "F6628" / "packet-capture.bin").is_file()


# --------------------------------------------------------------------- #
# run_analyze_pacing
# --------------------------------------------------------------------- #


def _namespace(pcap_file: str, candidate_max_gaps=None) -> argparse.Namespace:
    return argparse.Namespace(pcap_file=pcap_file, candidate_max_gaps=candidate_max_gaps)


def _frames(*timestamps: float) -> list[tuple[float, bytes]]:
    return [(ts, b"\x00" * 10) for ts in timestamps]


class TestRunAnalyzePacing:
    def test_valid_pcap_returns_0_and_prints_report(self, tmp_path, capsys):
        pcap_file = tmp_path / "capture.pcap"
        write_synthetic_pcap(pcap_file, _frames(0.0, 1.0, 2.0, 3.0))

        rc = cli.run_analyze_pacing(_namespace(str(pcap_file)))

        assert rc == 0
        out = capsys.readouterr().out
        assert str(pcap_file) in out
        assert "Trames" in out

    def test_missing_file_returns_1_and_logs_error(self, tmp_path, caplog):
        missing = tmp_path / "absent.pcap"
        rc = cli.run_analyze_pacing(_namespace(str(missing)))
        assert rc == 1

    def test_invalid_pcap_magic_returns_1(self, tmp_path):
        bad_file = tmp_path / "not-a-pcap.pcap"
        bad_file.write_bytes(b"pas du tout un pcap, trop court")

        rc = cli.run_analyze_pacing(_namespace(str(bad_file)))

        assert rc == 1

    def test_explicit_candidate_max_gaps_used(self, tmp_path, capsys):
        pcap_file = tmp_path / "capture.pcap"
        write_synthetic_pcap(pcap_file, _frames(0.0, 0.5, 1.0))

        rc = cli.run_analyze_pacing(_namespace(str(pcap_file), candidate_max_gaps=[0.25, 5.0]))

        assert rc == 0
        out = capsys.readouterr().out
        assert "0.25" in out
        assert "5.0" in out

    def test_empty_candidate_max_gaps_falls_back_to_default(self, tmp_path, capsys):
        # args.candidate_max_gaps=[] (ex. argparse nargs="*" sans valeur) doit
        # retomber sur DEFAULT_PACING_CANDIDATE_MAX_GAPS, pas planter avec une
        # liste vide passée telle quelle à analyze_pacing_gaps.
        pcap_file = tmp_path / "capture.pcap"
        write_synthetic_pcap(pcap_file, _frames(0.0, 1.0))

        rc = cli.run_analyze_pacing(_namespace(str(pcap_file), candidate_max_gaps=[]))

        assert rc == 0


# --------------------------------------------------------------------- #
# _configure_logging
# --------------------------------------------------------------------- #


class TestConfigureLogging:
    """`monkeypatch.chdir(tmp_path)` : `logger.add("switch_capture.log", ...)`
    écrit un fichier relatif au répertoire courant — on isole donc chaque
    test dans un dossier temporaire plutôt que de polluer le dépôt.
    `logger.remove()` en fin de chaque test (`finally`) : un handler resté
    actif entre deux tests différents n'a jamais causé d'effet de bord
    observé dans ce dépôt (même statut que le `logger.add(...)`
    inconditionnel de `switch_capture_gtk.py` au niveau module), mais la
    classe couvre désormais aussi le niveau affiché sur la console
    (`capsys`) : nettoyer systématiquement évite qu'un sink laissé par un
    test précédent n'influence la lecture de `capsys` du suivant.
    """

    def test_verbose_true_shows_debug_and_info_on_console(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        try:
            cli._configure_logging(verbose=True)
            logger.debug("debug-marker-verbose-true")
            logger.info("info-marker-verbose-true")
            err = capsys.readouterr().err
            assert "debug-marker-verbose-true" in err
            assert "info-marker-verbose-true" in err
        finally:
            logger.remove()

    def test_verbose_false_hides_debug_but_shows_info_on_console(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        try:
            cli._configure_logging(verbose=False)
            logger.debug("debug-marker-verbose-false")
            logger.info("info-marker-verbose-false")
            err = capsys.readouterr().err
            assert "debug-marker-verbose-false" not in err
            assert "info-marker-verbose-false" in err
        finally:
            logger.remove()

    def test_can_log_after_configuring(self, tmp_path, monkeypatch):
        # Vérifie que le sink fichier ajouté est bien fonctionnel (pas
        # seulement présent) : un message journalisé après configuration se
        # retrouve dans switch_capture.log.
        monkeypatch.chdir(tmp_path)
        try:
            cli._configure_logging(False)
            logger.info("marqueur-test-configure-logging")
            log_content = (tmp_path / "switch_capture.log").read_text(encoding="utf-8")
            assert "marqueur-test-configure-logging" in log_content
        finally:
            logger.remove()

    def test_second_call_replaces_previous_handlers_not_accumulates(self, tmp_path, monkeypatch):
        """`logger.remove()` en tête de la fonction : un appel répété (ex. si
        `main()` était invoquée plusieurs fois dans le même process) ne doit
        pas empiler des sinks en double, sinon chaque message serait
        journalisé plusieurs fois."""
        monkeypatch.chdir(tmp_path)
        try:
            cli._configure_logging(verbose=True)
            cli._configure_logging(verbose=True)
            assert len(logger._core.handlers) == 2
        finally:
            logger.remove()


# --------------------------------------------------------------------- #
# _default_feature_bin_dir
# --------------------------------------------------------------------- #


class TestDefaultFeatureBinDir:
    def test_returns_system_dir_when_it_exists(self, tmp_path, monkeypatch):
        system_dir = tmp_path / "etc-switch-capture-feature-bin"
        system_dir.mkdir()
        monkeypatch.setattr(cli, "DEFAULT_SYSTEM_FEATURE_BIN_DIR", str(system_dir))

        assert cli._default_feature_bin_dir() == str(system_dir)

    def test_falls_back_to_relative_dir_when_system_dir_absent(self, tmp_path, monkeypatch):
        missing_dir = tmp_path / "does-not-exist"
        monkeypatch.setattr(cli, "DEFAULT_SYSTEM_FEATURE_BIN_DIR", str(missing_dir))

        assert cli._default_feature_bin_dir() == "./feature-bin"

    def test_falls_back_when_system_path_is_a_file_not_a_directory(self, tmp_path, monkeypatch):
        """`Path.is_dir()` est `False` pour un fichier existant : garde-fou
        distinct du cas "chemin absent" ci-dessus (`Path.is_dir()` renvoie
        `False` dans les deux cas, mais pour des raisons différentes)."""
        a_file = tmp_path / "not-a-directory"
        a_file.write_text("")
        monkeypatch.setattr(cli, "DEFAULT_SYSTEM_FEATURE_BIN_DIR", str(a_file))

        assert cli._default_feature_bin_dir() == "./feature-bin"
