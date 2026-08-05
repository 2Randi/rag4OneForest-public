# Detache UNFCCC de Forest/Agrovoc, Forest_500 remplace Org_UNFCCC comme point de rattachement
from __future__ import annotations

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


def main() -> None:
    g = Graph()
    g.parse(INPUT_TTL, format="turtle")
    # print(f"graphe charge : {len(g)} triplets")

    members = list(g.objects(ORG_UNFCCC, SKOS.member))
    # print(f"{len(members)} membres actuels de Org_UNFCCC")

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

    # Forest coupe avec Agrovoc, definition Wikipedia a la place
    for triple in list(g.triples((FOREST, SKOS.definition, None))):
        g.remove(triple)
    for triple in list(g.triples((FOREST, SKOS.exactMatch, None))):
        g.remove(triple)
    g.add((FOREST, SKOS.definition, Literal(FOREST_DEF, lang="en")))
    g.add((FOREST, DCTERMS.source, Literal(FOREST_SRC, datatype=XSD.anyURI)))

    # print(f"{n_added} broadMatch -> Forest_500 ajoutes")
    # print(f"{n_moved} liens directs vers Forest retires")
    # print("Org_UNFCCC supprime")
    # print(f"graphe final : {len(g)} triplets")

    g.serialize(destination=OUTPUT_TTL, format="turtle")
    # print(f"sauvegarde : {OUTPUT_TTL}")


if __name__ == "__main__":
    main()
