# Extraction des filtres de requete (concept/org/scope/continent/pays/seuil).
# Priorite aux detecteurs regex de query_patterns.py (rapides, pas d'appel
# reseau) ; le LLM n'est sollicite qu'en repli, quand la regex ne trouve rien
# (mode "auto", par defaut) - pour ne pas doubler la latence/cout de chaque
# requete avec un aller-retour LLM systematique.
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core.settings import settings
from app.services.inventory import GraphInventory, get_inventory
from app.services.threshold_store import ThresholdStore, get_threshold_store
from app.services.rag_chain import get_llm_backends
from app.services.query_patterns import (
    _THRESHOLD_FIELDS, _LE_WORDS, _GE_WORDS,
    _detect_concept, _detect_org, _detect_scope, _detect_continent,
)

log = structlog.get_logger()


@dataclass
class QueryFilters:
    concept:         str | None = None
    org:             str | None = None
    scope:           str | None = None
    continent:       str | None = None
    countries:       list[str] = field(default_factory=list)
    threshold_field: str | None = None   # minCrown | minArea | minHeight | minWidth
    threshold_op:    str | None = None   # "le" | "ge"
    threshold_value: float | None = None
    source:          str = "regex"       # "regex" | "llm"

    def is_empty(self) -> bool:
        """
        'concept' est exclu expres : le pattern generique \\bforest\\w*\\b
        (query_patterns.py) matche quasiment toutes les questions du domaine,
        donc concept='forest' ne veut pas dire qu'on a trouve un filtre
        specifique - juste que la question parle de foret. Sans cette
        exclusion, le mode "auto" ne declenchait jamais le LLM des que le mot
        "forest" apparaissait (ie. presque toujours), meme quand org/scope/
        continent/seuil n'avaient rien trouve - typiquement une organisation
        pas encore dans _ORG_PATTERNS (ex: "REDD+" ajoutee au graphe apres
        coup) passait inapercue indefiniment.
        """
        return not any([self.org, self.scope, self.continent,
                        self.countries, self.threshold_field])


def _regex_threshold(query: str) -> tuple[str | None, str | None, float | None]:
    """Meme logique que _filter_by_threshold (retriever.py) mais renvoie le
    triplet (champ, operateur, valeur) au lieu de filtrer une liste de docs -
    reutilisable independamment de HybridRetriever."""
    for field_name, field_kw, unit in _THRESHOLD_FIELDS:
        if not re.search(field_kw, query, re.IGNORECASE):
            continue
        num_match = re.search(rf'(\d+(?:\.\d+)?)\s*(?:{unit})', query, re.IGNORECASE)
        if not num_match:
            continue
        value = float(num_match.group(1))
        if _LE_WORDS.search(query):
            return field_name, "le", value
        if _GE_WORDS.search(query):
            return field_name, "ge", value
    return None, None, None


def regex_extract(query: str) -> QueryFilters:
    """Enrobe les detecteurs regex existants sans changer leur comportement."""
    threshold_field, threshold_op, threshold_value = _regex_threshold(query)
    return QueryFilters(
        concept=_detect_concept(query),
        org=_detect_org(query),
        scope=_detect_scope(query),
        continent=_detect_continent(query),
        threshold_field=threshold_field,
        threshold_op=threshold_op,
        threshold_value=threshold_value,
        source="regex",
    )


_EXTRACTION_PROMPT_TEMPLATE = """\
You extract structured search filters from a question about forest \
definitions. Respond ONLY with a single JSON object, no prose, matching \
exactly this shape:

{{"concept": <string or null>, "org": <string or null>, \
"scope": <string or null>, "continent": <string or null>, \
"countries": [<string>, ...], "threshold_field": <string or null>, \
"threshold_op": <"le"|"ge"|null>, "threshold_value": <number or null>}}

Rules:
- concept MUST be one of: {concepts} (or null if none applies)
- org MUST be one of: {orgs} (or null)
- scope MUST be one of: {scopes} (or null)
- continent MUST be one of: {continents} (or null)
- countries: real country names explicitly mentioned in the question, [] if none
- threshold_field MUST be one of: minCrown, minArea, minHeight, minWidth (or null)
- threshold_op: "le" if the question asks for a value at most / or less / \
below a number, "ge" if at least / or more / above, else null
- threshold_value: the numeric value mentioned with the threshold, else null
- Never invent a value outside the allowed lists above. If unsure, use null.
"""


def _build_prompt(inventory: GraphInventory) -> str:
    return _EXTRACTION_PROMPT_TEMPLATE.format(
        concepts=", ".join(sorted(inventory.concepts)) or "(none)",
        orgs=", ".join(sorted(inventory.orgs)) or "(none)",
        scopes=", ".join(sorted(inventory.scopes)) or "(none)",
        continents=", ".join(sorted(inventory.continents)) or "(none)",
    )


def _parse_llm_json(content: str) -> dict[str, Any] | None:
    content = content.strip()
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
    return None


def llm_extract(query: str, inventory: GraphInventory,
                 backends: list[tuple[str, Any]]) -> QueryFilters | None:
    """
    Essaie chaque backend LLM dans l'ordre (meme logique de repli que
    RAGChain.generate) ; renvoie None si tous echouent ou si le JSON est
    invalide - jamais d'exception qui remonterait a l'appelant.
    """
    if not backends:
        return None

    from langchain_core.messages import SystemMessage, HumanMessage
    messages = [SystemMessage(content=_build_prompt(inventory)),
                HumanMessage(content=f"Question: {query}")]

    for name, llm in backends:
        try:
            response = llm.invoke(messages)
        except Exception as e:
            log.warning("llm_extract_backend_failed", backend=name, error=str(e)[:120])
            continue

        data = _parse_llm_json(response.content)
        if data is None:
            log.warning("llm_extract_parse_failed", backend=name)
            continue

        return QueryFilters(
            concept=data.get("concept") or None,
            org=data.get("org") or None,
            scope=data.get("scope") or None,
            continent=data.get("continent") or None,
            countries=[c for c in (data.get("countries") or []) if isinstance(c, str)],
            threshold_field=data.get("threshold_field") or None,
            threshold_op=data.get("threshold_op") or None,
            threshold_value=(float(data["threshold_value"])
                              if data.get("threshold_value") is not None else None),
            source="llm",
        )
    return None


def _validate_against_inventory(filters: QueryFilters, inventory: GraphInventory) -> None:
    """Rejette (remet a None) toute valeur choisie par le LLM qui n'existe pas
    reellement dans le graphe - garde-fou anti-hallucination."""
    def _check(value: str | None, valid: dict[str, str], kind: str) -> str | None:
        if value is None:
            return None
        match = {k.lower(): k for k in valid}.get(value.lower())
        if match is None:
            log.warning("llm_filter_rejected", kind=kind, value=value)
        return match

    filters.concept   = _check(filters.concept,   inventory.concepts,   "concept")
    filters.org       = _check(filters.org,       inventory.orgs,       "org")
    filters.scope     = _check(filters.scope,     inventory.scopes,     "scope")
    filters.continent = _check(filters.continent, inventory.continents, "continent")


def _validate_countries(filters: QueryFilters, threshold_store: ThresholdStore) -> None:
    """Valide les pays proposes par le LLM contre la liste reelle du Table 3 -
    les LLM peuvent halluciner un nom de pays qui n'existe pas dans nos donnees."""
    if not filters.countries:
        return
    known_lower = {c.lower(): c for c in threshold_store.get_all_countries()}
    validated: list[str] = []
    for c in filters.countries:
        match = known_lower.get(c.lower())
        if match is None:
            match = next((real for low, real in known_lower.items()
                          if c.lower() in low or low in c.lower()), None)
        if match:
            validated.append(match)
        else:
            log.warning("llm_country_rejected", country=c)
    filters.countries = validated


def _merge(base: QueryFilters, enhancement: QueryFilters) -> QueryFilters:
    """Le LLM ne peut qu'enrichir un champ laisse vide par la regex, jamais
    ecraser ni faire regresser un resultat deja trouve."""
    return QueryFilters(
        concept=base.concept or enhancement.concept,
        org=base.org or enhancement.org,
        scope=base.scope or enhancement.scope,
        continent=base.continent or enhancement.continent,
        countries=base.countries or enhancement.countries,
        threshold_field=base.threshold_field or enhancement.threshold_field,
        threshold_op=base.threshold_op or enhancement.threshold_op,
        threshold_value=(base.threshold_value if base.threshold_value is not None
                          else enhancement.threshold_value),
        source="llm" if enhancement.source == "llm" else base.source,
    )


def extract_filters(query: str,
                     threshold_store: ThresholdStore | None = None,
                     backends: list[tuple[str, Any]] | None = None,
                     force_llm: bool = False) -> QueryFilters:
    """
    Point d'entree unique, reutilise par HybridRetriever et AgentRAG.
    1. regex_extract() d'abord (rapide, pas d'appel LLM).
    2. Si la regex n'a rien trouve et qu'un backend LLM est disponible (ou si
       force_llm/mode="always"), tente llm_extract() en 2e passe, grounde
       dans l'inventaire reel du graphe (chantier 1).
    3. Valide/filtre les valeurs LLM contre le graphe et la liste des pays
       connus avant de les fusionner avec le resultat regex.
    """
    ts = threshold_store or get_threshold_store()
    base = regex_extract(query)

    mode = settings.llm_extraction_mode
    if mode == "off":
        return base
    should_try_llm = force_llm or mode == "always" or (mode == "auto" and base.is_empty())
    if not should_try_llm:
        return base

    inventory = get_inventory()
    llm_backends = backends if backends is not None else get_llm_backends()
    enhancement = llm_extract(query, inventory, llm_backends)
    if enhancement is None:
        return base

    _validate_against_inventory(enhancement, inventory)
    _validate_countries(enhancement, ts)
    merged = _merge(base, enhancement)
    log.info("filter_extraction_llm_used", query=query[:60], filters=str(merged))
    return merged
