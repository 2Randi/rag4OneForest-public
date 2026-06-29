# Indexation vectorielle et recherche semantique
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from app.core.settings import settings
from app.services.graph_store import GraphStore


# Extraction des documents pour l'indexation

EXTRACT_QUERY = """
SELECT ?uri ?label ?def ?country ?year ?org ?scope ?type ?parent WHERE {
    ?uri a skos:Concept ;
         skos:definition ?def .
    OPTIONAL { ?uri skos:prefLabel ?label   . FILTER(LANG(?label) IN ('en','fr','')) }
    OPTIONAL { ?uri dct:spatial    ?country . }
    OPTIONAL { ?uri dct:date       ?year    . }
    OPTIONAL { ?uri dct:creator    ?org     . }
    OPTIONAL { ?uri skos:scopeNote ?scope   . }
    OPTIONAL { ?uri skos:broader   ?parent  . }
}
"""


def _build_document_text(row: dict) -> str:
    """Construit le texte enrichi pour l'embedding d'un concept."""
    parts = []
    if row.get("label"):
        parts.append(f"Term: {row['label']}")
    if row.get("def"):
        parts.append(f"Definition: {row['def']}")

    meta_parts = []
    if row.get("country"): meta_parts.append(f"Country: {row['country']}")
    if row.get("year"):    meta_parts.append(f"Year: {row['year']}")
    if row.get("org"):     meta_parts.append(f"Organization: {row['org']}")
    if meta_parts:
        parts.append(" | ".join(meta_parts))

    if row.get("scope"):  parts.append(f"Scope: {row['scope']}")
    if row.get("parent"):
        parent_frag = str(row["parent"]).split("/")[-1]
        parts.append(f"Category: {parent_frag}")

    return "\n".join(parts)


def extract_documents(graph_store: GraphStore) -> list[dict]:
    """Extrait tous les concepts SKOS sous forme de documents enrichis."""
    rows = graph_store.query_sparql(EXTRACT_QUERY)

    # Dédoublonnage par URI (un concept peut avoir plusieurs scopeNotes)
    seen: dict[str, dict] = {}
    for row in rows:
        uri = row.get("uri", "")
        if not uri:
            continue
        if uri not in seen:
            seen[uri] = {
                "uri":     uri,
                "label":   row.get("label", ""),
                "def":     row.get("def", ""),
                "country": row.get("country", ""),
                "year":    row.get("year", ""),
                "org":     row.get("org", ""),
                "scope":   row.get("scope", ""),
                "parent":  row.get("parent", ""),
            }
        else:
            # Fusionner les scopeNotes
            if row.get("scope") and row["scope"] not in seen[uri]["scope"]:
                seen[uri]["scope"] += f", {row['scope']}"

    docs = []
    for uri, data in seen.items():
        doc_text = _build_document_text(data)
        if not doc_text.strip():
            continue
        # ID stable : hash de l'URI (ChromaDB requiert des IDs strings courts)
        doc_id = hashlib.sha1(uri.encode()).hexdigest()[:16]
        docs.append({
            "id":       doc_id,
            "text":     doc_text,
            "metadata": {k: str(v) for k, v in data.items()},
        })

    print(f"[VectorStore] {len(docs)} documents préparés pour l'indexation")
    return docs


# Service Vector Store

class VectorStore:
    """
    Gestion de l'index vectoriel ChromaDB.
    - build_index()  : indexation (à lancer une fois)
    - search()       : recherche sémantique par similarité cosinus
    - is_indexed()   : vérifie si l'index existe
    """

    def __init__(self):
        self._embedder = SentenceTransformer(settings.embed_model)
        self._client   = chromadb.PersistentClient(
            path=settings.chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._coll = None

    def _get_or_create_collection(self, create: bool = False):
        if create:
            try:
                self._client.delete_collection(settings.chroma_collection)
            except Exception:
                pass
            self._coll = self._client.create_collection(
                settings.chroma_collection,
                metadata={"hnsw:space": "cosine"}
            )
        else:
            self._coll = self._client.get_collection(settings.chroma_collection)
        return self._coll

    def is_indexed(self) -> bool:
        try:
            coll = self._client.get_collection(settings.chroma_collection)
            return coll.count() > 0
        except Exception:
            return False

    def build_index(self, graph_store: GraphStore, batch_size: int = 256) -> int:
        """
        Construit l'index vectoriel depuis le graphe.
        Retourne le nombre de documents indexés.
        """
        from tqdm import tqdm

        docs = extract_documents(graph_store)
        coll = self._get_or_create_collection(create=True)

        for i in tqdm(range(0, len(docs), batch_size), desc="Indexation"):
            batch = docs[i:i + batch_size]
            texts      = [d["text"]     for d in batch]
            ids        = [d["id"]       for d in batch]
            metadatas  = [d["metadata"] for d in batch]
            embeddings = self._embedder.encode(texts, show_progress_bar=False).tolist()
            coll.add(documents=texts, embeddings=embeddings,
                     ids=ids, metadatas=metadatas)

        print(f"[VectorStore] [OK] {len(docs)} documents indexés")
        return len(docs)

    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        """
        Recherche sémantique.
        Retourne les top_k documents les plus similaires.
        """
        if self._coll is None:
            self._get_or_create_collection(create=False)

        k = top_k or settings.retrieval_top_k
        q_emb = self._embedder.encode([query]).tolist()
        results = self._coll.query(query_embeddings=q_emb, n_results=k)

        docs = []
        for i, doc_text in enumerate(results["documents"][0]):
            distance = results["distances"][0][i]
            # ChromaDB cosine : distance ∈ [0, 2], score = 1 - distance/2
            vector_score = round(1.0 - distance / 2.0, 4)
            docs.append({
                "text":         doc_text,
                "metadata":     results["metadatas"][0][i],
                "vector_score": vector_score,
                "source":       "vector",
            })
        return docs

    def count(self) -> int:
        if self._coll is None:
            try:
                self._get_or_create_collection(create=False)
            except Exception:
                return 0
        return self._coll.count()


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    return VectorStore()
