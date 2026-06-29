# Configuration du pipeline de construction du graphe
from pydantic_settings import BaseSettings
from pathlib import Path


class KGBuilderSettings(BaseSettings):
    # Chemins
    data_dir: Path = Path("../data")
    output_ttl: Path = Path("../data/forest_kg.ttl")

    # Namespaces
    base_uri: str = "http://example.org/forest-def/"
    agrovoc_uri: str = "http://aims.fao.org/aos/agrovoc/"
    afo_uri: str = "https://seco.cs.aalto.fi/ontologies/afo/"

    # Endpoint SPARQL Agrovoc pour l'enrichissement des top-concepts
    agrovoc_sparql_endpoint: str = "https://agrovoc.fao.org/sparql"

    # Définition canonique UNFCCC de la forêt
    unfccc_canonical_definition: str = (
        "A minimum area of land of 0.05-1.0 hectares with tree crown cover "
        "(or equivalent stocking level) of more than 10-30 per cent with trees "
        "with the potential to reach a minimum height of 2-5 metres at maturity in situ."
    )

    # Alignements Agrovoc connus (label_upper → URI fragment)
    agrovoc_alignments: dict[str, str] = {
        "FOREST/FOREST LAND":                         "c_3062",
        "DEFORESTATION":                              "c_2593",
        "AFFORESTATION":                              "c_162",
        "REFORESTATION":                              "c_13802",
        "WOODS, WOODLAND, OTHER WOODED LANDS (OWL)": "c_8421",
        "TREE":                                       "c_7887",
        "LAND COVER":                                 "c_37897",
        "LAND USE":                                   "c_4182",
        "FORESTATION":                                "c_10984",
        "DEGRADATION":                                "c_10463",
        "REGENERATION":                               "c_6442",
    }

    # Labels des top-concepts (title_2 → label canonique)
    top_concept_labels: dict[str, str] = {
        "FOREST/FOREST LAND":                         "Forest",
        "DEFORESTATION":                              "Deforestation",
        "AFFORESTATION":                              "Afforestation",
        "REFORESTATION":                              "Reforestation",
        "WOODS, WOODLAND, OTHER WOODED LANDS (OWL)": "Woodland",
        "TREE":                                       "Tree",
        "LAND COVER":                                 "LandCover",
        "LAND USE":                                   "LandUse",
        "PLANTATION (Forest Cultures)":               "Plantation",
        "NATIVE FOREST":                              "NativeForest",
        "NATURAL FOREST":                             "NaturalForest",
        "SEMI-NATURAL FOREST":                        "SemiNaturalForest",
        "NON-FOREST":                                 "NonForest",
        "DEGRADATION":                                "Degradation",
        "REGENERATION":                               "Regeneration",
    }

    # Scopes valides (title_3 normalisé)
    valid_scopes: set[str] = {
        "General", "International", "National", "State"
    }

    # Types valides (title_4 normalisé)
    valid_types: set[str] = {
        "Declared", "Land use", "Land cover", "Ecological"
    }

    # Mapping title_3 brut → scope canonique
    scope_map: dict[str, str] = {
        "General definitions":                    "General",
        "International definitions":              "International",
        "National definitions":                   "National",
        "State, province and local definitions.": "State",
    }

    # Mapping title_4 brut → type canonique
    type_map: dict[str, str] = {
        "As a declared, legal, or administrative unit": "Declared",
        "As a land use type":                           "Land use",
        "As a land cover type":                         "Land cover",
        "Ecological/Miscellaneous Definitions":         "Ecological",
    }

    # Mapping definition_type (Table 3) → type canonique
    # (correspondance partielle, case-insensitive)
    table3_type_keywords: dict[str, str] = {
        "cover":      "Land cover",
        "civer":      "Land cover",
        "use":        "Land use",
        "declared":   "Declared",
        "admin":      "Declared",
        "ecological": "Ecological",
    }

    # Relations associatives entre top-concepts
    related_pairs: list[tuple[str, str]] = [
        # Forest et les actions
        ("Forest",          "Deforestation"),
        ("Forest",          "Afforestation"),
        ("Forest",          "Reforestation"),
        ("Forest",          "Degradation"),
        ("Forest",          "Regeneration"),
        # Forest et les types
        ("Forest",          "Woodland"),
        ("Forest",          "Plantation"),
        ("Forest",          "NativeForest"),
        ("Forest",          "NaturalForest"),
        ("Forest",          "SemiNaturalForest"),
        ("Forest",          "NonForest"),
        ("Forest",          "Tree"),
        ("Forest",          "LandCover"),
        ("Forest",          "LandUse"),
        # Actions entre elles
        ("Afforestation",   "Reforestation"),
        ("Deforestation",   "Reforestation"),
        ("Deforestation",   "Degradation"),
        ("Regeneration",    "Reforestation"),
        ("Regeneration",    "Afforestation"),
        ("Afforestation",   "Plantation"),
        # Types entre eux
        ("Woodland",        "Tree"),
        ("NativeForest",    "NaturalForest"),
        ("NaturalForest",   "Plantation"),
        ("LandCover",       "LandUse"),
        ("NonForest",       "Deforestation"),
    ]

    # Propriétés numériques xsd:decimal (name → label)
    numeric_properties: dict[str, str] = {
        "minAreaHa":        "Minimum area (ha)",
        "maxAreaHa":        "Maximum area (ha)",
        "minCrownCoverPct": "Minimum crown cover (%)",
        "maxCrownCoverPct": "Maximum crown cover (%)",
        "minTreeHeightM":   "Minimum tree height (m)",
        "maxTreeHeightM":   "Maximum tree height (m)",
        "minStripWidthM":   "Minimum strip width (m)",
        "maxStripWidthM":   "Maximum strip width (m)",
    }

    # Lignes à exclure du CSV (title_path, en minuscules)
    # Reprend concept.py + ajouts des chemins de discussion
    non_concept_paths: set[str] = {
        "",
        "introduction",
        "basic terms, forest/forest land, questions:",
        "basic terms, tree, summary table",
        "basic terms, tree, questions",
        "action terms, afforestation, questions:",
        "action terms, deforestation, questions:",
        "action terms, reforestation, questions:",
        "action terms, regeneration, questions:",
        "discussion",
        "discussion, illustrations",
        "discussion, implications and interpretations, from a land use interpretation - if taken literally",
        "discussion, implications and interpretations, from a land cover interpretation - if taken literally",
        "discussion, considerations",
        "final questions and observations",
        "references",
    }

    class Config:
        env_prefix = "KG_"


settings = KGBuilderSettings()
