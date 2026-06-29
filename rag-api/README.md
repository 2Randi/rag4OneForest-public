# rag-api — API GraphRAG

API FastAPI exposant le pipeline de Génération Augmentée de Récupération.

## Architecture des services

```
app/
├── main.py                   Point d'entrée FastAPI + tous les routes
├── core/
│   └── settings.py           Configuration (pydantic-settings + .env)
├── models/
│   └── schemas.py            Schémas Pydantic (request/response)
└── services/
    ├── graph_store.py         Graphe RDF en mémoire + SPARQL
    ├── vector_store.py        Index ChromaDB + embeddings
    ├── retriever.py           Fusion hybride RRF (vectoriel + SPARQL)
    └── rag_chain.py           Prompt engineering + LLM + évaluation
```

## Pipeline de retrieval hybride

```
Question utilisateur
    │
    ├──[1] VectorStore.search()           Similarité cosinus (sentence-transformers)
    │       └─ top-K concepts par embedding
    │
    ├──[2] GraphStore.search_by_keyword() Filtrage SPARQL regex
    │       └─ top-K concepts par présence de mots-clés
    │
    ├──[3] Fusion RRF                     Reciprocal Rank Fusion
    │       score = Σ 1/(60 + rank_i)
    │
    ├──[4] GraphStore.get_context()       Enrichissement structurel
    │       └─ parent, frères, seuils, alignements Agrovoc
    │
    └──[5] RAGChain.generate()            LLM avec contexte enrichi
            └─ réponse avec citations [N]
```

## Endpoints

| Méthode | Route | Description |
|---------|-------|-------------|
| `POST` | `/api/query` | Requête RAG complète |
| `GET`  | `/api/query/stream` | Requête RAG en streaming SSE |
| `POST` | `/api/index` | Construire l'index vectoriel |
| `GET`  | `/api/graph/stats` | Statistiques du graphe |
| `POST` | `/api/graph/sparql` | Requête SPARQL directe |
| `GET`  | `/api/graph/concept/{uri}` | Détail d'un concept |
| `GET`  | `/api/graph/search?q=...` | Recherche de concepts |
| `GET`  | `/api/graph/top-concepts` | Top concepts du schéma |
| `GET`  | `/health` | Healthcheck |

## Usage

```bash
# Démarrage
python -m app.main

# Indexation (une fois)
curl -X POST http://localhost:8000/api/index \
     -H "Content-Type: application/json" \
     -d '{"force_rebuild": false}'

# Requête RAG
curl -X POST http://localhost:8000/api/query \
     -H "Content-Type: application/json" \
     -d '{"query": "What are the UNFCCC threshold criteria for forest definition?", "top_k": 5}'

# SPARQL direct
curl -X POST http://localhost:8000/api/graph/sparql \
     -H "Content-Type: application/json" \
     -d '{"query": "SELECT ?label ?country WHERE { ?c skos:prefLabel ?label ; dct:spatial ?country . } LIMIT 10"}'
```

## Documentation interactive

Après démarrage : http://localhost:8000/docs
