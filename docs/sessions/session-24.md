# Session 24 — 29/08/2026

*[Index des sessions](index.md) · [Backlog](../features-backlog.md) · [Architecture](../architecture.md)*

---

## Squelette de projet futur — point 15 de features.md (29/08/2026, 4e session du jour)

Point 15 (« Projet futur (hors switch-capture lui-même) ») traité. Comme
demandé explicitement par le libellé du point, le squelette n'est **pas**
ajouté dans ce dépôt mais livré à côté, dans `gtk4-project-skeleton/`
(même niveau que `switch-capture/`) :

```
gtk4-project-skeleton/
├── README.md                # explique ce qui est repris de switch-capture,
│                             # et ce qui ne l'est délibérément pas
├── pyproject.toml           # [tool.ruff] ligne 120, deps loguru (+ PyGObject en extra)
├── .pre-commit-config.yaml  # mêmes hooks que ce dépôt (voir plus bas)
├── requirements.txt / requirements-dev.txt
├── .gitignore
├── src/
│   ├── app_core.py          # logique métier, sans dépendance GTK (exemple hello())
│   └── app_cli.py           # point d'entrée CLI, à enrichir avec argparse
└── tests/
    ├── conftest.py          # ajoute src/ à sys.path, même convention que ce dépôt
    └── test_app_core.py
```

Conventions reprises telles quelles de ce dépôt (voir plus haut, section
« Fichiers », et le reste de ce fichier) :
- séparation core (sans GTK) / CLI / (future) GUI, pour rester testable
  sans environnement GTK4 ;
- `loguru` pour la journalisation ;
- `tests/conftest.py` ajoutant `src/` à `sys.path` plutôt qu'un packaging
  `setup.py` orienté paquet installable ;
- `.pre-commit-config.yaml` : mêmes hooks que ce dépôt, y compris le
  doublon volontaire ruff/flake8 (flake8 attrape encore `E402`, que ruff
  seul laisse passer — voir plus haut, ligne ~2137 de ce fichier, pour la
  même justification déjà notée sur `test_gui_new_fields.py`), même
  ligne à 120 caractères, même liste d'ignore flake8.

Délibérément absent de ce squelette (à recréer depuis switch-capture le
jour où le futur projet en a effectivement besoin, pas avant) :
packaging `.deb`/`.rpm`/`install.sh`, `.desktop`/icône, toute logique
métier réelle.

**Vérifié réellement cette session** (pas juste relu) : `py_compile` sur
les 4 fichiers Python du squelette (`app_core.py`, `app_cli.py`,
`conftest.py`, `test_app_core.py`) — OK ; `pytest tests/ -q` exécuté
réellement dans le squelette — **1 passed, 0 failed** ; `pyproject.toml`
parsé avec `tomllib` (stdlib) sans erreur ; `.pre-commit-config.yaml`
parsé avec `pyyaml` sans erreur, 3 dépôts de hooks bien présents. `ruff`
disponible cette session (accès réseau pip présent) :
`ruff check --line-length 120 src/ tests/` → **0 erreur** (« All checks
passed! ») et `ruff format --line-length 120 --check src/ tests/` →
**4 fichiers déjà formatés**, sur le code du squelette lui-même — la
config `[tool.ruff]` de `pyproject.toml` a donc bien été exercée
réellement, pas seulement validée comme TOML syntaxiquement correct.

