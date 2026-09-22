"""Fusion YAML + arguments CLI pour `build_config`/`build_inspect_config`
(`switch_capture_cli.py`).

Repéré via l'audit `coverage.py` de la session 51 : les 15 tests existants
qui appellent `build_config` construisaient tous un `argparse.Namespace`
directement (`config=None`), sans jamais exercer la branche `if
getattr(args, "config", None): raw = load_yaml(args.config)` avec un vrai
fichier YAML sur disque — malgré `load_yaml` elle-même désormais couverte
en isolation par `test_cli_uncovered_pure_functions.py`. Ce module ferme ce
trou : chargement réel d'un fichier YAML, et priorité des arguments CLI
explicites sur les valeurs qu'il contient (comportement documenté dans la
docstring de `build_config`, jamais vérifié par un test avant cette
session).

Sans dépendance GTK4/PyGObject ni switch réel : uniquement
`switch_capture_cli`/`switch_capture_core` et un fichier texte.
"""

from __future__ import annotations

import argparse
import textwrap

import switch_capture_cli as cli


def _namespace(**overrides) -> argparse.Namespace:
    """Namespace minimal avec tous les attributs lus par `build_config`/
    `build_inspect_config` absents par défaut (`None`), comme le ferait
    argparse pour des options non fournies sur la ligne de commande."""
    defaults = {name: None for name in cli._CONFIG_FIELDS | cli._INSPECT_CONFIG_FIELDS}
    defaults.update(config=None, keepass_path=None)
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestBuildConfigYamlMerge:
    def test_loads_all_fields_from_yaml_file(self, tmp_path):
        yaml_file = tmp_path / "site-a.yaml"
        yaml_file.write_text(
            textwrap.dedent(
                """\
                switch_ip: 10.0.0.1
                ssh_user: mathilde
                ssh_password: s3cr3t
                capture_interface: GigabitEthernet1/0/1
                rotation_seconds: 30
                """
            ),
            encoding="utf-8",
        )
        args = _namespace(config=str(yaml_file))

        cfg = cli.build_config(args)

        assert cfg.switch_ip == "10.0.0.1"
        assert cfg.ssh_user == "mathilde"
        assert cfg.capture_interface == "GigabitEthernet1/0/1"
        assert cfg.rotation_seconds == 30

    def test_cli_argument_overrides_yaml_value(self, tmp_path):
        yaml_file = tmp_path / "site-a.yaml"
        yaml_file.write_text(
            textwrap.dedent(
                """\
                switch_ip: 10.0.0.1
                ssh_user: mathilde
                ssh_password: s3cr3t
                capture_interface: GigabitEthernet1/0/1
                rotation_seconds: 30
                """
            ),
            encoding="utf-8",
        )
        # rotation_seconds fourni explicitement en CLI : doit l'emporter sur
        # la valeur du YAML (docstring de build_config : « arguments CLI
        # prioritaires »).
        args = _namespace(config=str(yaml_file), rotation_seconds=60)

        cfg = cli.build_config(args)

        assert cfg.rotation_seconds == 60
        # Les champs non re-précisés en CLI restent bien ceux du YAML.
        assert cfg.switch_ip == "10.0.0.1"

    def test_keepass_path_read_from_yaml(self, tmp_path):
        yaml_file = tmp_path / "site-a.yaml"
        yaml_file.write_text(
            textwrap.dedent(
                """\
                switch_ip: 10.0.0.1
                ssh_user: mathilde
                ssh_password: s3cr3t
                capture_interface: GigabitEthernet1/0/1
                keepass_path: /home/mathilde/secrets.kdbx
                """
            ),
            encoding="utf-8",
        )
        # keepass_path n'est pas un champ de Config : il ne doit pas remonter
        # tel quel sur l'objet, mais ne doit pas non plus faire planter la
        # construction (filtré via _CONFIG_FIELDS avant Config(**raw)).
        args = _namespace(config=str(yaml_file))

        cfg = cli.build_config(args)

        assert not hasattr(cfg, "keepass_path")
        assert cfg.switch_ip == "10.0.0.1"

    def test_no_config_argument_ignores_yaml_entirely(self, tmp_path, monkeypatch):
        # Garde-fou : si args.config est None/absent, load_yaml ne doit même
        # pas être appelée (sinon une IsADirectoryError/FileNotFoundError
        # surviendrait ici puisqu'aucun fichier n'existe).
        def _fail(*_args, **_kwargs):
            raise AssertionError("load_yaml ne doit pas être appelée sans --config")

        monkeypatch.setattr(cli, "load_yaml", _fail)
        args = _namespace(
            config=None,
            switch_ip="10.0.0.1",
            ssh_user="mathilde",
            ssh_password="s3cr3t",
            capture_interface="GigabitEthernet1/0/1",
        )

        cfg = cli.build_config(args)

        assert cfg.switch_ip == "10.0.0.1"


class TestBuildInspectConfigYamlMerge:
    def test_loads_fields_from_yaml_file(self, tmp_path):
        yaml_file = tmp_path / "site-a.yaml"
        yaml_file.write_text(
            textwrap.dedent(
                """\
                switch_ip: 10.0.0.2
                ssh_user: admin
                ssh_password: s3cr3t
                transfer_mode: sshfs
                """
            ),
            encoding="utf-8",
        )
        args = _namespace(config=str(yaml_file))

        cfg = cli.build_inspect_config(args)

        assert cfg.switch_ip == "10.0.0.2"
        assert cfg.transfer_mode == "sshfs"

    def test_cli_argument_overrides_yaml_value(self, tmp_path):
        yaml_file = tmp_path / "site-a.yaml"
        yaml_file.write_text(
            textwrap.dedent(
                """\
                switch_ip: 10.0.0.2
                ssh_user: admin
                ssh_password: s3cr3t
                transfer_mode: sshfs
                """
            ),
            encoding="utf-8",
        )
        args = _namespace(config=str(yaml_file), transfer_mode="scp")

        cfg = cli.build_inspect_config(args)

        assert cfg.transfer_mode == "scp"

    def test_config_reused_from_capture_ignores_extra_capture_only_fields(self, tmp_path):
        # Docstring de build_inspect_config : un --config déjà utilisé pour
        # `capture` peut directement être réutilisé pour `inspect`, les
        # champs en trop (ex. capture_interface) sont simplement ignorés.
        yaml_file = tmp_path / "site-a.yaml"
        yaml_file.write_text(
            textwrap.dedent(
                """\
                switch_ip: 10.0.0.2
                ssh_user: admin
                ssh_password: s3cr3t
                capture_interface: GigabitEthernet1/0/1
                rotation_seconds: 30
                """
            ),
            encoding="utf-8",
        )
        args = _namespace(config=str(yaml_file))

        cfg = cli.build_inspect_config(args)  # ne doit pas lever malgré les champs en trop

        assert cfg.switch_ip == "10.0.0.2"
        assert not hasattr(cfg, "capture_interface")
