# Inventaire dynamique du graphe : orgs, continents, scopes, concepts.
# Remplace les listes codees en dur qui devaient etre resynchronisees a la
# main avec kg-builder/builder/skos_builder.py (source de verite reelle) et
# qui avaient fini par diverger (ex: CONTINENT_PATTERNS duplique a l'identique
# entre retriever.py et threshold_store.py -> 52 pays "Afrique" d'un cote,
# 46 dans le graphe de l'autre).
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from app.services.graph_store import GraphStore, get_graph_store

# Table de synonymes continent - source unique desormais (importee par
# retriever.py et threshold_store.py au lieu d'etre copiee dans les deux).
CONTINENT_PATTERNS: list[tuple[str, str]] = [
    (r'\bafrica\w*\b',           'Africa'),
    (r'\beurope\w*\b',           'Europe'),
    (r'\basia\w*\b',             'Asia'),
    (r'\bsouth\s*america\w*\b',  'SouthAmerica'),
    (r'\bnorth\s*america\w*\b',  'NorthAmerica'),
    (r'\boceania\w*\b',          'Oceania'),
    (r'\blatin\s*america\w*\b',  'SouthAmerica'),
    (r'\bamericas?\b',           'SouthAmerica'),
]


@dataclass
class GraphInventory:
    concepts:   dict[str, str] = field(default_factory=dict)  # ex:<Label>            (top concepts)
    orgs:       dict[str, str] = field(default_factory=dict)  # ex:Org_<key>
    scopes:     dict[str, str] = field(default_factory=dict)  # ex:Scope_<key>
    continents: dict[str, str] = field(default_factory=dict)  # ex:Continent_<key>


def _local_name(uri: str, prefix: str = "") -> str:
    frag = uri.rsplit("/", 1)[-1]
    return frag[len(prefix):] if prefix and frag.startswith(prefix) else frag


def _collection_members(gs: GraphStore, prefix: str) -> dict[str, str]:
    """skos:Collection dont l'URI commence par ex:<prefix> -> {cle: prefLabel}."""
    rows = gs.query_sparql(f"""
SELECT ?uri ?label WHERE {{
    ?uri a skos:Collection ;
         skos:prefLabel ?label .
    FILTER(STRSTARTS(STR(?uri), CONCAT(STR(ex:), "{prefix}")))
}}
""")
    return {_local_name(r["uri"], prefix): r["label"] for r in rows}


def discover_inventory(gs: GraphStore | None = None) -> GraphInventory:
    """4 requetes SPARQL locales (graphe deja en memoire, pas de reseau)."""
    gs = gs or get_graph_store()

    concept_rows = gs.query_sparql("""
SELECT ?uri ?label WHERE {
    ?uri skos:topConceptOf ex:ForestScheme ;
         skos:prefLabel ?label .
    FILTER(LANG(?label) = 'en')
}
""")
    concepts = {_local_name(r["uri"]): r["label"] for r in concept_rows}

    return GraphInventory(
        concepts=concepts,
        orgs=_collection_members(gs, "Org_"),
        scopes=_collection_members(gs, "Scope_"),
        continents=_collection_members(gs, "Continent_"),
    )


@lru_cache(maxsize=1)
def get_inventory() -> GraphInventory:
    return discover_inventory(get_graph_store())


def _pattern_targets(patterns: list[tuple[str, str]]) -> set[str]:
    return {key for _, key in patterns}


def validate_patterns(inventory: GraphInventory) -> list[str]:
    """
    Compare les cles ciblees par les tables de regex de query_patterns.py aux
    cles reellement presentes dans le graphe. Ne leve jamais - retourne des
    messages a logger. Import de query_patterns.py fait ici (et pas en tete
    de module) pour eviter un cycle d'import : query_patterns.py importe
    CONTINENT_PATTERNS depuis ce module.
    """
    from app.services.query_patterns import _CONCEPT_PATTERNS, _ORG_PATTERNS, _SCOPE_PATTERNS

    warnings: list[str] = []

    def _check(kind: str, pattern_keys: set[str], graph_keys: dict[str, str],
               collection_prefix: str | None) -> None:
        graph_lower = {k.lower() for k in graph_keys}
        pattern_lower = {k.lower() for k in pattern_keys}
        for key in sorted(pattern_keys):
            if key.lower() not in graph_lower:
                where = f"ex:{collection_prefix}{key}" if collection_prefix else f"ex:{key}"
                warnings.append(
                    f"{kind}: pattern '{key}' sans correspondance dans le graphe "
                    f"({where} absent) - pattern mort"
                )
        for key in sorted(graph_keys):
            if key.lower() not in pattern_lower:
                warnings.append(
                    f"{kind}: '{key}' existe dans le graphe mais aucune regex ne le "
                    f"detecte - entite invisible en recherche texte"
                )

    _check("concept",   _pattern_targets(_CONCEPT_PATTERNS),    inventory.concepts,   None)
    _check("org",       _pattern_targets(_ORG_PATTERNS),        inventory.orgs,       "Org_")
    _check("scope",     _pattern_targets(_SCOPE_PATTERNS),      inventory.scopes,     "Scope_")
    _check("continent", _pattern_targets(CONTINENT_PATTERNS),   inventory.continents, "Continent_")

    return warnings
