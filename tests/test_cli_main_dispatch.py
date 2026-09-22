"""Tests de `main()` (switch_capture_cli.py) — point d'entrée CLI.

Piste laissée ouverte en fin de session 52 (« poursuivre l'audit de
couverture ») : `main()` était à 0 % de couverture (lignes 968-999),
jamais exercée par aucun test du dépôt — confirmé par recherche croisée
(`grep -rn "\\.main(\\[" tests/*.py`, aucun résultat avant ce fichier).

Approche : argv réels passés à travers le vrai `build_arg_parser()` (pas
de parseur simulé — on veut exercer la vraie définition argparse), avec
seulement les six fonctions terminales (`run_import_bin`/`run_mirror`/
`run_inspect`/`run_analyze_pacing`/`run_capture`/`run_uninstall`)
remplacées par de faux callables qui enregistrent leurs arguments et
renvoient un code fourni par le test — même principe que
`test_run_capture_dispatch.py`/`test_run_mirror_command.py`, un niveau
au-dessus (dispatch, pas logique interne de chaque sous-commande, déjà
couverte ailleurs).

Une branche volontairement laissée de côté, documentée ici plutôt que
forcée par un mock artificiel qui ne refléterait aucun chemin
d'invocation réel :

- lignes ~997-999 (`action inconnue`) : `args.action` provient de
  `subparsers.add_parser(dest="action", required=True)`, restreint aux
  six noms de sous-commandes définis plus haut dans la même fonction —
  aucun argv, si exotique soit-il, ne peut faire produire à
  `parser.parse_args()` un `action` hors de cet ensemble (argparse
  rejette lui-même toute valeur inconnue avec « invalid choice » avant
  que `main()` ne voie quoi que ce soit). Branche défensive prouvée
  inatteignable via l'interface CLI réelle, même statut que le code GTK4
  hors périmètre pytest par construction.

La ligne 1003 (`if __name__ == "__main__": sys.exit(main())`), un temps
documentée comme hors périmètre pytest (ce garde ne s'exécute normalement
que si le fichier est lancé comme script, jamais importé), est en fait
couverte ci-dessous (`TestDunderMainBlock`) via
`runpy.run_module("switch_capture_cli", run_name="__main__")` : exécute
réellement le module sous cet alias dans le même process pytest, sans
sous-processus ni impact sur le module déjà importé (vérifié
explicitement, voir ce test).

Sans dépendance GTK4/PyGObject ni switch réel.
"""

from __future__ import annotations

import argparse
import runpy
import sys

import pytest

import switch_capture_cli as cli


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    # main() appelle toujours _configure_logging(), qui écrit
    # switch_capture.log relatif au répertoire courant (voir
    # test_cli_uncovered_pure_functions.py::TestConfigureLogging) : on
    # isole chaque test dans un dossier temporaire plutôt que de polluer
    # le dépôt.
    monkeypatch.chdir(tmp_path)


class _Recorder:
    """Faux callable de remplacement pour un run_* : enregistre ses arguments, renvoie `rc`."""

    def __init__(self, rc: int = 0):
        self.rc = rc
        self.calls: list[tuple] = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.rc


# --------------------------------------------------------------------- #
# Dispatch des quatre sous-commandes sans build_config (import-bin,
# mirror, inspect, analyze-pacing) : main() les appelle directement,
# avant tout appel à build_config.
# --------------------------------------------------------------------- #


def test_dispatch_import_bin(monkeypatch, tmp_path):
    fake = _Recorder(rc=0)
    monkeypatch.setattr(cli, "run_import_bin", fake)

    src = tmp_path / "feature-bin-src"
    rc = cli.main(["import-bin", str(src)])

    assert rc == 0
    assert fake.calls == [(str(src), None)]


def test_dispatch_import_bin_forwards_feature_bin_dir(monkeypatch, tmp_path):
    fake = _Recorder(rc=1)
    monkeypatch.setattr(cli, "run_import_bin", fake)

    src = tmp_path / "feature-bin-src"
    dst = tmp_path / "feature-bin-dst"
    rc = cli.main(["import-bin", str(src), "--feature-bin-dir", str(dst)])

    assert rc == 1
    assert fake.calls == [(str(src), str(dst))]


def test_dispatch_mirror(monkeypatch):
    fake = _Recorder(rc=0)
    monkeypatch.setattr(cli, "run_mirror", fake)

    rc = cli.main(
        [
            "mirror",
            "--switch-ip",
            "10.0.0.1",
            "--ssh-user",
            "mathilde",
            "--source-interface",
            "GigabitEthernet1/0/1",
        ]
    )

    assert rc == 0
    assert len(fake.calls) == 1
    (args,) = fake.calls[0]
    assert isinstance(args, argparse.Namespace)
    assert args.switch_ip == "10.0.0.1"


def test_dispatch_inspect(monkeypatch):
    fake = _Recorder(rc=0)
    monkeypatch.setattr(cli, "run_inspect", fake)

    rc = cli.main(["inspect", "--switch-ip", "10.0.0.1", "--ssh-user", "mathilde"])

    assert rc == 0
    assert len(fake.calls) == 1


def test_dispatch_analyze_pacing(monkeypatch, tmp_path):
    fake = _Recorder(rc=0)
    monkeypatch.setattr(cli, "run_analyze_pacing", fake)

    pcap_file = tmp_path / "capture.pcap"
    rc = cli.main(["analyze-pacing", str(pcap_file)])

    assert rc == 0
    (args,) = fake.calls[0]
    assert args.pcap_file == str(pcap_file)


# --------------------------------------------------------------------- #
# Dispatch capture/uninstall : passent par build_config() (pour de vrai)
# avant d'appeler run_capture/run_uninstall (mockées).
# --------------------------------------------------------------------- #


def _valid_capture_argv(action: str, *extra: str) -> list[str]:
    return [
        action,
        "--switch-ip",
        "10.0.0.1",
        "--ssh-user",
        "mathilde",
        "--ssh-password",
        "secret",
        "--capture-interface",
        "GigabitEthernet1/0/1",
        *extra,
    ]


def test_dispatch_capture(monkeypatch):
    fake = _Recorder(rc=0)
    monkeypatch.setattr(cli, "run_capture", fake)

    rc = cli.main(_valid_capture_argv("capture"))

    assert rc == 0
    (cfg,) = fake.calls[0]
    assert cfg.switch_ip == "10.0.0.1"
    assert cfg.capture_interface == "GigabitEthernet1/0/1"


def test_dispatch_uninstall_forwards_remove_bin_and_confirm_ip(monkeypatch):
    fake = _Recorder(rc=1)
    monkeypatch.setattr(cli, "run_uninstall", fake)

    rc = cli.main(_valid_capture_argv("uninstall", "--remove-bin", "--confirm-ip"))

    assert rc == 1
    cfg, remove_bin_from_flash, confirm_ip = fake.calls[0]
    assert cfg.switch_ip == "10.0.0.1"
    assert remove_bin_from_flash is True
    assert confirm_ip is True


def test_dispatch_uninstall_defaults_remove_bin_and_confirm_ip_to_false(monkeypatch):
    fake = _Recorder(rc=0)
    monkeypatch.setattr(cli, "run_uninstall", fake)

    cli.main(_valid_capture_argv("uninstall"))

    _cfg, remove_bin_from_flash, confirm_ip = fake.calls[0]
    assert remove_bin_from_flash is False
    assert confirm_ip is False


def test_capture_return_code_propagates(monkeypatch):
    # Le code de retour de run_capture doit être celui de main(), sans
    # transformation (régression triviale mais jamais vérifiée avant
    # cette session : main() n'était pas testée du tout).
    monkeypatch.setattr(cli, "run_capture", _Recorder(rc=1))

    assert cli.main(_valid_capture_argv("capture")) == 1


# --------------------------------------------------------------------- #
# build_config invalide (ValueError) -> parser.error() -> 2
# --------------------------------------------------------------------- #


def test_invalid_config_returns_2(monkeypatch):
    # `parser.error()` appelle sys.exit(2) dans un ArgumentParser réel —
    # on neutralise `.error()` (classe entière, portée limitée à ce test
    # par monkeypatch) pour observer le `return 2` explicite qui suit dans
    # main() sans avoir à intercepter un SystemExit, exactement comme
    # argparse se comporterait si `exit_on_error` était désactivé.
    errors: list[str] = []
    monkeypatch.setattr(argparse.ArgumentParser, "error", lambda self, msg: errors.append(msg))
    monkeypatch.setattr(cli, "run_capture", _Recorder(rc=0))

    # argv minimal valide côté argparse (aucun --switch-ip/--ssh-user
    # requis à ce niveau, voir _add_common_config_args) mais invalide
    # côté Config.__post_init__ (champs obligatoires manquants).
    rc = cli.main(["capture"])

    assert rc == 2
    assert len(errors) == 1
    assert "obligatoires" in errors[0]


# --------------------------------------------------------------------- #
# if __name__ == "__main__": sys.exit(main())
# --------------------------------------------------------------------- #


class TestDunderMainBlock:
    def test_runs_main_and_exits_with_its_return_code(self, tmp_path, monkeypatch):
        """Exécute réellement le module comme un script (runpy, dans le même
        process pytest — coverage.py voit donc l'exécution de la ligne
        `sys.exit(main())`), sans dépendre d'un switch : import-bin avec un
        dossier source absent renvoie 1 sans ouvrir la moindre connexion."""
        missing_source = tmp_path / "does-not-exist"
        monkeypatch.setattr(
            sys,
            "argv",
            ["switch-capture", "import-bin", str(missing_source), "--feature-bin-dir", str(tmp_path / "out")],
        )

        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("switch_capture_cli", run_name="__main__")

        assert exc_info.value.code == 1

    def test_does_not_replace_the_cached_module_in_sys_modules(self, monkeypatch):
        """runpy.run_module (sans alter_sys=True) exécute une copie du code
        sous __name__ == "__main__" sans toucher au module déjà importé —
        vérifié explicitement pour ne pas casser les monkeypatch d'autres
        fichiers de tests sur cli (ex: cli.run_capture) qui s'exécuteraient
        après celui-ci dans la même session pytest.

        Sous-commande "capture" sans --ssh-password/--capture-interface :
        ValueError propre (Config.__post_init__) -> parser.error() réel ->
        SystemExit(2), sans jamais tenter de connexion switch."""
        before = sys.modules["switch_capture_cli"]
        monkeypatch.setattr(
            sys, "argv", ["switch-capture", "capture", "--switch-ip", "10.0.0.1", "--ssh-user", "mathilde"]
        )

        with pytest.raises(SystemExit):
            runpy.run_module("switch_capture_cli", run_name="__main__")

        assert sys.modules["switch_capture_cli"] is before
        assert sys.modules["switch_capture_cli"] is cli
