# Acces au graphe RDF/SKOS via rdflib
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import SKOS, DCTERMS, RDF

from app.core.settings import settings

EX = Namespace(settings.base_uri)

# Mots vides à ignorer lors de l'extraction de mots-clés pour la recherche
# SPARQL par mots-clés (interrogatifs, articles, auxiliaires — FR/EN).
_STOPWORDS = {
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "does", "did", "do", "is", "are", "was", "were", "the", "and", "for",
    "use", "used", "with", "from", "that", "this", "these", "those",
    "have", "has", "had", "can", "could", "would", "should", "will",
    "shall", "about", "into", "under", "over", "you", "your", "please",
    "quel", "quelle", "quels", "quelles", "quoi", "comment", "pourquoi",
    "est", "sont", "les", "des", "une", "un", "pour", "dans", "avec",
}


class GraphStore:
    """Wrapper autour du graphe RDF/SKOS en mémoire."""

    def __init__(self, ttl_path: str | Path | None = None):
        path = Path(ttl_path or settings.ttl_path)
        if not path.exists():
            raise FileNotFoundError(f"TTL introuvable : {path}")
        self._g = Graph()
        self._g.parse(str(path), format="turtle")
        print(f"[GraphStore] {len(self._g)} triplets chargés depuis {path}")

    # SPARQL générique

    def query_sparql(
        self, sparql: str, bindings: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """
        Exécute une requête SPARQL SELECT et retourne les résultats.
        bindings : valeurs à lier à des variables (ex: {"uri": URIRef(...)})
        au lieu de les interpoler dans le texte de la requête — évite qu'une
        valeur contenant des caractères spéciaux SPARQL (>, ", {, }...) ne
        casse ou ne détourne la requête.
        """
        full_query = settings.sparql_prefixes + sparql
        rows = []
        for row in self._g.query(full_query, initBindings=bindings):
            rows.append({str(var): str(val) if val is not None else ""
                          for var, val in zip(row.labels, row)})
        return rows

    # Recherche par mots-clés

    def search_by_keyword(
        self,
        query:   str,
        top_k:   int = 10,
        concept: str | None = None,
        scope:   str | None = None,
        org:     str | None = None,
    ) -> list[dict]:
        """
        Recherche SPARQL structurée.
        concept : si fourni, filtre sur le top-concept parent (ex: 'forest')
        scope   : si fourni, filtre sur dct:spatial (ex: 'International')
        """
        # Les 5 premiers mots dans l'ordre de la phrase sont souvent des mots
        # interrogatifs/vides ("What ... does Germany use ..." -> what, does,
        # use passaient devant "Germany"). On filtre les stopwords et on
        # priorise les mots les plus longs (donc les plus discriminants,
        # typiquement les noms propres et termes techniques).
        raw_words = [w.lower() for w in re.findall(r"\b[a-zA-Z]{3,}\b", query)]
        candidates = [w for w in raw_words if w not in _STOPWORDS]
        if not candidates:
            candidates = raw_words
        keywords = sorted(candidates, key=len, reverse=True)[:8]
        if not keywords:
            return []

        # Filtre mots-clés (OR permissif)
        kw_filter = " || ".join(
            f'CONTAINS(LCASE(STR(?def)), "{kw}") || CONTAINS(LCASE(STR(?label)), "{kw}")'
            for kw in keywords
        )

        # Filtre concept (top-concept parent via broadMatch)
        concept_filter = ""
        if concept:
            concept_filter = (
                f'OPTIONAL {{ ?uri skos:broadMatch ?tc . }}\n'
                f'    FILTER(!BOUND(?tc) || CONTAINS(LCASE(STR(?tc)), "{concept.lower()}"))'
            )

        # Filtre scope (International/National/Local, via skos:scopeNote) —
        # testait par erreur ?country (dct:spatial) au lieu de ?scope, donc
        # ne filtrait jamais rien puisqu'aucun nom de pays ne contient les
        # mots "international"/"national"/"local".
        scope_filter = ""
        if scope:
            scope_filter = f'FILTER(!BOUND(?scope) || CONTAINS(LCASE(STR(?scope)), "{scope.lower()}"))'

        # Filtre organisation — dct:creator est un champ texte pollué par des
        # résidus de parsing du tableau source (ex: "&", "?", "10 degrees C")
        # et ne contient pas forcément le nom de l'org demandée (ex: les
        # concepts UNFCCC ont dct:creator="KP", pas "UNFCCC"). Le graphe a en
        # revanche de vraies collections propres ex:Org_UNFCCC, ex:Org_FAO...
        # avec skos:member correctement peuplé (cf. kg-builder/skos_builder.py
        # ORG_COLLECTIONS) : on filtre d'abord dessus, et on retombe sur
        # dct:creator seulement pour les organisations sans collection dédiée.
        org_filter = ""
        org_membership = ""
        if org:
            org_key = re.sub(r"[^A-Za-z]", "", org)
            org_membership = f'OPTIONAL {{ ex:Org_{org_key} skos:member ?uri . BIND(true AS ?orgMember) }}'
            org_filter = (
                'FILTER(BOUND(?orgMember) || !BOUND(?org) || '
                f'CONTAINS(LCASE(STR(?org)), "{org.lower()}"))'
            )

        sparql = f"""
SELECT DISTINCT ?uri ?label ?def ?country ?year ?scope ?org ?orgMember WHERE {{
    ?uri a skos:Concept ;
         skos:definition ?def .
    OPTIONAL {{ ?uri skos:prefLabel ?label   . FILTER(LANG(?label) IN ('en', 'fr', '')) }}
    OPTIONAL {{ ?uri dct:spatial ?countryUri .
               OPTIONAL {{ ?countryUri skos:prefLabel ?country .
                          FILTER(LANG(?country) IN ('en', 'fr', '')) }} }}
    OPTIONAL {{ ?uri dct:date       ?year    . }}
    OPTIONAL {{ ?uri skos:scopeNote ?scope   . }}
    OPTIONAL {{ ?uri dct:creator    ?org     . }}
    {org_membership}
    {concept_filter}
    FILTER ({kw_filter})
    {scope_filter}
    {org_filter}
}} LIMIT {max(top_k * 30, 500)}
"""
        # LIMIT large : le graphe est petit (~3400 concepts en mémoire, requête
        # <1s même sans borne). Un LIMIT serré ici coupait les lignes AVANT le
        # scoring Python ci-dessous, dans l'ordre d'itération arbitraire du
        # graphe — donc les vrais meilleurs matches pouvaient être perdus avant
        # même d'être évalués (même défaut que search_continent_thresholds).
        results = self.query_sparql(sparql)

        # Scoring : mots-clés + bonus si concept/scope correspondent
        scored = []
        for r in results:
            text  = f"{r.get('label','')} {r.get('def','')}".lower()
            score = sum(1 for kw in keywords if kw in text) / len(keywords)
            if concept and concept.lower() in text: score += 0.2
            if scope   and scope.lower()   in text: score += 0.1
            if org and (r.get("orgMember") or org.lower() in f"{r.get('org','')}".lower()):
                score += 0.4
            scored.append({**r, "sparql_score": round(min(score, 1.0), 3)})

        # Dédoublonnage par URI
        seen, deduped = set(), []
        for r in sorted(scored, key=lambda x: -x["sparql_score"]):
            if r["uri"] not in seen:
                seen.add(r["uri"])
                deduped.append(r)

        return deduped[:top_k]

    # Détail d'un concept

    def get_concept(self, uri: str) -> dict | None:
        """Récupère toutes les propriétés d'un concept donné."""
        # uri vient d'un paramètre d'URL utilisateur (urllib.parse.unquote) :
        # lié via initBindings plutôt qu'interpolé dans le texte de la
        # requête, sinon un caractère comme '>' casse la syntaxe IRIREF et
        # peut altérer la requête exécutée (vérifié : provoque une
        # ParseException, potentiellement pire selon le contenu).
        sparql = """
SELECT ?pred ?obj WHERE {
    ?uri ?pred ?obj .
}
"""
        try:
            rows = self.query_sparql(sparql, bindings={"uri": URIRef(uri)})
        except Exception:
            return None
        if not rows:
            return None

        result: dict[str, Any] = {"uri": uri, "labels": [], "definitions": [],
                                   "scopeNotes": [], "altLabels": [],
                                   "sources": [], "thresholds": {}}
        for row in rows:
            pred = row["pred"]
            obj  = row["obj"]
            if "prefLabel"   in pred: result["labels"].append(obj)
            elif "definition" in pred: result["definitions"].append(obj)
            elif "scopeNote" in pred:  result["scopeNotes"].append(obj)
            elif "altLabel"  in pred:  result["altLabels"].append(obj)
            elif "spatial"   in pred:
                # dct:spatial pointe vers ex:Country_ISO3 : on résout son
                # skos:prefLabel pour afficher un nom de pays, pas l'URI brute.
                labels = list(self._g.objects(URIRef(obj), SKOS.prefLabel))
                result["country"] = str(labels[0]) if labels else obj
            elif "date"      in pred:  result["year"] = obj
            elif "creator"   in pred:  result["organization"] = obj
            elif "source"    in pred:  result["sources"].append(obj)
            elif "broadMatch" in pred: result["broadMatch"] = obj
            elif any(t in pred for t in ["minArea", "maxArea", "CrownCover", "TreeHeight", "StripWidth"]):
                prop = pred.split("/")[-1]
                result["thresholds"][prop] = obj

        return result

    # Contexte structurel

    def get_context(self, uri: str) -> str:
        """
        Retourne le contexte structurel d'un concept pour enrichir le prompt RAG :
        - concept parent (broader)
        - concepts frères (siblings, max 5)
        - concepts associés (related, max 3)
        - seuils numériques
        - alignements externes (Agrovoc)
        """
        parts = []
        u = URIRef(uri)

        # Parent
        for parent in self._g.objects(u, SKOS.broadMatch):
            for lbl in self._g.objects(parent, SKOS.prefLabel):
                parts.append(f"Parent concept: {lbl}")
                # Frères (autres enfants du même parent)
                siblings = list(self._g.subjects(SKOS.broadMatch, parent))
                siblings = [s for s in siblings if str(s) != uri][:5]
                if siblings:
                    sib_labels = []
                    for sib in siblings:
                        for sl in self._g.objects(sib, SKOS.prefLabel):
                            sib_labels.append(str(sl))
                            break
                    if sib_labels:
                        parts.append(f"Related concepts (same category): {', '.join(sib_labels)}")
                break

        # Concepts associés (skos:related)
        related = list(self._g.objects(u, SKOS.related))[:3]
        if related:
            rl = []
            for r in related:
                for lbl in self._g.objects(r, SKOS.prefLabel):
                    rl.append(str(lbl))
                    break
            if rl:
                parts.append(f"Associated concepts: {', '.join(rl)}")

        # Seuils numériques
        thresholds = []
        for prop in ["minAreaHa", "maxAreaHa", "minCrownCoverPct", "maxCrownCoverPct",
                     "minTreeHeightM", "maxTreeHeightM"]:
            for val in self._g.objects(u, EX[prop]):
                thresholds.append(f"{prop}: {val}")
        if thresholds:
            parts.append("Numerical thresholds: " + " | ".join(thresholds))

        # Alignements
        for match in self._g.objects(u, SKOS.exactMatch):
            parts.append(f"Exact match (Agrovoc): {str(match).split('/')[-1]}")

        return "\n".join(parts)

    # Seuils nationaux par pays (requête dédiée)

    def search_country_thresholds(
        self,
        country: str,
        top_k: int = 4,
    ) -> list[dict]:
        """
        Requête SPARQL dédiée aux seuils nationaux.
        Filtre par dct:spatial (pays), retourne les concepts SKOS qui ont
        des propriétés de seuil (minAreaHa, minCrownCoverPct, minTreeHeightM)
        ou une définition textuelle des critères nationaux.
        Priorité : concepts avec le plus de propriétés numériques en premier.
        """
        # dct:spatial pointe vers le concept ex:Country_ISO3 (pas du texte
        # libre). Résoudre le pays et joindre les définitions en une seule
        # requête est correct mais très lent avec le moteur SPARQL de rdflib
        # (~90s mesuré : il évalue le filtre CONTAINS après avoir déjà tenté
        # de joindre sur tous les skos:Concept). On sépare donc en 2 requêtes
        # bon marché : résolution du pays sur le petit ensemble ex:Countries
        # (~230 membres), puis jointure sur l'URI concrète obtenue.
        c = country.lower().replace('"', "").replace("'", "")
        country_rows = self.query_sparql(f"""
SELECT ?countryUri WHERE {{
    ex:Countries skos:member ?countryUri .
    ?countryUri skos:prefLabel ?countryLabel .
    FILTER(CONTAINS(LCASE(STR(?countryLabel)), "{c}"))
}} LIMIT 5
""")
        if not country_rows:
            return []

        rows: list[dict] = []
        for cr in country_rows:
            rows.extend(self.query_sparql(f"""
SELECT DISTINCT ?uri ?label ?def ?year ?org
               ?minArea ?minCrown ?minHeight ?maxCrown WHERE {{
    ?uri a skos:Concept ;
         dct:spatial <{cr['countryUri']}> ;
         skos:definition ?def .
    OPTIONAL {{ ?uri skos:prefLabel ?label .
               FILTER(LANG(?label) IN ('en', 'fr', '')) }}
    OPTIONAL {{ ?uri dct:date       ?year    . }}
    OPTIONAL {{ ?uri dct:creator    ?org     . }}
    OPTIONAL {{ ?uri ex:minAreaHa       ?minArea  . }}
    OPTIONAL {{ ?uri ex:minCrownCoverPct ?minCrown . }}
    OPTIONAL {{ ?uri ex:maxCrownCoverPct ?maxCrown . }}
    OPTIONAL {{ ?uri ex:minTreeHeightM   ?minHeight . }}
}} LIMIT {max(top_k * 30, 200)}
"""))

        def _richness(r: dict) -> int:
            return sum(1 for k in ("minCrown", "minArea", "minHeight")
                       if r.get(k))

        rows.sort(key=_richness, reverse=True)

        results: list[dict] = []
        seen: set[str] = set()
        for r in rows:
            uri = r["uri"]
            if uri in seen:
                continue
            seen.add(uri)

            # Texte enrichi : définition + valeurs structurées
            threshold_parts: list[str] = []
            if r.get("minArea"):   threshold_parts.append(f"min area {r['minArea']} ha")
            if r.get("minCrown"):  threshold_parts.append(f"crown cover {r['minCrown']}%")
            if r.get("maxCrown"):  threshold_parts.append(f"(max {r['maxCrown']}%)")
            if r.get("minHeight"): threshold_parts.append(f"tree height {r['minHeight']} m")

            def_text = r.get("def", "")
            text = def_text
            if threshold_parts:
                text = def_text + "\nThresholds: " + " | ".join(threshold_parts)

            results.append({
                "uri":          uri,
                "label":        r.get("label", ""),
                "def":          def_text,
                "text":         text,
                "country":      country,
                "year":         r.get("year", ""),
                "scope":        "National",
                "org":          r.get("org", ""),
                "sparql_score": min(_richness(r) / 3.0, 1.0),
            })

            if len(results) >= top_k:
                break

        return results

    # Recherche par continent

    def get_countries_by_continent(self, continent: str) -> list[str]:
        """Retourne les noms des pays d'un continent via le graphe SPARQL."""
        # Interpolé dans une URI (ex:Continent_X), pas dans un littéral :
        # restreint aux lettres par défense en profondeur, cohérent avec
        # org_key dans search_by_keyword.
        continent_key = re.sub(r"[^A-Za-z]", "", continent)
        sparql = f"""
SELECT ?label WHERE {{
    ex:Continent_{continent_key} skos:member ?country .
    ?country skos:prefLabel ?label .
}}
"""
        rows = self.query_sparql(sparql)
        return [r["label"] for r in rows]

    def search_continent_thresholds(
        self, continent: str, top_k: int = 60
    ) -> list[dict]:
        """Cherche les definitions avec seuils pour tous les pays d'un continent.

        Un continent peut compter jusqu'à ~46 pays (Afrique) : top_k doit donc
        couvrir le continent entier, sinon des pays valides sont tronqués avant
        même d'être vus. Les concepts sont aussi triés par "richesse" (nombre de
        seuils numériques renseignés) pour que les vraies définitions nationales
        (minAreaHa/minCrownCoverPct) passent devant les concepts sans seuil
        (Afforestation, Tree, Woodland...) qui matchent le même pays par texte.
        """
        # dct:spatial pointe désormais vers ex:Country_ISO3 : la jointure
        # avec l'appartenance au continent se fait par égalité d'URI exacte
        # (?uri dct:spatial ?country, la même variable que skos:member),
        # plus par un CONTAINS texte fragile sur le nom du pays.
        # Interpolé dans une URI (ex:Continent_X), pas dans un littéral :
        # restreint aux lettres par défense en profondeur, cohérent avec
        # org_key dans search_by_keyword.
        continent_key = re.sub(r"[^A-Za-z]", "", continent)
        sparql = f"""
SELECT DISTINCT ?uri ?label ?def ?countryName ?year
               ?minArea ?minCrown ?minHeight WHERE {{
    ex:Continent_{continent_key} skos:member ?country .
    ?country skos:prefLabel ?countryName .
    ?uri a skos:Concept ;
         dct:spatial ?country ;
         skos:definition ?def .
    OPTIONAL {{ ?uri skos:prefLabel ?label .
               FILTER(LANG(?label) IN ('en', 'fr', '')) }}
    OPTIONAL {{ ?uri dct:date ?year . }}
    OPTIONAL {{ ?uri ex:minAreaHa ?minArea . }}
    OPTIONAL {{ ?uri ex:minCrownCoverPct ?minCrown . }}
    OPTIONAL {{ ?uri ex:minTreeHeightM ?minHeight . }}
}} LIMIT {top_k * 8}
"""
        rows = self.query_sparql(sparql)

        def _richness(r: dict) -> int:
            return sum(1 for k in ("minArea", "minCrown", "minHeight") if r.get(k))

        # Un seul concept par pays : le plus riche en seuils numériques.
        best_by_country: dict[str, dict] = {}
        for r in rows:
            country = r.get("countryName", "")
            if not country:
                continue
            if country not in best_by_country or _richness(r) > _richness(best_by_country[country]):
                best_by_country[country] = r

        results = []
        for country, r in sorted(best_by_country.items(), key=lambda kv: -_richness(kv[1])):
            results.append({
                "uri":     r["uri"],
                "label":   r.get("label", ""),
                "def":     r.get("def", ""),
                "text":    r.get("def", ""),
                "country": country,
                "year":    r.get("year", ""),
                "scope":   "National",
                "org":     "",
                "sparql_score": min(_richness(r) / 3.0, 1.0),
                "minArea":  r.get("minArea"),
                "minCrown": r.get("minCrown"),
                "minHeight": r.get("minHeight"),
            })
            if len(results) >= top_k:
                break
        return results

    # Statistiques

    def graph_stats(self) -> dict:
        stats = {}
        queries = {
            "total_triples":    "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o . }",
            "total_concepts":   "SELECT (COUNT(?c) AS ?n) WHERE { ?c a skos:Concept . }",
            "with_broad_match": "SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE { ?c skos:broadMatch ?p . }",
            "with_definition":  "SELECT (COUNT(?c) AS ?n) WHERE { ?c skos:definition ?d . }",
            "with_thresholds":  "SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE { ?c ex:minAreaHa ?v . }",
            "agrovoc_aligned":  "SELECT (COUNT(?c) AS ?n) WHERE { ?c skos:exactMatch ?a . FILTER(STRSTARTS(STR(?a),'http://aims.fao.org')) }",
            "countries_count":  "SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE { ?c dct:spatial ?p . }",
            "unfccc_concepts":  "SELECT (COUNT(?c) AS ?n) WHERE { ex:Org_UNFCCC skos:member ?c . }",
        }
        for key, q in queries.items():
            try:
                res = self.query_sparql(q)
                stats[key] = int(res[0]["n"]) if res else 0
            except Exception:
                stats[key] = 0
        return stats

    @property
    def rdflib_graph(self) -> Graph:
        return self._g


@lru_cache(maxsize=1)
def get_graph_store() -> GraphStore:
    return GraphStore()
