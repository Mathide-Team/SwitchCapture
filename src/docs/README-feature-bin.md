# Dépôt local des .bin `packet-capture`

Structure attendue (voir `resolve_feature_bin()` dans `switch_capture_core.py`) :

```
feature-bin/
  5130/
    R3113P05/
      5130ei-cmw710-packet-capture-r3113p05.bin
    R3115P05/
      5130ei-cmw710-packet-capture-r3115p05.bin
  5140/
    <version>/
      5140ei-cmw710-packet-capture-<version>.bin
  5510/
    <version>/
      5510ei-cmw710-packet-capture-<version>.bin
  5520/
    <version>/
      5520ei-cmw710-packet-capture-<version>.bin
```

- Le sous-dossier `<version>` doit correspondre à la chaîne extraite après
  `Release` dans `display version` (ex: `R3113P05`).
- Si aucun dossier de version ne correspond, le script se rabat sur le
  premier `packet-capture*.bin` trouvé directement sous `<model>/`.
- **5510 et 5520 ont bien besoin d'un fichier** : packet-capture n'est pas
  natif à l'image principale (correction par rapport à une hypothèse
  antérieure de ce dépôt) — même mécanisme d'installation que 5130/5140.
- 3600 V2 (Comware 5) n'a pas de mécanisme équivalent : non supporté, voir
  CLAUDE.md.

Le nom exact du `.bin` dépend du modèle **et** de la version logicielle : il
n'y a pas de fichier universel. Récupérez-le sur le portail HPE en même
temps que l'image système (`boot`/`system`), pas séparément.
