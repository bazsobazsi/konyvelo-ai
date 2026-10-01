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

ENV PYTHONUNBUFFERED=1
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python3 -c "import os,urllib.request; p=os.environ.get('PORT','80'); urllib.request.urlopen(f'http://localhost:{p}/')" || exit 1

CMD ["sh", "-c", "gunicorn -w 2 -b 0.0.0.0:${PORT:-80} run:app --access-logfile - --timeout 120"]