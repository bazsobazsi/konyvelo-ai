FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python3 -c "import os,urllib.request; p=os.environ.get('PORT','80'); urllib.request.urlopen(f'http://localhost:{p}/')" || exit 1

CMD ["sh", "-c", "gunicorn -w 2 -b 0.0.0.0:${PORT:-80} run:app --access-logfile - --timeout 120"]