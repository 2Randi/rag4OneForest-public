# kg-builder — Constructeur du graphe de connaissances

Transforme le document DOCX de Lund (2018) en graphe RDF/SKOS conforme aux standards W3C.

## Pipeline

```
DOCX
 │
 ├─ [1] extractor/docx_extractor.py   Extraction arborescente titres + paragraphes
 ├─ [2] extractor/table_extractor.py  Extraction Table 3 (critères numériques)
 ├─ [3] cleaner/text_cleaner.py       Normalisation, détection langue, NER pays
 ├─ [4] builder/skos_builder.py       Construction graphe RDF/SKOS
 ├─ [5] builder/threshold_linker.py   Jointure seuils Table 3 ↔ concepts
 ├─ [6] builder/agrovoc_aligner.py    Alignement externe Agrovoc (skos:exactMatch)
 ├─ [7] validator/shacl_validator.py  Validation SHACL des contraintes SKOS
 └─ [8] serializer/ttl_serializer.py  Sérialisation Turtle + statistiques
```

## Modèle SKOS produit

```
ex:ForestDefinitionsScheme  (skos:ConceptScheme)
  │
  ├── ex:Forest             (skos:Concept, topConceptOf)  ←→ agv:c_2981
  ├── ex:Deforestation      (skos:Concept, topConceptOf)  ←→ agv:c_2018
  ├── ex:Afforestation      (skos:Concept, topConceptOf)  ←→ agv:c_102
  ├── ex:Reforestation      (skos:Concept, topConceptOf)  ←→ agv:c_6399
  ├── ex:Woodland           (skos:Concept, topConceptOf)  ←→ agv:c_8373
  └── ex:Tree               (skos:Concept, topConceptOf)  ←→ agv:c_7850
        │
        └── ex:<ConceptHash>  (skos:Concept)
              ├── skos:broader        → ex:Forest
              ├── skos:prefLabel      "Forest"@en
              ├── skos:definition     "..."@fr
              ├── skos:scopeNote      "National"@en
              ├── dct:spatial         "France"
              ├── dct:date            "1997"^^xsd:gYear
              ├── ex:minAreaHa        "0.5"^^xsd:decimal
              ├── ex:maxAreaHa        "1.0"^^xsd:decimal
              ├── ex:minCrownCoverPct "10"^^xsd:decimal
              └── ex:minTreeHeightM   "2"^^xsd:decimal
```

## Usage

```bash
# Pipeline complet
python pipeline.py --input path/to/definitions.docx --output ../data/forest_kg.ttl

# Étapes individuelles (debug)
python pipeline.py --input ... --output ... --step extract
python pipeline.py --input ... --output ... --step build
python pipeline.py --input ... --output ... --step validate

# Avec table3
python pipeline.py --input ... --output ... --table3 path/to/table3_clean.csv

# Stats du graphe
python pipeline.py --stats --ttl ../data/forest_kg.ttl
```

## Conventions SKOS

| Relation | Usage |
|----------|-------|
| `skos:broader` | Relation hiérarchique **intra-thésaurus** |
| `skos:exactMatch` | Alignement **inter-thésaurus** (Agrovoc, AFO) |
| `skos:closeMatch` | Alignement approximatif |
| `skos:related` | Relation associative (ex: Forest ↔ Deforestation) |
| `skos:scopeNote` | Portée géographique (National/International/General) |
| `skos:altLabel` | Synonymes et variantes linguistiques |
