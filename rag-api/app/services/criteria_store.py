# Seuils extraits des textes de definitions (criteria.csv)
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.settings import settings

ROOT = Path(__file__).resolve().parents[3]   # e:\projects\rag4OneForest


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", " ", s.lower()).strip()


def _f(val: str) -> float | None:
    try:
        v = float(val)
        return None if v != v else v
    except (ValueError, TypeError):
        return None


class CriteriaStore:
    """
    Index in-memory des critères numériques extraits du texte des définitions.
    Permet de répondre à des questions comme :
      - "Which definitions specify crown cover > 30%?"
      - "What are Germany's forest criteria?"
    """

    def __init__(self, csv_path: str | Path | None = None):
        path = Path(csv_path) if csv_path else ROOT / "data" / "criteria.csv"
        self._rows: list[dict[str, Any]] = []
        self._by_country: dict[str, list[dict]] = {}
        self._by_org: dict[str, list[dict]] = {}
        self._by_concept: dict[str, list[dict]] = {}

        if not path.exists():
            return

        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                entry = {
                    "concept":           row.get("concept", "").strip(),
                    "organization":      row.get("organization", "").strip(),
                    "country":           row.get("country", "").strip(),
                    "year":              row.get("year", "").strip(),
                    "area_ha_min":       _f(row.get("area_ha_min", "")),
                    "area_ha_max":       _f(row.get("area_ha_max", "")),
                    "crown_cover_min":   _f(row.get("crown_cover_min", "")),
                    "crown_cover_max":   _f(row.get("crown_cover_max", "")),
                    "height_m_min":      _f(row.get("height_m_min", "")),
                    "height_m_max":      _f(row.get("height_m_max", "")),
                    "width_m_min":       _f(row.get("width_m_min", "")),
                    "definition_snippet": row.get("definition_snippet", "").strip(),
                }
                if not any(v is not None for k, v in entry.items() if "_min" in k or "_max" in k):
                    continue

                self._rows.append(entry)
                for key, index in [
                    (_norm(entry["country"]),      self._by_country),
                    (_norm(entry["organization"]), self._by_org),
                    (_norm(entry["concept"]),      self._by_concept),
                ]:
                    if key:
                        index.setdefault(key, []).append(entry)

    # Recherches

    def by_country(self, country: str, top_k: int = 5) -> list[dict]:
        key = _norm(country)
        results: list[dict] = []
        for k, rows in self._by_country.items():
            if key in k or k in key:
                results.extend(rows)
        return results[:top_k]

    def by_org(self, org: str, top_k: int = 5) -> list[dict]:
        key = _norm(org)
        results: list[dict] = []
        for k, rows in self._by_org.items():
            if key in k or k in key:
                results.extend(rows)
        return results[:top_k]

    def by_concept(self, concept: str, top_k: int = 10) -> list[dict]:
        key = _norm(concept)
        results: list[dict] = []
        for k, rows in self._by_concept.items():
            if key in k or k in key:
                results.extend(rows)
        return results[:top_k]

    def filter_by_threshold(
        self,
        field: str,
        operator: str,   # "gt", "ge", "lt", "le", "eq"
        value: float,
        concept: str | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """
        Recherche structurée : ex. filter_by_threshold("crown_cover_min", "ge", 30)
        → toutes les définitions avec couverture couronne ≥ 30%.
        """
        ops = {
            "gt": lambda v: v > value,
            "ge": lambda v: v >= value,
            "lt": lambda v: v < value,
            "le": lambda v: v <= value,
            "eq": lambda v: abs(v - value) < 0.01,
        }
        fn = ops.get(operator, ops["ge"])
        # Pas de by_concept(top_k) ici — on filtre sur tous les rows du concept
        if concept:
            key = _norm(concept)
            pool = [r for r in self._rows
                    if key in _norm(r.get("concept", "")) or _norm(r.get("concept", "")) in key]
        else:
            pool = self._rows
        return [r for r in pool if r.get(field) is not None and fn(r[field])][:top_k]

    def extract_countries(self, query: str) -> list[str]:
        """Détecte des noms de pays dans la requête."""
        q = _norm(query)
        found: list[str] = []
        for key, rows in self._by_country.items():
            if key and key in q:
                country = rows[0]["country"]
                if country not in found:
                    found.append(country)
        return found

    def extract_orgs(self, query: str) -> list[str]:
        q = _norm(query)
        found: list[str] = []
        orgs = ["fao", "unfccc", "ipcc", "ipbes", "eu", "world bank", "unep", "iucn"]
        for org in orgs:
            if org in q:
                found.append(org.upper())
        return found

    def format_as_context(
        self,
        country: str | None = None,
        org: str | None = None,
        concept: str | None = None,
        max_entries: int = 5,
    ) -> str | None:
        """Formate les critères trouvés en texte pour le prompt RAG."""
        if country:
            entries = self.by_country(country, top_k=max_entries)
            header = f"{country} forest criteria (extracted from definitions):"
        elif org:
            entries = self.by_org(org, top_k=max_entries)
            header = f"{org} forest criteria (extracted from definitions):"
        elif concept:
            entries = self.by_concept(concept, top_k=max_entries)
            header = f"Forest criteria for concept '{concept}':"
        else:
            return None

        if not entries:
            return None

        lines = [header]
        for e in entries:
            parts: list[str] = []
            if e["area_ha_min"] is not None:
                parts.append(f"min area {e['area_ha_min']} ha")
            if e["crown_cover_min"] is not None:
                parts.append(f"crown cover {e['crown_cover_min']}%")
            if e["height_m_min"] is not None:
                parts.append(f"tree height {e['height_m_min']} m")
            if e["width_m_min"] is not None:
                parts.append(f"strip width {e['width_m_min']} m")
            if not parts:
                continue
            meta = " | ".join(filter(None, [
                e.get("organization", ""),
                e.get("country", ""),
                e.get("year", ""),
            ]))
            lines.append(f"  [{meta}] " + " | ".join(parts))

        return "\n".join(lines) if len(lines) > 1 else None

    def __len__(self) -> int:
        return len(self._rows)


@lru_cache(maxsize=1)
def get_criteria_store() -> CriteriaStore:
    return CriteriaStore()
