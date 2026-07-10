# Agent CV — V2

Agent IA Colombus qui adapte automatiquement le CV d'un consultant au vocabulaire et aux exigences d'un appel d'offres (AO).

**Entrée** : 1 à N versions du CV (PDFs) + 1 AO (PDF ou texte).
**Sortie** : un PPTX 1 page au format Golden Source Colombus, prêt à envoyer.

> La V1 historique (Phase 4, branche [`feature/nouvelle-archi-2026-05-06`](https://github.com/Colombus-Consulting/agent-cv/tree/feature/nouvelle-archi-2026-05-06)) reste accessible pour comparaison. La V2 est une refonte architecturale, pas une simple évolution.

---

## Qu'est-ce que ça fait en pratique

1. Lit le ou les CV du consultant et l'appel d'offres
2. Identifie les besoins clés de l'AO (compétences attendues, deal-breakers, vocabulaire client)
3. Sélectionne les expériences les plus pertinentes du consultant et les **reformule** dans le vocabulaire de l'AO
4. Met en avant ce qui matche, occulte le reste, signale les manques (`[[À compléter : ...]]`)
5. Génère le PPTX dans le template Colombus Golden Source v2

L'agent ne ment jamais : il ne crée pas d'expérience qui n'existe pas, ne minimise pas de gap. Quand une exigence de l'AO n'est pas couverte par le CV, il le dit explicitement.

---

## V1 (Phase 4) vs V2 — qu'est-ce qui a changé ?

### Ce qui s'améliore en V2

| Sujet | V1 (Phase 4) | V2 |
|---|---|---|
| **Pipeline LLM (génération du contenu)** | 1 seul appel monolithique : tout le CV produit en une fois | 3 étapes auditables (Extract-Brief, Extract-CV, Match+Reformulate), 2 en parallèle |
| **Modèle métier** | Schéma plat figé : 4 missions × `titre` + `desc` (string) | Modèle hiérarchique riche : domaines → missions → réalisations, chacun typé |
| **Provider LLM** | Anthropic Claude uniquement | Multi-provider via `litellm` (Claude, OpenAI, Azure, Vertex…) en changeant 1 variable d'env |
| **AO en entrée** | PDF uniquement | PDF **ou** texte brut |
| **Multi-CV** | Concaténation des textes, l'IA "trie" elle-même | Étape dédiée `Extract-CV` qui fusionne explicitement les versions, marque les conflits, retourne un `RawCV` auditable |
| **Anti-débordement zones simples** | Auto-fit + troncature avec "..." en dernier recours | **Auto-shrink Python déterministe** (jamais de "...", réduction de police figée dans le XML) |
| **Sélection des expériences** | Logique opaque dans le prompt LLM | Packer round-robin équilibré, traçable dans un journal, déterministe |
| **Anti-hallucination** | Préambule + flags `[[À compléter]]` | Préambule renforcé + **plan de bataille obligatoire en chain-of-thought + validation interne avant émission** |
| **Coût par run** | ~0,30 € (génération + 5 itérations vision) | ~0,10 € (3 appels au lieu de 1 mais zéro itération vision) |

### Ce que V2 a abandonné ou simplifié vs V1

| Fonctionnalité V1 | Statut V2 | Raison |
|---|---|---|
| **Boucle de raffinement esthétique** (Claude vision sur grille 5×20, score visuel, mutation de `render_styles.json`) | **Retirée** | Coût/temps élevé, instable, et la grille de critères Colombus est maintenant respectée dès le premier rendu grâce à la calibration packer/auto-shrink |
| **Génération Word `.docx` de correspondances** (4 sections A/B/C/D, logo Colombus) | **Retirée** | Le `AdaptedCV` JSON contient déjà toutes ces infos (couverture, alertes, mapping besoins) ; le `.docx` peut être régénéré séparément si besoin |
| **`config/render_styles.json` mutable** (22 paramètres modifiables manuellement ou par la boucle) | **Retirée** | Le template Golden Source v2 est figé, plus de besoin de muter les styles |
| **Logo Colombus dans en-tête docx** | **Retiré** (avec le docx) | — |
| **Conversion PPTX→PDF via LibreOffice** | **Retirée** | Plus nécessaire sans la boucle vision |

Si tu veux récupérer une de ces features en V2 (notamment le `.docx` de correspondances), c'est facile à brancher : il suffit de réutiliser `correspondances_word.py` de la V1 en l'alimentant avec l'`AdaptedCV` v2.

### Ce qui reste pareil

- **Rendu PPTX local** via `python-pptx` (V1 l'avait depuis Phase 3, Carbone.io retiré dans les deux versions)
- **Template Golden Source Colombus** (V1 utilisait l'ancien template, V2 utilise la v2 qui a une grille 3×3 de compétences au lieu de 2 colonnes)
- **Multi-versions CV** supporté
- **Anti-hallucination** strict avec flags `[[À compléter]]` / `[[À arbitrer]]`
- **CLI + API HTTP** disponibles
- **Pydantic strict** (`extra='forbid'`) partout

---

## Architecture en deux blocs

```
                ┌──────────── BLOC 1 — ANALYSE ─────────────┐
                │                                            │
 PDFs (CVs)  →  │  Extract-Brief    ┐                        │   AdaptedCV
 PDF / texte    │                   ├──→ Match + Reformulate │   (JSON
 (AO)        →  │  Extract-CV       ┘                        │    structuré)
                │  (en parallèle)                            │
                └────────────────────────────────────────────┘
                                                       │
                                                       ▼
                                          ┌── BLOC 2 — RENDERING ──┐
                                          │                         │
                                          │   Packer round-robin    │  →  PPTX
                                          │   + Auto-shrink         │   1 page
                                          │   + Template Colombus   │
                                          │                         │
                                          └─────────────────────────┘
```

Les deux blocs ne se parlent qu'à travers le modèle `AdaptedCV` (Pydantic strict). Tu peux remplacer n'importe quel bloc sans toucher à l'autre — par exemple ajouter une étape de raffinement esthétique en post-rendering, ou remplacer le packer par un autre algorithme.

Le détail de conception complet est dans l'historique git (la V1 et son `plan.md` ont été retirés du repo lors du cleanup ; on les retrouve sur la branche [`feature/nouvelle-archi-2026-05-06`](https://github.com/Colombus-Consulting/agent-cv/tree/feature/nouvelle-archi-2026-05-06)).

---

## Lancer la V2

### Installation

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Configurer les clés API
cp .env.example .env
# Éditer .env :
#   LLM_MODEL=anthropic/claude-sonnet-5   (ou openai/gpt-5.4-mini)
#   ANTHROPIC_API_KEY=sk-ant-...          (ou OPENAI_API_KEY=sk-...)
```

### Utilisation CLI (ligne de commande, en local)

```bash
# AO en PDF
python -m src.cli --cvs input/cv-test1.pdf input/cv-test2.pdf --ao input/ao-test.pdf

# AO en texte brut
python -m src.cli --cvs input/cv.pdf --ao-text "Mission Enedis : pilotage SI distribution..."

# Avec sauvegarde du JSON intermédiaire pour audit
python -m src.cli --cvs input/cv.pdf --ao input/ao.pdf --output cv-final.pptx --debug-json adapted.json
```

### Utilisation API (pour intégration Polaris / site web Colombus)

```bash
python -m src.server
# Serveur démarre sur http://localhost:8000
```

| Endpoint | Description |
|---|---|
| `GET /health` | Vérifie que le serveur est en ligne |
| `POST /generate` | Multipart (`cvs[]` + `ao_file` ou `ao_text`) → JSON avec `adapted_cv` + `pptx_base64` |
| `POST /generate/pptx` | Idem mais retourne directement le fichier PPTX binaire (téléchargement direct) |
| `POST /jobs` + `GET /jobs/{id}` | Mode **asynchrone** (pour Polaris) : soumission d'un job, polling du résultat, callback |

---

## Tests

```bash
# Tests rapides (mockés, ~1 min, 0 cent)
pytest --ignore=tests/test_pipeline_live.py

# Test bout-en-bout avec vrais appels LLM (~0,10 €, ~1 min 30)
pytest -m live -v -s
```

**État** : suite complète verte couvrant le schéma, le parsing PDF/texte/bytes, chaque étape du pipeline, le packer (avec 8 tests-oracle qui détectent automatiquement le sous-remplissage ou le débordement), l'auto-shrink, le rendu PPTX bout-en-bout, l'API (sync + async pour Polaris) et la CLI.

---

## Visualiser le comportement du packer

Un script génère 5 PPTX de validation avec des densités de contenu variables :

```bash
python scripts/validate_packer_visual.py
```

Sortie dans `output/packer_validation/` : 5 fichiers de `01_light.pptx` (peu de contenu) à `05_extreme.pptx` (stress test). Utile pour vérifier visuellement après tout changement de calibration.

---

## Structure du dossier

```
agent_cv/
├── src/
│   ├── analysis/              # BLOC 1 — pipeline LLM
│   │   ├── pipeline/          #   Extract-Brief, Extract-CV, Match+Reformulate
│   │   ├── prompts/           #   prompts .md (chargés au runtime)
│   │   ├── llm_client.py      #   wrapper litellm multi-provider
│   │   └── parsing.py         #   extraction PDF/texte
│   ├── rendering/             # BLOC 2 — du modèle au PPTX
│   │   ├── packer.py          #   sélection round-robin équilibrée
│   │   ├── auto_shrink.py     #   réduction de police déterministe
│   │   ├── pptx_renderer.py   #   injection dans le template Golden Source
│   │   └── layout_budget.py   #   calibration de la zone expériences
│   ├── schemas.py             # tous les modèles Pydantic
│   ├── cli.py                 # interface ligne de commande
│   └── server.py              # API FastAPI (sync + async pour Polaris)
├── tests/                     # suite mockée + 1 live
├── golden_set/                # jeu de 12 cas synthétiques (CV+AO) + ground truth
├── assets/                    # template PPTX Golden Source v2 + polices Arial Narrow
├── input/                     # CV et AO de référence (Diane + Enedis)
├── scripts/                   # validation visuelle du packer, outillage golden set
├── Dockerfile                 # image Python 3.13-slim pour Railway
├── railway.json               # config de déploiement Railway
├── DEPLOY_PLAN.md             # plan de mise en production sur Polaris
└── README.md                  # ce fichier
```

---

## Reste à faire avant mise en service

Voir [`DEPLOY_PLAN.md`](DEPLOY_PLAN.md) pour le plan complet :

- Déploiement Railway de l'agent_cv (branche `main`, auto-deploy)
- Intégration côté backend Polaris (Étape 3)
- Page React `/tools/agent-cv` (Étape 4)
- Déploiement Polaris (Étape 6)
- Tests bout-en-bout avec Diane + 2-3 testeurs (Étape 7)
- *(Optionnel)* Réintégrer la génération Word `.docx` de correspondances en branchant l'ancien module sur l'`AdaptedCV` v2

---

## Contact

- Diane Maurin — Colombus Consulting

> Ce CV est généré par IA. Il doit être relu par le consultant concerné avant tout envoi externe.
