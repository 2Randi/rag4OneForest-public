#!/bin/sh
set -e

echo "[start] Vérification de l'index vectoriel..."

python -c "
from app.services.graph_store import get_graph_store
from app.services.vector_store import get_vector_store
vs = get_vector_store()
if vs.count() == 0:
    print('[start] Index vide — construction en cours (~2 min)...')
    gs = get_graph_store()
    n = vs.build_index(gs)
    print(f'[start] {n} concepts indexés.')
else:
    print(f'[start] Index déjà présent ({vs.count()} docs). OK.')
"

echo "[start] Démarrage de l'API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
