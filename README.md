# inventaireOMP — Suivi des achats et stocks théoriques

Application de suivi des achats fournisseurs (extraction automatique de factures PDF, mapping des références, export Excel). Voir [cahier-des-charges-gestion-achats.md](cahier-des-charges-gestion-achats.md) pour la spécification complète.

## Développement local (sans Docker)

```bash
python -m venv .venv
.venv/Scripts/activate      # Windows
pip install -r requirements.txt
```

Créer un `.env` à partir de `.env.example`. En local (hors Docker), pointer `DATA_DIR` vers un dossier existant, par exemple :

```
DATA_DIR=./data
```

Lancer le serveur :

```bash
uvicorn app.main:app --reload
```

Les migrations Alembic s'appliquent automatiquement au démarrage. Application disponible sur http://127.0.0.1:8000, healthcheck sur `/health`.

## Tests

```bash
pytest
```

La suite tourne sans clé API : les tests du pipeline d'extraction simulent les réponses de Claude (monkeypatch), et les PDF de test (natifs, scannés, OCR dégradée) sont générés à la volée dans `tests/fixtures/pdf_builder.py` — aucun document réel n'est nécessaire ni committé.

## Docker

```bash
docker compose up --build
```

Variable d'environnement requise : `ANTHROPIC_API_KEY` (sinon l'application fonctionne en mode saisie manuelle uniquement, cf. §5.1.f du cahier des charges).

## Avancement (plan de développement §12)

- [x] Étape 1 — Socle FastAPI, SQLAlchemy, Alembic, Docker, `/health`, écran d'accueil vide
- [x] Étape 2 — Référentiel (mappings) : import/export Excel avec upsert normalisé, écran de gestion, édition/désactivation en ligne
- [x] Étape 3 — Dépôt et extraction PDF : classification TEXTE/SCAN/MIXTE, mode texte + mode vision, escalade automatique, tool use Claude, dropzone accueil, liste + détail facture, Ré-extraire
- [x] Étape 4 — Doublons et anomalies : clé métier + hash + similarité, 9 codes d'anomalie (§6.3), statut auto VALIDATED/NEEDS_REVIEW
- [x] Étape 5 — Écran de vérification : édition des lignes (ajout/suppression), compteur d'écart temps réel, bouton Valider (grisé si total incohérent ou champ manquant), bandeau doublon possible, suppression avec corbeille 30 jours (§6.1, avancée depuis l'étape 8)
- [x] Étape 6 — File des références à mapper : regroupement par fournisseur/référence normalisée, quantité cumulée, saisie en ligne sans rechargement (HTMX), recalcul rétroactif des factures concernées (passage automatique en Validée si c'était la seule anomalie)
- [x] Étape 7 — Export Excel : deux onglets (Factures / Détail achats), filtres période/fournisseurs/statut, en-têtes figées + filtre auto, lignes non mappées surlignées, ligne de totaux
- [x] Étape 8 — Finitions : fusion/renommage de fournisseurs, écran Journal, tests §11 complets (chaque code d'anomalie, résolution de mapping spécifique>global>absent, plafond à 2 appels LLM)

## Statut

Les 8 étapes du plan de développement sont terminées. Reste à valider avec de vraies factures (clé `ANTHROPIC_API_KEY` à ajouter dans `.env`) pour caler les seuils de classification et le prompt d'extraction sur le parc réel de documents.
