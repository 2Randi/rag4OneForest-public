#!/usr/bin/env python3
# Script pour lancer le pipeline de construction du graphe
import sys
from pathlib import Path

# Ajouter le répertoire courant au path
sys.path.insert(0, str(Path(__file__).parent))

from pipeline import run_pipeline


def main():
    # Chemins par défaut
    project_root = Path(__file__).parent.parent
    data_dir = project_root / "data"
    
    input_docx = data_dir / "definitions.docx"
    output_ttl = data_dir / "forest_kg.ttl"
    table3_csv = data_dir / "table3.csv"
    
    # Vérifier l'existence du fichier d'entrée
    if not input_docx.exists():
        print(f"[ERROR] {input_docx} introuvable")
        print(f"   Placez votre fichier DOCX dans : {data_dir}/")
        sys.exit(1)
    
    # Créer le répertoire data s'il n'existe pas
    data_dir.mkdir(exist_ok=True)
    
    # Lancer le pipeline
    print(f"\n[INFO] Lancement du pipeline kg-builder...\n")
    run_pipeline(
        input_docx,
        output_ttl,
        table3_csv if table3_csv.exists() else None,
        no_csv=False
    )
    # print(f"\n[OK] Pipeline terminé !")
    # print(f"   Output : {output_ttl}\n")

if __name__ == "__main__":
    main()
