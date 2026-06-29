# Pipeline principal du kg-builder
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

console = Console()


def _step(label: str):
    return Progress(
        SpinnerColumn(),
        TextColumn(f"[bold green]{label}[/bold green]"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


def run_pipeline(
    docx_path: Path,
    output_path: Path,
    table3_path: Path | None = None,
    no_csv: bool = False,
) -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    from extractor.docx_extractor import extract_definitions, extract_table3, Table3Record
    from extractor.csv_exporter import (
        export_definitions_raw, export_definitions_clean, export_table3 as export_t3_csv
    )
    from builder.skos_builder import SKOSBuilder

    # Dossier data = parent du output_path (même dossier que le TTL)
    data_dir = output_path.parent

    console.print(Panel.fit(
        "[bold cyan]RAG4OneForest — kg-builder[/bold cyan]\n"
        f"Source   : [yellow]{docx_path}[/yellow]\n"
        f"Output   : [yellow]{output_path}[/yellow]\n"
        f"Data dir : [yellow]{data_dir}[/yellow]\n"
        f"Table 3  : [yellow]{table3_path or 'extraite depuis le DOCX'}[/yellow]\n"
        f"CSV      : [yellow]{'désactivé' if no_csv else 'activé'}[/yellow]\n"
        f"Agrovoc  : [yellow]fetch SPARQL intégré (top-concepts)[/yellow]",
        title="Pipeline", border_style="cyan"
    ))

    t0 = time.perf_counter()

    # Étape 1 : Extraction des définitions textuelles
    with _step("Extraction DOCX — définitions") as p:
        task = p.add_task("", total=None)
        records = extract_definitions(docx_path)
        p.update(task, completed=True)
    console.print(f"  [OK] [green]{len(records)}[/green] enregistrements extraits")

    # Étape 2 : Extraction ou chargement de la Table 3
    table3_records: list[Table3Record] = []

    if table3_path and table3_path.exists():
        with _step("Chargement Table 3 depuis CSV") as p:
            task = p.add_task("", total=None)
            df3 = pd.read_csv(str(table3_path))
            table3_records = [
                Table3Record(
                    countries=           str(row.get("countries",           "")),
                    definition_type=     str(row.get("definition_type",     "")),
                    area_ha=             str(row.get("area_ha",             "")),
                    crown_cover_percent= str(row.get("crown_cover_percent", "")),
                    tree_height_m=       str(row.get("tree_height_m",       "")),
                    strip_width_m=       str(row.get("strip_width_m",       "")),
                    notes=               str(row.get("notes",               "")),
                )
                for _, row in df3.iterrows()
            ]
            p.update(task, completed=True)
        console.print(f"  [OK] [green]{len(table3_records)}[/green] lignes chargées depuis CSV")
    else:
        with _step("Extraction Table 3 depuis DOCX") as p:
            task = p.add_task("", total=None)
            table3_records = extract_table3(docx_path)
            p.update(task, completed=True)
        n_unfccc = sum(1 for r in table3_records if r.is_unfccc)
        console.print(
            f"  [OK] [green]{len(table3_records)}[/green] lignes extraites "
            f"([green]{n_unfccc}[/green] UNFCCC)"
        )

    # Étape 3 : Export CSV intermédiaires
    if not no_csv:
        with _step("Export CSV — brut + nettoyé + Table 3") as p:
            task = p.add_task("", total=None)

            n_raw   = export_definitions_raw(records, data_dir / "definitions_raw.csv")
            n_clean = export_definitions_clean(records, data_dir / "definitions_clean.csv")
            n_t3    = export_t3_csv(table3_records, data_dir / "table3.csv")

            p.update(task, completed=True)

        console.print(
            f"  [OK] CSV exportés : "
            f"[green]{n_raw}[/green] bruts → definitions_raw.csv  |  "
            f"[green]{n_clean}[/green] filtrés → definitions_clean.csv  |  "
            f"[green]{n_t3}[/green] Table 3 → table3.csv"
        )

    # Étape 4 : Construction du graphe SKOS
    with _step("Construction SKOS — définitions textuelles") as p:
        task = p.add_task("", total=None)
        builder = SKOSBuilder()
        builder.build(records)
        p.update(task, completed=True)

    # Étape 5 : Concepts UNFCCC + seuils Table 3
    if table3_records:
        with _step("Construction concepts UNFCCC + seuils Table 3") as p:
            task = p.add_task("", total=None)
            builder.build_table3_concepts(table3_records)
            p.update(task, completed=True)
    else:
        console.print("  [WARNING] [yellow]Table 3 vide --- concepts UNFCCC non créés[/yellow]")

    # Étape 6 : Sérialisation Turtle
    with _step("Sérialisation Turtle") as p:
        task = p.add_task("", total=None)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        builder.graph.serialize(destination=str(output_path), format="turtle")
        p.update(task, completed=True)

    elapsed = time.perf_counter() - t0

    # Statistiques finales
    stats = builder.stats()
    table = Table(title="Graphe RDF/SKOS — Statistiques", border_style="green")
    table.add_column("Métrique", style="cyan")
    table.add_column("Valeur",   style="bold white", justify="right")
    for k, v in stats.items():
        table.add_row(k.replace("_", " ").capitalize(), str(v))
    if output_path.exists():
        table.add_row("Taille fichier", f"{output_path.stat().st_size // 1024} Ko")
    table.add_row("Temps total", f"{elapsed:.1f}s")
    console.print(table)
    console.print(f"\n[bold green][OK] Graphe sauvegardé :[/bold green] {output_path}")


def print_stats(ttl_path: Path) -> None:
    from rdflib import Graph
    g = Graph()
    g.parse(str(ttl_path), format="turtle")

    PREFIXES = """
    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
    PREFIX dct:  <http://purl.org/dc/terms/>
    PREFIX ex:   <http://example.org/forest-def/>
    """
    table = Table(title=f"Statistiques — {ttl_path.name}", border_style="blue")
    table.add_column("Requête SPARQL", style="cyan")
    table.add_column("Résultat", justify="right", style="bold white")

    queries = [
        ("Total triplets RDF",           "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o . }"),
        ("Total skos:Concept",           "SELECT (COUNT(?c) AS ?n) WHERE { ?c a skos:Concept . }"),
        ("Avec skos:broadMatch",         "SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE { ?c skos:broadMatch ?p . }"),
        ("Avec définition",              "SELECT (COUNT(?c) AS ?n) WHERE { ?c skos:definition ?d . }"),
        ("Concepts UNFCCC",              "SELECT (COUNT(?c) AS ?n) WHERE { ex:UNFCCC skos:member ?c . }"),
        ("Avec seuil minAreaHa",         "SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE { ?c ex:minAreaHa ?v . }"),
        ("Alignements Agrovoc",          "SELECT (COUNT(?c) AS ?n) WHERE { ?c skos:exactMatch ?a . FILTER(STRSTARTS(STR(?a),'http://aims.fao.org')) }"),
        ("Top Concepts",                 "SELECT (COUNT(?c) AS ?n) WHERE { ?c skos:topConceptOf ?s . }"),
        ("Collections SKOS",             "SELECT (COUNT(?c) AS ?n) WHERE { ?c a skos:Collection . }"),
        ("Pays couverts (dct:spatial)",  "SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE { ?c dct:spatial ?p . }"),
    ]
    for label, q in queries:
        res = list(g.query(PREFIXES + q))
        table.add_row(label, str(res[0][0]) if res else "—")

    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="RAG4OneForest — kg-builder pipeline")
    parser.add_argument("--input",   type=Path, help="Chemin vers le fichier DOCX source")
    parser.add_argument("--output",  type=Path, default=Path("../data/forest_kg.ttl"))
    parser.add_argument("--table3",  type=Path,
                        help="CSV Table 3 (optionnel — extrait du DOCX si absent)")
    parser.add_argument("--no-csv",  action="store_true",
                        help="Ne pas exporter les CSV intermédiaires")
    parser.add_argument("--stats",   action="store_true",
                        help="Afficher les statistiques d'un TTL existant")
    parser.add_argument("--ttl",     type=Path,
                        help="Fichier TTL pour --stats")
    args = parser.parse_args()

    if args.stats:
        ttl = args.ttl or args.output
        if not ttl or not ttl.exists():
            console.print("[red]Spécifier --ttl <path>[/red]")
            sys.exit(1)
        print_stats(ttl)
        return

    if not args.input or not args.input.exists():
        console.print("[red]Spécifier --input <path/to/definitions.docx>[/red]")
        sys.exit(1)

    run_pipeline(args.input, args.output, args.table3, args.no_csv)


if __name__ == "__main__":
    main()
