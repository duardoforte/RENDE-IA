FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Belem

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        xvfb \
        xauth \
        ca-certificates \
        tzdata \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

# Os módulos atuais usam caminhos relativos (tesouro_direto.db/gemini_usage.db).
# Mantemos esses nomes no /app, mas apontando para /data, que é volume persistente.
RUN mkdir -p /data \
    && rm -f tesouro_direto.db gemini_usage.db \
    && ln -s /data/tesouro_direto.db tesouro_direto.db \
    && ln -s /data/gemini_usage.db gemini_usage.db

EXPOSE 8000

CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp & export DISPLAY=:99; exec uvicorn app:app --host 0.0.0.0 --port 8000"]
