"""Tests des branches `except ImportError` en tête de `switch_capture_core.py`.

Repérées à 0 % par l'audit `coverage.py` de session 54 (lignes 33-34, 39-41,
46-50, 55-59) : `test_connect_switch.py::test_raises_when_netmiko_not_installed`
et les tests KeePass existants ne couvrent que la *conséquence* d'une
dépendance absente (`monkeypatch.setattr(core_mod, "ConnectHandler", None)`),
jamais le bloc `try/except ImportError` lui-même qui produit ce `None`.

Approche : charger une **copie indépendante** du module (`importlib.util`,
sans passer par `sys.modules["switch_capture_core"]`) pendant que la
dépendance visée est simulée absente. Un `importlib.reload()` du module
partagé a été tenté en premier et **rejeté** : il rétablit correctement
`sys.modules`, mais les classes qu'il redéfinit (dataclasses y compris)
deviennent de nouveaux objets `class` — tout fichier de test qui avait déjà
fait `from switch_capture_core import PacingGapAnalysis` (etc.) avant ce
reload garde l'ancienne classe, et un `isinstance(...)` contre elle échoue
ensuite pour un objet construit par le module rechargé (repéré en pratique :
`test_pacing_gap_analysis.py` a commencé à échouer une fois ce fichier de
test ajouté, purement à cause de l'ordre alphabétique de collecte pytest).
Charger une copie à part, jamais enregistrée dans `sys.modules`, élimine
complètement ce risque : le module `switch_capture_core` réellement partagé
par le reste de la suite n'est jamais touché.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

CORE_SOURCE_PATH = Path(__file__).resolve().parents[1] / "src" / "switch_capture_core.py"


def _import_isolated_copy_without(*absent_module_names: str):
    """Charge une copie indépendante de `switch_capture_core.py`.

    Les modules listés dans `absent_module_names` sont simulés absents
    (`sys.modules[name] = None`, mécanisme standard pour forcer un
    `ImportError` sur un import ultérieur de ce nom) le temps du chargement,
    puis `sys.modules` est restauré à l'identique avant de retourner — que
    le chargement ait réussi ou levé. Le module `switch_capture_core` déjà
    importé par le reste de la suite (`sys.modules["switch_capture_core"]`)
    n'est jamais lu ni modifié par cette fonction.
    """
    saved = {name: sys.modules.get(name) for name in absent_module_names}
    for name in absent_module_names:
        sys.modules[name] = None
    try:
        spec = importlib.util.spec_from_file_location("switch_capture_core_import_probe", CORE_SOURCE_PATH)
        module = importlib.util.module_from_spec(spec)
        # dataclasses (avec `from __future__ import annotations`) résout les
        # annotations différées via `sys.modules[cls.__module__]` au moment
        # de la définition de la classe : le module probe doit donc être
        # enregistré sous son propre nom le temps de l'exécution, sinon
        # `AttributeError: 'NoneType' object has no attribute '__dict__'`.
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop("switch_capture_core_import_probe", None)
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def test_connect_handler_none_when_netmiko_absent():
    probe = _import_isolated_copy_without("netmiko")
    assert probe.ConnectHandler is None


def test_paramiko_and_scpclient_none_when_paramiko_absent():
    """`scp.SCPClient` dépend de `paramiko` : les deux tombent ensemble
    (un seul bloc `try/except` commun en tête de fichier)."""
    probe = _import_isolated_copy_without("paramiko", "scp")
    assert probe.paramiko is None
    assert probe.SCPClient is None


def test_keyring_none_when_absent():
    probe = _import_isolated_copy_without("keyring", "keyring.errors")
    assert probe.keyring is None


def test_pykeepass_and_credentials_error_fallback_when_absent():
    """`CredentialsError` retombe sur `Exception` (voir commentaire en tête de
    fichier) plutôt que sur `None`, pour rester utilisable dans un `except`."""
    probe = _import_isolated_copy_without("pykeepass", "pykeepass.exceptions")
    assert probe.PyKeePass is None
    assert probe.CredentialsError is Exception


def test_all_four_present_by_default_as_sanity_check():
    """Garde-fou : sans rien simuler d'absent, les quatre dépendances
    optionnelles sont bien résolues (sinon les quatre tests ci-dessus
    passeraient pour la mauvaise raison — dépendance déjà absente dans
    l'environnement d'exécution plutôt que simulée par ce fichier)."""
    probe = _import_isolated_copy_without()
    assert probe.ConnectHandler is not None
    assert probe.paramiko is not None
    assert probe.SCPClient is not None
    assert probe.keyring is not None
    assert probe.PyKeePass is not None
    assert probe.CredentialsError is not Exception
