# ── RAG4OneForest — Makefile ─────────────────────────────────────────────────
.PHONY: help install install-api install-viz dev api index test clean

VENV        = venv/bin/activate
PYTHON      = . $(VENV) && python
PIP         = . $(VENV) && pip

help:
	@echo ""
	@echo "  RAG4OneForest — commandes disponibles"
	@echo "  ────────────────────────────────────────"
	@echo "  make install      Installer toutes les dépendances"
	@echo "  make api          Démarrer l'API RAG (port 8000)"
	@echo "  make viz          Démarrer le frontend graph-viz (port 5173)"
	@echo "  make dev          Démarrer API + frontend en parallèle"
	@echo "  make index        Construire l'index vectoriel ChromaDB"
	@echo "  make build-kg     Reconstruire le graphe RDF depuis DOCX"
	@echo "  make test         Lancer les tests"
	@echo "  make docker-up    Démarrer avec Docker Compose"
	@echo "  make clean        Nettoyer les fichiers temporaires"
	@echo ""

# ── Installation ──────────────────────────────────────────────────────────────
install:
	@echo "── Étape 1/4 : environnement Python ──────────────────────────────"
	@if [ ! -f venv/bin/activate ]; then python3 -m venv venv; fi
	$(PIP) install --upgrade pip -q
	$(PIP) install -r requirements.txt
	@echo "── Étape 2/4 : dépendances frontend ──────────────────────────────"
	cd graph-viz && npm install --silent
	@echo "── Étape 3/4 : fichier de configuration ──────────────────────────"
	@if [ ! -f rag-api/.env ]; then \
		cp rag-api/.env.example rag-api/.env; \
		echo ""; \
		echo "  ⚠  IMPORTANT : ajoutez votre clé API dans rag-api/.env"; \
		echo "     Exemple : GEMINI_API_KEY=AIza...  (gratuit sur aistudio.google.com)"; \
		echo ""; \
	fi
	@echo "── Étape 4/4 : construction de l'index vectoriel ──────────────────"
	@echo "   (téléchargement du modèle ~90 Mo la première fois)"
	cd rag-api && $(PYTHON) -c "\
from app.services.graph_store import get_graph_store; \
from app.services.vector_store import get_vector_store; \
gs = get_graph_store(); \
vs = get_vector_store(); \
n  = vs.build_index(gs); \
print(f'✓ {n} concepts indexés')"
	@echo ""
	@echo "✓ Installation terminée."
	@echo "  → Vérifiez rag-api/.env (clé API LLM requise)"
	@echo "  → Puis lancez : make dev"
	@echo ""

# ── Développement ─────────────────────────────────────────────────────────────
api:
	@echo "→ Démarrage API RAG sur http://localhost:8000"
	cd rag-api && $(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

viz:
	@echo "→ Démarrage graph-viz sur http://localhost:5173"
	cd graph-viz && npm run dev

dev:
	@echo "→ Démarrage API + frontend"
	@make -j2 api viz

# ── Index vectoriel ───────────────────────────────────────────────────────────
index:
	@echo "→ Construction de l'index vectoriel ChromaDB..."
	cd rag-api && $(PYTHON) -c "\
from app.services.graph_store import get_graph_store; \
from app.services.vector_store import get_vector_store; \
gs = get_graph_store(); \
vs = get_vector_store(); \
n  = vs.build_index(gs); \
print(f'✓ {n} concepts indexés')"

# ── Reconstruction du graphe RDF ─────────────────────────────────────────────
build-kg:
	@echo "→ Reconstruction du graphe RDF depuis DOCX..."
	$(PYTHON) kg-builder/pipeline.py \
		--input  data/definitions.docx \
		--output data/forest_kg.ttl
	@echo "✓ Graphe RDF reconstruit → data/forest_kg.ttl"

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	cd rag-api && $(PYTHON) -m pytest tests/ -v

# ── Docker ────────────────────────────────────────────────────────────────────
docker-up:
	docker compose up --build -d
	@echo "✓ Services démarrés"
	@echo "  API    : http://localhost:8000"
	@echo "  UI     : http://localhost:5173"
	@echo "  Docs   : http://localhost:8000/docs"

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

# ── Nettoyage ─────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Nettoyage effectué"
