# Application FastAPI - RAG4OneForest API
from __future__ import annotations

import time
import urllib.parse
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.core.settings import settings
from app.models.schemas import (
    QueryRequest, QueryResponse, SourceDocument,
    IndexRequest, IndexResponse,
    SPARQLRequest, GraphStatsResponse,
)
from app.services.graph_store import get_graph_store
from app.services.vector_store import get_vector_store
from app.services.retriever import HybridRetriever, VectorRetriever
from app.services.rag_chain import RAGChain, RAGEvaluator
from app.services.agent_rag import AgentRAG
from app.services.threshold_store import get_threshold_store
from app.services.criteria_store import get_criteria_store

log = structlog.get_logger()


# Lifespan : chargement des services au démarrage

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Démarrage RAG4OneForest API")
    # Pré-chargement du graphe RDF (lourd, une seule fois)
    try:
        gs = get_graph_store()
        log.info("GraphStore chargé", triples=len(gs.rdflib_graph))
    except FileNotFoundError as e:
        log.warning(f"GraphStore non disponible : {e}")

    # Vérification de l'index vectoriel
    vs = get_vector_store()
    if vs.is_indexed():
        log.info("VectorStore chargé", docs=vs.count())
    else:
        log.warning("Index vectoriel vide - lancer POST /api/index pour indexer")

    # Chargement des seuils nationaux (Table 3 Lund 2018)
    ts = get_threshold_store()
    log.info("ThresholdStore chargé", entries=len(ts))

    # Chargement des critères extraits du texte des définitions
    cs = get_criteria_store()
    log.info("CriteriaStore chargé", entries=len(cs))

    yield
    log.info("Arrêt RAG4OneForest API")


# Application

app = FastAPI(
    title="RAG4OneForest API",
    description="GraphRAG sur les définitions autour de la forêt SKOS/RDF",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health

@app.get("/health")
def health():
    vs = get_vector_store()
    ts = get_threshold_store()
    cs = get_criteria_store()
    return {
        "status":             "ok",
        "graph_loaded":       True,
        "index_ready":        vs.is_indexed(),
        "index_size":         vs.count(),
        "threshold_entries":  len(ts),
        "criteria_entries":   len(cs),
        "llm_provider":       settings.llm_provider,
    }


# Indexation

@app.post("/api/index", response_model=IndexResponse)
def build_index(req: IndexRequest):
    """Construit ou reconstruit l'index vectoriel ChromaDB."""
    vs = get_vector_store()
    if vs.is_indexed() and not req.force_rebuild:
        return IndexResponse(
            status="already_indexed",
            documents_indexed=vs.count(),
            message="Index déjà présent. Utiliser force_rebuild=true pour reconstruire."
        )
    gs = get_graph_store()
    n  = vs.build_index(gs)
    return IndexResponse(
        status="success",
        documents_indexed=n,
        message=f"{n} concepts SKOS indexés avec succès."
    )


# Requête RAG

@app.post("/api/query", response_model=QueryResponse)
def query_rag(req: QueryRequest):
    """4 modes : llm_only, vector_rag, graph_rag, agent_rag."""
    t0 = time.perf_counter()
    try:
        vs    = get_vector_store()
        chain = RAGChain()
        evaluator = RAGEvaluator()

        # Mode D : Agent IA
        if req.mode == "agent_rag":
            gs = get_graph_store()
            agent = AgentRAG(graph_store=gs, vector_store=vs)
            result = agent.run(req.query, top_k=req.top_k or settings.retrieval_top_k)
            docs = result["docs"]
            answer = result["answer"]
            eval_res = evaluator.evaluate(req.query, answer, docs)

            sources = []
            for doc in docs:
                m = doc.get("metadata", {})
                sources.append(SourceDocument(
                    uri          = m.get("uri", ""),
                    label        = m.get("label", ""),
                    definition   = m.get("def", ""),
                    country      = m.get("country", ""),
                    year         = m.get("year", ""),
                    scope        = m.get("scope", ""),
                    rrf_score    = doc.get("rrf_score", 0),
                    sources      = doc.get("sources", []),
                    graph_context= doc.get("graph_context"),
                ))

            latency = (time.perf_counter() - t0) * 1000
            log.info("query_agent", query=req.query[:60],
                     tools=result.get("tools_used", []), latency_ms=round(latency))

            return QueryResponse(
                query      = req.query,
                answer     = answer,
                sources    = sources,
                model      = result.get("model", settings.llm_model),
                mode       = "agent_rag",
                evaluation = eval_res,
                latency_ms = round(latency, 1),
            )

        # Mode A : LLM seul
        if req.mode == "llm_only":
            result   = chain.generate_llm_only(req.query)
            answer   = result["answer"]
            latency  = (time.perf_counter() - t0) * 1000
            log.info("query_llm_only", query=req.query[:60], latency_ms=round(latency))
            return QueryResponse(
                query      = req.query,
                answer     = answer,
                sources    = [],
                model      = result.get("model", settings.llm_model),
                mode       = "llm_only",
                evaluation = {"n_docs_retrieved": 0},
                latency_ms = round(latency, 1),
            )

        # Mode B : vectoriel seul
        if req.mode == "vector_rag":
            retriever = VectorRetriever(vector_store=vs)
        # Mode C : GraphRAG complet
        else:
            gs = get_graph_store()
            retriever = HybridRetriever(graph_store=gs, vector_store=vs)

        docs = retriever.retrieve(req.query, top_k=req.top_k)
        if not docs:
            raise HTTPException(status_code=404, detail="Aucun document pertinent trouvé.")

        result   = chain.generate(req.query, docs)
        answer   = result["answer"]
        eval_res = evaluator.evaluate(req.query, answer, docs)

        sources = []
        for doc in docs:
            m = doc.get("metadata", {})
            sources.append(SourceDocument(
                uri          = m.get("uri", ""),
                label        = m.get("label", ""),
                definition   = m.get("def", ""),
                country      = m.get("country", ""),
                year         = m.get("year", ""),
                scope        = m.get("scope", ""),
                rrf_score    = doc.get("rrf_score", 0),
                sources      = doc.get("sources", []),
                graph_context= doc.get("graph_context"),
            ))

        latency = (time.perf_counter() - t0) * 1000
        log.info("query_rag", mode=req.mode, query=req.query[:60],
                 n_docs=len(docs), latency_ms=round(latency))

        return QueryResponse(
            query      = req.query,
            answer     = answer,
            sources    = sources,
            model      = result.get("model", settings.llm_model),
            mode       = req.mode,
            evaluation = eval_res,
            latency_ms = round(latency, 1),
        )

    except Exception as e:
        log.error("query_rag_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/query/stream")
def query_rag_stream(query: str, top_k: int = 6):
    """Requête RAG en streaming Server-Sent Events (SSE)."""
    try:
        gs        = get_graph_store()
        vs        = get_vector_store()
        retriever = HybridRetriever(graph_store=gs, vector_store=vs)
        chain     = RAGChain()
        docs      = retriever.retrieve(query, top_k=top_k)

        def event_stream():
            import json
            # Envoyer les sources d'abord
            sources_data = [{"label": d.get("metadata", {}).get("label", ""),
                              "country": d.get("metadata", {}).get("country", ""),
                              "rrf_score": d.get("rrf_score", 0)} for d in docs]
            yield f"event: sources\ndata: {json.dumps(sources_data)}\n\n"

            # Streamer la réponse LLM
            for chunk in chain.generate_stream(query, docs):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"

            yield "event: done\ndata: {}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Graphe

@app.get("/api/graph/stats", response_model=GraphStatsResponse)
def graph_stats():
    """Statistiques du graphe RDF/SKOS."""
    gs    = get_graph_store()
    stats = gs.graph_stats()
    vs    = get_vector_store()
    return GraphStatsResponse(**stats, vector_indexed=vs.count())


@app.post("/api/graph/sparql")
def sparql_query(req: SPARQLRequest):
    """Exécute une requête SPARQL SELECT directe (pour exploration experte)."""
    gs = get_graph_store()
    try:
        results = gs.query_sparql(req.query)
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erreur SPARQL : {e}")


@app.get("/api/graph/concept/{uri_encoded}")
def get_concept(uri_encoded: str):
    """Détail complet d'un concept SKOS par son URI (encodé URL)."""
    uri = urllib.parse.unquote(uri_encoded)
    gs  = get_graph_store()
    concept = gs.get_concept(uri)
    if not concept:
        raise HTTPException(status_code=404, detail=f"Concept non trouvé : {uri}")
    return concept


@app.get("/api/graph/search")
def search_concepts(q: str, top_k: int = 10):
    """Recherche SPARQL par mots-clés dans les définitions."""
    gs = get_graph_store()
    return gs.search_by_keyword(q, top_k=top_k)


@app.get("/api/graph/top-concepts")
def get_top_concepts():
    """Liste les top concepts du schéma SKOS."""
    gs = get_graph_store()
    results = gs.query_sparql("""
SELECT ?uri ?label WHERE {
    ?uri skos:topConceptOf ex:ForestScheme ;
         skos:prefLabel ?label .
    FILTER(LANG(?label) = 'en')
}
""")
    return results


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.api_host,
                port=settings.api_port, reload=True, log_level=settings.log_level)
