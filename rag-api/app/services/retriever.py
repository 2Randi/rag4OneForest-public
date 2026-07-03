# Retrieval hybride vectoriel + SPARQL avec fusion RRF
from __future__ import annotations

import re
from typing import Any

from app.core.settings import settings
from app.services.graph_store import GraphStore, get_graph_store
from app.services.vector_store import VectorStore, get_vector_store
from app.services.threshold_store import ThresholdStore, get_threshold_store

_RRF_K = 60


def _normalise_country(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "-", s.lower()).strip("-")

# champs numeriques qu'on peut filtrer, avec le mot-cle et l'unite qui va avec
_THRESHOLD_FIELDS: list[tuple[str, str, str]] = [
    ("minCrown",  r'crown\s*cover|canopy\s*cover', r'%'),
    ("minArea",   r'\barea\b|hectares?|\bha\b',    r'ha\b|hectares?'),
    ("minHeight", r'tree\s*height|\bheight\b',     r'm\b|meters?|metres?'),
    ("minWidth",  r'strip\s*width|\bwidth\b',      r'm\b|meters?|metres?'),
]
# "minimum"/"maximum" pas dedans expres: dans ce domaine c'est juste le nom
# du champ ("Minimum Area"), pas forcement une direction de comparaison
_LE_WORDS = re.compile(
    r'or\s+less|or\s+lower|or\s+below|no\s+more\s+than|at\s+most|under|below|less\s+than|up\s+to',
    re.IGNORECASE)
_GE_WORDS = re.compile(
    r'or\s+more|or\s+higher|or\s+above|no\s+less\s+than|at\s+least|over|above|more\s+than',
    re.IGNORECASE)


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
            return [d for d in docs if d.get(field) and float(d[field]) <= value]
        if _GE_WORDS.search(query):
            return [d for d in docs if d.get(field) and float(d[field]) >= value]
    return docs

# Détection de concept

# ordre important : les plus specifiques d'abord. alignee sur les 15
# top-concepts reels du graphe (ex:ForestScheme), sinon la moitie d'entre
# eux (NaturalForest, LandUse, Regeneration...) ne matchent jamais
_CONCEPT_PATTERNS: list[tuple[str, str]] = [
    (r'\bdeforestat\w+\b',                     'deforestation'),
    (r'\bafforestat\w+\b',                     'afforestation'),
    (r'\breforestat\w+\b',                     'reforestation'),
    (r'\bregenerat\w+\b',                      'regeneration'),
    (r'\bsemi[\s\-]?natural\s+forest\w*\b',    'seminaturalforest'),
    (r'\bnative\s+forest\w*\b',                'nativeforest'),
    (r'\bnatural\s+forest\w*\b',               'naturalforest'),
    (r'\bnon[\s\-]?forest\w*\b',               'nonforest'),
    (r'\bwoodland\w*\b',                       'woodland'),
    (r'\btree\s+cover\b',                      'tree'),
    (r'\bplantation\w*\b',                     'plantation'),
    (r'\bdegradation\w*\b',                    'degradation'),
    (r'\bland\s*cover\w*\b',                   'landcover'),
    (r'\bland\s*use\w*\b',                     'landuse'),
    (r'\bforest\w*\b',                         'forest'),
]

# les valeurs renvoyees doivent matcher exactement skos:scopeNote dans le
# graphe (General/International/National/State), pas des synonymes a nous
_SCOPE_PATTERNS: list[tuple[str, str]] = [
    (r'\b(?:international|global|worldwide)\b',                    'International'),
    (r'\b(?:local|municipal|regional|sub.?national|province\w*)\b', 'State'),
    (r'\b(?:state|provincial)\b',                                  'State'),
    (r'\b(?:national|country|countries|federal|domestic)\b',       'National'),
    (r'\b(?:general|generic|broad)\b',                             'General'),
]

# Organisations spécifiques — filtrées via dct:creator, pas dct:spatial
_THRESHOLD_PATTERNS = re.compile(
    r'\b(threshold|criteria|criterion|minimum|maximum|crown\s*cover|canopy\s*cover|'
    r'tree\s*height|\barea\b|hectares?|\bha\b|crown\s*density|strip\s*width|'
    r'\bwidth\b|\btall\b|meters?|metres?|'
    r'seuil|superficie|couverture|hauteur|largeur|crit[eè]re)\b',
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


# alignee sur ORG_COLLECTIONS dans kg-builder/builder/skos_builder.py, sinon
# une orga qui existe bien dans le graphe (ex: WWF, IUCN, ITTO) ne matche
# jamais parce qu'on l'a pas mise ici
_ORG_PATTERNS: list[tuple[str, str]] = [
    (r'\bkp[l]?\b|\bkyoto\s+protocol\b',           'KP'),
    (r'\bun-?fa[o0]\b|\bun-?fra\b|\bgfra\b|\btbfra\b|\bfao\b', 'FAO'),
    (r'\bipcc\b',                                  'IPCC'),
    (r'\beu\b|\beuropean\s+(union|community|environment|commission)\b|\beurostat\b|\beea\b', 'EU'),
    (r'\bworld\s*bank\b',                          'WorldBank'),
    (r'\bsaf\b|\bsociety\s+of\s+american\s+foresters\b', 'SAF'),
    (r'\bun-?ep\b|\bunep\b',                       'UNEP'),
    (r'\bnir\b|\bnational\s+inventory\s+reports?\b', 'NIR'),
    (r'\bnfi\b|\bnational\s+forest\s+inventor',    'NFI'),
    (r'\bun-?fccc\b|\bunfccc\b',                   'UNFCCC'),
    (r'\busa-fed\b|\busda\b',                      'USDAFS'),
    (r'\biucn\b',                                  'IUCN'),
    (r'\bitto\b',                                  'ITTO'),
    (r'\biufro\b',                                 'IUFRO'),
    (r'\bwwf\b',                                   'WWF'),
    (r'\bwri\b|\bworld\s+resources\s+institute\b', 'WRI'),
    (r'\bwcmc\b|\bunep-wcmc\b',                    'WCMC'),
    (r'\bipbes\b',                                 'IPBES'),
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
    ):
        self._gs = graph_store     or get_graph_store()
        self._vs = vector_store    or get_vector_store()
        self._ts = threshold_store or get_threshold_store()

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
            # Recherche par continent via SPARQL sur le graphe
            if continent:
                continent_docs = self._gs.search_continent_thresholds(continent)
                continent_docs = _filter_by_threshold(continent_docs, query)
                # dict.fromkeys dédupe sans perdre l'ordre (un set() mélange tout)
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
