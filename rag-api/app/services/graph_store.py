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

    def query_sparql(self, sparql: str) -> list[dict[str, Any]]:
        """Exécute une requête SPARQL SELECT et retourne les résultats."""
        full_query = settings.sparql_prefixes + sparql
        rows = []
        for row in self._g.query(full_query):
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
        keywords = [w.lower() for w in re.findall(r"\b[a-zA-Z]{3,}\b", query)][:5]
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

        # Filtre scope géographique
        scope_filter = ""
        if scope:
            scope_filter = f'FILTER(!BOUND(?country) || CONTAINS(LCASE(STR(?country)), "{scope.lower()}"))'

        # Filtre organisation (dct:creator) — plus précis que le scope pour FAO/UNFCCC/IPCC
        org_filter = ""
        if org:
            org_filter = f'FILTER(!BOUND(?org) || CONTAINS(LCASE(STR(?org)), "{org.lower()}"))'

        sparql = f"""
SELECT DISTINCT ?uri ?label ?def ?country ?year ?scope ?org WHERE {{
    ?uri a skos:Concept ;
         skos:definition ?def .
    OPTIONAL {{ ?uri skos:prefLabel ?label   . FILTER(LANG(?label) IN ('en', 'fr', '')) }}
    OPTIONAL {{ ?uri dct:spatial    ?country . }}
    OPTIONAL {{ ?uri dct:date       ?year    . }}
    OPTIONAL {{ ?uri skos:scopeNote ?scope   . }}
    OPTIONAL {{ ?uri dct:creator    ?org     . }}
    {concept_filter}
    FILTER ({kw_filter})
    {scope_filter}
    {org_filter}
}} LIMIT {top_k * 4}
"""
        results = self.query_sparql(sparql)

        # Scoring : mots-clés + bonus si concept/scope correspondent
        scored = []
        for r in results:
            text  = f"{r.get('label','')} {r.get('def','')}".lower()
            score = sum(1 for kw in keywords if kw in text) / len(keywords)
            if concept and concept.lower() in text: score += 0.2
            if scope   and scope.lower()   in text: score += 0.1
            if org     and org.lower()     in f"{r.get('org','')}".lower(): score += 0.4
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
        sparql = f"""
SELECT ?pred ?obj WHERE {{
    <{uri}> ?pred ?obj .
}}
"""
        rows = self.query_sparql(sparql)
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
            elif "spatial"   in pred:  result["country"] = obj
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
        c = country.lower().replace('"', "").replace("'", "")
        sparql = f"""
SELECT DISTINCT ?uri ?label ?def ?year ?org
               ?minArea ?minCrown ?minHeight ?maxCrown WHERE {{
    ?uri a skos:Concept ;
         dct:spatial ?country ;
         skos:definition ?def .
    FILTER(CONTAINS(LCASE(STR(?country)), "{c}"))
    OPTIONAL {{ ?uri skos:prefLabel ?label .
               FILTER(LANG(?label) IN ('en', 'fr', '')) }}
    OPTIONAL {{ ?uri dct:date       ?year    . }}
    OPTIONAL {{ ?uri dct:creator    ?org     . }}
    OPTIONAL {{ ?uri ex:minAreaHa       ?minArea  . }}
    OPTIONAL {{ ?uri ex:minCrownCoverPct ?minCrown . }}
    OPTIONAL {{ ?uri ex:maxCrownCoverPct ?maxCrown . }}
    OPTIONAL {{ ?uri ex:minTreeHeightM   ?minHeight . }}
}} LIMIT {top_k * 4}
"""
        rows = self.query_sparql(sparql)

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
        continent_key = continent.strip().replace(" ", "")
        sparql = f"""
SELECT ?label WHERE {{
    ex:Continent_{continent_key} skos:member ?country .
    ?country skos:prefLabel ?label .
}}
"""
        rows = self.query_sparql(sparql)
        return [r["label"] for r in rows]

    def search_continent_thresholds(
        self, continent: str, top_k: int = 20
    ) -> list[dict]:
        """Cherche les definitions avec seuils pour tous les pays d'un continent."""
        continent_key = continent.strip().replace(" ", "")
        sparql = f"""
SELECT DISTINCT ?uri ?label ?def ?countryName ?year
               ?minArea ?minCrown ?minHeight WHERE {{
    ex:Continent_{continent_key} skos:member ?country .
    ?country skos:prefLabel ?countryName .
    ?uri a skos:Concept ;
         dct:spatial ?spatial ;
         skos:definition ?def .
    FILTER(CONTAINS(LCASE(STR(?spatial)), LCASE(STR(?countryName))))
    OPTIONAL {{ ?uri skos:prefLabel ?label .
               FILTER(LANG(?label) IN ('en', 'fr', '')) }}
    OPTIONAL {{ ?uri dct:date ?year . }}
    OPTIONAL {{ ?uri ex:minAreaHa ?minArea . }}
    OPTIONAL {{ ?uri ex:minCrownCoverPct ?minCrown . }}
    OPTIONAL {{ ?uri ex:minTreeHeightM ?minHeight . }}
}} LIMIT {top_k * 4}
"""
        rows = self.query_sparql(sparql)
        results = []
        seen = set()
        for r in rows:
            uri = r["uri"]
            if uri in seen:
                continue
            seen.add(uri)
            results.append({
                "uri":     uri,
                "label":   r.get("label", ""),
                "def":     r.get("def", ""),
                "text":    r.get("def", ""),
                "country": r.get("countryName", ""),
                "year":    r.get("year", ""),
                "scope":   "National",
                "org":     "",
                "sparql_score": 0.5,
                "minCrown": r.get("minCrown"),
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
            "unfccc_concepts":  "SELECT (COUNT(?c) AS ?n) WHERE { ex:UNFCCC skos:member ?c . }",
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
