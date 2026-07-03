# Construction du graphe RDF/SKOS depuis les definitions extraites
from __future__ import annotations

import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace, Literal, RDF, RDFS, URIRef
from rdflib.namespace import SKOS, DCTERMS, XSD
from langdetect import detect, DetectorFactory

DetectorFactory.seed = 42

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Collections organisations : (clé, label affiché, pattern regex sur org_str)
ORG_COLLECTIONS: list[tuple[str, str, str]] = [
    ("KP",        "Kyoto Protocol",                 r'\bKP[l]?\b'),
    ("FAO",       "FAO / UN-FAO",                   r'\bUN-?FA[O0]\b|\bUN-?FRA\b|\bGFRA\b|\bTBFRA\b|\bFAO\b'),
    ("IPCC",      "IPCC",                           r'\bIPCC\b'),
    ("EU",        "European Union / EC",            r'\bEU\b|\bEuropean[\s\-]+(Union|Community|Environment|Commission)\b|\bEUROSTAT\b|\bEEA\b'),
    ("WorldBank", "World Bank",                     r'\bWorld\s*Bank\b'),
    ("SAF",       "Society of American Foresters",  r'\bSAF\b'),
    ("UNEP",      "UNEP / UN-EP",                   r'\bUN-?EP\b|\bUNEP\b'),
    ("NIR",       "National Inventory Reports",     r'\bNIR\b'),
    ("NFI",       "National Forest Inventories",    r'\bNFI\b'),
    ("UNFCCC",    "UNFCCC",                         r'\bUN-?FCCC\b|\bUNFCCC\b'),
    ("USDAFS",    "USDA Forest Service",            r'\bUSA-FED\b|\bUSDA\b'),
    ("IUCN",      "IUCN",                           r'\bIUCN\b'),
    ("ITTO",      "ITTO",                           r'\bITTO\b'),
    ("IUFRO",     "IUFRO",                          r'\bIUFRO\b'),
    ("WWF",       "WWF",                            r'\bWWF\b'),
    ("WRI",       "WRI / World Resources Institute",r'\bWRI\b'),
    ("WCMC",      "WCMC / UNEP-WCMC",              r'\bWCMC\b'),
]
from config import settings
from extractor.docx_extractor import DefinitionRecord, Table3Record


# Namespaces
EX  = Namespace(settings.base_uri)
AGV = Namespace(settings.agrovoc_uri)
AFO = Namespace(settings.afo_uri)


# Helpers module-level

def _make_camel(label: str) -> str:
    """
    Convertit un label en CamelCase URI fragment.
    'carbon stock' → 'CarbonStock'
    Identique à make_uri() de build_graph.py.
    """
    clean = re.sub(r"[^A-Za-z0-9 ]", " ", label)
    parts = clean.split()
    return "".join(p.capitalize() for p in parts if p)


def _lang_literal(text: str) -> Optional[Literal]:
    """Crée un Literal avec tag de langue détecté automatiquement."""
    if not text or not text.strip() or text == "nan":
        return None
    t = text.strip()
    try:
        lang = detect(t)
    except Exception:
        lang = "en"
    return Literal(t, lang=lang)


def _label_literal(text: str) -> Optional[Literal]:
    """
    Pareil que _lang_literal mais pour les labels courts (1-3 mots, genre
    "FORESTRY", "STAND"). langdetect se plante souvent dessus (verifie :
    "FORESTRY" detecte comme allemand, "STAND" pareil, sur des milliers
    de labels). Sur des mots seuls y a pas assez de signal, donc pas la
    peine d'essayer, on part sur anglais direct.
    """
    if not text or not text.strip() or text == "nan":
        return None
    return Literal(text.strip(), lang="en")


def _decimal_literal(val) -> Optional[Literal]:
    """Convertit une valeur numérique en xsd:decimal."""
    try:
        return Literal(Decimal(str(float(str(val).strip()))), datatype=XSD.decimal)
    except Exception:
        return None


def _parse_range(val: str) -> tuple[Optional[float], Optional[float]]:
    """
    Parse une plage ou valeur numérique.
    '10-30' → (10.0, 30.0) | '0.5' → (0.5, None) | 'NS' → (None, None)
    """
    s = str(val).strip() if val and str(val).strip() not in ("", "nan") else ""
    if not s or s.lower() in ("ns", "n.s.", "-", ""):
        return None, None
    m = re.match(r'([\d.]+)\s*[-–/]\s*([\d.]+)', s)
    if m:
        return float(m.group(1)), float(m.group(2))
    try:
        v = float(re.sub(r'[^\d.]', '', s))
        return v, None
    except Exception:
        return None, None


def _is_unfccc_source(s: str) -> bool:
    """True si la source cite une définition UNFCCC ou Kyoto Protocol."""
    if not isinstance(s, str):
        return False
    return bool(re.search(r'\b(KPl?|UNFCCC)\b', s, re.IGNORECASE))


def _normalize_country_name(s: str) -> str:
    """
    Normalise un champ pays/source en retirant année, acronymes (UNFCCC, KP, FREL)
    et caractères parasites. Fonctionne sur les deux côtés de la jointure :
      'Brazil 2015 KP'  → 'Brazil'
      'Brazil UNFCCC'   → 'Brazil'
    """
    if not isinstance(s, str):
        return ""
    s = re.sub(r'(19|20)\d{2}[?]?', '', s)
    s = re.sub(r'\b(KPl?|UNFCCC|FREL)\b', '', s, flags=re.IGNORECASE)
    s = re.sub(r'[&]+', '', s)
    return re.sub(r'\s+', ' ', s).strip(' -,.;')


# Constructeur principal

class SKOSBuilder:
    """
    Construit le graphe RDF/SKOS depuis des DefinitionRecord et Table3Record.

    Ordre d'appel recommandé :
        builder = SKOSBuilder()
        builder.build(records)                   # définitions textuelles
        builder.build_table3_concepts(t3_recs)   # concepts UNFCCC + seuils
        builder.enrich_from_agrovoc()            # descriptions Agrovoc (optionnel)
        g = builder.graph
    """

    def __init__(self):
        self.graph = Graph()
        self._bind_namespaces()

        # Registres internes
        self._top_concepts:      dict[str, URIRef] = {}   # title2_upper → URI
        self._scope_colls:       dict[str, URIRef] = {}   # scope  → Collection URI
        self._type_colls:        dict[str, URIRef] = {}   # type   → Collection URI
        self._org_colls:         dict[str, URIRef] = {}   # org key → Collection URI
        self._country_idx:       dict[str, list[URIRef]] = {}  # iso3 → [concept URIs]

        # Compteur pour URI uniques CamelCase (comme unique_uri() de build_graph.py)
        # 'CarbonStock' → 1re fois: ex:CarbonStock, 2e fois: ex:CarbonStock_2
        self._uri_counter:        dict[str, int] = {}

        # Stockage des définitions UNFCCC Forest pour la jointure Table 3
        self._unfccc_defs:        dict[str, list[DefinitionRecord]] = {}  # country_key → recs
        self._unfccc_concept_idx: dict[str, URIRef] = {}                  # country_key → URI

        # Initialisation du schéma
        self._scheme_uri = EX["ForestScheme"]
        self._init_scheme()
        self._init_properties()
        self._init_country_collections()
        self._init_top_concepts()
        self._init_collections()
        self._init_org_collections()
        self._init_related_links()

    # Initialisation

    def _bind_namespaces(self) -> None:
        g = self.graph
        g.bind("skos", SKOS)
        g.bind("dct",  DCTERMS)
        g.bind("ex",   EX)
        g.bind("agv",  AGV)
        g.bind("afo",  AFO)
        g.bind("xsd",  XSD)
        g.bind("rdfs", RDFS)

    def _init_scheme(self) -> None:
        g, s = self.graph, self._scheme_uri
        g.add((s, RDF.type,            SKOS.ConceptScheme))
        g.add((s, SKOS.prefLabel,      Literal("Forest Definitions Vocabulary", lang="en")))
        g.add((s, DCTERMS.title,       Literal("RAG4OneForest Knowledge Graph", lang="en")))
        g.add((s, DCTERMS.description, Literal(
            "SKOS vocabulary of forest, deforestation, afforestation and reforestation "
            "definitions compiled from Lund (2018) — used in the RAG4OneForest system "
            "within the RAG4OneForest project.", lang="en")))
        g.add((s, DCTERMS.source, Literal(
            "Lund, H.G. (2018). Definitions of Forest, Deforestation, "
            "Afforestation and Reforestation. Forest Information Services.")))
        g.add((s, DCTERMS.hasVersion, Literal("3.0")))

    def _init_properties(self) -> None:
        g = self.graph
        for prop_key, label in settings.numeric_properties.items():
            uri = EX[prop_key]
            g.add((uri, RDF.type,    RDF.Property))
            g.add((uri, RDFS.label,  Literal(label, lang="en")))
            g.add((uri, RDFS.domain, SKOS.Concept))
            g.add((uri, RDFS.range,  XSD.decimal))


    def _init_country_collections(self) -> None:
        """Cree la collection Countries et les collections par continent."""
        g = self.graph

        # Collection de tous les pays
        self._countries_coll = EX["Countries"]
        g.add((self._countries_coll, RDF.type,       SKOS.Collection))
        g.add((self._countries_coll, SKOS.prefLabel, Literal("All countries", lang="en")))

        # Collections par continent
        self._continent_colls: dict[str, URIRef] = {}
        continents = {
            "Africa":        "African countries",
            "Europe":        "European countries",
            "Asia":          "Asian countries",
            "SouthAmerica":  "South American countries",
            "NorthAmerica":  "North American countries",
            "Oceania":       "Oceanian countries",
        }
        for key, label in continents.items():
            uri = EX[f"Continent_{key}"]
            g.add((uri, RDF.type,       SKOS.Collection))
            g.add((uri, SKOS.prefLabel, Literal(label, lang="en")))
            self._continent_colls[key] = uri

    def _fetch_agrovoc_description(self, agv_uri: str) -> Optional[str]:
        """
        Récupère la skos:definition anglaise d'un concept Agrovoc via SPARQL.
        Agrovoc stocke la définition dans un nœud intermédiaire :
          <concept> skos:definition ?node . ?node rdf:value ?text .
        Retourne None si l'endpoint est inaccessible ou le concept sans définition.
        """
        try:
            from rdflib.plugins.stores.sparqlstore import SPARQLStore
        except ImportError:
            return None
        try:
            store = SPARQLStore(settings.agrovoc_sparql_endpoint)
            g2 = Graph(store=store)
            q = f"""
                PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
                PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                SELECT ?text WHERE {{
                    <{agv_uri}> skos:definition ?defNode .
                    ?defNode rdf:value ?text .
                    FILTER (langMatches(lang(?text), "en"))
                }}
                LIMIT 1
            """
            for row in g2.query(q):
                return str(row[0])
        except Exception:
            pass
        return None

    def _init_top_concepts(self) -> None:
        g, s = self.graph, self._scheme_uri
        for title2_key, label in settings.top_concept_labels.items():
            uri = EX[label]
            g.add((uri, RDF.type,           SKOS.Concept))
            g.add((uri, SKOS.inScheme,      s))
            g.add((uri, SKOS.topConceptOf,  s))
            g.add((uri, SKOS.prefLabel,     Literal(label, lang="en")))
            g.add((s,   SKOS.hasTopConcept, uri))

            # Alignement Agrovoc + récupération de la description via SPARQL
            key_upper = title2_key.upper()
            if key_upper in settings.agrovoc_alignments:
                agv_frag = settings.agrovoc_alignments[key_upper]
                agv_uri  = AGV[agv_frag]
                g.add((uri, SKOS.exactMatch, agv_uri))
                # Fetch de la définition Agrovoc - silencieux si l'endpoint est absent
                defn = self._fetch_agrovoc_description(str(agv_uri))
                if defn:
                    g.add((uri, SKOS.definition, Literal(defn, lang="en")))

            self._top_concepts[key_upper] = uri

    def _init_collections(self) -> None:
        g = self.graph
        scope_descs = {
            "General":       "General scope definitions",
            "International": "International scope definitions",
            "National":      "National scope definitions",
            "State":         "State/province level definitions",
        }
        for scope, desc in scope_descs.items():
            uri = EX[f"Scope_{scope}"]
            g.add((uri, RDF.type,            SKOS.Collection))
            g.add((uri, SKOS.prefLabel,      Literal(f"{scope} definitions", lang="en")))
            g.add((uri, DCTERMS.description, Literal(desc, lang="en")))
            self._scope_colls[scope] = uri

        type_descs = {
            "Declared":   "Declared, legal or administrative forest units",
            "Land use":   "Forest as a land use type",
            "Land cover": "Forest as a land cover type",
            "Ecological": "Ecological and miscellaneous forest definitions",
        }
        for ftype, desc in type_descs.items():
            uri = EX[f"Type_{ftype.replace(' ', '_')}"]
            g.add((uri, RDF.type,            SKOS.Collection))
            g.add((uri, SKOS.prefLabel,      Literal(f"{ftype} type", lang="en")))
            g.add((uri, DCTERMS.description, Literal(desc, lang="en")))
            self._type_colls[ftype] = uri

    def _init_org_collections(self) -> None:
        """Crée une skos:Collection par organisation internationale reconnue."""
        g = self.graph
        for key, label, _ in ORG_COLLECTIONS:
            uri = EX[f"Org_{key}"]
            g.add((uri, RDF.type,       SKOS.Collection))
            g.add((uri, SKOS.prefLabel, Literal(label, lang="en")))
            self._org_colls[key] = uri

    def _match_org_collections(self, org_str: str) -> list[URIRef]:
        """
        Retourne les URIs de collections organisation correspondant à org_str.
        Un concept peut appartenir à plusieurs collections (ex : NIR + KP).
        """
        if not org_str or not org_str.strip() or org_str in ("nan", "?"):
            return []
        matched = []
        for key, _, pattern in ORG_COLLECTIONS:
            if re.search(pattern, org_str, re.IGNORECASE):
                uri = self._org_colls.get(key)
                if uri:
                    matched.append(uri)
        return matched

    # code continent pycountry_convert -> clé ex:Continent_X dans le graphe
    _CONTINENT_CODES = {
        "AF": "Africa", "AS": "Asia", "EU": "Europe",
        "NA": "NorthAmerica", "SA": "SouthAmerica", "OC": "Oceania",
    }

    def _get_continent(self, iso3: str) -> str | None:
        # avant y avait une liste de ~174 pays codee a la main ici, et une
        # bonne vingtaine de vrais pays du graphe (dont les USA !) n'y
        # etaient juste pas, donc jamais rattaches a un continent. Autant
        # utiliser une vraie source de donnees pays -> continent
        import pycountry
        import pycountry_convert
        country = pycountry.countries.get(alpha_3=iso3)
        if not country:
            return None
        try:
            code = pycountry_convert.country_alpha2_to_continent_code(country.alpha_2)
        except KeyError:
            return None
        return self._CONTINENT_CODES.get(code)

    def _add_country_to_collections(self, country_uri: URIRef, iso3: str) -> None:
        """Ajoute un concept pays dans la collection Countries et son continent."""
        g = self.graph
        g.add((self._countries_coll, SKOS.member, country_uri))
        continent = self._get_continent(iso3)
        if continent and continent in self._continent_colls:
            g.add((self._continent_colls[continent], SKOS.member, country_uri))

    # des trucs qui trainent dans la colonne pays de table3.csv mais qui ne
    # sont pas des pays : des organisations, et la ligne d'en-tete du tableau
    _NOT_A_COUNTRY = {
        "eu", "iiasa", "sadc", "un ccd", "un esco", "un fcc", "un fccc",
        "un fra", "un lccs", "un land use",
    }

    # pays renommes officiellement que pycountry.search_fuzzy ne retrouve
    # plus depuis l'ancien nom courant (verifie un par un), ou formulations
    # sans "and" qui font echouer le matching flou
    _COUNTRY_ALIASES = {
        "turkey": "Turkiye",
        "swaziland": "Eswatini",
        "cape verde": "Cabo Verde",
        "antigua barbuda": "Antigua and Barbuda",
        "trinidad tobago": "Trinidad and Tobago",
        "st. kitts nevis": "Saint Kitts and Nevis",
        "western samoa": "Samoa",
        "korea- republic of": "Korea, Republic of",
        "moldova- republic of": "Moldova, Republic of",
        "libya arab jamahiriy": "Libya",
        "congo- republic of": "Congo",
        "congo (zaire)": "Congo, The Democratic Republic of the",
        "democratic republic congo": "Congo, The Democratic Republic of the",
    }

    def _resolve_country_uri(self, country_raw: str) -> URIRef | None:
        """
        Résout un nom de pays en concept ex:Country_ISO3 (le crée si besoin)
        et renvoie son URI. dct:spatial pointe vers ce concept au lieu de
        porter le nom en texte libre, comme ça les recherches par pays sont
        exactes au lieu de faire un CONTAINS fragile. None si vide ou si
        c'est pas un pays du tout (organisation, ligne d'en-tete...).
        """
        import pycountry

        country_raw = (country_raw or "").strip()
        if not country_raw or country_raw.lower() == "nan":
            return None

        key = country_raw.lower()
        if key in self._NOT_A_COUNTRY or "table 3" in key:
            return None

        # "Chile ()" -> "Chile" : parentheses vides qui trainent dans la source
        search_name = re.sub(r'\(\s*\)', '', country_raw).strip()
        search_name = self._COUNTRY_ALIASES.get(search_name.lower(), search_name)

        try:
            match = pycountry.countries.search_fuzzy(search_name)[0]
            iso3 = match.alpha_3
            display_name = match.name
        except Exception:
            iso3 = re.sub(r'[^A-Za-z0-9]', '_', country_raw)[:10].upper()
            display_name = country_raw

        g = self.graph
        country_uri = EX[f"Country_{iso3}"]
        if (country_uri, RDF.type, SKOS.Concept) not in g:
            g.add((country_uri, RDF.type,       SKOS.Concept))
            g.add((country_uri, SKOS.prefLabel, Literal(display_name, lang="en")))
            g.add((country_uri, SKOS.notation,  Literal(iso3)))
            g.add((country_uri, SKOS.inScheme,  self._scheme_uri))
            self._add_country_to_collections(country_uri, iso3)
        return country_uri

    def _init_related_links(self) -> None:
        """Relie les top-concepts par skos:related (relations associatives)."""
        g = self.graph
        for label_a, label_b in settings.related_pairs:
            uri_a = EX[label_a]
            uri_b = EX[label_b]
            if (uri_a, RDF.type, SKOS.Concept) in g and \
               (uri_b, RDF.type, SKOS.Concept) in g:
                g.add((uri_a, SKOS.related, uri_b))
                g.add((uri_b, SKOS.related, uri_a))

    # Métadonnées Dublin Core

    def _add_metadata(self, uri: URIRef, rec: DefinitionRecord) -> None:
        g = self.graph
        if rec.year and rec.year not in ("", "nan"):
            try:
                g.add((uri, DCTERMS.date, Literal(str(int(float(rec.year))), datatype=XSD.gYear)))
            except Exception:
                pass
        if rec.organization and rec.organization not in ("", "nan"):
            g.add((uri, DCTERMS.creator, Literal(rec.organization.strip())))
        country_uri = self._resolve_country_uri(rec.country)
        if country_uri:
            g.add((uri, DCTERMS.spatial, country_uri))
        for url in rec.urls:
            g.add((uri, DCTERMS.source, Literal(url, datatype=XSD.anyURI)))
        for ref in rec.references:
            g.add((uri, DCTERMS.bibliographicCitation, Literal(ref)))
        if rec.sources and rec.sources not in ("", "nan"):
            g.add((uri, SKOS.note, Literal(rec.sources)))

    def _unique_concept_uri(self, base: str) -> URIRef:
        """
        Retourne un URIRef CamelCase unique par compteur.
        Toujours suffixé _i (i commence à 1) :
          1re occurrence : ex:Forest_1
          2e occurrence  : ex:Forest_2
        Le top concept ex:Forest reste séparé (créé via EX[label] dans _init_top_concepts).
        """
        if not base:
            base = "Concept"
        base = base[0].upper() + base[1:]
        self._uri_counter[base] = self._uri_counter.get(base, 0) + 1
        return EX[f"{base}_{self._uri_counter[base]}"]

    # Construction des concepts textuels

    def build(self, records: list[DefinitionRecord]) -> None:
        """
        Construit les skos:Concept depuis les DefinitionRecord.

        Les définitions nationales UNFCCC pour Forest/Forest Land sont
        mises de côté dans _unfccc_defs pour être jointes dans
        build_table3_concepts(). Tous les autres records créent un concept.
        """
        import pycountry

        n_ok = n_skip = n_unfccc = 0
        for rec in records:
            if not rec.definition.strip():
                n_skip += 1
                continue

            t2_upper = (rec.title_2 or "").upper()

            # Filtrer les lignes non-concept (navigation, discussion, etc.)
            title_path = ", ".join(filter(None, [
                rec.title_1, rec.title_2, rec.title_3, rec.title_4
            ])).lower()
            if title_path in settings.non_concept_paths:
                n_skip += 1
                continue

            # Les définitions UNFCCC Forest sont réservées pour la jointure Table 3
            if _is_unfccc_source(rec.sources) and t2_upper == "FOREST/FOREST LAND":
                key = _normalize_country_name(rec.sources).lower()
                self._unfccc_defs.setdefault(key, []).append(rec)
                n_unfccc += 1
                continue

            # URI : premier bold_term (ex: ex:Treed_1) ou nom canonique du top concept
            # (ex: ex:Forest_1) quand pas de bold term.
            # Toujours suffixé _i pour que chaque concept ait un URI unique.
            first_term = rec.bold_terms.split(";")[0].strip() if rec.bold_terms else ""
            if first_term:
                base_label = _make_camel(first_term)
            else:
                # Utiliser le label canonique du top concept (« Forest », « Deforestation »…)
                # plutôt que le raw title_2 (« FOREST/FOREST LAND ») qui donnerait ForestForestLand
                top_canonical = settings.top_concept_labels.get(t2_upper, "")
                base_label = _make_camel(top_canonical) if top_canonical else "Concept"
            uri = self._unique_concept_uri(base_label)

            g = self.graph
            g.add((uri, RDF.type,      SKOS.Concept))
            g.add((uri, SKOS.inScheme, self._scheme_uri))

            # skos:broadMatch → top-concept (les définitions indexées sont plus
            # spécifiques que le concept général du thésaurus)
            parent_uri = self._top_concepts.get(t2_upper)
            if parent_uri:
                g.add((uri, SKOS.broadMatch, parent_uri))

            # prefLabel = premier bold_term ou title_2 par défaut
            pref_label = _label_literal(first_term or rec.title_2)
            if pref_label:
                g.add((uri, SKOS.prefLabel, pref_label))

            # altLabel = autres bold_terms séparés par ";"
            for alt in (rec.bold_terms.split(";")[1:] if rec.bold_terms else []):
                alt = alt.strip()
                if alt:
                    lbl = _label_literal(alt)
                    if lbl:
                        g.add((uri, SKOS.altLabel, lbl))

            # Définition textuelle
            def_lit = _lang_literal(rec.definition)
            if def_lit:
                g.add((uri, SKOS.definition, def_lit))

            # Scope (title_3) → scopeNote + Collection
            scope = settings.scope_map.get(rec.title_3, "")
            if not scope and rec.title_3 in settings.valid_scopes:
                scope = rec.title_3
            if scope:
                g.add((uri, SKOS.scopeNote, Literal(scope, lang="en")))
                if scope in self._scope_colls:
                    g.add((self._scope_colls[scope], SKOS.member, uri))

            # Type (title_4) → scopeNote + Collection
            ftype = settings.type_map.get(rec.title_4, "")
            if ftype:
                g.add((uri, SKOS.scopeNote, Literal(ftype, lang="en")))
                if ftype in self._type_colls:
                    g.add((self._type_colls[ftype], SKOS.member, uri))

            # Métadonnées Dublin Core
            self._add_metadata(uri, rec)

            # Rattachement aux collections organisation (KP, FAO, IPCC, EU…)
            for org_coll_uri in self._match_org_collections(rec.organization):
                g.add((org_coll_uri, SKOS.member, uri))

            # Index pays pour la jointure (hors UNFCCC déjà traités)
            if rec.country and rec.country not in ("", "nan"):
                try:
                    iso3 = pycountry.countries.search_fuzzy(rec.country)[0].alpha_3
                    self._country_idx.setdefault(iso3, []).append(uri)
                except Exception:
                    pass

            n_ok += 1

        print(
            f"[SKOSBuilder] build: {n_ok} concepts créés, "
            f"{n_unfccc} définitions UNFCCC réservées, "
            f"{n_skip} lignes ignorées"
        )

    # Construction des concepts UNFCCC (Table 3)

    def build_table3_concepts(self, table3_records: list[Table3Record]) -> None:
        """
        Crée un concept SKOS dédié par pays UNFCCC depuis la Table 3.

        Pour chaque pays :
        - Crée ex:Country_ISO3  (concept pays, classe ex:Country)
        - Crée le concept UNFCCC avec :
            * skos:broadMatch → Forest top-concept
            * Seuils numériques (minAreaHa, maxAreaHa, etc.) en xsd:decimal
            * Lien type → Collection (Declared / Land use / Land cover / Ecological)
            * Membres des collections Scope_National et UNFCCC
        - Joint les définitions textuelles collectées dans _unfccc_defs
        """
        g            = self.graph
        forest_uri   = self._top_concepts.get("FOREST/FOREST LAND")
        national_col = self._scope_colls.get("National")

        # Collection UNFCCC — déjà créée dans _init_org_collections, on ajoute juste la définition
        unfccc_coll = self._org_colls.get("UNFCCC", EX["Org_UNFCCC"])
        g.add((unfccc_coll, SKOS.definition, Literal(settings.unfccc_canonical_definition, lang="en")))

        n_created = n_joined = 0

        for rec in table3_records:
            if not rec.is_unfccc:
                continue

            country_raw = _normalize_country_name(rec.countries).strip()
            if not country_raw:
                continue

            country_uri = self._resolve_country_uri(country_raw)
            iso3 = (str(country_uri).rsplit("Country_", 1)[-1] if country_uri
                    else re.sub(r'[^A-Za-z0-9]', '_', country_raw)[:10].upper())

            unfccc_uri = self._unique_concept_uri(f"{iso3}Unfccc")
            g.add((unfccc_uri, RDF.type,        SKOS.Concept))
            g.add((unfccc_uri, SKOS.inScheme,   self._scheme_uri))
            g.add((unfccc_uri, SKOS.prefLabel,  Literal(f"{country_raw} UNFCCC", lang="en")))
            if country_uri:
                g.add((unfccc_uri, DCTERMS.spatial, country_uri))
            g.add((unfccc_uri, SKOS.scopeNote,  Literal("National", lang="en")))

            # skos:broadMatch → Forest top-concept (plus spécifique que le général)
            if forest_uri:
                g.add((unfccc_uri, SKOS.broadMatch, forest_uri))

            # Membre de la collection UNFCCC et de Scope_National
            g.add((unfccc_coll, SKOS.member, unfccc_uri))
            if national_col:
                g.add((national_col, SKOS.member, unfccc_uri))

            # Seuils numériques directement depuis Table 3
            def_parts = []
            for col_val, min_prop, max_prop, label in [
                (rec.area_ha,            "minAreaHa",        "maxAreaHa",        "Min. Area (ha)"),
                (rec.crown_cover_percent, "minCrownCoverPct", "maxCrownCoverPct", "Min. Crown Cover (%)"),
                (rec.tree_height_m,      "minTreeHeightM",   "maxTreeHeightM",   "Min. Tree Height (m)"),
                (rec.strip_width_m,      "minStripWidthM",   "maxStripWidthM",   "Min. Strip Width (m)"),
            ]:
                vmin, vmax = _parse_range(col_val)
                if vmin is not None:
                    g.add((unfccc_uri, EX[min_prop],
                           Literal(Decimal(str(vmin)), datatype=XSD.decimal)))
                    def_parts.append(f"{label} = {vmin}")
                if vmax is not None:
                    g.add((unfccc_uri, EX[max_prop],
                           Literal(Decimal(str(vmax)), datatype=XSD.decimal)))

            # definition de secours a partir des chiffres, au cas ou la
            # jointure texte plus bas (par nom de pays) rate a cause d'une
            # variante d'orthographe ("Columbia" vs "Colombia" par ex).
            # sans skos:definition le concept est invisible aux recherches
            if def_parts:
                g.add((unfccc_uri, SKOS.definition, Literal(" ".join(def_parts), lang="en")))

            # Type de définition (Table 3) → Collection type
            def_type = (rec.definition_type or "").strip().lower()
            if def_type and def_type not in ("nan", ""):
                g.add((unfccc_uri, SKOS.scopeNote, Literal(def_type, lang="en")))
                for kw, type_label in settings.table3_type_keywords.items():
                    if kw in def_type:
                        coll_uri = self._type_colls.get(type_label)
                        if coll_uri:
                            g.add((coll_uri, SKOS.member, unfccc_uri))
                        break

            # Notes / URLs de la colonne notes
            if rec.notes and rec.notes not in ("", "nan"):
                urls_found = re.findall(r'https?://\S+', rec.notes)
                for u in urls_found:
                    g.add((unfccc_uri, DCTERMS.source,
                           Literal(u.rstrip('.,;'), datatype=XSD.anyURI)))
                remaining = rec.notes
                for u in urls_found:
                    remaining = remaining.replace(u, '')
                remaining = remaining.strip(' -\n')
                if remaining:
                    g.add((unfccc_uri, SKOS.scopeNote, Literal(remaining)))

            # Index pour la jointure
            self._unfccc_concept_idx[country_raw.lower()] = unfccc_uri
            self._country_idx.setdefault(iso3, []).append(unfccc_uri)
            n_created += 1

        # Jointure : définitions textuelles → concepts UNFCCC
        for country_key, def_records in self._unfccc_defs.items():
            concept_uri = self._unfccc_concept_idx.get(country_key)
            if not concept_uri:
                continue
            for drec in def_records:
                def_lit = _lang_literal(drec.definition)
                if def_lit:
                    g.add((concept_uri, SKOS.definition, def_lit))
                # Scope et type depuis la définition textuelle
                scope = settings.scope_map.get(drec.title_3, "")
                if not scope and drec.title_3 in settings.valid_scopes:
                    scope = drec.title_3
                if scope and scope in self._scope_colls:
                    g.add((self._scope_colls[scope], SKOS.member, concept_uri))
                ftype = settings.type_map.get(drec.title_4, "")
                if ftype and ftype in self._type_colls:
                    g.add((self._type_colls[ftype], SKOS.member, concept_uri))
                self._add_metadata(concept_uri, drec)
                for org_coll_uri in self._match_org_collections(drec.organization):
                    g.add((org_coll_uri, SKOS.member, concept_uri))
                n_joined += 1

        print(
            f"[SKOSBuilder] table3 UNFCCC: {n_created} concepts créés, "
            f"{n_joined} définitions textuelles jointes"
        )

        # Critères nationaux non-UNFCCC (Table 3, is_unfccc=False)
        # Pays avec seuils propres (surface, couvert, hauteur) hors protocole Kyoto
        national_coll = self._scope_colls.get("National")
        n_national = 0
        for rec in table3_records:
            if rec.is_unfccc:
                continue
            country_raw = _normalize_country_name(rec.countries).strip()
            if not country_raw or country_raw.lower() in ("nan", ""):
                continue

            # Concept pays partagé avec UNFCCC si déjà créé
            country_uri = self._resolve_country_uri(country_raw)
            iso3 = (str(country_uri).rsplit("Country_", 1)[-1] if country_uri
                    else re.sub(r'[^A-Za-z0-9]', '_', country_raw)[:10].upper())

            nat_uri = self._unique_concept_uri(f"{iso3}National")
            g.add((nat_uri, RDF.type,       SKOS.Concept))
            g.add((nat_uri, SKOS.inScheme,  self._scheme_uri))
            g.add((nat_uri, SKOS.prefLabel, Literal(f"{country_raw} national criteria", lang="en")))
            if country_uri:
                g.add((nat_uri, DCTERMS.spatial, country_uri))
            g.add((nat_uri, SKOS.scopeNote, Literal("National", lang="en")))

            if forest_uri:
                g.add((nat_uri, SKOS.broadMatch, forest_uri))
            if national_col:
                g.add((national_col, SKOS.member, nat_uri))

            # Type de définition
            def_type = (rec.definition_type or "").strip().lower()
            if def_type and def_type not in ("nan", ""):
                g.add((nat_uri, SKOS.scopeNote, Literal(def_type, lang="en")))
                for kw, type_label in settings.table3_type_keywords.items():
                    if kw in def_type:
                        coll_uri = self._type_colls.get(type_label)
                        if coll_uri:
                            g.add((coll_uri, SKOS.member, nat_uri))
                        break

            # Seuils numériques
            def_parts = []
            for col_val, min_prop, max_prop, label in [
                (rec.area_ha,             "minAreaHa",        "maxAreaHa",        "Min. Area (ha)"),
                (rec.crown_cover_percent, "minCrownCoverPct", "maxCrownCoverPct", "Min. Crown Cover (%)"),
                (rec.tree_height_m,       "minTreeHeightM",   "maxTreeHeightM",   "Min. Tree Height (m)"),
                (rec.strip_width_m,       "minStripWidthM",   "maxStripWidthM",   "Min. Strip Width (m)"),
            ]:
                vmin, vmax = _parse_range(col_val)
                if vmin is not None:
                    g.add((nat_uri, EX[min_prop], Literal(Decimal(str(vmin)), datatype=XSD.decimal)))
                    def_parts.append(f"{label} = {vmin}")
                if vmax is not None:
                    g.add((nat_uri, EX[max_prop], Literal(Decimal(str(vmax)), datatype=XSD.decimal)))

            # sans skos:definition, ce concept est invisible pour toutes les
            # recherches (search_country_thresholds, search_continent_thresholds,
            # search_by_keyword l'exigent). C'etait le cas pour tous les
            # concepts nationaux non-UNFCCC avant ce fix (222 pays, dont les USA)
            if def_parts:
                g.add((nat_uri, SKOS.definition, Literal(" ".join(def_parts), lang="en")))

            self._country_idx.setdefault(iso3, []).append(nat_uri)
            n_national += 1

        print(f"[SKOSBuilder] table3 National: {n_national} concepts nationaux créés")

    def attach_thresholds(self, df_table3) -> None:
        """
        Compatibilité ascendante : convertit un DataFrame pandas en
        liste de Table3Record puis appelle build_table3_concepts().
        """
        records = [
            Table3Record(
                countries=           str(row.get("countries",           "")),
                definition_type=     str(row.get("definition_type",     "")),
                area_ha=             str(row.get("area_ha",             "")),
                crown_cover_percent= str(row.get("crown_cover_percent", "")),
                tree_height_m=       str(row.get("tree_height_m",       "")),
                strip_width_m=       str(row.get("strip_width_m",       "")),
                notes=               str(row.get("notes",               "")),
            )
            for _, row in df_table3.iterrows()
        ]
        self.build_table3_concepts(records)

    # Enrichissement Agrovoc via SPARQL

    def enrich_from_agrovoc(self, timeout: int = 10) -> None:
        """
        Enrichit les top-concepts avec skos:definition depuis Agrovoc via SPARQL.
        Pattern Agrovoc : <concept> skos:definition ?node . ?node rdf:value ?text .
        Silencieux si l'endpoint est injoignable.
        """
        try:
            from rdflib.plugins.stores.sparqlstore import SPARQLStore
        except ImportError:
            print("[SKOSBuilder] rdflib SPARQLStore indisponible — skip enrichissement Agrovoc")
            return

        n_enriched = 0
        for _, top_uri in self._top_concepts.items():
            agv_uri = None
            for _, _, o in self.graph.triples((top_uri, SKOS.exactMatch, None)):
                if str(o).startswith("http://aims.fao.org"):
                    agv_uri = str(o)
                    break
            if not agv_uri:
                continue

            try:
                store = SPARQLStore(settings.agrovoc_sparql_endpoint)
                g2 = Graph(store=store)
                q = f"""
                    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
                    PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                    SELECT ?text WHERE {{
                        <{agv_uri}> skos:definition ?defNode .
                        ?defNode rdf:value ?text .
                        FILTER (langMatches(lang(?text), "en"))
                    }}
                    LIMIT 1
                """
                for row in g2.query(q):
                    defn = str(row[0])
                    if defn:
                        self.graph.add((top_uri, SKOS.definition, Literal(defn, lang="en")))
                        n_enriched += 1
                    break
            except Exception:
                pass

        print(f"[SKOSBuilder] Agrovoc: {n_enriched} top-concepts enrichis avec skos:definition")

    # Statistiques

    def stats(self) -> dict:
        g = self.graph
        PREFIXES = """
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX dct:  <http://purl.org/dc/terms/>
        PREFIX ex:   <http://example.org/forest-def/>
        """

        def count(q: str) -> int:
            try:
                return int(list(g.query(PREFIXES + q))[0][0])
            except Exception:
                return 0

        return {
            "total_triples":     len(g),
            "total_concepts":    count("SELECT (COUNT(?c) AS ?n) WHERE { ?c a skos:Concept . }"),
            "with_broad_match":  count("SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE { ?c skos:broadMatch ?p . }"),
            "with_definition":   count("SELECT (COUNT(?c) AS ?n) WHERE { ?c skos:definition ?d . }"),
            "with_thresholds":   count("SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE { ?c ex:minAreaHa ?v . }"),
            "unfccc_concepts":   count("SELECT (COUNT(?c) AS ?n) WHERE { ex:Org_UNFCCC skos:member ?c . }"),
            "agrovoc_aligned":   count(
                "SELECT (COUNT(?c) AS ?n) WHERE { "
                "?c skos:exactMatch ?a . "
                "FILTER(STRSTARTS(STR(?a),'http://aims.fao.org')) }"
            ),
            "top_concepts":      len(self._top_concepts),
            "scope_collections": len(self._scope_colls),
            "type_collections":  len(self._type_colls),
        }
