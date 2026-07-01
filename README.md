# RAG4OneForest

> **GraphRAG sur un Knowledge Graph de définitions forestières** - Projet de stage, IRD, Université de Montpellier (RAG4OneForest)

**Auteur :** RANDRIAMISAINA Tsiory
**Laboratoire :** UMR ESPACE-DEV, IRD   
**Période :** 13/04/2026 - 13/08/2026

[![Python](https://img.shields.io/badge/Python-3.12+-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-blue)](https://react.dev)
[![RDF/SKOS](https://img.shields.io/badge/RDF-SKOS%20W3C-orange)](https://www.w3.org/TR/skos-reference/)
[![LangChain](https://img.shields.io/badge/LangChain-1.3-purple)](https://python.langchain.com)

---

## Vue d'ensemble

RAG4OneForest est un système **GraphRAG** (Retrieval-Augmented Generation sur graphe de connaissances) dédié à l'exploration et à l'interrogation des **définitions forestières internationales**. Il s'appuie sur le corpus de Lund (2018) qui recense plus de centaine de définitions issues de plusieurs pays et organisations.

Le système intègre trois composants principaux :

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          RAG4OneForest                                   │
│                                                                           │
│  ┌────────────────┐    ┌──────────────────────┐    ┌─────────────────┐  │
│  │  kg-builder    │    │      rag-api          │    │   graph-viz     │  │
│  │  (Python)      │───▶│  (FastAPI + Python)   │◀───│  (React / D3)  │  │
│  │                │    │                      │    │                 │  │
│  │ DOCX → SKOS    │    │ SPARQL + Vectoriel    │    │ Graphe SKOS    │  │
│  │ RDF/Turtle     │    │ Retrieval hybride     │    │ Chat RAG       │  │
│  │ 34 480 triplets│    │ Multi-LLM fallback    │    │ Vue RDF        │  │
│  └────────────────┘    └──────────────────────┘    │ Statistiques   │  │
│           │                       │                 └─────────────────┘  │
│           ▼                       ▼                                       │
│  ┌────────────────┐    ┌──────────────────────┐                          │
│  │ forest_kg.ttl  │    │  ChromaDB            │                          │
│  │ (RDF/SKOS)     │    │  2 972 embeddings    │                          │
│  └────────────────┘    └──────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Structure du projet

```
rag4oneforest/
├── data/                          Données sources et graphe RDF
│   ├── forest_kg.ttl              Knowledge Graph SKOS (34 480 triplets)
│   ├── definitions.docx           Corpus source — Lund (2018)
│   ├── definitions_clean.csv      Définitions extraites (nettoyées)
│   └── definitions_raw.csv        Extraction brute
│
├── kg-builder/                    Pipeline d'extraction et de construction du KG
│   ├── extractor/
│   │   ├── docx_extractor.py      Extraction DOCX → DefinitionRecord
│   │   └── csv_exporter.py        Export CSV
│   ├── builder/
│   │   └── skos_builder.py        Construction RDF/SKOS (rdflib)
│   ├── pipeline.py                Orchestrateur du pipeline complet
│   ├── config.py                  Configuration chemins et namespaces
│   ├── run.py                     Point d'entrée CLI
│   └── requirements.txt
│
├── rag-api/                       API GraphRAG (FastAPI)
│   ├── app/
│   │   ├── main.py                Endpoints FastAPI
│   │   ├── core/
│   │   │   └── settings.py        Configuration (pydantic-settings)
│   │   ├── models/
│   │   │   └── schemas.py         Schémas Pydantic (requête/réponse)
│   │   └── services/
│   │       ├── graph_store.py     Accès SPARQL au graphe (rdflib)
│   │       ├── vector_store.py    Index ChromaDB + embeddings
│   │       ├── retriever.py       Retrieval hybride + fusion RRF
│   │       └── rag_chain.py       Multi-LLM fallback + prompt
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example               Template de configuration
│   └── README.md
│
├── graph-viz/                     Interface de visualisation (React + D3)
│   ├── src/
│   │   ├── App.tsx                Application principale (4 vues)
│   │   ├── lib/
│   │   │   └── graphStore.ts      Parsing TTL + API graphe (n3.js)
│   │   └── components/
│   │       ├── GraphCanvas.tsx    Visualisation D3 force-directed
│   │       ├── FilterPanel.tsx    Filtres et recherche
│   │       ├── ConceptRDFView.tsx Vue détail RDF d'un concept
│   │       ├── StatsView.tsx      Statistiques interactives
│   │       └── ChatRAG.tsx        Interface de chat RAG
│   ├── Dockerfile
│   └── package.json
│
├── docs/
│   └── rapport.md                 Rapport de stage complet
│
├── docker-compose.yml             Déploiement conteneurisé
├── tasks.py                       Commandes de développement (cross-platform)
├── .gitignore
└── README.md                      (ce fichier)
```

---

## Prérequis

| Outil | Version minimale | Usage |
|-------|-----------------|-------|
| Python | 3.12+ | Backend RAG API + kg-builder |
| Node.js | 20+ | Frontend graph-viz |
| npm | 9+ | Gestion dépendances JS |
| Git | 2.40+ | Gestion des sources |
| Docker | 24+ | Déploiement (optionnel) |

**Clé API LLM requise** (au moins une) :
- [Google AI Studio](https://aistudio.google.com) — Gemini (gratuit, recommandé)
- [Anthropic](https://console.anthropic.com) — Claude
- [OpenAI](https://platform.openai.com) — GPT-4o
- [DeepSeek](https://platform.deepseek.com) — DeepSeek
- [Groq](https://console.groq.com) — Llama (gratuit)

---

## Démarrage rapide

### Option A — Sans Docker (développement local)

> Prérequis : Python 3.12+, Node.js 20+

**1. Cloner et installer**

```bash
git clone <url-du-depot>
cd rag4oneforest-public
python tasks.py install
```

`python tasks.py install` fait tout automatiquement : environnement Python, dépendances frontend, index vectoriel (~2 min, télécharge le modèle d'embeddings).

**2. Ajouter votre clé API LLM**

Ouvrir `rag-api/.env` et renseigner au moins une clé :

```bash
# Gemini — gratuit sur https://aistudio.google.com (recommandé)
GEMINI_API_KEY=AIza...

# Ou Groq — gratuit sur https://console.groq.com
# GROQ_API_KEY=gsk_...
```

**3. Lancer**

```bash
python tasks.py dev
```

Ouvrir **http://localhost:5173** dans le navigateur.

---

### Option B — Docker

> Prérequis : Docker + Docker Compose

**1. Cloner**

```bash
git clone <url-du-depot>
cd rag4oneforest-public
```

**2. Ajouter votre clé API LLM**

```bash
cp rag-api/.env.example rag-api/.env
# Ouvrir rag-api/.env et renseigner GEMINI_API_KEY ou GROQ_API_KEY
```

**3. Lancer**

```bash
docker compose up --build
```

Ouvrir **http://localhost:5173** dans le navigateur.

> Au premier lancement, l'index vectoriel se construit automatiquement (~2 min). Aucune commande supplémentaire n'est nécessaire. Les lancements suivants sont immédiats (index persisté dans un volume Docker).

**Installer Docker sur Ubuntu :**

```bash
sudo apt install docker.io

# Installer Docker Compose V2
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
     -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Autoriser Docker sans sudo
sudo usermod -aG docker $USER
newgrp docker
```

---

## Configuration

Toute la configuration se fait via `rag-api/.env` :

```bash
# ── LLM (priorité : Gemini → DeepSeek → Claude → GPT → Groq) ──
GEMINI_API_KEY=AIza...           # recommandé (gratuit)
# DEEPSEEK_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# GROQ_API_KEY=gsk_...

# ── Vector Store ──────────────────────────────────────────────────
CHROMA_PATH=./chroma_db
EMBED_MODEL=all-MiniLM-L6-v2    # modèle d'embeddings (local, ~90 Mo)

# ── Retrieval ─────────────────────────────────────────────────────
RETRIEVAL_TOP_K=8               # nombre de documents récupérés
```

> Le système sélectionne automatiquement le premier LLM dont la clé est configurée. En cas d'erreur de quota, il bascule sur le suivant.

---

## API REST

L'API est disponible sur `http://localhost:8000`. La documentation interactive est à `http://localhost:8000/docs`.

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/health` | État du système (LLM, index, graphe) |
| `POST` | `/api/query` | Question RAG en langage naturel |
| `GET` | `/api/query/stream` | Réponse RAG en streaming (SSE) |
| `POST` | `/api/index` | Construire/reconstruire l'index vectoriel |
| `GET` | `/api/graph/stats` | Statistiques du graphe RDF |
| `POST` | `/api/graph/sparql` | Requête SPARQL directe |
| `GET` | `/api/graph/concept/{uri}` | Détail d'un concept SKOS |
| `GET` | `/api/graph/search?q=...` | Recherche par mots-clés |

**Exemple de requête :**

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the FAO definition of deforestation?", "top_k": 6}'
```

---

## Interface graph-viz

L'interface React propose quatre vues accessibles depuis la barre de navigation :

| Vue | Description |
|-----|-------------|
| **Graphe global** | Visualisation D3 force-directed du SKOS. Clic → déplier ; double-clic → fiche RDF |
| **Vue RDF** | Détail complet d'un concept : littéraux, relations, alignements |
| **Statistiques** | Tableaux de bord interactifs (qualité KG, distribution géographique, temporelle…) |
| **Chat RAG** | Interface de conversation avec Gemini/Claude/GPT, sources traçables et cliquables |

Le panneau de gauche permet de filtrer par :
- Catégorie (Forest, Deforestation, Afforestation…)
- Pays
- Année
- Organisation (FAO, UNFCCC, IPCC, EU, World Bank…)
- Portée (General, International, National, State)

---

## Reconstruction du Knowledge Graph

Si vous souhaitez régénérer le graphe depuis les données sources :

```bash
# Reconstruire le graphe RDF depuis le DOCX source
python tasks.py build-kg

# Ré-indexer après reconstruction
python tasks.py index
```

---

## Données

| Fichier | Format | Contenu |
|---------|--------|---------|
| `data/forest_kg.ttl` | RDF/Turtle | Knowledge Graph SKOS — 34 480 triplets, 2 972 concepts |
| `data/definitions.docx` | Word | Corpus source — Lund (2018), 800+ définitions |
| `data/definitions_clean.csv` | CSV | Définitions structurées extraites |

**Vocabulaires RDF utilisés :**
- [SKOS](https://www.w3.org/TR/skos-reference/) - structure conceptuelle
- [DCTERMS](https://www.dublincore.org/specifications/dublin-core/dcmi-terms/) - métadonnées (pays, année, organisation, source)
- [QUDT](http://qudt.org) - critères techniques (surface minimale, taux de couverture…)

---

## Architecture technique

### Pipeline RAG

```
Question utilisateur
        │
        ├─→ Détection concept + portée (regex)
        │
        ├─→ [Bras 1] Recherche SPARQL (rdflib)
        │   Requête structurée sur le graphe RDF
        │   Filtre concept / portée géographique
        │
        ├─→ [Bras 2] Recherche vectorielle (ChromaDB)
        │   Embedding all-MiniLM-L6-v2 (384 dims)
        │   Similarité cosinus
        │
        ├─→ Fusion RRF (Reciprocal Rank Fusion, k=60)
        │   Déduplique + classe les résultats hybrides
        │
        ├─→ Enrichissement contextuel (graphe)
        │   Concept parent, frères, relations, seuils
        │
        └─→ Génération LLM (chaîne de fallback)
            Gemini → DeepSeek → Claude → GPT → Groq
            Prompt structuré + citations [N]
            Température 0.1 (réponses déterministes)
```

### Qualité des réponses (évaluation RAGAS)

| Métrique | Score |
|----------|-------|
| Faithfulness (claims ancrés dans le contexte) | **~96%** |
| Answer Relevancy (pertinence de la réponse) | **~86%** |

---

## Développement

```bash
# Lancer les tests
python tasks.py test

# Nettoyer les fichiers temporaires
python tasks.py clean

# Vérifier la santé de l'API
curl http://localhost:8000/health

# Re-indexer (après modification du TTL)
python tasks.py index
```

Toutes les commandes disponibles :

```bash
python tasks.py help
```

---

## Références

- Lund, G. (2018). *Definitions of Forest, Deforestation, Afforestation and Reforestation*
- Edge, D. et al. (2024). *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*
- Collarana Vargas, D. et al. (2025). *Graph RAG in the Wild*
- Es, S. et al. (2023). *RAGAS: Automated Evaluation of Retrieval Augmented Generation*
- W3C (2009). *SKOS Simple Knowledge Organization System Reference*
- Mikolov, T. et al. (2013). *Distributed Representations of Words and Phrases*

