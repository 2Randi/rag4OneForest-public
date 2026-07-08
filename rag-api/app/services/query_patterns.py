# Detection texte -> cle canonique (concept/org/scope/continent/seuil).
# Isole des autres modules de retrieval pour eviter un cycle d'import :
# filter_extractor.py (LLM, chantier 2) et retriever.py (chantier 3) ont tous
# les deux besoin de ces detecteurs regex, mais ne doivent pas s'importer l'un
# l'autre.
from __future__ import annotations

import re

from app.services.inventory import CONTINENT_PATTERNS

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


def _detect_continent(query: str) -> str | None:
    for pattern, continent in CONTINENT_PATTERNS:
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
