FROM python:3.12-slim

WORKDIR /app

# Dépendances système (pour sentence-transformers et chromadb)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif
COPY app/ ./app/
COPY start.sh ./start.sh
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh

# Volume pour la persistance ChromaDB
VOLUME ["/app/chroma_db"]

EXPOSE 8000

CMD ["./start.sh"]
