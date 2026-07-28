# Cahier des charges — Application de suivi des achats et stocks théoriques

> Document destiné à être fourni tel quel à Claude Code comme spécification de développement.
> Écris le code en suivant ce document. Ne prends pas d'initiative sur les points marqués **[DÉCIDÉ]**.
> Les points marqués **[À CONFIRMER]** doivent être posés en question à l'utilisateur avant implémentation.

---

## 1. Contexte et objectif

Un établissement (salle de sport / studio géré avec Bsport) achète des marchandises auprès d'une dizaine de fournisseurs et reçoit leurs factures en PDF. Aujourd'hui, aucune saisie du détail des achats n'est faite : il est impossible de reconstituer les entrées en stock.

L'application doit :

1. Recevoir les factures fournisseurs en PDF et en extraire automatiquement l'en-tête et les lignes d'articles.
2. Rattacher chaque référence fournisseur à une référence interne via un référentiel importé depuis Excel.
3. Produire deux exports Excel : la liste des factures (rapprochement comptable) et le détail des achats par article (calcul des entrées en stock).

Le calcul du stock théorique (entrées − ventes) est fait **hors application**, dans Excel, à partir de l'export. L'application ne gère que les entrées.

### Utilisateur

Un seul utilisateur métier, non technique. L'ergonomie doit privilégier le nombre minimal de clics : déposer des PDF, ne s'occuper que de ce qui pose problème, exporter.

---

## 2. Périmètre

### Dans le périmètre (v1)

- Dépôt de PDF de factures et d'avoirs fournisseurs (unitaire ou multiple).
- Extraction automatique en-tête + lignes.
- Import d'un fichier Excel de correspondance références fournisseur ↔ références internes.
- Détection des doublons.
- Écran de vérification/correction déclenché uniquement en cas d'anomalie.
- File d'attente des références fournisseur non mappées, avec application rétroactive du mapping.
- Export Excel à deux onglets, filtrable par période et fournisseur.

### Hors périmètre (v1)

- Aucune intégration Bsport, aucune reprise des ventes. **[DÉCIDÉ]**
- Aucune authentification, aucune gestion d'utilisateurs, aucun rôle. Le serveur est sur un réseau interne déjà protégé. **[DÉCIDÉ]**
- Pas de gestion des mouvements de stock, inventaires, ni valorisation dans l'application.
- Pas de rapprochement bancaire ni d'export comptable normé (FEC, etc.).
- Pas de gestion multi-établissement ni multi-devise (le champ devise est stocké mais l'application suppose EUR).

---

## 3. Contraintes techniques

| Élément | Choix | Statut |
|---|---|---|
| Langage | Python 3.12 | **[DÉCIDÉ]** |
| Framework web | FastAPI | **[DÉCIDÉ]** |
| Base de données | SQLite (fichier unique) | **[DÉCIDÉ]** |
| ORM | SQLAlchemy 2.x + Alembic pour les migrations | recommandé |
| Interface | HTML server-rendered (Jinja2) + HTMX pour l'interactivité, CSS minimal (Pico.css ou équivalent en CDN local). Pas de build front, pas de npm. | **[DÉCIDÉ]** |
| Extraction PDF texte | `pdfplumber` | **[DÉCIDÉ]** |
| Rendu image des scans | `pypdfium2` (pas de dépendance système poppler) | recommandé |
| Structuration | API Anthropic, modèle `claude-sonnet-5` | **[DÉCIDÉ]** |
| Génération Excel | `openpyxl` | recommandé |
| Validation des données | Pydantic v2 | recommandé |
| Déploiement | Un seul conteneur Docker, sur serveur interne | **[DÉCIDÉ]** |

### Volume attendu

Moins de 20 factures par mois, moins de 10 fournisseurs. Aucun besoin de traitement asynchrone, de worker, ni de file de tâches : le traitement d'un PDF peut être synchrone (quelques secondes). Prévoir simplement une barre de progression côté navigateur pour un dépôt multiple.

### Persistance

Tout ce qui doit survivre au redémarrage du conteneur est sous `/data` :

```
/data
  app.db            # base SQLite
  pdfs/             # PDF originaux, nommés <invoice_id>.pdf
  exports/          # exports générés (purgeables)
```

Un unique volume Docker monté sur `/data`. Une sauvegarde = copie de ce répertoire.

### Configuration (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(vide)* | Si absente, l'application démarre et fonctionne, mais les factures scannées et les échecs d'extraction native basculent directement en saisie manuelle. |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Modèle utilisé pour la structuration. |
| `DATA_DIR` | `/data` | Racine de persistance. |
| `TOLERANCE_TOTAL` | `0.02` | Écart en euros toléré entre la somme des lignes et le total HT de la facture. |
| `TZ` | `Europe/Paris` | |

---

## 4. Modèle de données

### Principe fondamental à respecter

**La référence interne n'est jamais copiée dans les lignes de facture.** Elle est résolue par jointure sur la table `mappings` au moment de l'affichage et de l'export. C'est ce qui permet qu'un mapping créé aujourd'hui s'applique rétroactivement à toutes les factures déjà importées, sans retraitement. **[DÉCIDÉ]**

### Schéma

```sql
CREATE TABLE suppliers (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,          -- libellé affiché, éditable
    normalized_name   TEXT NOT NULL UNIQUE,   -- clé de dédoublonnage : minuscules, sans accents,
                                              -- sans ponctuation, sans forme juridique (SAS, SARL, SA...)
    created_at        TEXT NOT NULL
);

CREATE TABLE supplier_aliases (
    id                INTEGER PRIMARY KEY,
    supplier_id       INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    normalized_alias  TEXT NOT NULL UNIQUE    -- autres graphies rencontrées sur les factures
);

CREATE TABLE invoices (
    id                INTEGER PRIMARY KEY,
    supplier_id       INTEGER REFERENCES suppliers(id),
    document_type     TEXT NOT NULL,          -- 'INVOICE' | 'CREDIT_NOTE'
    invoice_number    TEXT,
    invoice_date      TEXT,                   -- ISO 'YYYY-MM-DD'
    currency          TEXT NOT NULL DEFAULT 'EUR',
    total_ht          REAL,                   -- signé : négatif pour un avoir
    total_vat         REAL,
    total_ttc         REAL,
    status            TEXT NOT NULL,          -- 'NEEDS_REVIEW' | 'VALIDATED'
    extraction_method TEXT NOT NULL,          -- 'NATIVE_LLM' | 'VISION_LLM' | 'NATIVE_THEN_VISION' | 'MANUAL'
    doc_class         TEXT,                   -- 'TEXTE' | 'SCAN' | 'MIXTE' (cf. §5.1.a)
    raw_diagnostics   TEXT,                   -- JSON : indicateurs de classification + trace des tentatives
    source_filename   TEXT NOT NULL,
    file_hash         TEXT NOT NULL,          -- SHA-256 du PDF
    stored_path       TEXT NOT NULL,
    anomalies         TEXT,                   -- JSON : liste de codes d'anomalie (cf. §6.3)
    notes             TEXT,
    created_at        TEXT NOT NULL,
    validated_at      TEXT
);

-- Anti-doublon métier : le même document ne peut pas entrer deux fois,
-- même s'il a été rescanné ou renommé.
CREATE UNIQUE INDEX ux_invoice_business_key
    ON invoices (supplier_id, invoice_number, document_type)
    WHERE invoice_number IS NOT NULL;

CREATE INDEX ix_invoices_hash ON invoices (file_hash);
CREATE INDEX ix_invoices_date ON invoices (invoice_date);

CREATE TABLE invoice_lines (
    id                INTEGER PRIMARY KEY,
    invoice_id        INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    line_no           INTEGER NOT NULL,
    line_type         TEXT NOT NULL,          -- 'ARTICLE' | 'CHARGE'
    charge_kind       TEXT,                   -- si CHARGE : 'SHIPPING'|'ECO_TAX'|'DISCOUNT'|'DEPOSIT'|'OTHER'
    supplier_ref      TEXT,
    supplier_label    TEXT,
    quantity          REAL,                   -- signée : négative pour un avoir
    unit_price_net    REAL,                   -- PU net, remises de ligne déduites
    line_total_net    REAL,                   -- signé
    vat_rate          REAL,
    raw               TEXT                    -- JSON brut renvoyé par l'extraction, pour audit
);

CREATE INDEX ix_lines_ref ON invoice_lines (supplier_ref);

CREATE TABLE mappings (
    id                INTEGER PRIMARY KEY,
    supplier_id       INTEGER REFERENCES suppliers(id),   -- NULL = mapping global tous fournisseurs
    supplier_ref      TEXT NOT NULL,
    supplier_label    TEXT,                   -- libellé fournisseur de référence (informatif)
    our_ref           TEXT NOT NULL,
    our_label         TEXT NOT NULL,
    ean               TEXT,                   -- seule source du code-barres
    active            INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE UNIQUE INDEX ux_mapping ON mappings (IFNULL(supplier_id, -1), supplier_ref);

CREATE TABLE import_log (
    id                INTEGER PRIMARY KEY,
    kind              TEXT NOT NULL,          -- 'INVOICE' | 'MAPPING'
    filename          TEXT NOT NULL,
    file_hash         TEXT,
    invoice_id        INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
    outcome           TEXT NOT NULL,          -- 'CREATED'|'REJECTED_DUPLICATE'|'ERROR'|'MAPPINGS_UPSERTED'
    message           TEXT,
    created_at        TEXT NOT NULL
);
```

### Résolution du mapping

Pour une ligne donnée, chercher dans l'ordre :

1. `mappings` où `supplier_id = <fournisseur de la facture>` et `supplier_ref = <ref>` et `active = 1`
2. sinon `mappings` où `supplier_id IS NULL` et `supplier_ref = <ref>` et `active = 1`
3. sinon : non mappée.

La comparaison de `supplier_ref` se fait sur une forme normalisée (majuscules, espaces et tirets supprimés) pour absorber les variations de saisie. Stocker la référence telle qu'elle figure sur la facture, mais comparer en normalisé — prévoir une colonne calculée ou un index sur expression.

---

## 5. Pipeline d'extraction

**Contexte confirmé : le parc de factures mélange des PDF natifs (couche texte propre) et des scans.** Les deux modes sont donc de première classe, aucun n'est un cas dégradé. Le point critique n'est pas de choisir le bon mode en entrée — l'heuristique se trompera parfois — mais de **détecter qu'on s'est trompé et de réessayer automatiquement**. C'est la règle §5.1.b, à ne pas omettre.

### 5.1 Enchaînement

```
PDF déposé
  ├─ calcul du SHA-256, contrôle de doublon fichier (avant tout appel API)
  ├─ pdfplumber : extraction du texte + des tables, page par page
  ├─ classification du document (§5.1.a) ──► TEXTE | SCAN | MIXTE
  │
  ├─ TENTATIVE 1
  │     ├─ TEXTE          ──► MODE A  (texte → Claude)
  │     └─ SCAN | MIXTE   ──► MODE B  (images → Claude vision)
  │
  ├─ validation Pydantic + contrôles arithmétiques (§5.4)
  │
  ├─ TENTATIVE 2 — escalade automatique (§5.1.b)
  │     si tentative 1 en MODE A et résultat jugé non fiable
  │        ──► rejouer en MODE B, conserver le meilleur des deux résultats
  │
  ├─ détection des doublons métier (§6.1)
  ├─ détection des anomalies (§6.3)
  └─ statut VALIDATED (aucune anomalie) ou NEEDS_REVIEW
```

#### 5.1.a Classification du document

Ne **pas** se contenter d'un seuil sur le nombre de caractères : certains scanners incorporent une couche OCR de mauvaise qualité, ce qui produit un PDF qui *semble* natif mais dont le texte est inexploitable. C'est le piège principal de ce projet.

Calculer, **page par page**, les indicateurs suivants via `pdfplumber` :

| Indicateur | Comment | Seuil |
|---|---|---|
| Densité de texte | `len(page.extract_text() or "")` | < 150 caractères → page suspecte |
| Couverture image | Somme des aires de `page.images` / aire de la page | > 0,80 → page probablement scannée |
| Ratio alphanumérique | Part de caractères `[A-Za-z0-9À-ÿ ,.\-/€%]` dans le texte | < 0,85 → couche OCR dégradée |
| Présence de montants | Nombre de motifs `\d+[ .,]\d{2}` détectés | 0 sur une page de facture → suspect |
| Mots courts isolés | Part de « mots » d'un seul caractère | > 0,30 → OCR dégradée |

Classification du document :

- **TEXTE** : aucune page suspecte.
- **SCAN** : toutes les pages suspectes.
- **MIXTE** : au moins une page suspecte et une page saine. Traiter **l'intégralité du document en MODE B** — ne pas mélanger les deux modes au sein d'une même facture, cela produit des lignes dupliquées ou manquantes.

Stocker le résultat de la classification et les indicateurs dans `invoices.raw_diagnostics` (nouvelle colonne JSON), pour pouvoir régler les seuils après quelques semaines d'usage réel.

#### 5.1.b Escalade automatique du mode texte vers le mode vision **[DÉCIDÉ]**

Après une tentative en MODE A, le résultat est jugé **non fiable** si l'une de ces conditions est vraie :

- aucune ligne extraite ;
- `total_ht` absent, ou `invoice_number` et `invoice_date` tous deux absents ;
- écart `|Σ lignes − total_ht| > TOLERANCE_TOTAL`.

Dans ce cas, rejouer automatiquement en MODE B **sans intervention de l'utilisateur**, puis conserver le résultat qui présente le plus petit écart entre la somme des lignes et le total HT (à égalité, préférer le MODE B). Renseigner `extraction_method = 'NATIVE_THEN_VISION'` et journaliser les deux tentatives.

Au volume annoncé (< 20 factures/mois), le surcoût d'une seconde tentative est de l'ordre de quelques centimes par mois. Il ne faut donc **jamais** renoncer à l'escalade pour des raisons de coût, ni la rendre optionnelle. Prévoir malgré tout un garde-fou : maximum 2 tentatives LLM par facture et par dépôt, pour qu'un PDF pathologique ne boucle pas.

#### 5.1.c MODE A — PDF avec couche texte fiable

Concaténer, page par page : le texte brut (`page.extract_text()`) puis les tables détectées (`page.extract_tables()`) sérialisées en TSV, en conservant l'ordre de lecture et en préfixant chaque page par `--- Page n ---`. Envoyer ce contenu à Claude en mode texte.

#### 5.1.d MODE B — PDF scanné ou mixte

- Rendu de chaque page en PNG via `pypdfium2`, **200 dpi**, converti en niveaux de gris (les factures scannées en couleur pèsent 3 à 4 fois plus pour aucun gain).
- Redimensionner pour que le plus grand côté ne dépasse pas 1 800 px — au-delà, l'image est rééchantillonnée côté API sans bénéfice, et la facture coûte plus cher.
- Envoyer toutes les pages dans **un seul appel** (une seule facture = un seul contexte), et non page par page : les totaux figurent en dernière page alors que les lignes commencent en première, le modèle a besoin de l'ensemble.
- Limite : **12 pages**. Au-delà, ne pas appeler l'API : créer la facture avec l'anomalie `A_TOO_MANY_PAGES` et proposer la saisie manuelle.
- **Pas de prétraitement d'image en v1** (pas de deskew, pas de binarisation, pas de Tesseract). Les modèles vision encaissent bien une numérisation de travers. N'ajouter un redressement (via Pillow) que si l'usage réel montre des échecs répétés sur des scans penchés.

#### 5.1.e Fonctions manuelles associées

Deux boutons sur l'écran de détail d'une facture, indispensables pour mettre au point l'extraction sur le parc réel :

- **« Ré-extraire »** : rejoue le pipeline complet sur le PDF déjà stocké, remplace les lignes, conserve l'identifiant et le journal. Une confirmation est demandée si la facture a été corrigée manuellement.
- **« Ré-extraire en mode vision »** : force le MODE B, quelle que soit la classification. Recours quand l'utilisateur voit que le résultat est mauvais alors que le PDF paraissait natif.

#### 5.1.f Sans clé API

Si `ANTHROPIC_API_KEY` est absente, créer la facture avec `extraction_method = 'MANUAL'`, statut `NEEDS_REVIEW`, zéro ligne, et afficher l'écran de saisie manuelle avec le PDF à côté.

### 5.2 Contrat de sortie de l'extraction

Imposer à Claude ce schéma JSON exact, via un prompt et un outil (tool use) avec `input_schema`. Utiliser le tool use plutôt qu'un parsing de texte libre.

```json
{
  "document_type": "INVOICE | CREDIT_NOTE",
  "supplier_name": "string",
  "invoice_number": "string | null",
  "invoice_date": "YYYY-MM-DD | null",
  "currency": "EUR",
  "total_ht": 0.0,
  "total_vat": 0.0,
  "total_ttc": 0.0,
  "lines": [
    {
      "line_type": "ARTICLE | CHARGE",
      "charge_kind": "SHIPPING | ECO_TAX | DISCOUNT | DEPOSIT | OTHER | null",
      "supplier_ref": "string | null",
      "supplier_label": "string",
      "quantity": 0.0,
      "unit_price_net": 0.0,
      "line_total_net": 0.0,
      "vat_rate": 0.0,
      "low_confidence": false
    }
  ],
  "page_count_documents": 1
}
```

`page_count_documents` : nombre de factures distinctes détectées dans le PDF (cf. §5.5). Vaut 1 dans l'immense majorité des cas.

### 5.3 Règles à inscrire dans le prompt d'extraction

À reprendre littéralement dans le prompt système :

- Répondre uniquement via l'outil, sans texte libre.
- Ne jamais inventer une valeur absente : mettre `null`.
- **Format français** : `1 234,56` vaut `1234.56`. Les espaces (y compris insécables) sont des séparateurs de milliers, la virgule est le séparateur décimal. Les dates `JJ/MM/AAAA` deviennent `AAAA-MM-JJ`.
- **`unit_price_net`** : prix unitaire net, remise de ligne déduite. Si la facture affiche un PU brut et un pourcentage de remise, calculer `PU_brut × (1 − remise%)` et n'renvoyer que ce résultat. Ne pas renvoyer le PU brut. **[DÉCIDÉ]**
- **`line_type`** : `ARTICLE` uniquement pour une marchandise physique achetée. Tout le reste est `CHARGE` : frais de port, participation aux frais, éco-participation / éco-contribution / DEEE, consigne / emballages consignés, remise globale de pied de facture, frais de dossier, escompte, arrondi. En cas de doute, choisir `CHARGE`.
- **Avoirs** : si le document est un avoir, une note de crédit ou un « credit note », alors `document_type = "CREDIT_NOTE"` et **toutes** les quantités, `line_total_net` et totaux sont **négatifs**, quelle que soit la façon dont ils sont imprimés sur le document. **[DÉCIDÉ]**
- Une ligne de commentaire, un sous-total intermédiaire ou un rappel de commande ne sont pas des lignes : les omettre.
- **Spécifique au mode vision (scans)** : le document peut être penché, taché, ou comporter des annotations manuscrites (tampon « payé », coche, mention marginale). Ignorer toute annotation manuscrite et ne retenir que le contenu imprimé. Si un caractère est illisible dans une référence, renvoyer la référence telle que lue en la signalant : ajouter le champ `"low_confidence": true` sur la ligne concernée. Ne jamais deviner un chiffre de montant ou de quantité : si le doute porte sur un nombre, mettre `null` plutôt qu'une valeur approchée. Une valeur nulle déclenche une vérification humaine, une valeur fausse passe inaperçue.
- Si un article apparaît sur plusieurs lignes (colisage détaillé), conserver les lignes séparées telles quelles.
- `total_ht`, `total_vat`, `total_ttc` proviennent du pied de facture, pas d'un recalcul.

### 5.4 Contrôles automatiques après extraction

- Recalculer `line_total_net` si absent : `quantity × unit_price_net`, arrondi à 2 décimales.
- Recalculer `unit_price_net` si absent et quantité non nulle : `line_total_net / quantity`.
- Vérifier `|total_ht − total_vat − ... |` : contrôler la cohérence `total_ht + total_vat ≈ total_ttc` (tolérance `TOLERANCE_TOTAL`) ; incohérence → anomalie `A_TOTALS_INCONSISTENT`, non bloquante mais signalée.
- Forcer les signes en fonction de `document_type`.

### 5.5 Plusieurs factures dans un même PDF

Risque propre au flux scanné : l'utilisateur passe une pile de factures au chargeur automatique et obtient un seul PDF de 8 pages contenant 4 factures différentes. Sans traitement, l'application enregistrerait une facture unique aux totaux aberrants.

Traitement v1, volontairement minimal : demander au modèle de renseigner `page_count_documents`. Si la valeur est supérieure à 1, **ne rien enregistrer** ; afficher un message explicite (« Ce PDF semble contenir N factures distinctes — merci de le découper et de redéposer les fichiers séparément ») et journaliser en `outcome = 'ERROR'`. Le découpage automatique est hors périmètre v1 ; il pourra être ajouté ensuite si le cas se présente souvent.

Cette détection s'ajoute au filet de sécurité `A_TOTAL_MISMATCH`, qui attraperait de toute façon l'incohérence.

---

## 6. Règles métier

### 6.1 Doublons **[DÉCIDÉ]**

Deux mécanismes, dans cet ordre :

**a) Clé métier — bloquant.** L'unicité `(supplier_id, invoice_number, document_type)` est garantie en base. Si l'insertion viole cette contrainte, l'import est **refusé** : aucune facture créée, message explicite à l'écran (« Cette facture n° X du fournisseur Y a déjà été importée le JJ/MM/AAAA — [voir la facture existante] ») et entrée `import_log` avec `outcome = 'REJECTED_DUPLICATE'`.

Le hash SHA-256 est calculé et stocké systématiquement. S'il correspond à une facture existante, afficher le même refus avec le motif « fichier identique déjà importé ». Ce contrôle passe avant l'appel au LLM, pour ne pas consommer d'API inutilement.

**b) Similarité — alerte non bloquante.** À l'issue de l'extraction, si une autre facture existe avec le même fournisseur, la même `invoice_date` et un `total_ttc` identique à 0,01 € près, mais un numéro différent (ou absent) : créer la facture avec l'anomalie `A_POSSIBLE_DUPLICATE`, statut `NEEDS_REVIEW`. L'écran de vérification affiche un bandeau avec un lien vers la facture soupçonnée et deux boutons : « Ce n'est pas un doublon, valider » / « Supprimer cet import ».

**Numéro de facture absent.** Si l'extraction ne trouve pas de numéro, la contrainte d'unicité ne s'applique pas (index partiel). Anomalie `A_MISSING_FIELD` → l'utilisateur saisit le numéro dans l'écran de vérification ; la contrainte est alors évaluée à l'enregistrement, avec message clair si conflit.

**Annulation.** Toute facture est supprimable depuis l'interface (confirmation requise). La suppression retire les lignes en cascade, conserve le PDF 30 jours dans `/data/pdfs/deleted/`, et journalise l'opération.

### 6.2 Mapping des références **[DÉCIDÉ]**

- Une référence fournisseur inconnue **ne bloque jamais** l'enregistrement d'une facture. La ligne est conservée avec sa référence et son libellé fournisseur ; les colonnes internes restent vides.
- Elle alimente un écran **« Références à mapper »** listant, par fournisseur, chaque `supplier_ref` non résolue avec : le libellé fournisseur, le nombre de lignes concernées, la première et la dernière date d'achat, la quantité cumulée. Deux champs de saisie (notre référence, notre libellé) + un champ EAN, et un bouton « Enregistrer » qui crée le mapping.
- La création d'un mapping est **rétroactive** par construction (résolution par jointure, cf. §4). Après création, l'anomalie `A_UNMAPPED_REF` doit être recalculée sur les factures concernées : si c'était la seule anomalie, la facture repasse automatiquement en `VALIDATED`.
- Correspondance **1 pour 1** : la quantité facturée est directement la quantité en stock. Pas de coefficient de conversion, pas de colisage. **[DÉCIDÉ]**
- Le **code-barres provient exclusivement du fichier de correspondance**, jamais de la facture. Ne pas chercher d'EAN dans le PDF. **[DÉCIDÉ]**

### 6.3 Anomalies et déclenchement de la vérification **[DÉCIDÉ]**

Une facture est enregistrée **automatiquement en `VALIDATED`** si aucune anomalie n'est détectée. Sinon elle passe en `NEEDS_REVIEW` et apparaît dans la file « À vérifier ».

| Code | Condition | Effet |
|---|---|---|
| `A_TOTAL_MISMATCH` | `\|Σ(line_total_net de toutes les lignes, ARTICLE + CHARGE) − total_ht\| > TOLERANCE_TOTAL` | Vérification |
| `A_UNMAPPED_REF` | Au moins une ligne `ARTICLE` dont la référence n'est pas résolue | Vérification |
| `A_MISSING_FIELD` | `supplier_name`, `invoice_number`, `invoice_date` ou `total_ht` absent | Vérification |
| `A_BAD_LINE` | Une ligne `ARTICLE` avec quantité ou PU nul, absent ou non numérique | Vérification |
| `A_POSSIBLE_DUPLICATE` | Cf. §6.1.b | Vérification |
| `A_TOTALS_INCONSISTENT` | `total_ht + total_vat ≉ total_ttc` | Vérification |
| `A_NO_LINES` | Aucune ligne extraite | Vérification |
| `A_LOW_CONFIDENCE` | Au moins une ligne marquée `low_confidence` par l'extraction (scan peu lisible) | Vérification |
| `A_TOO_MANY_PAGES` | PDF de plus de 12 pages classé SCAN ou MIXTE | Vérification, saisie manuelle |
| `A_NEW_SUPPLIER` | Fournisseur jamais vu | Information seule, ne déclenche pas la vérification |

Le contrôle `A_TOTAL_MISMATCH` est le garde-fou principal : c'est lui qui garantit que le rapprochement comptable reste juste malgré l'exclusion des lignes `CHARGE` de l'export détaillé.

Une facture en `NEEDS_REVIEW` reste **incluse** dans les exports, avec sa colonne « Statut » à « À vérifier », afin qu'aucun achat ne disparaisse silencieusement.

### 6.4 Traitement des lignes hors articles **[DÉCIDÉ]**

Les lignes `CHARGE` sont enregistrées en base et **comptent dans le contrôle du total HT**, mais sont **exclues de l'onglet « Détail achats »**. Elles restent consultables dans le détail d'une facture à l'écran, et sont résumées dans l'onglet « Factures » par une colonne « dont frais et remises ».

### 6.5 Fournisseurs

Créer automatiquement le fournisseur à la première rencontre, à partir de `normalized_name`. Fournir un écran de gestion permettant de renommer un fournisseur et de **fusionner deux fournisseurs** (le fournisseur absorbé devient un alias, ses factures et mappings sont réaffectés) — indispensable quand une même enseigne apparaît sous deux graphies.

---

## 7. Fichier Excel de correspondance

### Format attendu à l'import

Première feuille du classeur, une ligne d'en-tête, noms de colonnes reconnus sans distinction de casse ni d'accents :

| Colonne | Obligatoire | Contenu |
|---|---|---|
| `reference_fournisseur` | oui | Référence telle qu'elle apparaît sur les factures |
| `fournisseur` | non | Nom du fournisseur. Si vide, le mapping est global (tous fournisseurs). |
| `libelle_fournisseur` | non | Informatif |
| `notre_reference` | oui | Référence interne |
| `notre_libelle` | oui | Libellé interne |
| `code_barre` | non | EAN — **seule source du code-barres dans l'application** |

Accepter aussi les variantes `ref_fournisseur`, `référence fournisseur`, `notre_ref`, `ean`, `code-barres`. Fournir un bouton « Télécharger le modèle » générant un .xlsx vide avec les bons en-têtes.

### Comportement à l'import **[DÉCIDÉ]**

- **Upsert** sur la clé `(supplier_id, reference_fournisseur normalisée)` : une ligne existante est mise à jour, une ligne nouvelle est créée. Un import ne supprime jamais de mapping existant.
- Le nom de fournisseur est rapproché des fournisseurs connus par `normalized_name` et par les alias ; s'il ne correspond à rien, le fournisseur est créé.
- Écran de compte rendu avant validation définitive : *n* créations, *n* mises à jour (avec l'ancienne et la nouvelle valeur), *n* lignes ignorées et pourquoi. Bouton « Appliquer » / « Annuler ».
- Après application, recalculer les anomalies `A_UNMAPPED_REF` de toutes les factures concernées (cf. §6.2).
- Un export « référentiel actuel » au même format doit être disponible, pour que l'utilisateur puisse repartir du fichier existant.

---

## 8. Interface

Six écrans, navigation par un menu horizontal simple.

### 8.1 Accueil / tableau de bord

- Zone de dépôt glisser-déposer, multi-fichiers, PDF uniquement.
- Pendant le traitement : une ligne par fichier avec son statut (en cours / importé / à vérifier / refusé doublon / erreur).
- Trois compteurs cliquables : « Factures à vérifier », « Références à mapper », « Factures ce mois ».

### 8.2 Liste des factures

Tableau filtrable : période (du / au), fournisseur, statut, type (facture / avoir). Colonnes : date, fournisseur, type, n°, total HT, total TTC, nb lignes articles, statut, actions (ouvrir, télécharger le PDF, supprimer). Tri par colonne. Bouton « Exporter la sélection ».

### 8.3 Vérification / détail d'une facture

Écran en deux colonnes :

- **Gauche** : le PDF original affiché dans un `<iframe>` (visionneuse native du navigateur), pleine hauteur.
- **Droite** :
  - Bandeau rouge listant les anomalies en clair, avec pour chacune l'action attendue.
  - Champs d'en-tête éditables : fournisseur (liste déroulante + création), type de document, n°, date, total HT, TVA, TTC.
  - Tableau des lignes éditable en place : type (ARTICLE/CHARGE), référence fournisseur, libellé fournisseur, quantité, PU net, montant ligne, référence interne résolue (lecture seule, avec un lien « mapper » si vide). Ajout et suppression de ligne possibles.
  - **Compteur permanent en pied de tableau** : `Σ lignes = X,XX € | Total HT facture = Y,YY € | Écart = Z,ZZ €`, l'écart passant au vert dès qu'il est dans la tolérance. Recalcul à chaque frappe.
  - Les lignes marquées `low_confidence` (scan peu lisible) sont signalées par une bordure orange, pour concentrer la relecture là où le risque est réel.
  - Sous les boutons, une mention discrète du mode d'extraction utilisé et de la classification du document (ex. « Extrait en mode vision — document classé SCAN »), utile pour comprendre un mauvais résultat.
  - Boutons : « Enregistrer », « Valider » (grisé si `A_TOTAL_MISMATCH` ou `A_MISSING_FIELD` subsiste), « Ré-extraire », « Ré-extraire en mode vision », « Supprimer ».

Note : `A_UNMAPPED_REF` **ne doit pas empêcher la validation** — le mapping peut être fait plus tard.

### 8.4 Références à mapper

Cf. §6.2. Regroupement par fournisseur, tri par quantité cumulée décroissante (traiter d'abord ce qui pèse). Saisie en ligne, enregistrement sans rechargement de page.

### 8.5 Référentiel

Liste des mappings, recherche, édition et désactivation en ligne. Boutons « Importer un Excel », « Télécharger le modèle », « Exporter le référentiel ».

### 8.6 Export

Sélection de la période et, optionnellement, d'un ou plusieurs fournisseurs et du statut. Bouton « Générer le fichier Excel ».

### 8.7 Journal (secondaire)

Contenu de `import_log`, consultable, pour retracer ce qui a été importé, refusé ou supprimé.

---

## 9. Export Excel **[DÉCIDÉ]**

Un seul fichier `.xlsx`, nommé `achats_<AAAAMMJJ>_<AAAAMMJJ>.xlsx`, contenant deux onglets. Sur chaque onglet : ligne d'en-tête figée, filtre automatique activé, largeurs de colonnes ajustées, montants au format `# ##0,00 €`, dates au format `JJ/MM/AAAA`.

### Onglet 1 — « Factures »

Rapprochement comptable. Une ligne par facture.

| # | Colonne |
|---|---|
| 1 | Date |
| 2 | Fournisseur |
| 3 | Type (Facture / Avoir) |
| 4 | N° facture |
| 5 | Total HT |
| 6 | Total TVA |
| 7 | Total TTC |
| 8 | dont frais et remises (Σ des lignes CHARGE) |
| 9 | Nb lignes articles |
| 10 | Statut (Validée / À vérifier) |
| 11 | Fichier source |

Ligne de totaux en pied (colonnes 5 à 8).

### Onglet 2 — « Détail achats »

Une ligne par ligne d'article. **Les lignes `CHARGE` sont exclues.** Ordre des colonnes imposé :

| # | Colonne | Source |
|---|---|---|
| 1 | Date | `invoices.invoice_date` |
| 2 | Fournisseur | `suppliers.name` |
| 3 | Référence fournisseur | `invoice_lines.supplier_ref` |
| 4 | Code barre | `mappings.ean` — vide si non mappé |
| 5 | Libellé fournisseur | `invoice_lines.supplier_label` |
| 6 | Notre référence | `mappings.our_ref` — vide si non mappé |
| 7 | Notre libellé | `mappings.our_label` — vide si non mappé |
| 8 | Quantité achetée | `invoice_lines.quantity` (négative pour un avoir) |
| 9 | Prix unitaire d'achat | `invoice_lines.unit_price_net` |
| 10 | Montant ligne | `invoice_lines.line_total_net` |
| 11 | N° facture | `invoices.invoice_number` |
| 12 | Statut facture | Validée / À vérifier |

Tri par date croissante, puis fournisseur, puis n° de facture, puis n° de ligne.

Les lignes non mappées sont surlignées en jaune clair, pour être repérables d'un coup d'œil dans Excel.

---

## 10. Docker

`Dockerfile` unique, base `python:3.12-slim`, `uvicorn` en `CMD`, port 8000 exposé. Aucune dépendance système lourde (éviter poppler, tesseract, wkhtmltopdf).

`docker-compose.yml` :

```yaml
services:
  achats:
    build: .
    restart: unless-stopped
    ports: ["8000:8000"]
    volumes: ["./data:/data"]
    environment:
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      TZ: Europe/Paris
```

Migrations Alembic appliquées automatiquement au démarrage. Un endpoint `/health` renvoyant `{"status":"ok"}`.

---

## 11. Tests attendus

- **Unitaires** : parsing des nombres et dates au format français ; normalisation des noms de fournisseurs et des références ; calcul et détection de chaque code d'anomalie ; inversion des signes sur les avoirs ; résolution du mapping (spécifique > global > absent).
- **Intégration** : import d'un même PDF deux fois → refus ; import de deux PDF différents portant le même n° de facture → refus ; création d'un mapping → disparition rétroactive de `A_UNMAPPED_REF` et passage automatique en `VALIDATED` ; import d'un Excel de correspondance en upsert.
- **Export** : à partir d'un jeu de données de test, vérifier que la somme de la colonne « Montant ligne » de l'onglet 2 plus la colonne « dont frais et remises » de l'onglet 1 égale la somme des « Total HT ».
- **Classification et escalade** : vérifier qu'un PDF natif propre est classé TEXTE ; qu'un PDF sans couche texte est classé SCAN ; qu'un PDF portant une couche OCR dégradée (texte présent mais ratio alphanumérique faible) est bien classé SCAN et non TEXTE ; qu'un résultat MODE A sans lignes déclenche exactement une seconde tentative en MODE B ; qu'un PDF pathologique ne dépasse jamais 2 appels LLM.
- **Jeu de test** : générer 5 factures PDF synthétiques — une simple, une avec remises et frais de port, un avoir, une version *scannée* de la première (rendue en image puis réencapsulée en PDF, sans couche texte), et une variante de cette scannée avec une couche OCR volontairement bruitée. Ces deux dernières sont indispensables pour tester la classification sans dépendre de documents réels dans la CI.
- **Enregistrement des appels API** : mettre en place un mécanisme de rejeu hors ligne (réponses LLM enregistrées en fixtures JSON) pour que la suite de tests tourne sans clé API ni coût.

---

## 12. Plan de développement

Livrer par étapes, chacune testable :

1. **Socle** — squelette FastAPI, SQLAlchemy, migrations, Docker, `/health`, écran d'accueil vide.
2. **Référentiel** — modèle `mappings`, import/export Excel, écran de gestion, modèle téléchargeable. *Testable sans aucune facture.*
3. **Dépôt et extraction** — upload, hash, pdfplumber, classification TEXTE/SCAN/MIXTE, MODE A, MODE B, escalade automatique, appel Claude via tool use, création facture + lignes, journal. Écran liste des factures. *Les deux modes sont livrés ensemble : le parc mélange natifs et scans, livrer le seul mode texte ne permettrait pas de tester sur des documents réels.*
4. **Doublons et anomalies** — contraintes, détection, statuts, file « À vérifier ».
5. **Écran de vérification** — visionneuse PDF, édition des lignes, compteur d'écart, validation.
6. **File des références à mapper** — écran dédié, recalcul rétroactif.
7. **Export Excel** — les deux onglets, filtres, mise en forme.
8. **Finitions** — fusion de fournisseurs, suppression avec corbeille, journal, tests.

Après chaque étape, faire tourner l'application et vérifier le comportement avec de vraies factures avant de passer à la suivante. La qualité de l'extraction ne se juge que sur des documents réels : prévoir dès l'étape 3 un moyen simple de rejouer l'extraction d'une facture déjà importée (bouton « Ré-extraire ») pour itérer sur le prompt sans tout réimporter.

---

## 13. Points à confirmer avant de coder

**[À CONFIRMER]** — poser ces questions à l'utilisateur :

1. ~~Les factures reçues sont-elles des PDF texte ou des scans ?~~ **Répondu : les deux.** Les deux modes sont donc obligatoires dès l'étape 3, avec escalade automatique (§5.1.b). Question résiduelle : les scans proviennent-ils d'un scanner de bureau produisant une couche OCR, ou de photos / envois par e-mail sans OCR ? Cela permet de caler les seuils de §5.1.a dès le départ plutôt qu'après coup.
2. Existe-t-il déjà un fichier Excel de correspondance, même partiel ? Si oui, en récupérer les colonnes réelles pour caler le parseur d'import.
3. Faut-il conserver la TVA par ligne, ou le taux global de la facture suffit-il ?
4. Souhaite-t-on une durée de conservation des PDF (obligation légale : 10 ans en France pour les pièces comptables) et une sauvegarde automatique du répertoire `/data` ?
