# Export des enregistrements vers CSV
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extractor.docx_extractor import DefinitionRecord, Table3Record
from config import settings


# Helpers Table 3

# Tokens à supprimer pour obtenir country_clean
_T3_NOISE_RE = re.compile(
    r'\b(UNFCCC|KP|FREL|Kyoto\s+Protocol)\b'
    r'|\(\s*(19|20)\d{2}(?:\s*,\s*(19|20)\d{2})*\s*\)'
    r'|\b(19|20)\d{2}\b',
    re.IGNORECASE,
)
_T3_SEP_RE = re.compile(r'\s*[/|]\s*|\s*-{1,2}\s*')
_T3_PUNCT_RE = re.compile(r'[().,;:]')


def _normalize_t3_country(raw: str) -> str:
    """Supprime année, UNFCCC/KP/FREL et ponctuation — laisse le nom du pays."""
    clean = _T3_NOISE_RE.sub(' ', raw)
    clean = _T3_PUNCT_RE.sub(' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _map_t3_type(raw: str) -> str:
    """Mappe definition_type brut vers Declared/Land use/Land cover/Ecological."""
    raw_lower = raw.lower()
    for kw, canonical in settings.table3_type_keywords.items():
        if kw in raw_lower:
            return canonical
    return raw


# Export brut

def export_definitions_raw(records: list[DefinitionRecord], path: Path) -> int:
    """
    Exporte tous les enregistrements extraits sans filtrage.
    Équivalent de definitionStructured.csv dans ton script docxExtract.py.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(DefinitionRecord().to_dict().keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow(rec.to_dict())
    return len(records)


# Export nettoyé/filtré

def _build_title_path(d: dict) -> str:
    """Construit le chemin hiérarchique complet depuis les colonnes title_*."""
    parts = [d.get(f"title_{i}", "").strip() for i in range(1, 5)]
    return ", ".join(p.lower() for p in parts if p)


def export_definitions_clean(records: list[DefinitionRecord], path: Path) -> int:
    """
    Exporte les enregistrements filtrés et normalisés.
    Équivalent de clean_Def.csv dans ton script concept.py.

    Applique :
    - Suppression des sections non-concept (introductions, questions, discussions…)
    - Normalisation title_3 (scope_map) et title_4 (type_map)
    - Nettoyage bold_terms (seuls les caractères alphabétiques + tiret + ;)
    - Ajout colonne title_path (chemin hiérarchique lisible)
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(DefinitionRecord().to_dict().keys()) + ["title_path"]
    kept: list[dict] = []

    for rec in records:
        d = rec.to_dict()

        # Filtre 1 : définition vide ou junk
        defn = d["definition"].strip()
        if not defn:
            continue
        if re.fullmatch(r'[-–—]', defn):       # tiret unique (comme concept.py)
            continue
        if re.fullmatch(r'\d+(\.\d+)*', defn):
            continue
        if re.fullmatch(r'\(\s*\)', defn):
            continue

        # Filtre 2 : sections non-concept (questions, discussions…)
        title_path = _build_title_path(d)
        if title_path in settings.non_concept_paths:
            continue

        # Normalisation title_3 (scope) et title_4 (type)
        d["title_3"] = settings.scope_map.get(d["title_3"], d["title_3"])
        d["title_4"] = settings.type_map.get(d["title_4"], d["title_4"])

        # Nettoyage bold_terms
        bt = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ\s\-;]", " ", d["bold_terms"])
        d["bold_terms"] = re.sub(r"\s+", " ", bt).strip()

        # Chemin normalisé
        d["title_path"] = _build_title_path(d)   # recalcul après normalisation

        kept.append(d)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)

    return len(kept)


# Export Table 3

def export_table3(records: list[Table3Record], path: Path) -> int:
    """
    Exporte les enregistrements de la Table 3 avec colonnes nettoyées.
    Colonnes ajoutées :
      - country_clean          : nom pays sans année/UNFCCC/KP/FREL
      - definition_type_clean  : type canonique (Declared / Land use / Land cover / Ecological)
      - is_unfccc              : True si ligne concerne un engagement UNFCCC
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(Table3Record().to_dict().keys()) + [
        "country_clean", "definition_type_clean", "is_unfccc"
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            row = rec.to_dict()
            row["country_clean"]         = _normalize_t3_country(rec.countries)
            row["definition_type_clean"] = _map_t3_type(rec.definition_type)
            row["is_unfccc"]             = rec.is_unfccc
            writer.writerow(row)
    return len(records)
