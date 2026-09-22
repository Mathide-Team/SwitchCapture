"""Invariant « modèle » de `SetupAndCaptureThread._prepare_switch` — clôture
formelle de la seconde sous-piste du point 4 de `CLAUDE.md` (session 61).

Contexte : la branche défensive de `_prepare_switch`

    model = self.cfg.model or detect_model(version_output)
    if not model:
        raise RuntimeError("Modèle switch non reconnu automatiquement ...")
    if model not in MODEL_PROFILES:            # <- cette ligne
        raise RuntimeError(f"Modèle inconnu : {model!r}")

est restée non couverte de session 51 à session 60 et avait été identifiée en
[session 54](../docs/sessions/session-54.md) comme « probablement du code
mort », sans confirmation formelle. La consigne du backlog était explicite :
**confirmer/documenter plutôt que forcer la couverture** par une mutation
post-construction du dataclass (`cfg.model = "bogus"`), qui ne refléterait
aucun chemin d'invocation réel — même principe que les lignes 998-999 de
`switch_capture_cli.py`, laissées non couvertes en session 53.

Ce fichier ne couvre donc **pas** la ligne en question : il verrouille par des
tests les trois prémisses dont dépend le raisonnement d'inatteignabilité, pour
qu'une régression future les casse bruyamment au lieu de rendre silencieusement
fausse une analyse consignée dans la documentation.

    A. `detect_model()` ne renvoie jamais que `None` ou une **clé réelle** de
       `MODEL_PROFILES` (jamais un alias, jamais une valeur construite).
    B. `Config.__post_init__` refuse à la construction tout `model` qui n'est
       pas une clé de `MODEL_PROFILES` — y compris un alias, qui n'est pas une
       clé (`"5510hi"`, `"5130-28-EI"`...).
    C. Aucun code de `src/` ne réaffecte `cfg.model` après construction : le
       seul contournement théorique de (B) n'existe nulle part dans le dépôt.

A + B + C ⇒ à la ligne ci-dessus, `model` est soit une clé de `MODEL_PROFILES`
(cas nominal), soit vide (déjà traité par le `raise` précédent). La branche est
inatteignable par tout chemin d'invocation réel.

Deux tests de bout en bout (section « Conclusion ») exercent en plus le chemin
réel — chaque alias, puis chaque clé forcée via `cfg.model` — et vérifient que
le message « Modèle inconnu » ne sort jamais.

Sans switch réel ni dépendance GTK4 : `FakeConn` local minimal, sur le même
principe que `test_setup_and_capture_thread.py` / `test_inspect.py` (chaque
fichier garde le sien plutôt que d'en importer un d'un autre module de test).
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

import switch_capture_core as core
from switch_capture_core import MODEL_PROFILES, Config, SetupAndCaptureThread, SharedState, detect_model

SRC_DIR = Path(__file__).resolve().parents[1] / "src"

# Tous les couples (clé de profil, alias) déclarés dans MODEL_PROFILES —
# construits par compréhension plutôt qu'écrits en dur : un modèle ajouté
# demain est automatiquement soumis aux mêmes invariants, sans toucher ce
# fichier (c'est précisément ce qu'on veut verrouiller ici).
ALL_ALIASES = [(key, alias) for key, profile in MODEL_PROFILES.items() for alias in profile["aliases"]]

# Aliases qui ne sont pas eux-mêmes des clés : ils rendent les prémisses A et B
# non triviales (sans eux, « renvoyer un alias » et « renvoyer une clé »
# seraient indiscernables).
ALIASES_THAT_ARE_NOT_KEYS = sorted({alias for _key, alias in ALL_ALIASES if alias not in MODEL_PROFILES})

NTP_SYNCED = "Clock status: synchronized\nClock stratum: 3\n"
VERSION_UNKNOWN = "HPE Comware Software, Version 9.9.99, Release 9999\nHPE MystereSwitch\n"


def version_output_for(alias: str) -> str:
    """Fabrique une sortie 'display version' plausible contenant `alias`."""
    return f"HPE Comware Software, Version 7.1.070, Release 6555P05\nHPE {alias} Switch\n"


def make_config(**overrides) -> Config:
    """Config valide minimale (mêmes défauts que les autres fichiers de tests)."""
    base = {
        "switch_ip": "10.0.0.1",
        "ssh_user": "mathilde",
        "ssh_password": "secret",
        "capture_interface": "GigabitEthernet1/0/1",
    }
    base.update(overrides)
    return Config(**base)


class FakeConn:
    """Session netmiko minimale : répond à la première clé de `responses`
    contenue dans la commande reçue (même principe que `FakeConn` dans
    `test_setup_and_capture_thread.py`, réduit ici à ce dont `_prepare_switch`
    a besoin)."""

    def __init__(self, version_output: str):
        self.responses = {
            "display version": version_output,
            "display current-configuration": "scp server enable\n",
            "display ntp-service status": NTP_SYNCED,
            "packet-capture ?": "packet-capture ok",
            "display install active": "",
        }
        self.disconnected = False

    def send_command(self, cmd: str, **_kwargs) -> str:
        for key, value in self.responses.items():
            if key in cmd:
                return value
        return ""

    def send_command_timing(self, cmd: str, **_kwargs) -> str:
        return self.send_command(cmd)

    def config_mode(self) -> None:
        pass

    def exit_config_mode(self) -> None:
        pass

    def disconnect(self) -> None:
        self.disconnected = True


def patch_connect(monkeypatch, conn: FakeConn) -> None:
    monkeypatch.setattr(core, "connect_switch", lambda _cfg: conn)


# --------------------------------------------------------------------- #
# Prémisse A — detect_model ne renvoie que None ou une clé réelle
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(("key", "alias"), ALL_ALIASES, ids=[f"{k}:{a}" for k, a in ALL_ALIASES])
def test_detect_model_returns_a_real_profile_key_for_every_alias(key, alias):
    """Pour *chaque* alias déclaré, `detect_model` renvoie une clé de
    `MODEL_PROFILES` — pas l'alias, pas une chaîne reconstruite."""
    detected = detect_model(version_output_for(alias))

    assert detected is not None, f"alias {alias!r} du profil {key!r} non détecté"
    assert detected in MODEL_PROFILES, f"{detected!r} n'est pas une clé de MODEL_PROFILES"


def test_some_aliases_are_not_profile_keys():
    """Garde-fou du test précédent : si un jour tous les alias devenaient aussi
    des clés, « renvoyer une clé » cesserait d'être une propriété testable et
    ce fichier ne prouverait plus rien."""
    assert ALIASES_THAT_ARE_NOT_KEYS, "aucun alias distinct d'une clé : prémisse A devenue triviale"
    assert "5510hi" in ALIASES_THAT_ARE_NOT_KEYS
    assert "5130-28-EI" in ALIASES_THAT_ARE_NOT_KEYS


@pytest.mark.parametrize(
    "version_output",
    [
        "",
        "   \n\t  ",
        "HPE Comware Software, Version 9.9.99\nHPE MystereSwitch\n",
        "5150-28-EI",  # chiffres voisins d'un alias réel, mais aucun alias
        "513",  # préfixe strict d'un alias
        "MSR",  # préfixe strict d'un alias
        "Cisco IOS Software, C2960 Software",  # constructeur sans rapport
        "\x00\xff octets arbitraires \U0001f600",
    ],
)
def test_detect_model_returns_none_or_real_key_on_arbitrary_input(version_output):
    """Sur une entrée quelconque, la valeur de retour reste dans l'ensemble
    {None} ∪ clés(MODEL_PROFILES) — c'est exactement ce dont dépend la
    prémisse A, indépendamment de ce que contient la sortie du switch."""
    detected = detect_model(version_output)

    assert detected is None or detected in MODEL_PROFILES


# --------------------------------------------------------------------- #
# Prémisse B — Config refuse tout modèle hors clés, dès la construction
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("key", sorted(MODEL_PROFILES), ids=sorted(MODEL_PROFILES))
def test_config_accepts_every_profile_key(key):
    """Le pendant positif : toute clé réelle passe la validation (sinon la
    détection automatique produirait des `Config` impossibles à construire)."""
    assert make_config(model=key).model == key


@pytest.mark.parametrize("alias", ALIASES_THAT_ARE_NOT_KEYS, ids=ALIASES_THAT_ARE_NOT_KEYS)
def test_config_rejects_aliases_that_are_not_keys(alias):
    """Un alias n'est pas une clé : `--model 5510hi` est refusé à la
    construction, `detect_model` ne peut donc pas non plus « glisser » un alias
    dans `cfg.model` par un autre chemin."""
    with pytest.raises(ValueError, match="Modèle invalide"):
        make_config(model=alias)


@pytest.mark.parametrize(
    "bogus",
    ["inconnu-9999", "5150-28-EI", "5130", "msr4000", "MODEL_PROFILES", "5130EI ", " 5130EI"],
)
def test_config_rejects_lookalike_models(bogus):
    """Valeurs proches d'une clé réelle (casse, espaces, troncature) : toutes
    refusées, aucune normalisation implicite qui les ferait passer."""
    with pytest.raises(ValueError, match="Modèle invalide"):
        make_config(model=bogus)


def test_dataclasses_replace_revalidates_model():
    """`dataclasses.replace()` — la seule façon *documentée* de dériver un
    dataclass — repasse par `__post_init__` : elle ne permet pas de contourner
    la validation. Reste l'affectation brute d'attribut, traitée par la
    prémisse C ci-dessous."""
    cfg = make_config(model="5130EI")

    with pytest.raises(ValueError, match="Modèle invalide"):
        dataclasses.replace(cfg, model="inconnu-9999")


# --------------------------------------------------------------------- #
# Prémisse C — aucune réaffectation de cfg.model dans src/
# --------------------------------------------------------------------- #

# `self.state.model` (SharedState, ligne ~2418 de switch_capture_core.py) est
# la seule affectation légitime : SharedState est un simple porteur d'état
# partagé vers la GUI, sans validation ni influence sur _prepare_switch.
_ALLOWED_MODEL_ASSIGNMENTS = {"self.state.model"}

# `\.model\s*=` sans `==` : affectation d'attribut nommé `model`, quel que soit
# le porteur (cfg, self.cfg, config, session.cfg...).
_MODEL_ASSIGNMENT_RE = re.compile(r"([\w.]*\.model)\s*=(?!=)")


def test_no_post_construction_assignment_to_model_in_src():
    """Prémisse C, vérifiée sur le source plutôt qu'affirmée en prose.

    Si une future modification introduit `cfg.model = ...` quelque part dans
    `src/`, la branche `if model not in MODEL_PROFILES` de `_prepare_switch`
    redevient potentiellement atteignable et l'analyse consignée en session 61
    doit être refaite : ce test échoue alors, au lieu de laisser la
    documentation devenir silencieusement fausse.
    """
    offenders: list[str] = []
    for path in sorted(SRC_DIR.glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in _MODEL_ASSIGNMENT_RE.finditer(line):
                if match.group(1) not in _ALLOWED_MODEL_ASSIGNMENTS:
                    offenders.append(f"{path.name}:{lineno}: {line.strip()}")

    assert not offenders, (
        "affectation(s) de .model hors construction — revoir docs/sessions/session-61.md :\n" + "\n".join(offenders)
    )


def test_model_assignment_regex_actually_matches_something():
    """Garde-fou du test précédent : une regex qui ne matcherait plus rien (par
    exemple après un renommage de champ) le rendrait vert pour de mauvaises
    raisons."""
    assert _MODEL_ASSIGNMENT_RE.search("            self.state.model = model")
    assert _MODEL_ASSIGNMENT_RE.search("cfg.model = 'bogus'")
    assert not _MODEL_ASSIGNMENT_RE.search("if self.model == other.model:")


# --------------------------------------------------------------------- #
# Conclusion — le chemin réel ne produit jamais « Modèle inconnu »
# --------------------------------------------------------------------- #

_UNKNOWN_MODEL_MESSAGE = "Modèle inconnu"


@pytest.mark.parametrize(("key", "alias"), ALL_ALIASES, ids=[f"{k}:{a}" for k, a in ALL_ALIASES])
def test_prepare_switch_never_reports_unknown_model_for_any_alias(monkeypatch, key, alias):
    """Auto-détection : pour chaque alias, `_prepare_switch` soit aboutit avec
    un `state.model` qui est une clé réelle, soit échoue sur le motif
    « non supporté » (Comware 5) — jamais sur « Modèle inconnu »."""
    conn = FakeConn(version_output_for(alias))
    patch_connect(monkeypatch, conn)
    thread = SetupAndCaptureThread(make_config(feature_bin_path="/inexistant/packet-capture.bin"), SharedState())

    try:
        thread._prepare_switch()
    except RuntimeError as exc:
        assert _UNKNOWN_MODEL_MESSAGE not in str(exc), f"branche morte atteinte via l'alias {alias!r}"
        assert "non supporté" in str(exc), f"échec inattendu pour {alias!r} : {exc}"
        assert MODEL_PROFILES[key]["packet_capture"] == "unsupported"
    else:
        assert thread.state.model in MODEL_PROFILES

    assert conn.disconnected is True  # le `finally` de _prepare_switch déconnecte dans les deux cas


@pytest.mark.parametrize("key", sorted(MODEL_PROFILES), ids=sorted(MODEL_PROFILES))
def test_prepare_switch_never_reports_unknown_model_for_any_forced_key(monkeypatch, key):
    """Modèle forcé (`cfg.model`, chemin qui court-circuite `detect_model`) :
    même conclusion pour chaque clé, ici avec une sortie `display version`
    volontairement non reconnaissable."""
    conn = FakeConn(VERSION_UNKNOWN)
    patch_connect(monkeypatch, conn)
    cfg = make_config(model=key, feature_bin_path="/inexistant/packet-capture.bin")
    thread = SetupAndCaptureThread(cfg, SharedState())

    try:
        thread._prepare_switch()
    except RuntimeError as exc:
        assert _UNKNOWN_MODEL_MESSAGE not in str(exc), f"branche morte atteinte via cfg.model={key!r}"
        assert "non supporté" in str(exc)
        assert MODEL_PROFILES[key]["packet_capture"] == "unsupported"
    else:
        assert thread.state.model == key


def test_prepare_switch_unrecognized_output_reports_detection_failure_not_unknown_model(monkeypatch):
    """Sortie non reconnue et aucun modèle forcé : c'est le `raise` *précédent*
    (« non reconnu automatiquement », `model` vide) qui se déclenche — la
    branche « Modèle inconnu » n'est pas son doublon et reste inatteignable."""
    conn = FakeConn(VERSION_UNKNOWN)
    patch_connect(monkeypatch, conn)
    thread = SetupAndCaptureThread(make_config(), SharedState())

    with pytest.raises(RuntimeError) as excinfo:
        thread._prepare_switch()

    assert "non reconnu automatiquement" in str(excinfo.value)
    assert _UNKNOWN_MODEL_MESSAGE not in str(excinfo.value)
