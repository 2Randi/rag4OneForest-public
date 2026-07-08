# Retrieval hybride vectoriel + SPARQL avec fusion RRF
from __future__ import annotations

import re
from typing import Any

from app.core.settings import settings
from app.services.graph_store import GraphStore, get_graph_store
from app.services.vector_store import VectorStore, get_vector_store
from app.services.threshold_store import ThresholdStore, get_threshold_store
from app.services.query_patterns import _THRESHOLD_FIELDS, _LE_WORDS, _GE_WORDS, _is_threshold_query
from app.services.filter_extractor import QueryFilters, extract_filters

_RRF_K = 60


def _normalise_country(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "-", s.lower()).strip("-")


def _apply_threshold(docs: list[dict], field: str, op: str, value: float) -> list[dict]:
    if op == "le":
        return [d for d in docs if d.get(field) and float(d[field]) <= value]
    if op == "ge":
        return [d for d in docs if d.get(field) and float(d[field]) >= value]
    return docs


def _filter_by_threshold(docs: list[dict], query: str) -> list[dict]:
    """
    coupe la liste de pays si la question donne un seuil numerique (crown
    cover, area, height), peu importe comment c'est formule ("or less",
    "at most", "under", "or more", "at least"...). sans ca le LLM doit
    compter/filtrer lui meme sur 40+ docs bruts et se trompe a chaque fois
    """
    for field, field_kw, unit in _THRESHOLD_FIELDS:
        if not re.search(field_kw, query, re.IGNORECASE):
            continue
        num_match = re.search(rf'(\d+(?:\.\d+)?)\s*(?:{unit})', query, re.IGNORECASE)
        if not num_match:
            continue
        value = float(num_match.group(1))
        if _LE_WORDS.search(query):
            return _apply_threshold(docs, field, "le", value)
        if _GE_WORDS.search(query):
            return _apply_threshold(docs, field, "ge", value)
    return docs


# Mode B : retriever vectoriel seul

class VectorRetriever:
    """Mode B — ChromaDB uniquement, sans SPARQL ni enrichissement graphe."""

    def __init__(self, vector_store: VectorStore | None = None):
        self._vs = vector_store or get_vector_store()

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        k = top_k or settings.retrieval_top_k
        if not self._vs.is_indexed():
            return []
        return self._vs.search(query, top_k=k)


# RRF

def _rrf_score(ranks: list[int]) -> float:
    return sum(1.0 / (_RRF_K + r) for r in ranks)


# Retriever hybride

class HybridRetriever:

    def __init__(
        self,
        graph_store:     GraphStore     | None = None,
        vector_store:    VectorStore    | None = None,
        threshold_store: ThresholdStore | None = None,
    ):
        self._gs = graph_store     or get_graph_store()
        self._vs = vector_store    or get_vector_store()
        self._ts = threshold_store or get_threshold_store()

    # Etapes composables (chantier 3 : reutilisees telles quelles par AgentRAG
    # pour que le mode agent beneficie du meme filtrage/enrichissement que le
    # mode graph_rag, au lieu de re-implementer cette logique une 2e fois)

    def detect_filters(self, query: str) -> QueryFilters:
        return extract_filters(query, threshold_store=self._ts)

    def vector_search(self, query: str, top_k: int) -> list[dict]:
        return self._vs.search(query, top_k=top_k) if self._vs.is_indexed() else []

    def sparql_search(self, query: str, filters: QueryFilters, top_k: int) -> list[dict]:
        # Quand une org spécifique est détectée, le scope géographique est redondant
        # et filtre à tort les docs dont dct:spatial ≠ "international"
        scope = filters.scope if not filters.org else None
        return self._gs.search_by_keyword(
            query, top_k=top_k, concept=filters.concept, scope=scope, org=filters.org
        )

    def rrf_merge(self, vec_docs: list[dict], sparql_docs: list[dict], top_k: int) -> list[dict]:
        uri_data: dict[str, dict] = {}

        for rank, doc in enumerate(vec_docs, 1):
            uri = doc["metadata"].get("uri", f"vec_{rank}")
            if uri not in uri_data:
                uri_data[uri] = {
                    "text":          doc["text"],
                    "metadata":      doc["metadata"],
                    "sources":       ["vector"],
                    "vec_rank":      rank,
                    "sparql_rank":   None,
                    "vector_score":  doc.get("vector_score", 0),
                    "sparql_score":  0,
                }
            else:
                uri_data[uri]["vec_rank"]     = rank
                uri_data[uri]["vector_score"] = doc.get("vector_score", 0)
                if "vector" not in uri_data[uri]["sources"]:
                    uri_data[uri]["sources"].append("vector")

        for rank, doc in enumerate(sparql_docs, 1):
            uri = doc.get("uri", f"sparql_{rank}")
            if uri not in uri_data:
                uri_data[uri] = {
                    "text":     self._format_sparql_doc(doc),
                    "metadata": {
                        "uri":     uri,
                        "label":   doc.get("label",   ""),
                        "def":     doc.get("def",     ""),
                        "country": doc.get("country", ""),
                        "year":    doc.get("year",    ""),
                        "scope":   doc.get("scope",   ""),
                        "org":     doc.get("org",     ""),
                    },
                    "sources":       ["sparql"],
                    "vec_rank":      None,
                    "sparql_rank":   rank,
                    "vector_score":  0,
                    "sparql_score":  doc.get("sparql_score", 0),
                }
            else:
                uri_data[uri]["sparql_rank"]  = rank
                uri_data[uri]["sparql_score"] = doc.get("sparql_score", 0)
                if "sparql" not in uri_data[uri]["sources"]:
                    uri_data[uri]["sources"].append("sparql")

        # Score RRF + tri
        for data in uri_data.values():
            ranks = []
            if data["vec_rank"]   is not None: ranks.append(data["vec_rank"])
            if data["sparql_rank"] is not None: ranks.append(data["sparql_rank"])
            data["rrf_score"] = round(_rrf_score(ranks), 6)

        return sorted(uri_data.values(), key=lambda d: -d["rrf_score"])[:top_k]

    def enrich_graph_context(self, docs: list[dict]) -> list[dict]:
        for doc in docs:
            uri = doc["metadata"].get("uri", "")
            if uri:
                ctx = self._gs.get_context(uri)
                if ctx:
                    doc["graph_context"] = ctx
        return docs

    def enrich_thresholds(self, query: str, docs: list[dict], filters: QueryFilters) -> list[dict]:
        continent = filters.continent
        if not (_is_threshold_query(query) or continent):
            return docs

        # Recherche par continent via SPARQL sur le graphe
        if continent:
            continent_docs = self._gs.search_continent_thresholds(continent)
            if filters.threshold_field and filters.threshold_op:
                continent_docs = _apply_threshold(
                    continent_docs, filters.threshold_field,
                    filters.threshold_op, filters.threshold_value)
            else:
                continent_docs = _filter_by_threshold(continent_docs, query)
            # dict.fromkeys dédupe sans perdre l'ordre (un set() mélange tout)
            countries_ctx = list(dict.fromkeys(d["country"] for d in continent_docs))
        else:
            countries_ctx = list(filters.countries) or list(self._ts.extract_countries_from_query(query))

        if not countries_ctx:
            for doc in docs[:3]:
                c = doc["metadata"].get("country", "")
                if c and c not in countries_ctx:
                    countries_ctx.append(c)

        already_uris = {doc["metadata"].get("uri") for doc in docs}
        threshold_docs: list[dict] = []

        # pas de limite à 10 si continent (l'Afrique a 46 pays à couvrir)
        country_limit = len(countries_ctx) if continent else 10
        for country in countries_ctx[:country_limit]:
            kg_docs = self._gs.search_country_thresholds(country, top_k=3)
            for td in kg_docs:
                if td["uri"] in already_uris:
                    continue
                already_uris.add(td["uri"])
                graph_ctx = self._gs.get_context(td["uri"]) or ""
                has_structured = td.get("sparql_score", 0) > 0
                sources = ["sparql", "threshold"] if has_structured else ["sparql"]
                threshold_docs.append({
                    "text": td["text"],
                    "metadata": {
                        "uri":     td["uri"],
                        "label":   td.get("label", ""),
                        "def":     td.get("def", ""),
                        "country": td["country"],
                        "year":    td.get("year", ""),
                        "scope":   "National",
                        "org":     td.get("org", ""),
                    },
                    "sources":       sources,
                    "vec_rank":      None,
                    "sparql_rank":   None,
                    "rrf_score":     0.06 + td.get("sparql_score", 0) * 0.01,
                    "vector_score":  0,
                    "sparql_score":  td.get("sparql_score", 0),
                    "graph_context": graph_ctx,
                })

            # Ajouter aussi les seuils du ThresholdStore comme contexte
            ts_context = self._ts.format_as_context(country)
            if ts_context and not kg_docs:
                threshold_docs.append({
                    "text": ts_context,
                    "metadata": {
                        "uri":     f"threshold://{_normalise_country(country)}",
                        "label":   f"{country} forest thresholds",
                        "def":     ts_context,
                        "country": country,
                        "year":    "",
                        "scope":   "National",
                        "org":     "",
                    },
                    "sources":       ["threshold"],
                    "vec_rank":      None,
                    "sparql_rank":   None,
                    "rrf_score":     0.05,
                    "vector_score":  0,
                    "sparql_score":  0,
                    "graph_context": ts_context,
                })

        # Insertion en position 1 (après le meilleur doc naturel)
        if threshold_docs and countries_ctx:
            insert_pos = min(1, len(docs))
            for s in reversed(threshold_docs):
                docs.insert(insert_pos, s)
        else:
            docs.extend(threshold_docs)

        return docs

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        k       = top_k or settings.retrieval_top_k
        fetch_k = k * 3

        filters     = self.detect_filters(query)
        vec_docs    = self.vector_search(query, fetch_k)
        sparql_docs = self.sparql_search(query, filters, fetch_k)
        merged      = self.rrf_merge(vec_docs, sparql_docs, k)
        merged      = self.enrich_graph_context(merged)
        merged      = self.enrich_thresholds(query, merged, filters)
        return merged

    @staticmethod
    def _format_sparql_doc(row: dict) -> str:
        parts = []
        if row.get("label"): parts.append(f"Term: {row['label']}")
        if row.get("def"):   parts.append(f"Definition: {row['def']}")
        meta = " | ".join(filter(None, [
            f"Country: {row['country']}" if row.get("country") else "",
            f"Year: {row['year']}"       if row.get("year")    else "",
            f"Scope: {row['scope']}"     if row.get("scope")   else "",
            f"Org: {row['org']}"         if row.get("org")     else "",
        ]))
        if meta: parts.append(meta)
        return "\n".join(parts)
