# Retrieval hybride vectoriel + SPARQL avec fusion RRF
from __future__ import annotations

import re
from typing import Any

from app.core.settings import settings
from app.services.graph_store import GraphStore, get_graph_store
from app.services.vector_store import VectorStore, get_vector_store
from app.services.threshold_store import ThresholdStore, get_threshold_store
from app.services.criteria_store import CriteriaStore, get_criteria_store

_RRF_K = 60


def _normalise_country(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "-", s.lower()).strip("-")

# Détection de concept

# Ordre important : les plus spécifiques d'abord
_CONCEPT_PATTERNS: list[tuple[str, str]] = [
    (r'\bdeforestat\w+\b',        'deforestation'),
    (r'\bafforestat\w+\b',        'afforestation'),
    (r'\breforestat\w+\b',        'reforestation'),
    (r'\bwoodland\w*\b',          'woodland'),
    (r'\btree\s+cover\b',         'tree'),
    (r'\bplantation\w*\b',        'plantation'),
    (r'\bdegradation\w*\b',       'degradation'),
    (r'\bforest\w*\b',            'forest'),
]

_SCOPE_PATTERNS: list[tuple[str, str]] = [
    (r'\b(?:international|global|worldwide)\b', 'International'),
    (r'\b(?:national|country|countries|federal|domestic)\b', 'National'),
    (r'\b(?:local|municipal|regional|sub.?national|state)\b', 'Local'),
]

# Organisations spécifiques — filtrées via dct:creator, pas dct:spatial
_THRESHOLD_PATTERNS = re.compile(
    r'\b(threshold|criteria|criterion|minimum|crown\s*cover|canopy\s*cover|'
    r'tree\s*height|minimum\s*area|hectare|ha\b|crown\s*density|'
    r'seuil|superficie|couverture|hauteur|crit[eè]re)\b',
    re.IGNORECASE,
)


def _is_threshold_query(query: str) -> bool:
    return bool(_THRESHOLD_PATTERNS.search(query))


_CONTINENT_PATTERNS: list[tuple[str, str]] = [
    (r'\bafrica\w*\b',           'Africa'),
    (r'\beurope\w*\b',           'Europe'),
    (r'\basia\w*\b',             'Asia'),
    (r'\bsouth\s*america\w*\b',  'SouthAmerica'),
    (r'\bnorth\s*america\w*\b',  'NorthAmerica'),
    (r'\boceania\w*\b',          'Oceania'),
    (r'\blatin\s*america\w*\b',  'SouthAmerica'),
]


def _detect_continent(query: str) -> str | None:
    for pattern, continent in _CONTINENT_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            return continent
    return None


_ORG_PATTERNS: list[tuple[str, str]] = [
    (r'\bunfccc\b',                  'UNFCCC'),
    (r'\bfao\b',                     'FAO'),
    (r'\bipcc\b',                    'IPCC'),
    (r'\bipbes\b',                   'IPBES'),
    (r'\b(?:eu|european\s+union)\b', 'EU'),
    (r'\bworld\s*bank\b',            'World Bank'),
    (r'\bunep\b',                    'UNEP'),
]


def _detect_concept(query: str) -> str | None:
    q = query.lower()
    for pattern, concept in _CONCEPT_PATTERNS:
        if re.search(pattern, q):
            return concept
    return None


def _detect_scope(query: str) -> str | None:
    q = query.lower()
    for pattern, scope in _SCOPE_PATTERNS:
        if re.search(pattern, q):
            return scope
    return None


def _detect_org(query: str) -> str | None:
    q = query.lower()
    for pattern, org in _ORG_PATTERNS:
        if re.search(pattern, q):
            return org
    return None


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
        criteria_store:  CriteriaStore  | None = None,
    ):
        self._gs = graph_store     or get_graph_store()
        self._vs = vector_store    or get_vector_store()
        self._ts = threshold_store or get_threshold_store()
        self._cs = criteria_store  or get_criteria_store()

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        k       = top_k or settings.retrieval_top_k
        fetch_k = k * 3

        # Détection sémantique de la requête
        concept = _detect_concept(query)
        org     = _detect_org(query)
        # Quand une org spécifique est détectée, le scope géographique est redondant
        # et filtre à tort les docs dont dct:spatial ≠ "international"
        scope   = _detect_scope(query) if not org else None

        # Bras 1 : vectoriel
        vec_docs = self._vs.search(query, top_k=fetch_k) if self._vs.is_indexed() else []

        # Bras 2 : SPARQL (avec filtres concept + scope + org)
        sparql_docs = self._gs.search_by_keyword(
            query, top_k=fetch_k, concept=concept, scope=scope, org=org
        )

        # Fusion RRF
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

        merged = sorted(uri_data.values(), key=lambda d: -d["rrf_score"])[:k]

        # Enrichissement contextuel (graphe RDF)
        for doc in merged:
            uri = doc["metadata"].get("uri", "")
            if uri:
                ctx = self._gs.get_context(uri)
                if ctx:
                    doc["graph_context"] = ctx

        # Enrichissement seuils via le graphe
        continent = _detect_continent(query)
        if _is_threshold_query(query) or continent:
            orgs_explicit = self._cs.extract_orgs(query)

            # Recherche par continent via SPARQL sur le graphe
            if continent:
                continent_docs = self._gs.search_continent_thresholds(continent)
                # Filtrer par seuil si demande (ex: "crown cover 30%")
                crown_match = re.search(r'crown\s*cover.*?(\d+)\s*%', query, re.IGNORECASE)
                if crown_match:
                    min_crown = float(crown_match.group(1))
                    continent_docs = [d for d in continent_docs
                                      if d.get("minCrown") and float(d["minCrown"]) >= min_crown]
                # dict.fromkeys pour dédupliquer sans perdre le tri par richesse
                # de search_continent_thresholds (un set() mélange l'ordre).
                countries_ctx = list(dict.fromkeys(d["country"] for d in continent_docs))
            else:
                countries_ctx = list(self._ts.extract_countries_from_query(query))

            if not countries_ctx:
                for doc in merged[:3]:
                    c = doc["metadata"].get("country", "")
                    if c and c not in countries_ctx:
                        countries_ctx.append(c)

            already_uris = {doc["metadata"].get("uri") for doc in merged}
            threshold_docs: list[dict] = []

            # Un continent peut compter jusqu'à ~46 pays (Afrique) : une
            # question d'énumération ("which countries...", "how many...")
            # a besoin de la couverture complète, pas d'un top 10 arbitraire.
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

            # Org détectée sans pays explicite → critères extraits du texte
            for org_name in orgs_explicit[:2]:
                cr_ctx = self._cs.format_as_context(org=org_name, max_entries=5)
                if cr_ctx:
                    threshold_docs.append({
                        "text": cr_ctx,
                        "metadata": {
                            "uri":     f"criteria://{org_name.lower()}",
                            "label":   f"Forest criteria: {org_name}",
                            "def":     cr_ctx,
                            "country": "",
                            "year":    "",
                            "scope":   "International",
                            "org":     org_name,
                        },
                        "sources":       ["sparql", "threshold"],
                        "vec_rank":      None,
                        "sparql_rank":   None,
                        "rrf_score":     0.04,
                        "vector_score":  0,
                        "sparql_score":  0,
                        "graph_context": cr_ctx,
                    })

            # Insertion en position 1 (après le meilleur doc naturel)
            if threshold_docs and (countries_ctx or orgs_explicit):
                insert_pos = min(1, len(merged))
                for s in reversed(threshold_docs):
                    merged.insert(insert_pos, s)
            else:
                merged.extend(threshold_docs)

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
