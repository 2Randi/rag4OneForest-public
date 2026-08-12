# MAJ du graphe avec quelque nettoyege du skos:definition 
from __future__ import annotations

import re
from pathlib import Path

from rdflib import Graph, Namespace, Literal, XSD
from rdflib.namespace import SKOS, DCTERMS

EX = Namespace("http://example.org/forest-def/")

INPUT_TTL  = Path(__file__).parent.parent / "data" / "forest_kg.ttl"
OUTPUT_TTL = Path(__file__).parent.parent / "data" / "forest_kg2.ttl"
ORG_UNFCCC = EX["Org_UNFCCC"]
FOREST     = EX["Forest"]
FOREST_500 = EX["Forest_500"]

TOP_CONCEPTS = [EX[l] for l in (
    "Forest", "Deforestation", "Afforestation", "Reforestation", "Woodland",
    "Tree", "LandCover", "LandUse", "Plantation", "NativeForest",
    "NaturalForest", "SemiNaturalForest", "NonForest", "Degradation", "Regeneration",
    "Stand", "Stocking", "GroveThicket", "Forestry", "Forestation",
)]

FOREST_DEF = "A forest is an ecosystem characterized by a dense community of trees."
FOREST_SRC = "https://en.wikipedia.org/wiki/Forest"


AND_RE = re.compile(r"(\s+and)+\s*$", re.IGNORECASE)


def count_issues(g: Graph) -> dict:
    defs = [str(d) for _, d in g.subject_objects(SKOS.definition)]
    return {
        "parenthese": sum(1 for d in defs if d.count("(") != d.count(")")),
        "and": sum(1 for d in defs if AND_RE.search(d.rstrip())),
    }


def strip_paren(text: str) -> str:
    stack = []
    for i, c in enumerate(text):
        if c == "(":
            stack.append(i)
        elif c == ")" and stack:
            stack.pop()
    return text[:min(stack)] if stack else text


def clean_defs(g: Graph) -> None:
    for uri, defn in list(g.subject_objects(SKOS.definition)):
        text = str(defn)
        cleaned = strip_paren(text)
        cleaned = AND_RE.sub("", cleaned.rstrip())
        cleaned = cleaned.rstrip(" .,;:-")
        if cleaned and cleaned != text:
            g.remove((uri, SKOS.definition, defn))
            g.add((uri, SKOS.definition, Literal(cleaned, lang=defn.language)))


def main() -> None:
    g = Graph()
    g.parse(INPUT_TTL, format="turtle")
    # print(f"graphe charge : {len(g)} triplets")

    members = list(g.objects(ORG_UNFCCC, SKOS.member))

    n_added = 0
    n_moved = 0

    for member in members:
        if member == FOREST_500:
            continue

        for top in TOP_CONCEPTS:
            if (member, SKOS.broadMatch, top) in g:
                g.remove((member, SKOS.broadMatch, top))
                n_moved += 1

        if (member, SKOS.broadMatch, FOREST_500) not in g:
            g.add((member, SKOS.broadMatch, FOREST_500))
            n_added += 1

    for triple in list(g.triples((ORG_UNFCCC, None, None))):
        g.remove(triple)
    for triple in list(g.triples((None, None, ORG_UNFCCC))):
        g.remove(triple)

    # Forest sarahana @ agrovoc
    for triple in list(g.triples((FOREST, SKOS.definition, None))):
        g.remove(triple)
    for triple in list(g.triples((FOREST, SKOS.exactMatch, None))):
        g.remove(triple)
    g.add((FOREST, SKOS.definition, Literal(FOREST_DEF, lang="en")))
    g.add((FOREST, DCTERMS.source, Literal(FOREST_SRC, datatype=XSD.anyURI)))

    clean_defs(g)

    g.serialize(destination=OUTPUT_TTL, format="turtle")

if __name__ == "__main__":
    main()
