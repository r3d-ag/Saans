FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libpq5 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY core ./core
COPY ingest ./ingest
COPY ml ./ml
COPY apps ./apps
COPY db ./db
COPY docs ./docs
EXPOSE 8000
CMD ["sh", "-c", "uvicorn apps.api.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
