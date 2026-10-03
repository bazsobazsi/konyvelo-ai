FROM python:3.11-slim

WORKDIR /app

# Layer 1: core deps (gyors, ritkán változik)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Layer 2: ML deps — sentence-transformers + torch (~800MB)
# Ezt a réteget a Docker cache-eli az első build után
COPY requirements.ml.txt .
RUN pip install --no-cache-dir -r requirements.ml.txt

RUN mkdir -p /app/data

COPY . .

# Embeddingek előre számítása build időben + HF modell cache az image-ben.
# Így az első felhasználói keresés nem számolja újra a 6000+ chunk vektorát.
RUN python3 collectors/precompute_embeddings.py || echo "⚠ precompute kihagyva (build tovább)"

ENV PYTHONUNBUFFERED=1
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
  CMD python3 -c "import os,urllib.request; p=os.environ.get('PORT','80'); urllib.request.urlopen(f'http://localhost:{p}/')" || exit 1

# --preload: az app (és a DB init) EGYSZER fut le a master processzben fork előtt
#   -> megszünteti a 'table already exists' race-t két worker között
# -k gthread: hosszú SSE streamelés mellett sem foglalja le az összes workert
CMD ["sh", "-c", "gunicorn -w 2 --threads 8 -k gthread --preload -b 0.0.0.0:${PORT:-80} run:app --access-logfile - --timeout 300 --graceful-timeout 30 --keep-alive 5"]
