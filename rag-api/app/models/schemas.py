# Schemas Pydantic pour l'API
from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000,
                       description="Question en langage naturel")
    top_k: Optional[int] = Field(None, ge=1, le=20,
                                  description="Nombre de documents à récupérer")
    stream: bool = Field(False, description="Activer le streaming SSE")
    mode: Literal["llm_only", "vector_rag", "graph_rag", "agent_rag"] = Field(
        "graph_rag",
        description=(
            "Mode de retrieval - "
            "llm_only: LLM seul | "
            "vector_rag: ChromaDB seul | "
            "graph_rag: hybride SPARQL+vectoriel | "
            "agent_rag: agent IA qui choisit ses outils"
        ),
    )


class SourceDocument(BaseModel):
    uri:          str
    label:        str
    definition:   str
    country:      str
    year:         str
    scope:        str
    rrf_score:    float
    sources:      list[str]        # ["vector", "sparql"]
    graph_context: Optional[str]


class QueryResponse(BaseModel):
    query:        str
    answer:       str
    sources:      list[SourceDocument]
    model:        str
    mode:         str
    evaluation:   dict[str, Any]
    latency_ms:   float


class IndexRequest(BaseModel):
    force_rebuild: bool = False


class IndexResponse(BaseModel):
    status:         str
    documents_indexed: int
    message:        str


class SPARQLRequest(BaseModel):
    query: str = Field(..., description="Requête SPARQL SELECT (sans les PREFIX)")


class GraphStatsResponse(BaseModel):
    total_triples:    int
    total_concepts:   int
    with_broad_match: int
    with_definition:  int
    with_thresholds:  int
    agrovoc_aligned:  int
    countries_count:  int
    unfccc_concepts:  int
    vector_indexed:   int
