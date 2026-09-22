"""Tests de `detect_model` / `detect_software_version` / `resolve_feature_bin`
(switch_capture_core).

Couvre trois des six fonctions identifiées comme sans couverture persistante
en session 49 (voir CLAUDE.md, « Prochaine feature »). Recherche exhaustive
préalable (noms de fonctions dans tout `tests/`) confirmée avant d'écrire le
moindre test : aucune des trois n'apparaissait, même indirectement, malgré
leur usage par `SetupAndCaptureThread._prepare_switch` (lui-même déjà décrit
comme critique par `docs/architecture.md`) et par le mode dry run
(`inspect_switch`, qui appelle directement `detect_model`/
`detect_software_version` mais n'est testé que via ses propres réponses
`FakeConn`, jamais ces deux fonctions en isolation).

Point d'attention découvert en écrivant ces tests, pas corrigé ici (portée
volontairement limitée à la couverture, pas un correctif) : la session 08
(voir `docs/sessions/session-08.md`) a élargi les alias `5130EI`/`5130HI`/
`5140EI`/`5140HI` au format réel HPE (suffixe de gamme après le numéro de
port, ex. « 5130-28-EI ») après une régression où la forme collée seule
(« 5130EI ») ne matchait aucune sortie `display version` réelle. Cette même
session note explicitement, en limite connue, que `MSR4000`/`5510`/`5520`/
`3600v2` n'ont **pas** été audités faute de sortie réelle disponible pour
ces modèles — leurs alias sont restés sous forme collée (`"5510HI"`, pas de
variante à tiret). Les tests ci-dessous couvrent donc le comportement RÉEL
du code tel qu'il existe aujourd'hui pour 5510/5520 (alias collé), et
ajoutent un test dédié qui verrouille explicitement cette limite connue
(texte au format à tiret, cohérent avec 5130/5140 désormais corrigés, non
reconnu) plutôt que de la corriger silencieusement en marge d'une tâche de
couverture de tests.
"""

from __future__ import annotations

from switch_capture_core import detect_model, detect_software_version, resolve_feature_bin

# --------------------------------------------------------------------- #
# detect_model — modèles reconnus (alias vérifiés depuis la session 08)
# --------------------------------------------------------------------- #

VERSION_MSR4000 = "HPE Comware Software, Version 7.1.070, Release 8377\nHPE MSR4000 Router\n"

VERSION_5130EI = "HPE Comware Software, Version 7.1.070, Release 6555P05,\nHPE 5130-28-EI Switch\n"

VERSION_5130HI = "HPE Comware Software, Version 7.1.070, Release 6555P05\nHPE 5130-52-HI Switch\n"

VERSION_5140EI = "HPE Comware Software, Version 7.1.070, Release 6635P01\nHPE 5140-28-EI Switch\n"

VERSION_5140HI = "HPE Comware Software, Version 7.1.070, Release 6635P01\nHPE 5140-52-HI Switch\n"

VERSION_3600V2 = "HPE Comware Software, Version 5.20.99, Release 2513\nHPE A3600-24 3600 V2 EI Switch\n"

VERSION_UNKNOWN = "HPE Comware Software, Version 9.9.99, Release 9999\nHPE MystereSwitch\n"


def test_detect_model_msr4000():
    assert detect_model(VERSION_MSR4000) == "MSR4000"


def test_detect_model_5130ei():
    assert detect_model(VERSION_5130EI) == "5130EI"


def test_detect_model_5130hi():
    assert detect_model(VERSION_5130HI) == "5130HI"


def test_detect_model_5130hi_not_confused_with_5130ei():
    """Garde-fou direct : le texte « -HI » ne doit jamais matcher le profil « EI »."""
    assert detect_model(VERSION_5130HI) != "5130EI"


def test_detect_model_5140ei():
    assert detect_model(VERSION_5140EI) == "5140EI"


def test_detect_model_5140hi():
    assert detect_model(VERSION_5140HI) == "5140HI"


def test_detect_model_3600v2():
    assert detect_model(VERSION_3600V2) == "3600v2"


def test_detect_model_unknown_returns_none():
    assert detect_model(VERSION_UNKNOWN) is None


def test_detect_model_case_insensitive():
    """`detect_model` uppercase le texte ET les alias avant comparaison."""
    lowered = VERSION_5130EI.lower()
    assert detect_model(lowered) == "5130EI"


def test_detect_model_empty_string_returns_none():
    assert detect_model("") is None


# --------------------------------------------------------------------- #
# detect_model — 5510/5520 : comportement réel + limite connue (session 08)
# --------------------------------------------------------------------- #


def test_detect_model_5510_matches_current_glued_alias():
    """Comportement RÉEL du code : alias `"5510HI"` collé (pas de tiret),
    jamais audité contre une sortie switch réelle (session 08). Texte
    contrivé pour contenir littéralement ce collé, à seule fin de fixer le
    comportement actuel — pas une sortie `display version` HPE authentique."""
    version_output = "HPE Comware Software, Version 7.1.070, Release 3208P01\nHPE5510HI Switch\n"
    assert detect_model(version_output) == "5510"


def test_detect_model_5520_matches_current_glued_alias():
    version_output = "HPE Comware Software, Version 7.1.070, Release 3208P01\nHPE5520HI Switch\n"
    assert detect_model(version_output) == "5520"


def test_detect_model_5510_dash_format_not_recognized_known_limitation():
    """Verrouille la limite connue documentée en session 08 : contrairement à
    5130/5140 (corrigés la même session), les alias 5510/5520 n'ont jamais
    été élargis au format à tiret réel HPE faute d'exemple vérifié. Un texte
    cohérent avec le format confirmé pour 5130/5140 (« 5510-28-HI ») n'est
    donc PAS reconnu aujourd'hui — ce test documente ce fait plutôt que de
    supposer silencieusement un comportement corrigé."""
    version_output = "HPE Comware Software, Version 7.1.070, Release 3208P01\nHPE 5510-28-HI Switch\n"
    assert detect_model(version_output) is None


def test_detect_model_5520_dash_format_not_recognized_known_limitation():
    version_output = "HPE Comware Software, Version 7.1.070, Release 3208P01\nHPE 5520-52-HI Switch\n"
    assert detect_model(version_output) is None


# --------------------------------------------------------------------- #
# detect_software_version
# --------------------------------------------------------------------- #


def test_detect_software_version_basic():
    assert detect_software_version("HPE Comware Software, Version 7.1.070, Release 6555P05\n") == "6555P05"


def test_detect_software_version_strips_trailing_comma():
    assert detect_software_version("HPE Comware Software, Version 7.1.070, Release 6555P05,\n") == "6555P05"


def test_detect_software_version_no_release_keyword_returns_none():
    assert detect_software_version("HPE Comware Software, Version 7.1.070\nHPE 5130-28-EI Switch\n") is None


def test_detect_software_version_release_keyword_without_token_returns_none():
    """`Release` présent mais rien de non-blanc juste après (fin de ligne) : pas de match, pas de crash."""
    assert detect_software_version("blabla Release \n") is None


def test_detect_software_version_empty_string_returns_none():
    assert detect_software_version("") is None


def test_detect_software_version_real_world_multiline_output():
    output = (
        "HPE Comware Software, Version 7.1.070, Release 6555P05\n"
        "Copyright (c) 2010-2026 Hewlett Packard Enterprise Development LP\n"
        "HPE 5130-28-EI Switch uptime is 12 weeks, 3 days, 4 hours, 5 minutes\n"
    )
    assert detect_software_version(output) == "6555P05"


# --------------------------------------------------------------------- #
# resolve_feature_bin
# --------------------------------------------------------------------- #


def test_resolve_feature_bin_versioned_dir_match(tmp_path):
    versioned = tmp_path / "5130EI" / "6555P05"
    versioned.mkdir(parents=True)
    bin_file = versioned / "packet-capture-5130-6555p05.bin"
    bin_file.write_bytes(b"\x00")

    result = resolve_feature_bin(str(tmp_path), "5130EI", "6555P05")

    assert result == bin_file


def test_resolve_feature_bin_falls_back_to_model_root_when_version_dir_missing(tmp_path):
    model_dir = tmp_path / "5130EI"
    model_dir.mkdir(parents=True)
    bin_file = model_dir / "packet-capture-5130-generic.bin"
    bin_file.write_bytes(b"\x00")

    result = resolve_feature_bin(str(tmp_path), "5130EI", "9999INCONNUE")

    assert result == bin_file


def test_resolve_feature_bin_falls_back_when_versioned_dir_has_no_match(tmp_path):
    """Le dossier versionné existe mais ne contient aucun `.bin` correspondant
    -> repli sur la racine du modèle, pas un `None` prématuré."""
    versioned = tmp_path / "5130EI" / "6555P05"
    versioned.mkdir(parents=True)
    (versioned / "readme.txt").write_text("pas un .bin")
    model_dir = tmp_path / "5130EI"
    fallback_bin = model_dir / "packet-capture-5130-fallback.bin"
    fallback_bin.write_bytes(b"\x00")

    result = resolve_feature_bin(str(tmp_path), "5130EI", "6555P05")

    assert result == fallback_bin


def test_resolve_feature_bin_no_version_uses_model_root_directly(tmp_path):
    model_dir = tmp_path / "5130EI"
    model_dir.mkdir(parents=True)
    bin_file = model_dir / "packet-capture-5130.bin"
    bin_file.write_bytes(b"\x00")

    result = resolve_feature_bin(str(tmp_path), "5130EI", None)

    assert result == bin_file


def test_resolve_feature_bin_model_dir_missing_returns_none(tmp_path):
    assert resolve_feature_bin(str(tmp_path), "5130EI", "6555P05") is None


def test_resolve_feature_bin_model_dir_exists_but_empty_returns_none(tmp_path):
    (tmp_path / "5130EI").mkdir(parents=True)

    assert resolve_feature_bin(str(tmp_path), "5130EI", None) is None


def test_resolve_feature_bin_ignores_files_not_matching_pattern(tmp_path):
    model_dir = tmp_path / "5130EI"
    model_dir.mkdir(parents=True)
    (model_dir / "readme.txt").write_text("pas un .bin")
    (model_dir / "other-feature-5130.bin").write_bytes(b"\x00")  # ne contient pas "packet-capture"

    assert resolve_feature_bin(str(tmp_path), "5130EI", None) is None


def test_resolve_feature_bin_multiple_matches_returns_sorted_first(tmp_path):
    model_dir = tmp_path / "5130EI"
    model_dir.mkdir(parents=True)
    (model_dir / "packet-capture-5130-v2.bin").write_bytes(b"\x00")
    (model_dir / "packet-capture-5130-v1.bin").write_bytes(b"\x00")

    result = resolve_feature_bin(str(tmp_path), "5130EI", None)

    assert result.name == "packet-capture-5130-v1.bin"
