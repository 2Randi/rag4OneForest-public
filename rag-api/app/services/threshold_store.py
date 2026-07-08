# Seuils nationaux de definition forestiere (Table 3 Lund 2018)
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.settings import settings
from app.services.graph_store import GraphStore, get_graph_store
from app.services.inventory import CONTINENT_PATTERNS


def _normalise(s: str) -> str:
    import unicodedata
    # Retirer les accents (ô → o, é → e, etc.)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", " ", s.lower()).strip()


class ThresholdStore:
    """
    Lookup in-memory des seuils forestiers nationaux (Table 3, Lund 2018).
    Un pays peut avoir plusieurs entrées (définition nationale + UNFCCC + FREL…).
    """

    def __init__(
        self,
        csv_path: str | Path | None = None,
        graph_store: GraphStore | None = None,
    ):
        self._graph_store = graph_store  # chargé seulement si besoin de résoudre un continent
        path = Path(csv_path or settings.table3_path)
        self._rows: list[dict[str, Any]] = []
        self._index: dict[str, list[dict]] = {}   # pays normalisé → lignes

        if not path.exists():
            return

        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                country_raw = row.get("country_clean", "").strip()
                if not country_raw or "Table 3" in country_raw:
                    continue

                entry: dict[str, Any] = {
                    "country":     country_raw,
                    "type":        row.get("definition_type_clean", ""),
                    "is_unfccc":   row.get("is_unfccc", "False").strip() == "True",
                    "area_ha":     self._float(row.get("area_ha", "")),
                    "crown_cover": self._float(row.get("crown_cover_percent", "")),
                    "height_m":    self._float(row.get("tree_height_m", "")),
                    "width_m":     self._float(row.get("strip_width_m", "")),
                    "notes":       self._clean_note(row.get("notes", "")),
                    "source_row":  row.get("countries", "").strip(),
                }
                key = _normalise(country_raw)
                self._index.setdefault(key, []).append(entry)
                self._rows.append(entry)

    @staticmethod
    def _clean_note(val: str) -> str:
        v = val.strip()
        return "" if v.lower() in ("nan", "none", "") else v

    @staticmethod
    def _float(val: str) -> float | None:
        try:
            v = float(val.split("/")[0].split("-")[0].strip())
            return None if v != v else v      # NaN → None
        except (ValueError, AttributeError):
            return None

    # Recherche principale

    def get_by_country(self, country: str, unfccc_only: bool = False) -> list[dict]:
        """Retourne toutes les entrées pour un pays donné.

        Exact d'abord : un matching partiel bidirectionnel confondait
        "Guinea" avec "Equatorial Guinea"/"Guinea Bissau"/"Papua New Guinea"
        (toutes les combinaisons se contiennent l'une l'autre). Le partiel
        reste un filet de secours si le nom donné n'est pas exact.
        """
        key = _normalise(country)
        results = []
        if key in self._index:
            results.extend(self._index[key])
        else:
            for stored_key, rows in self._index.items():
                if key in stored_key or stored_key in key:
                    results.extend(rows)
        if unfccc_only:
            results = [r for r in results if r["is_unfccc"]]
        seen = set()
        deduped = []
        for r in results:
            ident = (r["country"], r["is_unfccc"])
            if ident not in seen:
                seen.add(ident)
                deduped.append(r)
        return deduped

    def extract_countries_from_query(self, query: str) -> list[str]:
        """Detecte les pays ou continents dans la requete."""
        q = _normalise(query)
        found: list[str] = []

        # d'abord chercher un continent, la liste des pays vient du graphe
        for pattern, continent_key in CONTINENT_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                try:
                    gs = self._graph_store or get_graph_store()
                    continent_countries = gs.get_countries_by_continent(continent_key)
                except FileNotFoundError:
                    continent_countries = []
                for c in continent_countries:
                    if c not in found and _normalise(c) in self._index:
                        found.append(c)
                break

        # Ensuite chercher des pays specifiques. On garde seulement les
        # matches les plus specifiques : "guinea" est un mot entier dans
        # "papua new guinea" aussi, donc sans ce filtre une question sur la
        # Papua New Guinea declenchait aussi la Guinea toute seule.
        if not found:
            candidates: list[tuple[str, str]] = []
            for key, rows in self._index.items():
                if key and re.search(rf'\b{re.escape(key)}\b', q):
                    candidates.append((key, rows[0]["country"]))
            keys = [k for k, _ in candidates]
            for key, country in candidates:
                if any(key != other and key in other for other in keys):
                    continue
                if country not in found:
                    found.append(country)

        return found

    def format_as_context(self, country: str) -> str | None:
        """
        Formate les seuils d'un pays en texte structuré pour le prompt RAG.
        Exemple :
          Madagascar forest thresholds (Lund 2018 Table 3):
            National definition (Land use): no area/cover/height threshold specified.
            UNFCCC definition: min area 1.0 ha | crown cover 30% | tree height 5 m
        """
        entries = self.get_by_country(country)
        if not entries:
            return None

        lines = [f"{country} forest thresholds (Lund 2018 Table 3):"]
        for e in entries:
            tag = "UNFCCC definition" if e["is_unfccc"] else f"National definition ({e['type'] or 'unspecified'})"
            parts: list[str] = []
            if e["area_ha"]     is not None: parts.append(f"min area {e['area_ha']} ha")
            if e["crown_cover"] is not None: parts.append(f"crown cover {e['crown_cover']}%")
            if e["height_m"]    is not None: parts.append(f"tree height {e['height_m']} m")
            if e["width_m"]     is not None: parts.append(f"strip width {e['width_m']} m")
            if e["notes"] and e["notes"].lower() not in ("nan", "none"):
                parts.append(f"note: {e['notes'][:120]}")
            body = " | ".join(parts) if parts else "no numerical threshold specified"
            lines.append(f"  {tag}: {body}")

        return "\n".join(lines)

    def get_all_countries(self) -> list[str]:
        return list({r["country"] for r in self._rows})

    def search_by_threshold(self, countries: list[str],
                            min_crown_cover: float | None = None,
                            min_area: float | None = None,
                            min_height: float | None = None) -> list[dict]:
        """Filtre les pays par valeur de seuil."""
        results = []
        for country in countries:
            entries = self.get_by_country(country)
            for e in entries:
                match = True
                if min_crown_cover is not None:
                    if e["crown_cover"] is None or e["crown_cover"] < min_crown_cover:
                        match = False
                if min_area is not None:
                    if e["area_ha"] is None or e["area_ha"] < min_area:
                        match = False
                if min_height is not None:
                    if e["height_m"] is None or e["height_m"] < min_height:
                        match = False
                if match:
                    results.append(e)
        return results

    def __len__(self) -> int:
        return len(self._rows)


@lru_cache(maxsize=1)
def get_threshold_store() -> ThresholdStore:
    return ThresholdStore()
