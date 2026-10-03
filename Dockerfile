# ── 1. Build the farmer app (React) ─────────────────────────────────────────
FROM node:22-alpine AS web
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json vite.config.ts ./
COPY web/ web/
RUN npm run build

# ── 2. Python API, serving the built app ────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# No system packages needed — Pillow ships pre-built wheels.
# libgl1/libglib2.0-0 are only required for OpenCV, which this project does not use.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY --from=web /app/web/dist web/dist

ENV MODEL_PATH=/app/backend/models
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

# Run as an unprivileged user (a compromised request must not own the container).
RUN useradd --system --no-create-home --uid 10001 app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3   CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz'%os.environ.get('PORT','8000'),timeout=3)"

WORKDIR /app/backend
CMD ["python", "main.py"]
